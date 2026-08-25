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
from browser_auto_ops.snapshot.resolve import resolve_action_request
from browser_auto_ops.trace import TraceRecorder


@dataclass
class ManagedSession:
    session: BrowserSession
    connection: BrowserConnection
    trace: TraceRecorder
    network: NetworkRecorder
    last_state: PageState | None = None
    network_archive: list[NetworkRequestInfo] | None = None


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
        self._sync_session_from_connection(managed)
        previous = managed.last_state
        state = await self.snapshot.capture(managed.connection.page, session_id, previous=previous)
        _mark_changed_elements(previous, state)
        managed.last_state = state
        managed.trace.event("state.capture", state)
        managed.trace.save_json("states", f"{_stamp()}.json", state)
        return state

    async def action(
        self,
        session_id: str,
        request: ActionRequest,
        *,
        capture_state: bool = True,
        wait_after_action: bool = True,
    ) -> tuple[ActionResult, PageState | None]:
        managed = self._managed(session_id)
        before_state = managed.last_state or await self.state(session_id)
        before_facts = await self._connection_facts(managed.connection)
        try:
            request = resolve_action_request(before_state, request)
        except Exception:
            pass
        managed.trace.event("action.request", request)
        result = await self.executor.execute(managed.connection.page, before_state, request, wait_after_action=wait_after_action)
        if request.type not in {"screenshot", "execute_js", "extract"}:
            await self._reconcile_after_action(managed, before_facts, wait_stable_after=wait_after_action)
        after_facts = await self._connection_facts(managed.connection)
        result.verification = _verification_payload(before_facts, after_facts)
        managed.trace.event("action.result", result)
        after_state: PageState | None = None
        if capture_state and request.type not in {"screenshot", "execute_js", "extract"}:
            after_state = await self.state(session_id)
            _apply_action_verification(before_state, after_state, request, result)
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
        self._archive_network(managed)
        return _filter_network(managed.network_archive or [], filter_text=filter_text, resource_types=resource_types)

    def network_request(self, session_id: str, request_id: str) -> NetworkRequestInfo | None:
        managed = self._managed(session_id)
        self._archive_network(managed)
        return next((item for item in (managed.network_archive or []) if item.request_id == request_id), None)

    def network_clear(self, session_id: str) -> int:
        managed = self._managed(session_id)
        count = len(managed.network_archive or []) + managed.network.clear()
        managed.network_archive = []
        managed.trace.event("network.clear", {"cleared": count})
        return count

    async def _register(self, session: BrowserSession, connection: BrowserConnection) -> None:
        trace = TraceRecorder(self.data_root, session.session_id)
        network = NetworkRecorder(connection.page)
        await network.enable()
        self.sessions[session.session_id] = ManagedSession(
            session=session,
            connection=connection,
            trace=trace,
            network=network,
            network_archive=[],
        )
        self._sync_session_from_connection(self.sessions[session.session_id])

    async def _reconcile_after_action(
        self,
        managed: ManagedSession,
        before: PageFacts,
        *,
        wait_stable_after: bool = True,
    ) -> None:
        deadline = asyncio.get_event_loop().time() + (3.0 if wait_stable_after else 0.5)
        switched = False
        while asyncio.get_event_loop().time() < deadline:
            switched = await self._adopt_new_page_if_needed(managed, before) or switched
            facts = await self._connection_facts(managed.connection)
            if switched or facts.target_id != before.target_id or facts.url != before.url:
                break
            await asyncio.sleep(0.2)
        if wait_stable_after:
            try:
                await wait_stable(managed.connection.page)
            except Exception:
                pass
        if switched:
            self._archive_network(managed)
            managed.network = NetworkRecorder(managed.connection.page)
            await managed.network.enable()
        self._sync_session_from_connection(managed)

    def _archive_network(self, managed: ManagedSession) -> None:
        archive = managed.network_archive
        if archive is None:
            archive = []
            managed.network_archive = archive
        by_id = {item.request_id: idx for idx, item in enumerate(archive)}
        for item in managed.network.list(resource_types=["xhr", "fetch"]):
            if item.request_id in by_id:
                archive[by_id[item.request_id]] = item
                continue
            archive.append(item)
            by_id[item.request_id] = len(archive) - 1
            managed.trace.event("network.request", _compact_network_event(item))

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

    def _sync_session_from_connection(self, managed: ManagedSession) -> None:
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
        for session_id in self.sessions.copy():
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


def _mark_changed_elements(previous: PageState | None, current: PageState) -> None:
    if not previous:
        return
    previous_keys = {_element_signature(element) for element in previous.elements}
    for element in current.elements:
        element.changed = _element_signature(element) not in previous_keys


def _element_signature(element) -> tuple[str, str, str, str]:
    return (
        element.kind,
        element.locator.value,
        element.name or element.text or element.placeholder or element.value,
        element.frame_url or "",
    )


def _apply_action_verification(
    before: PageState,
    after: PageState,
    request: ActionRequest,
    result: ActionResult,
) -> None:
    if request.type != "click" or request.index is None or not result.success:
        return
    before_element = next((element for element in before.elements if element.index == request.index), None)
    if not before_element:
        return
    label = " ".join(
        [
            before_element.kind,
            before_element.role or "",
            before_element.name,
            before_element.text,
            " ".join(before_element.attributes.values()),
        ]
    )
    if before_element.kind == "checkbox" or before_element.checked is not None:
        after_match = _find_matching_after_element(before_element, after)
        if after_match and after_match.checked == before_element.checked:
            result.success = False
            result.message = "click did not change checkbox state"
    if before_element.modal or any(word in label for word in ["确认选择", "前往查看", "确定"]):
        if any(element.modal for element in after.elements) and any(element.modal for element in before.elements):
            result.success = False
            result.message = "modal is still open after click"


def _find_matching_after_element(before: Any, after: PageState):
    for element in after.elements:
        if element.locator.value == before.locator.value:
            return element
        if before.action_locator and element.action_locator and element.action_locator.value == before.action_locator.value:
            return element
    return None


def _filter_network(
    items: list[NetworkRequestInfo],
    *,
    filter_text: str | None = None,
    resource_types: list[str] | None = None,
) -> list[NetworkRequestInfo]:
    rows = list(items)
    if filter_text:
        rows = [item for item in rows if filter_text in item.url]
    if resource_types:
        allowed = {item.lower() for item in resource_types}
        rows = [item for item in rows if (item.resource_type or "").lower() in allowed]
    return rows


def _compact_network_event(item: NetworkRequestInfo) -> dict[str, Any]:
    return {
        "request_id": item.request_id,
        "method": item.method,
        "url": item.url,
        "status": item.status,
        "resource_type": item.resource_type,
        "post_data": item.post_data,
        "started_at": item.started_at.isoformat(),
        "finished_at": item.finished_at.isoformat() if item.finished_at else None,
    }
