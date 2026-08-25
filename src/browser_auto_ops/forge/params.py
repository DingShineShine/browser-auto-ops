from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from browser_auto_ops.forge.date_params import extract_date_parameters, is_relative_date_token

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_US_DATE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")
_LONG_DATE = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", flags=re.I)
_FILENAME = re.compile(r"\b[\w.-]+\.(?:csv|xlsx?|pdf|json|zip|txt|png|jpg|jpeg)\b", flags=re.I)
_ARTIFACT_STEM = re.compile(r"\b[A-Za-z][\w.-]*\d{4}-\d{2}-\d{2}[\w.-]*\b")
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\[^\n\r\"']{3,160}")
_TOKEN = re.compile(r"\b[A-Za-z]-\d+\b")
_QUOTED = re.compile(r"\"([^\"]{2,80})\"|'([^']{2,80})'")
_RUNTIME_RESULT_FIELDS = {"latestid", "reportid", "id", "filename", "url", "downloadurl", "download_url"}

_SKIP_VALUES = {"true", "false", "null", "none", "click", "input", "wait"}


def extract_parameters(summary: dict[str, Any], goal: str | None = None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    params: list[dict[str, Any]] = []
    resolved_goal = goal or str(summary.get("goal") or "")
    for item in extract_date_parameters(resolved_goal):
        seen.add(str(item["value"]))
        params.append(item)
    for value, source in _iter_literals(summary, resolved_goal):
        cleaned = value.strip()
        if not cleaned or cleaned.lower() in _SKIP_VALUES or cleaned in seen:
            continue
        if is_relative_date_token(cleaned):
            continue
        if _looks_secret(cleaned, source):
            continue
        seen.add(cleaned)
        params.append(
            {
                "name": _name_for(cleaned, len(params) + 1),
                "value": cleaned,
                "source": source,
            }
        )
    return params


def extract_parameter_candidates(summary: dict[str, Any], goal: str | None = None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    resolved_goal = goal or str(summary.get("goal") or "")
    for value, source, location in _iter_candidate_values(summary, resolved_goal):
        cleaned = value.strip()
        if not cleaned or cleaned.lower() in _SKIP_VALUES:
            continue
        if _looks_secret(cleaned, source):
            continue
        kind = _candidate_kind(cleaned, location)
        if not kind:
            continue
        binding_scope = _binding_scope(kind, location)
        key = (kind, cleaned)
        if key in seen:
            _append_candidate_location(candidates, kind, cleaned, location)
            continue
        seen.add(key)
        candidates.append(
            {
                "name": _candidate_name(cleaned, kind, len(candidates) + 1),
                "value": cleaned,
                "kind": kind,
                "recommended_binding": _recommended_binding(kind, location),
                "confidence": _candidate_confidence(kind, location),
                "binding_scope": binding_scope,
                "locations": [location],
                "reason": _candidate_reason(kind, location),
                "requires_confirmation": _requires_confirmation(kind, binding_scope),
            }
        )
    return candidates


def _iter_literals(summary: dict[str, Any], goal: str) -> list[tuple[str, str]]:
    return [*_goal_literals(goal), *_action_literals(summary)]


def _iter_candidate_values(summary: dict[str, Any], goal: str) -> list[tuple[str, str, dict[str, Any]]]:
    found: list[tuple[str, str, dict[str, Any]]] = []
    for value, source in _goal_literals(goal):
        found.append((value, source, {"source": source, "field": "goal"}))
    for action_index, action in enumerate(summary.get("actions") or [], start=1):
        if not isinstance(action, dict):
            continue
        element = action.get("element") if isinstance(action.get("element"), dict) else {}
        if _is_secret_field(element):
            continue
        found.extend(_action_candidate_values(action, action_index))
    return found


def _action_candidate_values(action: dict[str, Any], action_index: int) -> list[tuple[str, str, dict[str, Any]]]:
    request = action.get("request") if isinstance(action.get("request"), dict) else {}
    result = action.get("result") if isinstance(action.get("result"), dict) else {}
    return [
        *_request_candidate_values(request, action_index),
        *_result_candidate_values(result.get("data"), action_index),
    ]


def _request_candidate_values(request: dict[str, Any], action_index: int) -> list[tuple[str, str, dict[str, Any]]]:
    rows: list[tuple[str, str, dict[str, Any]]] = []
    for key in ("text", "option", "url", "script"):
        value = request.get(key)
        if isinstance(value, str) and value.strip():
            rows.extend(
                (item, "action", {"source": "action", "action_index": action_index, "field": f"request.{key}"})
                for item in _interesting_literals(value)
            )
    return rows


def _result_candidate_values(data: Any, action_index: int) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (item, "result", {"source": "result", "action_index": action_index, "field": field})
        for item, field in _result_literals(data)
    ]


def _goal_literals(goal: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    found.extend((match.group(0), "goal") for match in _EMAIL.finditer(goal))
    found.extend((match.group(0), "goal") for match in _ISO_DATE.finditer(goal))
    found.extend((match.group(0), "goal") for match in _US_DATE.finditer(goal))
    found.extend((match.group(0), "goal") for match in _LONG_DATE.finditer(goal))
    found.extend((match.group(0), "goal") for match in _UUID.finditer(goal))
    found.extend((match.group(0), "goal") for match in _FILENAME.finditer(goal))
    found.extend((match.group(0), "goal") for match in _ARTIFACT_STEM.finditer(goal))
    found.extend((match.group(0), "goal") for match in _WINDOWS_PATH.finditer(goal))
    found.extend((match.group(0), "goal") for match in _TOKEN.finditer(goal))
    for match in _QUOTED.finditer(goal):
        found.append((match.group(1) or match.group(2), "goal"))
    return found


def _interesting_literals(value: str) -> list[str]:
    found: list[str] = []
    for regex in (_ISO_DATE, _US_DATE, _LONG_DATE, _UUID, _FILENAME, _ARTIFACT_STEM, _WINDOWS_PATH, _TOKEN):
        found.extend(match.group(0) for match in regex.finditer(value))
    for match in _QUOTED.finditer(value):
        literal = match.group(1) or match.group(2)
        if _candidate_kind(literal, {"source": "action"}):
            found.append(literal)
    return found


def _result_literals(data: Any, field_prefix: str = "result.data") -> list[tuple[str, str]]:
    parsed = _parse_json(data) if isinstance(data, str) else data
    rows: list[tuple[str, str]] = []
    if isinstance(parsed, dict):
        for key, value in parsed.items():
            field = f"{field_prefix}.{key}"
            if isinstance(value, str):
                if key.lower() in _RUNTIME_RESULT_FIELDS:
                    rows.append((value, field))
                rows.extend((item, field) for item in _interesting_literals(value))
            elif isinstance(value, (dict, list)):
                rows.extend(_result_literals(value, field))
    elif isinstance(parsed, list):
        for item in parsed[:20]:
            rows.extend(_result_literals(item, field_prefix))
    return rows


def _action_literals(summary: dict[str, Any]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for action in summary.get("actions") or []:
        if not isinstance(action, dict):
            continue
        request = action.get("request") if isinstance(action.get("request"), dict) else {}
        element = action.get("element") if isinstance(action.get("element"), dict) else {}
        if _is_secret_field(element):
            continue
        found.extend((value, "action") for value in _request_values(request))
    return found


def _request_values(request: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("text", "option", "url"):
        value = request.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    return values


def _name_for(value: str, index: int) -> str:
    if "@" in value:
        return "email"
    if _ISO_DATE.fullmatch(value) or _US_DATE.fullmatch(value):
        return f"date_{index}"
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return "url" if index == 1 else f"url_{index}"
    if _TOKEN.fullmatch(value):
        return f"token_{index}"
    return f"value_{index}"


def _candidate_kind(value: str, location: dict[str, Any]) -> str:
    if _is_date_literal(value):
        return "date"
    if _UUID.fullmatch(value) or str(location.get("field") or "").lower().endswith("id"):
        return "id"
    if _FILENAME.fullmatch(value):
        return "filename"
    if _ARTIFACT_STEM.fullmatch(value):
        return "artifact_stem"
    if _WINDOWS_PATH.fullmatch(value) or value.lower() in {"desktop", "downloads"}:
        return "path"
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return "url"
    if _TOKEN.fullmatch(value):
        return "token"
    return ""


def _is_date_literal(value: str) -> bool:
    return bool(_ISO_DATE.fullmatch(value) or _US_DATE.fullmatch(value) or _LONG_DATE.fullmatch(value) or is_relative_date_token(value))


def _candidate_name(value: str, kind: str, index: int) -> str:
    prefixes = {
        "date": "date",
        "id": "runtime_id",
        "filename": "filename",
        "artifact_stem": "report_name",
        "path": "output_dir",
        "url": "url",
    }
    prefix = prefixes.get(kind)
    if prefix:
        return prefix if index == 1 and kind != "date" else f"{prefix}_{index}"
    return _name_for(value, index)


def _recommended_binding(kind: str, location: dict[str, Any]) -> str:
    if kind == "id" and location.get("source") == "result":
        return "runtime_output"
    if kind in {"date", "filename", "path", "artifact_stem"}:
        return "user_parameter"
    return "recorded_constant"


def _candidate_confidence(kind: str, location: dict[str, Any]) -> float:
    if kind == "id" and location.get("source") == "result":
        return 0.95
    if kind in {"date", "filename", "artifact_stem"}:
        return 0.9
    if kind == "path":
        return 0.85
    return 0.7


def _candidate_reason(kind: str, location: dict[str, Any]) -> str:
    source = location.get("source") or "trace"
    if kind == "id":
        return f"{source} contains an identifier that often changes between runs"
    if kind == "date":
        return f"{source} contains a date literal that may need relative replay"
    if kind == "filename":
        return f"{source} contains a filename that may be an artifact name"
    if kind == "artifact_stem":
        return f"{source} contains a report name that may be used as an artifact stem"
    if kind == "path":
        return f"{source} contains a filesystem location"
    return f"{source} contains a reusable literal"


def _binding_scope(kind: str, location: dict[str, Any]) -> str:
    source = location.get("source")
    if source == "goal":
        return "goal_parameter"
    if source == "action":
        return "action_input"
    if source == "result" and _is_runtime_result_field(location):
        return "runtime_output" if kind in {"id", "filename", "url"} else "observed_state"
    return "observed_state"


def _is_runtime_result_field(location: dict[str, Any]) -> bool:
    field = str(location.get("field") or "").rsplit(".", 1)[-1].lower()
    return field in _RUNTIME_RESULT_FIELDS


def _requires_confirmation(kind: str, binding_scope: str) -> bool:
    if binding_scope not in {"goal_parameter", "action_input"}:
        return False
    return kind in {"date", "filename", "path", "artifact_stem"}


def _append_candidate_location(candidates: list[dict[str, Any]], kind: str, value: str, location: dict[str, Any]) -> None:
    for item in candidates:
        if item.get("kind") == kind and item.get("value") == value:
            item.setdefault("locations", []).append(location)
            return


def _parse_json(value: str) -> Any:
    try:
        return __import__("json").loads(value)
    except Exception:
        return None


def _is_secret_field(element: dict[str, Any]) -> bool:
    blob = " ".join(
        str(element.get(key) or "")
        for key in ("name", "text", "placeholder", "kind")
    ).lower()
    return any(marker in blob for marker in ("password", "passwd", "secret", "otp", "验证码"))


def _looks_secret(value: str, source: str) -> bool:
    lower = value.lower()
    if any(marker in lower for marker in ("password", "passwd", "secret=")):
        return True
    return source == "action" and len(value) >= 12 and any(ch in value for ch in "!@#$%^&*")
