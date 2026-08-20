from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
import asyncio

from fastapi import FastAPI, HTTPException

from browser_auto_ops import __version__
from browser_auto_ops.browsers import BrowserStore, provider_config_for_browser
from browser_auto_ops.config import ensure_data_dirs, project_data_dir
from browser_auto_ops.downloads import DownloadManager
from browser_auto_ops.forge import ForgeEngine
from browser_auto_ops.forge.api_scripts import compact_network
from browser_auto_ops.forge.engine import load_trace_summary
from browser_auto_ops.forge.replay import load_workflow, workflow_actions
from browser_auto_ops.forge.tester import evaluate_skill
from browser_auto_ops.intelligence import ActService, ExtractService, ObserveService
from browser_auto_ops.network import to_har
from browser_auto_ops.safety import is_dangerous_text
from browser_auto_ops.schemas import ActionRequest, BrowserIdentity, BrowserSession, ProviderConfig
from browser_auto_ops.sessions import SessionManager, SessionStore
from browser_auto_ops.sessions.payload import compact_action_payload

app = FastAPI(title="browser-auto-ops", version="0.1.0")
manager = SessionManager()
browser_store = BrowserStore()
session_store = SessionStore()
download_manager = DownloadManager()


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "sessions": len(manager.sessions),
        "data_root": str(project_data_dir()),
        "cwd": str(Path.cwd()),
        "version": __version__,
        "import_path": str(Path(__file__).resolve()),
        "python": __import__("sys").version.split()[0],
    }


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


@app.post("/browsers/{browser_id_or_name}/open")
async def open_browser(browser_id_or_name: str, payload: dict[str, Any]) -> dict[str, Any]:
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
        observe = await _page_observe(manager.sessions[session.session_id].connection.page)
        return {"session": session.model_dump(mode="json"), **observe}
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
async def run_action(session_id: str, request: ActionRequest, include_state: bool = False) -> dict[str, Any]:
    try:
        result, state = await manager.action(_session_id(session_id), request)
        return compact_action_payload(result, state, include_state=include_state)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/sessions/{session_id}/batch")
