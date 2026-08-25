from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
import asyncio
from datetime import date, timedelta
import hashlib

from fastapi import FastAPI, HTTPException

from browser_auto_ops import __version__
from browser_auto_ops.browsers import BrowserStore, provider_config_for_browser
from browser_auto_ops.config import ensure_data_dirs, project_data_dir
from browser_auto_ops.downloads import DownloadManager
from browser_auto_ops.forge import ForgeEngine
from browser_auto_ops.forge.api_scripts import compact_network
from browser_auto_ops.forge.auth import auth_gate_failure
from browser_auto_ops.forge.engine import load_trace_summary
from browser_auto_ops.forge.replay import action_candidates_for_replay_step, load_workflow, workflow_replay_steps
from browser_auto_ops.forge.tester import evaluate_skill
from browser_auto_ops.intelligence import ActService, ExtractService, ObserveService
from browser_auto_ops.network import to_har
from browser_auto_ops.safety import is_dangerous_text
from browser_auto_ops.schemas import ActionRequest, BrowserIdentity, BrowserSession, ProviderConfig
from browser_auto_ops.sessions import SessionManager, SessionStore
from browser_auto_ops.sessions.payload import compact_action_payload

app = FastAPI(title="browser-auto-ops", version=__version__)
manager = SessionManager()
browser_store = BrowserStore()
session_store = SessionStore()
download_manager = DownloadManager()
_FILENAME_PLACEHOLDER = "{filename}"
_OUTPUT_DIR_PLACEHOLDER = "{output_dir}"
_DEFAULT_DOWNLOAD_NAME = "download.bin"


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


@app.post("/forge/run")
async def forge_run_job(payload: dict[str, Any]) -> dict[str, Any]:
    session_ref = payload.get("session")
    if not session_ref:
        return {"ok": False, "reason": "--session is required", "results": []}
    skill_dir = Path(payload["skill_dir"])
    include_state = bool(payload.get("include_state"))
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    output_dir = payload.get("output_dir")
    managed = _managed(str(session_ref))
    return await _replay_workflow(
        skill_dir,
        managed.session.session_id,
        include_state=include_state,
        params=params,
        output_dir=str(output_dir) if output_dir else None,
    )


async def _replay_workflow(
    skill_dir: Path,
    session_id: str,
    *,
    include_state: bool = False,
    params: dict[str, Any] | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    try:
        managed = manager.sessions[session_id]
        live = await _page_observe(managed.connection.page)
        workflow = load_workflow(skill_dir)
        gate_failure = auth_gate_failure(workflow, live)
        if gate_failure:
            return {
                "ok": False,
                "skill_dir": str(skill_dir),
                "steps": 0,
                "results": [],
                "artifacts": [],
                **gate_failure,
            }
        steps = workflow_replay_steps(workflow, live=live)
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "results": []}
    results: list[dict[str, Any]] = []
    runtime_context = _runtime_context(workflow, params=params or {}, output_dir=output_dir)
    ok = True
    for idx, step in enumerate(steps, start=1):
        item, result, state, raw = await _apply_replay_step(
            idx,
            step,
            workflow,
            session_id,
            managed,
            include_state=include_state,
            runtime_context=runtime_context,
        )
        results.append(item)
        if not item.get("success"):
            ok = False
            if result is not None and raw is not None:
                failure_state = state or await manager.state(session_id)
                screenshot_path = await _capture_replay_failure_screenshot(skill_dir, session_id, idx)
                item["screenshot"] = screenshot_path
                item["repair_suggestion"] = _write_replay_repair_suggestion(
                    skill_dir,
                    idx,
                    raw,
                    result,
                    failure_state,
                    step=step,
                    recent_results=results[-5:],
                    screenshot=screenshot_path,
                )
            break
    return {"ok": ok, "skill_dir": str(skill_dir), "steps": len(steps), "results": results, "artifacts": runtime_context["artifacts"]}


async def _apply_replay_step(
    idx: int,
    step: dict[str, Any],
    workflow: dict[str, Any],
    session_id: str,
    managed: Any,
    *,
    include_state: bool,
    runtime_context: dict[str, Any],
) -> tuple[dict[str, Any], Any, Any, dict[str, Any] | None]:
    if step.get("type") == "wait_condition":
        item = await _apply_replay_wait(managed.connection.page, step)
        _stamp_replay_item(item, idx, step)
        return item, None, None, None
    missing_uses = _missing_step_uses(step, runtime_context)
    if missing_uses:
        return _step_failure(idx, step, f"missing runtime values: {missing_uses}"), None, None, None
    if step.get("type") == "artifact":
        item = await _apply_replay_artifact_step(idx, step, session_id, managed, runtime_context)
        return item, None, None, None
    candidates = action_candidates_for_replay_step(step, workflow)
    if not candidates:
        return _step_failure(idx, step, "workflow step is not executable"), None, None, None
    return await _apply_replay_action_step(idx, step, session_id, candidates, include_state=include_state, runtime_context=runtime_context)


