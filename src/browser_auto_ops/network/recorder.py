from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Iterable

from playwright.async_api import Page, Request, Response

from browser_auto_ops.schemas import NetworkRequestInfo
from browser_auto_ops.trace.redaction import redact


class NetworkRecorder:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.requests: dict[str, NetworkRequestInfo] = {}
        self._by_playwright_request: dict[Request, str] = {}
        self._enabled = False

    async def enable(self) -> None:
        if self._enabled:
            return
        self.page.on("request", self._on_request)
        self.page.on("response", self._on_response)
        self.page.on("requestfailed", self._on_request_failed)
        self._enabled = True

    def list(
        self,
        *,
        filter_text: str | None = None,
        resource_types: Iterable[str] | None = None,
    ) -> list[NetworkRequestInfo]:
        items = list(self.requests.values())
        if filter_text:
            items = [item for item in items if filter_text in item.url]
        if resource_types:
            allowed = {item.lower() for item in resource_types}
            items = [
                item
                for item in items
                if (item.resource_type or "").lower() in allowed
            ]
        return items

    def get(self, request_id: str) -> NetworkRequestInfo | None:
        return self.requests.get(request_id)

    def _on_request(self, request: Request) -> None:
        info = NetworkRequestInfo(
            url=request.url,
            method=request.method,
            resource_type=request.resource_type,
            request_headers=redact(request.headers),
            post_data=_safe_post_data(request),
        )
        self.requests[info.request_id] = info
        self._by_playwright_request[request] = info.request_id

    def _on_response(self, response: Response) -> None:
        request_id = self._by_playwright_request.get(response.request)
        if not request_id:
            return
        info = self.requests[request_id]
        info.status = response.status
        info.response_headers = redact(response.headers)
        info.finished_at = datetime.now(timezone.utc)
        try:
            asyncio.create_task(self._capture_body(response, request_id))
        except RuntimeError:
            pass

    def _on_request_failed(self, request: Request) -> None:
        request_id = self._by_playwright_request.get(request)
        if not request_id:
            return
        info = self.requests[request_id]
        info.error = request.failure or "request failed"
        info.finished_at = datetime.now(timezone.utc)

    async def _capture_body(self, response: Response, request_id: str) -> None:
        try:
            body = await response.text()
            if len(body) > 1_000_000:
                body = body[:1_000_000] + "\n[TRUNCATED]"
            self.requests[request_id].response_body = body
        except Exception as exc:
            self.requests[request_id].error = f"response body unavailable: {exc}"


def _safe_post_data(request: Request) -> str | None:
    try:
        data = request.post_data
        if data and len(data) > 200_000:
            return data[:200_000] + "\n[TRUNCATED]"
        return data
    except Exception:
        return None

