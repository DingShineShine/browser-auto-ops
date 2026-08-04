from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from browser_auto_ops.browsers import BrowserStore, provider_config_for_browser
from browser_auto_ops.config import ensure_data_dirs
from browser_auto_ops.forge import ForgeEngine
from browser_auto_ops.intelligence import ActService, ExtractService, ObserveService
from browser_auto_ops.safety import is_dangerous_text
from browser_auto_ops.schemas import ActionRequest, BrowserIdentity, BrowserSession, ProviderConfig
from browser_auto_ops.sessions import SessionManager

app = FastAPI(title="browser-auto-ops", version="0.1.0")
manager = SessionManager()
browser_store = BrowserStore()


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
        return session
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/sessions", response_model=BrowserSession)
async def create_session(config: ProviderConfig) -> BrowserSession:
    try:
        return await manager.start(config)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    managed = manager.sessions.get(session_id)
    if not managed:
        raise HTTPException(status_code=404, detail="session not found")
    return managed.session.model_dump(mode="json")


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, Any]:
    try:
        session = await manager.stop(session_id)
        return session.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/sessions/{session_id}/state")
async def get_state(session_id: str) -> dict[str, Any]:
    try:
        return (await manager.state(session_id)).model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/sessions/{session_id}/actions")
async def run_action(session_id: str, request: ActionRequest) -> dict[str, Any]:
    try:
        result, state = await manager.action(session_id, request)
        return {
            "result": result.model_dump(mode="json"),
            "state": state.model_dump(mode="json") if state else None,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/sessions/{session_id}/observe")
async def observe(session_id: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    state = await manager.state(session_id)
    candidates = ObserveService().observe(state, str(payload.get("goal", "")))
    return [candidate.model_dump(mode="json") for candidate in candidates]


@app.post("/sessions/{session_id}/act")
async def act(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    goal = str(payload.get("goal", ""))
    confirm = bool(payload.get("confirm") or payload.get("require_confirm"))
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
    managed = manager.sessions.get(session_id)
    if not managed:
        raise HTTPException(status_code=404, detail="session not found")
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
        for item in manager.network_requests(session_id, filter_text=filter, resource_types=resource_types)
    ]


@app.get("/sessions/{session_id}/network/requests/{request_id}")
async def network_request(session_id: str, request_id: str) -> dict[str, Any] | None:
    item = manager.network_request(session_id, request_id)
    return item.model_dump(mode="json") if item else None


@app.post("/forge/jobs")
async def forge_job(payload: dict[str, Any]) -> dict[str, Any]:
    trace = Path(payload["trace"])
    name = str(payload["name"])
    goal = payload.get("goal")
    root = ensure_data_dirs()
    skill_path = ForgeEngine(root / "skills").generate(trace, name, goal)
    return {"skill_path": str(skill_path)}
