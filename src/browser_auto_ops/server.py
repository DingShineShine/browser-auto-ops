from __future__ import annotations

from pathlib import Path
from typing import Any
import asyncio

from fastapi import FastAPI, HTTPException

from browser_auto_ops.browsers import BrowserStore, provider_config_for_browser
from browser_auto_ops.config import ensure_data_dirs
from browser_auto_ops.downloads import DownloadManager
from browser_auto_ops.forge import ForgeEngine
from browser_auto_ops.intelligence import ActService, ExtractService, ObserveService
from browser_auto_ops.safety import is_dangerous_text
from browser_auto_ops.schemas import ActionRequest, BrowserIdentity, BrowserSession, ProviderConfig
from browser_auto_ops.sessions import SessionManager, SessionStore

app = FastAPI(title="browser-auto-ops", version="0.1.0")
manager = SessionManager()
browser_store = BrowserStore()
session_store = SessionStore()
download_manager = DownloadManager()


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "sessions": len(manager.sessions)}


@app.get("/browsers")
async def list_browsers() -> list[dict[str, Any]]:
    return [browser.model_dump(mode="json") for browser in browser_store.list()]


@app.post("/browsers", response_model=BrowserIdentity)
async def create_browser(browser: BrowserIdentity) -> BrowserIdentity:
    if browser.type not in {"chrome-direct", "ads"}:
        raise HTTPException(status_code=400, detail="browser type must be chrome-direct or ads")
    browser_store.save(browser)
    return browser


@app.delete("/browsers/{browser_id_or_name}")
async def delete_browser(browser_id_or_name: str) -> dict[str, Any]:
    deleted = browser_store.delete(browser_id_or_name)
    if not deleted:
        raise HTTPException(status_code=404, detail="browser not found")
    return deleted.model_dump(mode="json")


@app.post("/browsers/{browser_id_or_name}/open", response_model=BrowserSession)
async def open_browser(browser_id_or_name: str, payload: dict[str, Any]) -> BrowserSession:
    browser = browser_store.get(browser_id_or_name)
    if not browser:
        raise HTTPException(status_code=404, detail="browser not found")
    try:
        config = provider_config_for_browser(
            browser,
            start_url=payload.get("url"),
            confirm=bool(payload.get("confirm")),
        )
        session = await manager.start(config)
        session.name = str(payload.get("session") or payload.get("session_name") or "")
        session.browser_id = browser.browser_id
        session_store.save(session)
        return session
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/sessions", response_model=BrowserSession)
async def create_session(config: ProviderConfig) -> BrowserSession:
    try:
        session = await manager.start(config)
        session_store.save(session)
        return session
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    managed = _managed(session_id)
    if not managed:
        raise HTTPException(status_code=404, detail="session not found")
    return managed.session.model_dump(mode="json")


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, Any]:
    try:
        session = await manager.stop(_session_id(session_id))
        session_store.delete(session.session_id)
        return session.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/sessions/{session_id}/state")
async def get_state(session_id: str) -> dict[str, Any]:
    try:
        return (await manager.state(_session_id(session_id))).model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/sessions/{session_id}/actions")
