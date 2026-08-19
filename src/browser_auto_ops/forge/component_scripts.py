from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_component_scripts(scripts_dir: Path, workflow: dict[str, Any]) -> list[str]:
    scripts_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    if any(item.get("type") == "date_offset" for item in workflow.get("parameters") or [] if isinstance(item, dict)):
        (scripts_dir / "date-params.py").write_text(_date_params_script(workflow), encoding="utf-8")
        written.append("date-params.py")
    (scripts_dir / "download-artifact.py").write_text(_download_artifact_script(), encoding="utf-8")
    written.append("download-artifact.py")
    return written


def _date_params_script(workflow: dict[str, Any]) -> str:
    params = [
        item
        for item in workflow.get("parameters") or []
        if isinstance(item, dict) and item.get("type") == "date_offset"
    ]
    literal = repr(json.dumps(params, ensure_ascii=False))
    return f'''import argparse
import json
from datetime import date, datetime, timedelta


DATE_PARAMS = json.loads({literal})


def _parse_today(value: str) -> date:
    if value:
        return datetime.strptime(value, "%Y-%m-%d").date()
    return date.today()


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve forge relative date parameters.")
    parser.add_argument("--today", default="", help="Override today as YYYY-MM-DD for tests or deterministic replay")
    args = parser.parse_args()
    today = _parse_today(args.today)
    rows = []
    for item in DATE_PARAMS:
        target = today - timedelta(days=int(item.get("offset_days") or 0))
        rows.append({{
            "name": item.get("name"),
            "token": item.get("value"),
            "iso": target.strftime("%Y-%m-%d"),
            "us": target.strftime("%m/%d/%Y"),
            "long_en": f"{{target.strftime('%B')}} {{target.day}}, {{target.year}}",
            "compact": target.strftime("%Y%m%d"),
        }})
    print(json.dumps({{"dates": rows}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
'''


def _download_artifact_script() -> str:
    return '''import argparse
import base64
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Save a base64 download artifact to disk.")
    parser.add_argument("--json-file", required=True)
    parser.add_argument("--output-dir", default=str(Path.home() / "Downloads"))
    parser.add_argument("--filename", default="")
    args = parser.parse_args()
    payload = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
    body64 = payload.get("base64") or payload.get("response_body_base64")
    if not body64:
        raise SystemExit("payload does not contain base64 download content")
    filename = args.filename or payload.get("filename") or payload.get("suggested_filename") or "download.bin"
    output = Path(args.output_dir).expanduser().resolve() / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(base64.b64decode(body64))
    print(json.dumps({"saved": str(output), "bytes": output.stat().st_size}, ensure_ascii=False))


if __name__ == "__main__":
    main()
'''
