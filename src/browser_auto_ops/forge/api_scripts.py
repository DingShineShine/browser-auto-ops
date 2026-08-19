from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def compact_network(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        method = str(item.get("method") or "GET")
        post_data = item.get("post_data")
        operation = _graphql_operation(post_data) or _operation_from_url(url)
        compact.append(
            {
                "method": method,
                "url": url,
                "path": urlparse(url).path,
                "status": item.get("status"),
                "resource_type": item.get("resource_type"),
                "operation": operation,
                "post_data": _trim_body(post_data),
            }
        )
    return compact


_SKIP_NETWORK = (
    "scribe",
    "clickstream",
    "appcues",
    "analytics",
    "datadog",
    "google-analytics",
    "gtm",
    "remote_config",
    "/events/",
    "hotjar",
    "fullstory",
)


def write_api_scripts(scripts_dir: Path, summary: dict[str, Any]) -> list[str]:
    requests = [
        item
        for item in (summary.get("network") or [])
        if isinstance(item, dict) and _is_replayable_api(item)
    ]
    if not requests:
        return []
    scripts_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for item in _unique_operations(requests):
        slug = _slug(str(item.get("operation") or item.get("path") or "request"))
        filename = f"api-{slug}.py"
        path = scripts_dir / filename
        path.write_text(_script_for(item), encoding="utf-8")
        written.append(filename)
    return written


def _is_replayable_api(item: dict[str, Any]) -> bool:
    url = str(item.get("url") or "")
    path = str(item.get("path") or "")
    operation = str(item.get("operation") or "")
    blob = f"{url} {path} {operation}".lower()
    if any(marker in blob for marker in _SKIP_NETWORK):
        return False
    if operation and operation[0].isupper() and operation not in {"GET", "POST", "PUT", "DELETE"}:
        return True
    return "graphql" in blob


def _unique_operations(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in requests:
        key = str(item.get("operation") or item.get("path") or item.get("url") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:8]


def _graphql_operation(post_data: Any) -> str | None:
    payload = _parse_json(post_data)
    if isinstance(payload, dict):
        name = payload.get("operationName") or payload.get("operation_name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and item.get("operationName"):
                return str(item["operationName"])
    return None


def _operation_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    name = path.split("/")[-1] if path else "request"
    return name or "request"


def _parse_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def _trim_body(value: Any) -> Any:
    if isinstance(value, str) and len(value) > 4000:
        return value[:4000]
    return value


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return slug or "request"


def _script_for(item: dict[str, Any]) -> str:
    hint = {
        "method": item.get("method"),
        "url": item.get("url"),
        "path": item.get("path"),
        "operation": item.get("operation"),
    }
    literal = repr(json.dumps(hint, ensure_ascii=False))
    return f'''import argparse
import json
import sys
from urllib.request import Request, urlopen


HINT = json.loads({literal})


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a captured API request shape from trace evidence.")
    parser.add_argument("--url", default=HINT.get("url") or "")
    parser.add_argument("--cookie", default="")
    parser.add_argument("--body", default="")
    args = parser.parse_args()
    headers = {{"content-type": "application/json"}}
    if args.cookie:
        headers["cookie"] = args.cookie
    request = Request(args.url, data=args.body.encode("utf-8") if args.body else None, headers=headers, method=HINT.get("method") or "GET")
    with urlopen(request) as response:
        sys.stdout.write(response.read().decode("utf-8", errors="replace"))


if __name__ == "__main__":
    main()
'''