async def run_action(session_id: str, request: ActionRequest) -> dict[str, Any]:
    try:
        result, state = await manager.action(_session_id(session_id), request)
        return {
            "result": result.model_dump(mode="json"),
            "state": state.model_dump(mode="json") if state else None,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/sessions/{session_id}/observe")
async def observe(session_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    state = await manager.state(_session_id(session_id))
    candidates = ObserveService().observe(state, str(payload.get("goal", "")))
    return [candidate.model_dump(mode="json") for candidate in candidates]


@app.post("/sessions/{session_id}/act")
async def act(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    goal = str(payload.get("goal", ""))
    confirm = bool(payload.get("confirm") or payload.get("require_confirm"))
    session_id = _session_id(session_id)
    state = await manager.state(session_id)
    if is_dangerous_text(goal) and not confirm:
        return {
            "blocked": True,
            "reason": "goal requires explicit confirmation; send confirm=true or require_confirm=true",
            "actions": [],
            "results": [],
        }
    actions = ActService().plan(state, goal, allow_dangerous=confirm, require_confirm=confirm)[:3]
    results = []
    for request in actions:
        result, _ = await manager.action(session_id, request)
        results.append(result.model_dump(mode="json"))
    return {"actions": [item.model_dump(mode="json") for item in actions], "results": results}


@app.post("/sessions/{session_id}/extract")
async def extract(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    managed = _managed(session_id)
    data = await ExtractService().extract(
        managed.connection.page,
        str(payload.get("goal", "")),
        payload.get("schema"),
    )
    managed.trace.event("extract", data)
    return data


@app.get("/sessions/{session_id}/network/requests")
async def network_requests(
    session_id: str,
    type: str | None = None,
    filter: str | None = None,
) -> list[dict[str, Any]]:
    resource_types = type.split(",") if type else None
    return [
        item.model_dump(mode="json")
        for item in manager.network_requests(_session_id(session_id), filter_text=filter, resource_types=resource_types)
    ]


@app.get("/sessions/{session_id}/network/requests/{request_id}")
async def network_request(session_id: str, request_id: str) -> dict[str, Any] | None:
    item = manager.network_request(_session_id(session_id), request_id)
    return item.model_dump(mode="json") if item else None


@app.post("/sessions/{session_id}/network/clear")
async def network_clear(session_id: str) -> dict[str, Any]:
    cleared = manager.network_clear(_session_id(session_id))
    return {"cleared": cleared}


@app.get("/sessions/{session_id}/downloads")
async def downloads(session_id: str) -> list[dict[str, Any]]:
    resolved = _session_id(session_id)
    return [item.model_dump(mode="json") for item in download_manager.list(resolved)]


@app.post("/sessions/{session_id}/downloads/wait")
async def downloads_wait(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    resolved = _session_id(session_id)
    managed = manager.sessions[resolved]
    timeout_ms = int(payload.get("timeout_ms") or 300_000)
    deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
    href = None
    while asyncio.get_event_loop().time() < deadline:
        href = await _latest_export_href(managed.connection.page)
        if href:
            break
        await asyncio.sleep(2.0)
    if not href:
        raise HTTPException(status_code=404, detail="no completed export download link found")
    output = payload.get("output")
    output_dir = Path(output) if output else None
    record = await download_manager.download_url(
        session_id=resolved,
        browser_id=managed.session.browser_id,
        url=href,
        output_dir=output_dir,
    )
    return record.model_dump(mode="json")


@app.post("/forge/jobs")
async def forge_job(payload: dict[str, Any]) -> dict[str, Any]:
    trace = Path(payload["trace"])
    name = str(payload["name"])
    goal = payload.get("goal")
    root = ensure_data_dirs()
    skill_path = ForgeEngine(root / "skills").generate(trace, name, goal)
    return {"skill_path": str(skill_path)}


def _session_id(session_ref: str) -> str:
    if session_ref in manager.sessions:
        return session_ref
    for managed in manager.sessions.values():
        if managed.session.name == session_ref:
            return managed.session.session_id
    session = session_store.get(session_ref)
    if session:
        return session.session_id
    raise HTTPException(status_code=404, detail="session not found")


def _managed(session_ref: str):
    return manager.sessions[_session_id(session_ref)]


async def _latest_export_href(page) -> str | None:
    value = await page.evaluate(
        """
        () => {
          const rows = Array.from(document.querySelectorAll('#table-condition-search tbody tr'));
          for (const row of rows) {
            const text = row.innerText || '';
            if (!text.includes('已完成')) continue;
            const link = Array.from(row.querySelectorAll('a[href]')).find((a) => a.href.includes('.xlsx'));
            if (link) return link.href;
          }
          const link = Array.from(document.querySelectorAll('a[href]')).find((a) => a.href.includes('.xlsx'));
          return link ? link.href : null;
        }
        """
    )
    return str(value) if value else None
