from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from browser_auto_ops.actions import ActionExecutor, wait_stable
from browser_auto_ops.config import ensure_data_dirs
from browser_auto_ops.errors import SessionNotFoundError
from browser_auto_ops.network import NetworkRecorder
from browser_auto_ops.providers.base import BrowserConnection
from browser_auto_ops.providers.registry import provider_for
from browser_auto_ops.schemas import (
    ActionRequest,
    ActionResult,
    BrowserSession,
    NetworkRequestInfo,
    PageState,
    ProviderConfig,
)
from browser_auto_ops.snapshot import SnapshotEngine
from browser_auto_ops.trace import TraceRecorder


@dataclass
class ManagedSession:
    session: BrowserSession
    connection: BrowserConnection
    trace: TraceRecorder
    network: NetworkRecorder
    last_state: PageState | None = None


@dataclass
class PageFacts:
    url: str = ""
    title: str = ""
    target_id: str | None = None
    page_ids: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "target_id": self.target_id,
            "page_ids": self.page_ids or [],
        }


class SessionManager:
    def __init__(self, data_root: Path | None = None) -> None:
        self.data_root = ensure_data_dirs(data_root)
        self.sessions: dict[str, ManagedSession] = {}
        self.snapshot = SnapshotEngine()
        self.executor = ActionExecutor()

    async def start(self, config: ProviderConfig) -> BrowserSession:
        provider = provider_for(config.provider)
        connection = await provider.start(config)
        session = BrowserSession(
            provider=config.provider,
            cdp_url=connection.cdp_url,
            endpoint=connection.cdp_url,
            ads_user_id=config.ads_user_id,
            process_pid=connection.process.pid if connection.process else None,
            owns_browser=connection.owns_browser,
            provider_config=config,
            meta=connection.meta,
        )
        await self._register(session, connection)
        self.sessions[session.session_id].trace.event("provider.start", session)
        return session

    async def attach(self, session: BrowserSession) -> ManagedSession:
        if session.session_id in self.sessions:
            return self.sessions[session.session_id]
        provider = provider_for(session.provider)
        connection = await provider.connect(session)
        await self._register(session, connection)
        self.sessions[session.session_id].trace.event("provider.connect", session)
        return self.sessions[session.session_id]

    async def stop(self, session_id: str) -> BrowserSession:
        managed = self.sessions.get(session_id)
        if not managed:
            raise SessionNotFoundError(session_id)
        provider = provider_for(managed.session.provider)
        await provider.stop(managed.session, managed.connection)
        managed.session.status = "stopped"
        managed.session.updated_at = _now()
        managed.trace.event("provider.stop", managed.session)
        self.sessions.pop(session_id, None)
        return managed.session

    async def stop_stored_only(self, session: BrowserSession) -> BrowserSession:
        provider = provider_for(session.provider)
        await provider.stop(session, None)
        session.status = "stopped"
        session.updated_at = _now()
        return session

    async def state(self, session_id: str) -> PageState:
        managed = self._managed(session_id)
        await self._sync_session_from_connection(managed)
        state = await self.snapshot.capture(managed.connection.page, session_id)
        managed.last_state = state
        managed.trace.event("state.capture", state)
        managed.trace.save_json("states", f"{_stamp()}.json", state)
        return state

    async def action(self, session_id: str, request: ActionRequest) -> tuple[ActionResult, PageState | None]:
        managed = self._managed(session_id)
        before_state = managed.last_state or await self.state(session_id)
        before_facts = await self._connection_facts(managed.connection)
        managed.trace.event("action.request", request)
        result = await self.executor.execute(managed.connection.page, before_state, request)
        if request.type not in {"screenshot", "execute_js", "extract"}:
            await self._reconcile_after_action(managed, before_facts)
        after_facts = await self._connection_facts(managed.connection)
        result.verification = _verification_payload(before_facts, after_facts)
        managed.trace.event("action.result", result)
        after_state: PageState | None = None
        if request.type not in {"screenshot", "execute_js", "extract"}:
            after_state = await self.state(session_id)
        return result, after_state

    async def screenshot(self, session_id: str, output: Path | None = None) -> Path:
        managed = self._managed(session_id)
        output = output or managed.trace.screenshots_dir / f"{_stamp()}.png"
        await managed.connection.page.screenshot(path=str(output), full_page=True)
        managed.trace.event("screenshot", {"path": str(output)})
        return output

    def network_requests(
        self,
        session_id: str,
        *,
        filter_text: str | None = None,
        resource_types: list[str] | None = None,
    ) -> list[NetworkRequestInfo]:
        managed = self._managed(session_id)
        return managed.network.list(filter_text=filter_text, resource_types=resource_types)

    def network_request(self, session_id: str, request_id: str) -> NetworkRequestInfo | None:
        managed = self._managed(session_id)
        return managed.network.get(request_id)

    def network_clear(self, session_id: str) -> int:
        managed = self._managed(session_id)
        return managed.network.clear()

    async def _register(self, session: BrowserSession, connection: BrowserConnection) -> None:
        trace = TraceRecorder(self.data_root, session.session_id)
        network = NetworkRecorder(connection.page)
        await network.enable()
        self.sessions[session.session_id] = ManagedSession(
            session=session,
            connection=connection,
            trace=trace,
            network=network,
        )
        await self._sync_session_from_connection(self.sessions[session.session_id])

    async def _reconcile_after_action(self, managed: ManagedSession, before: PageFacts) -> None:
        deadline = asyncio.get_event_loop().time() + 3.0
        switched = False
        while asyncio.get_event_loop().time() < deadline:
            switched = await self._adopt_new_page_if_needed(managed, before) or switched
            facts = await self._connection_facts(managed.connection)
            if switched or facts.target_id != before.target_id or facts.url != before.url:
                break
            await asyncio.sleep(0.2)
        try:
            await wait_stable(managed.connection.page)
        except Exception:
            pass
        if switched:
            managed.network = NetworkRecorder(managed.connection.page)
            await managed.network.enable()
        await self._sync_session_from_connection(managed)

    async def _adopt_new_page_if_needed(self, managed: ManagedSession, before: PageFacts) -> bool:
        connection = managed.connection
        browser = connection.browser
        before_ids = set(before.page_ids or [])
        if hasattr(browser, "adopt_new_or_related_page"):
            changed = await browser.adopt_new_or_related_page(before_ids, opener_target_id=before.target_id)
            if changed:
                connection.context = browser.contexts[0]
                connection.page = connection.context.pages[0]
            return bool(changed)

        context = connection.context
        pages = [page for page in getattr(context, "pages", []) if not _page_is_closed(page)]
        new_pages = [page for page in pages if _page_identity(page) not in before_ids]
        if new_pages:
            connection.page = new_pages[-1]
            try:
                await connection.page.bring_to_front()
            except Exception:
                pass
            return True
        if _page_is_closed(connection.page) and pages:
            connection.page = pages[-1]
            return True
        return False

    async def _connection_facts(self, connection: BrowserConnection) -> PageFacts:
        page = connection.page
        page_ids = await _connection_page_ids(connection)
        title = ""
        try:
            title = await page.title()
        except Exception:
            pass
        url = ""
        try:
            url = str(page.url or "")
        except Exception:
            pass
        return PageFacts(
            url=url,
            title=title,
            target_id=_page_target_id(page),
            page_ids=page_ids,
        )

    async def _sync_session_from_connection(self, managed: ManagedSession) -> None:
        target_id = _page_target_id(managed.connection.page)
        if target_id:
            managed.connection.meta["target_id"] = target_id
        managed.session.meta.update(managed.connection.meta)
        managed.session.cdp_url = managed.connection.cdp_url
        managed.session.endpoint = managed.connection.cdp_url
        managed.session.updated_at = _now()

    def _managed(self, session_id: str) -> ManagedSession:
        try:
            return self.sessions[session_id]
        except KeyError as exc:
            raise SessionNotFoundError(session_id) from exc

    async def close_all(self) -> None:
        for session_id in list(self.sessions):
            try:
                await self.stop(session_id)
            except Exception:
                pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


async def _connection_page_ids(connection: BrowserConnection) -> list[str]:
    browser = connection.browser
    if hasattr(browser, "page_targets"):
        try:
            targets = await browser.page_targets()
            return [str(target.get("targetId")) for target in targets if target.get("targetId")]
        except Exception:
            return []
    return [_page_identity(page) for page in getattr(connection.context, "pages", [])]


def _page_identity(page: Any) -> str:
    target_id = _page_target_id(page)
    if target_id:
        return target_id
    return f"page:{id(page)}"


def _page_target_id(page: Any) -> str | None:
    target_id = getattr(page, "target_id", None)
    return target_id if isinstance(target_id, str) and target_id else None


def _page_is_closed(page: Any) -> bool:
    is_closed = getattr(page, "is_closed", None)
    if callable(is_closed):
        try:
            return bool(is_closed())
        except Exception:
            return False
    return False


def _verification_payload(before: PageFacts, after: PageFacts) -> dict[str, Any]:
    return {
        "before": before.as_dict(),
        "after": after.as_dict(),
        "url_changed": before.url != after.url,
        "title_changed": before.title != after.title,
        "target_changed": before.target_id != after.target_id,
        "page_count_changed": len(before.page_ids or []) != len(after.page_ids or []),
    }
