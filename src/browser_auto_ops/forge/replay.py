from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from browser_auto_ops.forge.ir import action_from_step, replayable_step_actions, step_locator
from browser_auto_ops.forge.locators import relaxed_match_payloads


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


def workflow_replay_steps(workflow: dict[str, Any], *, live: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return executable workflow steps while preserving step metadata.

    `workflow_actions` is kept for older callers that only need ActionRequest
    payloads. The replay runner needs step ids, types, and wait conditions so
    failures can point at the exact generated workflow step.
    """

    steps = workflow.get("workflow_steps")
    if isinstance(steps, list):
        rows = _workflow_step_rows(workflow, steps, live)
        if rows:
            return rows

    rows = []
    for idx, action in enumerate(workflow_actions(workflow, live=live), start=1):
        rows.append(
            {
                "id": f"legacy_{idx}",
                "type": "browser_action",
                "description": action.get("type") or "legacy action",
                "legacy_action": action,
            }
        )
    return rows


def _workflow_step_rows(workflow: dict[str, Any], steps: list[Any], live: dict[str, Any] | None) -> list[dict[str, Any]]:
    requires_auth = _live_requires_auth(live, workflow.get("auth") if isinstance(workflow.get("auth"), dict) else None)
    rows: list[dict[str, Any]] = []
    for step in steps:
        if _is_replayable_step(step, workflow, requires_auth):
            rows.append(step)
    return rows


def _is_replayable_step(step: Any, workflow: dict[str, Any], requires_auth: bool) -> bool:
    if not isinstance(step, dict):
        return False
    if step.get("branch") == "auth" and not requires_auth:
        return False
    if step.get("type") == "fallback":
        return False
    if step.get("replay") is False:
        return False
    if step.get("type") == "artifact":
        return True
    return step.get("type") == "wait_condition" or bool(action_from_step(step, workflow))


def action_for_replay_step(step: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any] | None:
    if step.get("legacy_action"):
        action = step["legacy_action"]
        return action if isinstance(action, dict) else None
    if step.get("type") == "wait_condition":
        return None
    return action_from_step(step, workflow)


def action_candidates_for_replay_step(step: dict[str, Any], workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """Return ordered replay action candidates with resolution labels."""

    action = action_for_replay_step(step, workflow)
    if not action:
        return []
    candidates = [{"strategy": _primary_strategy(step), "action": action}]
    if step.get("type") != "browser_action":
        return candidates
    locator = step_locator(step)
    if not locator:
        return candidates
    strict = _action_from_locator(locator, workflow)
    if strict:
        candidates.append({"strategy": "strict_locator", "action": strict})
    for match in relaxed_match_payloads(locator):
        relaxed = _action_from_locator({**locator, "match": match, "within": None}, workflow)
        if relaxed:
            candidates.append({"strategy": _relaxed_strategy(match), "action": relaxed})
    return _dedupe_action_candidates(candidates)


def _primary_strategy(step: dict[str, Any]) -> str:
    if isinstance(step.get("request"), dict):
        return "recorded_request"
    if step.get("legacy_action"):
        return "legacy_action"
    return "workflow_step"


def _relaxed_strategy(match: dict[str, Any]) -> str:
    if "kind" not in match and any(key in match for key in ("text", "name", "label", "placeholder")):
        if any(match.get(f"{key}_mode") == "contains" for key in ("text", "name", "label", "placeholder")):
            return "relaxed_locator_contains"
        return "relaxed_locator_without_kind"
    if match.get("name"):
        return "role_name_contains"
    if match.get("text_mode") == "starts_with":
        return "scoped_shortest_unique_text"
    return "relaxed_locator"


def _dedupe_action_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for item in candidates:
        action = item.get("action")
        try:
            key = json.dumps(action, sort_keys=True, ensure_ascii=False)
        except Exception:
            key = str(action)
        if key in seen:
            continue
        seen.add(key)
        rows.append(item)
    return rows


def _locators_for_live_state(workflow: dict[str, Any], live: dict[str, Any] | None) -> list[Any]:
    locators = workflow.get("locators") if isinstance(workflow.get("locators"), list) else []
    auth = workflow.get("auth") if isinstance(workflow.get("auth"), dict) else None
    if not auth:
        return locators
    auth_locators = auth.get("locators") if isinstance(auth.get("locators"), list) else []
    main_locators = locators[len(auth_locators) :]
    return auth_locators + main_locators if _live_requires_auth(live, auth) else main_locators


def _live_requires_auth(live: dict[str, Any] | None, auth: dict[str, Any] | None) -> bool:
    if not live or not auth:
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
