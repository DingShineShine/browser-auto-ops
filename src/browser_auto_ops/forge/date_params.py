from __future__ import annotations

import re
from typing import Any

_RELATIVE_T = re.compile(r"\b[Tt]\s*([+-])\s*(\d+)\b")
_KEYWORDS = {
    "today": 0,
    "yesterday": 1,
}


def extract_date_parameters(text: str) -> list[dict[str, Any]]:
    """Extract generic relative date parameters from free-form task text.

    Forge should preserve the user's relative intent (for example T-3) instead
    of freezing the observed calendar day into a site-specific literal.
    """
    params: list[dict[str, Any]] = []
    for match in _RELATIVE_T.finditer(text or ""):
        sign = match.group(1)
        days = int(match.group(2))
        offset_days = days if sign == "-" else -days
        token = f"T{sign}{days}"
        params.append(_param(token, offset_days, len(params)))
    lower = text.lower()
    for keyword, offset_days in _KEYWORDS.items():
        if re.search(rf"\b{re.escape(keyword)}\b", lower):
            params.append(_param(keyword, offset_days, len(params)))
    return params


def is_relative_date_token(value: str) -> bool:
    cleaned = (value or "").strip()
    return bool(_RELATIVE_T.fullmatch(cleaned)) or cleaned.lower() in _KEYWORDS


def _param(token: str, offset_days: int, index: int) -> dict[str, Any]:
    names = ("start_date", "end_date")
    name = names[index] if index < len(names) else f"date_{index + 1}"
    return {
        "name": name,
        "value": token,
        "source": "goal",
        "type": "date_offset",
        "relative_to": "today",
        "offset_days": offset_days,
        "format_hints": ["YYYY-MM-DD", "MM/DD/YYYY", "Month D, YYYY", "YYYYMMDD"],
    }