async def _apply_replay_action_step(
    idx: int,
    step: dict[str, Any],
    session_id: str,
    candidates: list[dict[str, Any]],
    *,
    include_state: bool,
    runtime_context: dict[str, Any],
) -> tuple[dict[str, Any], Any, Any, dict[str, Any] | None]:
    result = None
    state = None
    raw: dict[str, Any] | None = None
    resolution_path: list[dict[str, Any]] = []
    semantic_ok = False
    semantic_reason = ""
    for candidate in candidates:
        raw = _resolve_runtime_templates(candidate["action"], runtime_context)
        request = ActionRequest.model_validate(raw)
        result, state = await manager.action(session_id, request, capture_state=include_state, wait_after_action=False)
        semantic_ok, semantic_reason = _semantic_step_success(step, result)
        resolution_path.append(_resolution_attempt(candidate, raw, result, semantic_ok=semantic_ok, semantic_reason=semantic_reason))
        if semantic_ok:
            break
    if result is None or raw is None:
        return _step_failure(idx, step, "workflow step produced no executable candidates"), None, None, None
    item = compact_action_payload(result, state, include_state=include_state and state is not None)
    _stamp_replay_item(item, idx, step)
    item["success"] = semantic_ok
    if semantic_reason:
        item["reason"] = semantic_reason
    item["resolution_path"] = resolution_path
    if semantic_ok:
        _attach_runtime_step_outputs(step, result, runtime_context, item)
    return item, result, state, raw


def _stamp_replay_item(item: dict[str, Any], idx: int, step: dict[str, Any]) -> None:
    item["step"] = idx
    item["step_id"] = step.get("id")
    item["workflow_step_type"] = step.get("type")


def _step_failure(idx: int, step: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "step": idx,
        "step_id": step.get("id"),
        "workflow_step_type": step.get("type"),
        "success": False,
        "reason": reason,
    }


def _semantic_step_success(step: dict[str, Any], result: Any) -> tuple[bool, str]:
    if not bool(result.success):
        return False, str(result.message or "action failed")
    if step.get("type") not in {"eval_helper", "api_call", "assertion"}:
        return True, ""
    data = _parse_result_data(getattr(result, "data", None))
    if isinstance(step.get("failure_predicate"), dict) and _predicate_matches(data, step["failure_predicate"]):
        return False, "failure_predicate matched"
    failure_reason = _semantic_failure_reason(data)
    if failure_reason:
        return False, failure_reason
    if isinstance(step.get("success_predicate"), dict) and not _predicate_matches(data, step["success_predicate"]):
        return False, "success_predicate did not match"
    return True, ""


