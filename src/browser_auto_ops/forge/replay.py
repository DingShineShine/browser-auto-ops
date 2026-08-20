from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from browser_auto_ops.forge.ir import replayable_step_actions


def load_workflow(path_or_skill_dir: Path) -> dict[str, Any]:
    path = path_or_skill_dir
    if path.is_dir():
        path = path / "evidence" / "workflow.json"
    if not path.exists():
        raise FileNotFoundError(f"workflow not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def workflow_actions(workflow: dict[str, Any], *, live: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    step_actions = replayable_step_actions(workflow, live=live)
    if step_actions:
        return step_actions
    locators = _locators_for_live_state(workflow, live)
    actions: list[dict[str, Any]] = []
    for locator in locators:
        action = _action_from_locator(locator, workflow)
        if action:
            actions.append(action)
    return actions


def _locators_for_live_state(workflow: dict[str, Any], live: dict[str, Any] | None) -> list[Any]:
    locators = workflow.get("locators") if isinstance(workflow.get("locators"), list) else []
    auth = workflow.get("auth") if isinstance(workflow.get("auth"), dict) else None
    if not auth:
        return locators
    auth_locators = auth.get("locators") if isinstance(auth.get("locators"), list) else []
    main_locators = locators[len(auth_locators) :]
    return auth_locators + main_locators if _live_requires_auth(live, auth) else main_locators


def _live_requires_auth(live: dict[str, Any] | None, auth: dict[str, Any]) -> bool:
    if not live:
        return False
    blob = f"{live.get('url') or ''} {live.get('title') or ''}".lower()
    rules = auth.get("login_required_when") if isinstance(auth.get("login_required_when"), dict) else {}
    for value in rules.get("title_contains") or []:
        if str(value).lower() in blob:
            return True
    for value in rules.get("url_contains") or []:
        if str(value).lower() in blob:
            return True
    return False


def _action_from_locator(locator: Any, workflow: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(locator, dict):
        return None
    action = str(locator.get("action") or "click")
    match_payload = _match_payload(locator)
    if action == "input":
        return {"type": "input_text", "match": match_payload, "text": locator.get("value") or ""}
    if action == "select":
        return {"type": "select_option", "match": match_payload, "option": locator.get("value") or ""}
    if action == "open":
        return {"type": "goto_url", "url": locator.get("value") or workflow.get("start_url") or ""}
    if action == "click":
        return {"type": "click", "match": match_payload}
    return None


def _match_payload(locator: dict[str, Any]) -> dict[str, Any]:
    match = locator.get("match") if isinstance(locator.get("match"), dict) else {}
    within = locator.get("within") if isinstance(locator.get("within"), dict) else None
    payload = dict(match)
    if within:
        payload["within_role"] = within.get("role")
        payload["within_text"] = within.get("text")
        if within.get("text_mode"):
            payload["within_text_mode"] = within.get("text_mode")
    return payload
