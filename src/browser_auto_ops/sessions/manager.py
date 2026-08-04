from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from browser_auto_ops.actions import ActionExecutor
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
        state = await self.snapshot.capture(managed.connection.page, session_id)
        managed.last_state = state
        managed.trace.event("state.capture", state)
        managed.trace.save_json("states", f"{_stamp()}.json", state)
        return state

    async def action(self, session_id: str, request: ActionRequest) -> tuple[ActionResult, PageState | None]:
        managed = self._managed(session_id)
        before_state = managed.last_state or await self.state(session_id)
        managed.trace.event("action.request", request)
        result = await self.executor.execute(managed.connection.page, before_state, request)
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

