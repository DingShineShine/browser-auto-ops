from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from browser_auto_ops.forge.date_params import extract_date_parameters, is_relative_date_token

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_US_DATE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")
_TOKEN = re.compile(r"\b[A-Za-z]-\d+\b")
_QUOTED = re.compile(r"\"([^\"]{2,80})\"|'([^']{2,80})'")

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


def _iter_literals(summary: dict[str, Any], goal: str) -> list[tuple[str, str]]:
    return [*_goal_literals(goal), *_action_literals(summary)]


def _goal_literals(goal: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    found.extend((match.group(0), "goal") for match in _EMAIL.finditer(goal))
    found.extend((match.group(0), "goal") for match in _ISO_DATE.finditer(goal))
    found.extend((match.group(0), "goal") for match in _US_DATE.finditer(goal))
    found.extend((match.group(0), "goal") for match in _TOKEN.finditer(goal))
    for match in _QUOTED.finditer(goal):
        found.append((match.group(1) or match.group(2), "goal"))
    return found


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