def _semantic_failure_reason(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    if data.get("error") is True:
        return str(data.get("message") or "helper returned error=true")
    if data.get("ok") is False:
        return str(data.get("message") or "helper returned ok=false")
    if data.get("success") is False:
        return str(data.get("message") or "helper returned success=false")
    return ""


def _predicate_matches(data: Any, predicate: dict[str, Any]) -> bool:
    path = str(predicate.get("json_path") or "")
    value = _json_path(data, path) if path else data
    if predicate.get("exists") is True:
        return value is not None
    if "equals" in predicate:
        return value == predicate.get("equals")
    return bool(value)


def _resolution_attempt(
    candidate: dict[str, Any],
    raw: dict[str, Any],
    result: Any,
    *,
    semantic_ok: bool,
    semantic_reason: str,
) -> dict[str, Any]:
    return {
        "strategy": candidate.get("strategy"),
        "success": semantic_ok,
        "message": result.message,
        "semantic_reason": semantic_reason or None,
        "request": raw,
    }


def _attach_runtime_step_outputs(step: dict[str, Any], result: Any, runtime_context: dict[str, Any], item: dict[str, Any]) -> None:
    outputs = _capture_runtime_outputs(step, result, runtime_context)
    if outputs:
        item["outputs"] = outputs
    artifact = _collect_runtime_artifact(step, result, runtime_context)
    if artifact:
        item["artifact"] = artifact
        if not _artifact_valid(artifact):
            item["success"] = False


async def _apply_replay_artifact_step(
    idx: int,
    step: dict[str, Any],
    session_id: str,
    managed: Any,
    runtime_context: dict[str, Any],
) -> dict[str, Any]:
    item = {
        "result": {"type": "artifact", "success": False, "message": "artifact not saved"},
        "success": False,
    }
    _stamp_replay_item(item, idx, step)
    artifact = await _save_runtime_download_artifact(step, session_id, managed, runtime_context)
    if not artifact:
        item["reason"] = "no completed download artifact was found"
        return item
    item["artifact"] = artifact
    item["result"] = {"type": "artifact", "success": _artifact_valid(artifact), "message": artifact.get("path")}
    item["success"] = _artifact_valid(artifact)
    return item


async def _save_runtime_download_artifact(
    step: dict[str, Any],
    session_id: str,
    managed: Any,
    runtime_context: dict[str, Any],
) -> dict[str, Any] | None:
    contract = _artifact_contract_for_step(step, runtime_context)
    output_dir = Path(_resolve_template_string(str(contract.get("output_dir") or _OUTPUT_DIR_PLACEHOLDER), runtime_context)).expanduser()
    filename = _artifact_filename({"filename": _DEFAULT_DOWNLOAD_NAME}, contract, runtime_context)
    href = await _latest_export_href(managed.connection.page)
    if href:
        record = await download_manager.download_url(
            session_id=session_id,
            browser_id=managed.session.browser_id,
            url=href,
            output_dir=output_dir,
        )
        path = _record_path(record.model_dump(mode="json"))
        if path and path.exists() and filename:
            path = _rename_artifact(path, filename)
        return _artifact_from_path(path, contract, runtime_context, source_step=step.get("id")) if path else None
    item = _latest_download_artifact(manager.network_requests(session_id, resource_types=["xhr", "fetch"]))
    if not item:
        return None
    content = _network_artifact_bytes(item)
    if content is None:
        return None
    record = download_manager.save_bytes(
        session_id=session_id,
        browser_id=managed.session.browser_id,
        source_url=str(item.get("url") or ""),
        filename=filename or _filename_from_network(item),
        content=content,
        output_dir=output_dir,
    )
    return _artifact_from_path(_record_path(record.model_dump(mode="json")), contract, runtime_context, source_step=step.get("id"))


def _record_path(record: dict[str, Any]) -> Path | None:
    path = record.get("final_path")
    return Path(str(path)) if path else None


def _rename_artifact(path: Path, filename: str) -> Path:
    target = path.with_name(Path(filename).name)
    if target == path:
        return path
    target.parent.mkdir(parents=True, exist_ok=True)
    path.replace(target)
    return target


def _artifact_from_path(path: Path | None, contract: dict[str, Any], context: dict[str, Any], *, source_step: Any) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    artifact = {
        "name": contract.get("name") or source_step or "artifact",
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_step": source_step,
        "validators": _validate_artifact(path, contract, context),
    }
    context.setdefault("artifacts", []).append(artifact)
    return artifact


def _artifact_valid(artifact: dict[str, Any]) -> bool:
    validators = artifact.get("validators")
    return isinstance(validators, list) and all(isinstance(item, dict) and item.get("ok") for item in validators)


async def _apply_replay_wait(page: Any, step: dict[str, Any]) -> dict[str, Any]:
    condition = str(step.get("condition") or "short").lower()
    timeout_ms = int(step.get("timeout_ms") or 1_000)
    try:
        if condition in {"stable", "domcontentloaded"}:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            except Exception:
                pass
            await page.wait_for_timeout(min(timeout_ms, 300))
        else:
            await page.wait_for_timeout(min(timeout_ms, 500))
        return {
            "result": {"type": "wait", "success": True, "message": f"replay wait: {condition}"},
            "checkpoint": await _page_observe(page),
            "success": True,
        }
    except Exception as exc:
        return {
            "result": {"type": "wait", "success": False, "message": str(exc)},
            "checkpoint": await _page_observe(page),
            "success": False,
        }


def _runtime_context(workflow: dict[str, Any], *, params: dict[str, Any], output_dir: str | None) -> dict[str, Any]:
    resolved = _workflow_params(workflow)
    resolved.update(params)
    resolved.setdefault("output_dir", output_dir or str(Path.home() / "Desktop"))
    _resolve_derived_params(resolved, workflow)
    return {"params": resolved, "outputs": {}, "artifacts": [], "workflow": workflow}


def _workflow_params(workflow: dict[str, Any]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for item in workflow.get("parameters") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        name = str(item["name"])
        if item.get("type") == "date_offset":
            rows[name] = _date_param_value(item)
        else:
            rows[name] = item.get("default", item.get("value"))
    return rows


def _date_param_value(item: dict[str, Any]) -> dict[str, str]:
    today = date.today()
    offset = int(item.get("offset_days") or 0)
    target = today - timedelta(days=offset)
    return {
        "token": str(item.get("value") or ""),
        "iso": target.strftime("%Y-%m-%d"),
        "us": target.strftime("%m/%d/%Y"),
        "long_en": f"{target.strftime('%B')} {target.day}, {target.year}",
        "compact": target.strftime("%Y%m%d"),
    }


def _resolve_derived_params(params: dict[str, Any], workflow: dict[str, Any]) -> None:
    for item in workflow.get("parameters") or []:
        if not isinstance(item, dict) or item.get("type") != "template" or not item.get("name"):
            continue
        template = str(item.get("template") or item.get("value") or "")
        params[str(item["name"])] = _resolve_template_string(template, {"params": params, "outputs": {}, "artifacts": []})


def _missing_step_uses(step: dict[str, Any], context: dict[str, Any]) -> list[str]:
    uses = step.get("uses") if isinstance(step.get("uses"), dict) else {}
    missing: list[str] = []
    for name, ref in uses.items():
        if isinstance(ref, str) and _lookup_runtime_value(ref.strip("{}"), context) is None:
            missing.append(str(name))
    return missing


def _resolve_runtime_templates(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_runtime_templates(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_runtime_templates(item, context) for item in value]
    if isinstance(value, str):
        return _resolve_template_string(value, context)
    return value


def _resolve_template_string(value: str, context: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        resolved = _lookup_runtime_value(match.group(1), context)
        return str(resolved) if resolved is not None else match.group(0)

    return re.sub(r"\{([^{}]+)\}", replace, value)


def _lookup_runtime_value(path: str, context: dict[str, Any]) -> Any:
    parts = path.split(".")
    if not parts:
        return None
    if parts[0] == "outputs" and len(parts) >= 3:
        current: Any = context.get("outputs", {})
        for part in parts[1:]:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current
    current = context.get("params", {})
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _capture_runtime_outputs(step: dict[str, Any], result: Any, context: dict[str, Any]) -> dict[str, Any]:
    outputs = step.get("outputs") if isinstance(step.get("outputs"), dict) else {}
    if not outputs:
        return {}
    data = _parse_result_data(getattr(result, "data", None))
    if data is None:
        return {}
    step_id = str(step.get("id") or "")
    step_outputs = context.setdefault("outputs", {}).setdefault(step_id, {})
    captured: dict[str, Any] = {}
    for name, selector in outputs.items():
        value = _json_path(data, str(selector))
        if value is not None:
            step_outputs[str(name)] = value
            captured[str(name)] = value
    return captured


def _parse_result_data(data: Any) -> Any:
    if isinstance(data, str):
        try:
            return json.loads(data)
        except Exception:
            return data
    return data


def _json_path(data: Any, selector: str) -> Any:
    if selector == "$":
        return data
    if not selector.startswith("$."):
        return None
    current = data
    for part in selector[2:].split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _collect_runtime_artifact(step: dict[str, Any], result: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    payload = _artifact_payload(getattr(result, "data", None))
    if not payload:
        return None
    contract = _artifact_contract_for_step(step, context)
    output_dir = _resolve_template_string(str(contract.get("output_dir") or _OUTPUT_DIR_PLACEHOLDER), context)
    filename = _artifact_filename(payload, contract, context)
    target = Path(output_dir).expanduser() / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    data = base64.b64decode(payload["base64"])
    target.write_bytes(data)
    artifact = {
        "name": contract.get("name") or step.get("id") or "artifact",
        "path": str(target),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "source_step": step.get("id"),
        "validators": _validate_artifact(target, contract, context),
    }
    context.setdefault("artifacts", []).append(artifact)
    return artifact


def _artifact_payload(data: Any) -> dict[str, Any] | None:
    parsed = _parse_result_data(data)
    if not isinstance(parsed, dict):
        return None
    body64 = parsed.get("base64") or parsed.get("response_body_base64")
    if not isinstance(body64, str) or not body64:
        return None
    return {
        "base64": body64,
        "filename": parsed.get("filename") or parsed.get("suggested_filename"),
        "content_type": parsed.get("contentType") or parsed.get("content_type"),
    }


def _artifact_contract_for_step(step: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    step_id = step.get("id")
    for contract in (context.get("workflow") or {}).get("artifacts") or []:
        if isinstance(contract, dict) and contract.get("from_step") == step_id:
            return contract
    return {
        "name": step_id or "artifact",
        "filename_template": _FILENAME_PLACEHOLDER,
        "output_dir": _OUTPUT_DIR_PLACEHOLDER,
        "validators": [{"type": "exists"}, {"type": "non_empty"}],
    }


def _artifact_filename(payload: dict[str, Any], contract: dict[str, Any], context: dict[str, Any]) -> str:
    payload_name = str(payload.get("filename") or _DEFAULT_DOWNLOAD_NAME)
    local_context = {
        **context,
        "params": {**context.get("params", {}), "filename": payload_name},
    }
    template = str(contract.get("filename_template") or _FILENAME_PLACEHOLDER)
    filename = _resolve_template_string(template, local_context)
    if filename == _FILENAME_PLACEHOLDER:
        filename = payload_name
    return Path(filename).name or _DEFAULT_DOWNLOAD_NAME


def _validate_artifact(path: Path, contract: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for validator in contract.get("validators") or [{"type": "exists"}, {"type": "non_empty"}]:
        if not isinstance(validator, dict):
            continue
        row = _validate_artifact_rule(path, validator, context)
        if not row:
            continue
        rows.append(row)
    return rows


def _validate_artifact_rule(path: Path, validator: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(validator.get("type") or "")
    if kind == "exists":
        return {"type": kind, "ok": path.exists(), "reason": None}
    if kind == "non_empty":
        return {"type": kind, "ok": path.exists() and path.stat().st_size > 0, "reason": None}
    if kind == "extension":
        expected = str(validator.get("value") or "")
        ok = path.suffix.lower() == expected.lower()
        return {"type": kind, "ok": ok, "reason": None if ok else f"{path.suffix!r} != {expected!r}"}
    if kind == "csv_header_contains":
        expected = str(validator.get("value") or "")
        ok = expected in _first_line(path)
        return {"type": kind, "ok": ok, "reason": None if ok else f"header does not contain {expected!r}"}
    if kind == "date_range_contains":
        return _validate_date_range_artifact(path, validator, context)
    return None


def _validate_date_range_artifact(path: Path, validator: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    start = _resolve_template_string(str(validator.get("from") or ""), context)
    end = _resolve_template_string(str(validator.get("to") or ""), context)
    ok = bool(start and end and start in text and end in text)
    return {"type": "date_range_contains", "ok": ok, "reason": None if ok else "date range values not found"}


def _first_line(path: Path) -> str:
    if not path.exists():
        return ""
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        return handle.readline().strip()


async def _capture_replay_failure_screenshot(skill_dir: Path, session_id: str, step_index: int) -> str | None:
    try:
        evidence = skill_dir / "evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        output = evidence / f"replay-failure-step-{step_index}.png"
        path = await manager.screenshot(session_id, output)
        return str(path)
    except Exception:
        return None


def _write_replay_repair_suggestion(
    skill_dir: Path,
    step_index: int,
    request: dict[str, Any],
    result: Any,
    state: Any,
    *,
    step: dict[str, Any] | None = None,
    recent_results: list[dict[str, Any]] | None = None,
    screenshot: str | None = None,
) -> str:
    evidence = skill_dir / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    state_payload = state.model_dump(mode="json") if hasattr(state, "model_dump") else {}
    payload = {
        "step": step_index,
        "step_id": (step or {}).get("id"),
        "workflow_step_type": (step or {}).get("type"),
        "description": (step or {}).get("description"),
        "failed_request": request,
        "message": getattr(result, "message", ""),
        "current_url": state_payload.get("url"),
        "current_title": state_payload.get("title"),
        "screenshot": screenshot,
        "recent_results": recent_results or [],
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
          const looksDownload = (href, text) => {
            const blob = `${href || ''} ${text || ''}`.toLowerCase();
            return /download|export|report|csv|xlsx|excel|zip|pdf/.test(blob);
          };
          const completed = (text) => /complete|completed|ready|已完成|下载/.test(String(text || '').toLowerCase());
          const rows = Array.from(document.querySelectorAll('tr, [role="row"], li, [data-row]'));
          for (const row of rows) {
            const text = row.innerText || row.textContent || '';
            if (!completed(text)) continue;
            const link = Array.from(row.querySelectorAll('a[href]')).find((a) => looksDownload(a.href, a.innerText || a.textContent));
            if (link) return link.href;
          }
          const link = Array.from(document.querySelectorAll('a[href]')).find((a) => looksDownload(a.href, a.innerText || a.textContent));
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