async def run_batch(session_id: str, payload: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    try:
        include_state = bool(payload.get("include_state")) if isinstance(payload, dict) else False
        bail = bool(payload.get("bail")) if isinstance(payload, dict) else False
        raw_actions = payload.get("actions") if isinstance(payload, dict) else payload
        if not isinstance(raw_actions, list):
            raise ValueError("batch payload must be a list or {actions: [...]}")
        resolved = _session_id(session_id)
        results: list[dict[str, Any]] = []
        ok = True
        for idx, raw in enumerate(raw_actions, start=1):
            request = ActionRequest.model_validate(raw)
            result, state = await manager.action(resolved, request)
            item = compact_action_payload(result, state, include_state=include_state)
            item["step"] = idx
            item["success"] = bool(result.success)
            results.append(item)
            if not result.success:
                ok = False
                if bail:
                    break
        return {"ok": ok, "results": results}
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


@app.get("/sessions/{session_id}/network/har")
async def network_har(session_id: str, type: str | None = None, filter: str | None = None) -> dict[str, Any]:
    resource_types = type.split(",") if type else None
    items = manager.network_requests(_session_id(session_id), filter_text=filter, resource_types=resource_types)
    return to_har(items)


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
    output = payload.get("output")
    output_dir = Path(output) if output else None
    if not href:
        item = _latest_download_artifact(manager.network_requests(resolved, resource_types=["xhr", "fetch"]))
        if not item:
            raise HTTPException(status_code=404, detail="no completed export download link or downloadable network artifact found")
        content = _network_artifact_bytes(item)
        if content is None:
            raise HTTPException(status_code=404, detail="downloadable network artifact has no captured response body")
        record = download_manager.save_bytes(
            session_id=resolved,
            browser_id=managed.session.browser_id,
            source_url=str(item.get("url") or ""),
            filename=str(payload.get("filename") or _filename_from_network(item)),
            content=content,
            output_dir=output_dir,
        )
        return record.model_dump(mode="json")
    record = await download_manager.download_url(
        session_id=resolved,
        browser_id=managed.session.browser_id,
        url=href,
        output_dir=output_dir,
    )
    return record.model_dump(mode="json")


@app.get("/sessions/{session_id}/trace")
async def session_trace(session_id: str) -> dict[str, Any]:
    managed = _managed(session_id)
    network = compact_network([item.model_dump(mode="json") for item in manager.network_requests(_session_id(session_id), resource_types=["xhr", "fetch"])])
    managed.trace.save_json("network", "snapshot.json", network)
    summary = load_trace_summary(managed.trace.root)
    return {
        "trace_dir": str(managed.trace.root),
        "events": summary.get("events", 0),
        "event_types": summary.get("event_types", {}),
        "network": network,
    }


@app.post("/sessions/{session_id}/forge/explore")
async def forge_explore_session(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    managed = _managed(session_id)
    goal = str(payload.get("goal") or "")
    page_state = await manager.state(_session_id(session_id))
    managed.trace.event("forge.explore", {"goal": goal, "state": page_state})
    return {"trace_dir": str(managed.trace.root), "goal": goal, "url": page_state.url, "title": page_state.title}


@app.post("/forge/jobs")
@app.post("/forge/generate")
async def forge_job(payload: dict[str, Any]) -> dict[str, Any]:
    session_ref = payload.get("session")
    if session_ref:
        managed = _managed(str(session_ref))
        network = compact_network(
            [item.model_dump(mode="json") for item in manager.network_requests(_session_id(str(session_ref)), resource_types=["xhr", "fetch"])]
        )
        managed.trace.save_json("network", "snapshot.json", network)
        trace = managed.trace.root
        session_name = managed.session.name
        browser_type = None
    else:
        trace = Path(payload["trace"])
        network = None
        session_name = payload.get("session_name")
        browser_type = payload.get("browser_type")
    name = str(payload["name"])
    goal = payload.get("goal")
    root = ensure_data_dirs()
    skill_path = ForgeEngine(root / "skills").generate(
        trace,
        name,
        goal,
        network=network,
        session_name=session_name,
        browser_type=browser_type,
    )
    return {"skill_path": str(skill_path), "generation_report": _read_generation_report(skill_path)}


@app.post("/forge/test")
async def forge_test_job(payload: dict[str, Any]) -> dict[str, Any]:
    skill_dir = Path(payload["skill_dir"])
    session_ref = payload.get("session")
    replay = bool(payload.get("replay"))
    live = None
    state = None
    replay_result = None
    if replay and not session_ref:
        return {"ok": False, "skill_dir": str(skill_dir), "checks": [{"name": "replay", "ok": False, "reason": "--replay requires session"}]}
    if session_ref:
        try:
            managed = _managed(str(session_ref))
            if replay:
                replay_result = await _replay_workflow(skill_dir, managed.session.session_id)
            live = await _page_observe(managed.connection.page)
            state = (await manager.state(managed.session.session_id)).model_dump(mode="json")
        except Exception:
            live = None
    result = evaluate_skill(skill_dir, live=live, state=state)
    if replay_result is not None:
        replay_ok = bool(replay_result.get("ok"))
        result["checks"].append({"name": "replay", "ok": replay_ok, "result": replay_result})
        result["ok"] = bool(result.get("ok")) and replay_ok
    return result


async def _replay_workflow(skill_dir: Path, session_id: str) -> dict[str, Any]:
    try:
        managed = manager.sessions[session_id]
        live = await _page_observe(managed.connection.page)
        workflow = load_workflow(skill_dir)
        actions = workflow_actions(workflow, live=live)
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "results": []}
    results: list[dict[str, Any]] = []
    ok = True
    for idx, raw in enumerate(actions, start=1):
        request = ActionRequest.model_validate(raw)
        result, state = await manager.action(session_id, request)
        item = compact_action_payload(result, state, include_state=False)
        item["step"] = idx
        item["success"] = bool(result.success)
        results.append(item)
        if not result.success:
            ok = False
            item["repair_suggestion"] = _write_replay_repair_suggestion(skill_dir, idx, raw, result, state)
            break
    return {"ok": ok, "results": results}


def _write_replay_repair_suggestion(
    skill_dir: Path,
    step_index: int,
    request: dict[str, Any],
    result: Any,
    state: Any,
) -> str:
    evidence = skill_dir / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    state_payload = state.model_dump(mode="json") if hasattr(state, "model_dump") else {}
    payload = {
        "step": step_index,
        "failed_request": request,
        "message": getattr(result, "message", ""),
        "current_url": state_payload.get("url"),
        "current_title": state_payload.get("title"),
        "suggestions": [
            "Run `bao state` and prefer role/name/label/placeholder over @eN or numeric indexes.",
            "If multiple controls match, add a stable `within` container or shortest unique text prefix.",
            "If the action was a DOM/API helper, keep it as an eval_helper/api_call step with an explicit assertion.",
        ],
    }
    path = evidence / "repair-suggestion.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


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


def _read_generation_report(skill_path: Path) -> dict[str, Any]:
    path = skill_path / "evidence" / "generation-report.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


async def _page_observe(page) -> dict[str, str]:
    url = str(getattr(page, "url", "") or "")
    title = ""
    getter = getattr(page, "title", None)
    if callable(getter):
        try:
            title = str(await getter())
        except Exception:
            title = ""
    return {"url": url, "title": title}


def _checkpoint_from_verification(verification: dict[str, Any] | None) -> dict[str, Any]:
    payload = verification or {}
    after = payload.get("after") if isinstance(payload.get("after"), dict) else {}
    return {
        "url": after.get("url"),
        "title": after.get("title"),
        "url_changed": bool(payload.get("url_changed")),
        "title_changed": bool(payload.get("title_changed")),
    }


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


def _latest_download_artifact(items: list[Any]) -> dict[str, Any] | None:
    for raw in reversed(items):
        item = raw.model_dump(mode="json") if hasattr(raw, "model_dump") else raw
        if isinstance(item, dict) and _looks_downloadable(item):
            return item
    return None


def _looks_downloadable(item: dict[str, Any]) -> bool:
    headers = item.get("response_headers") if isinstance(item.get("response_headers"), dict) else {}
    content_type = str(headers.get("content-type") or headers.get("Content-Type") or "").lower()
    disposition = str(headers.get("content-disposition") or headers.get("Content-Disposition") or "").lower()
    url = str(item.get("url") or "").lower()
    if "attachment" in disposition or "filename=" in disposition:
        return True
    if any(marker in content_type for marker in ("csv", "excel", "spreadsheet", "zip", "octet-stream")):
        return True
    return any(marker in url for marker in ("/download", "download", "export", "report")) and bool(
        item.get("response_body_base64") or item.get("response_body")
    )


def _network_artifact_bytes(item: dict[str, Any]) -> bytes | None:
    body64 = item.get("response_body_base64")
    if isinstance(body64, str) and body64:
        try:
            return base64.b64decode(body64)
        except Exception:
            return None
    body = item.get("response_body")
    if isinstance(body, str):
        return body.encode("utf-8")
    return None


def _filename_from_network(item: dict[str, Any]) -> str:
    headers = item.get("response_headers") if isinstance(item.get("response_headers"), dict) else {}
    disposition = str(headers.get("content-disposition") or headers.get("Content-Disposition") or "")
    for part in disposition.split(";"):
        if "filename" not in part.lower():
            continue
        _, _, value = part.partition("=")
        cleaned = value.strip().strip('"')
        if cleaned:
            return cleaned
    name = Path(unquote(urlparse(str(item.get("url") or "")).path)).name
    return name or "download.bin"
