from __future__ import annotations

from typing import Any

from browser_auto_ops import __version__
from browser_auto_ops.schemas import NetworkRequestInfo


def to_har(items: list[NetworkRequestInfo]) -> dict[str, Any]:
    return {
        "log": {
            "version": "1.2",
            "creator": {"name": "browser-auto-ops", "version": __version__},
            "entries": [_entry(item) for item in items],
        }
    }


def _entry(item: NetworkRequestInfo) -> dict[str, Any]:
    body = item.response_body or ""
    return {
        "startedDateTime": item.started_at.isoformat(),
        "time": _duration_ms(item),
        "request": {
            "method": item.method,
            "url": item.url,
            "httpVersion": "HTTP/1.1",
            "headers": _headers(item.request_headers),
            "queryString": [],
            "headersSize": -1,
            "bodySize": len(item.post_data or ""),
            "postData": {"mimeType": item.request_headers.get("content-type", ""), "text": item.post_data or ""},
        },
        "response": {
            "status": item.status or 0,
            "statusText": item.error or "",
            "httpVersion": "HTTP/1.1",
            "headers": _headers(item.response_headers),
            "cookies": [],
            "content": {
                "size": len(body),
                "mimeType": item.response_headers.get("content-type", ""),
                "text": body,
            },
            "redirectURL": "",
            "headersSize": -1,
            "bodySize": len(body),
        },
        "cache": {},
        "timings": {"send": 0, "wait": _duration_ms(item), "receive": 0},
    }


def _headers(headers: dict[str, str]) -> list[dict[str, str]]:
    return [{"name": key, "value": value} for key, value in headers.items()]


def _duration_ms(item: NetworkRequestInfo) -> int:
    if not item.finished_at:
        return 0
    return max(0, int((item.finished_at - item.started_at).total_seconds() * 1000))
