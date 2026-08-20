from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any


DropReason = Callable[[Any], str | None]


def build_workflow_steps(
    raw_actions: list[Any],
    locators: list[dict[str, Any]],
    drop_reason: DropReason,
    *,
    auth_count: int = 0,
) -> list[dict[str, Any]]:
    """Build a richer replay IR without removing the legacy locator workflow.

    The v1 workflow is effectively a list of locators. Real portal work often
    depends on waits, DOM helpers, polling, or download fetches, so v2 preserves
    those actions as typed steps while keeping browser actions tied to the
    already-generated semantic locators.
    """

    steps: list[dict[str, Any]] = []
    locator_index = 0
    last_failed: dict[str, Any] | None = None
    for index, action in enumerate(raw_actions, start=1):
        facts = _action_facts(index, action, drop_reason)
        if facts is None:
            continue

        if _failed(facts["result"]):
            last_failed = _fallback_step(index, facts["request"], facts["result"], facts["reason"] or "failed_action")
            steps.append(last_failed)
            continue

        locator, locator_index, is_auth_step = _maybe_consume_locator(
            facts["reason"],
            locators,
            locator_index,
            auth_count,
        )
        step = _step_from_action(
            index,
            facts["action_type"],
            facts["action"],
            facts["request"],
            facts["result"],
            facts["reason"],
            locator,
        )
        if step is None:
            continue
        if is_auth_step:
            step["branch"] = "auth"
        last_failed = _attach_recovery(last_failed, step)
        steps.append(step)
    return steps


def _action_facts(index: int, action: Any, drop_reason: DropReason) -> dict[str, Any] | None:
    if not isinstance(action, dict):
        return None
    request = action.get("request") if isinstance(action.get("request"), dict) else {}
    result = action.get("result") if isinstance(action.get("result"), dict) else {}
    return {
        "index": index,
        "action": action,
        "request": request,
        "result": result,
        "action_type": str(request.get("type") or result.get("type") or ""),
        "reason": drop_reason(action),
    }


def _failed(result: dict[str, Any]) -> bool:
    return bool(result and result.get("success") is False)


def _maybe_consume_locator(
    reason: str | None,
    locators: list[dict[str, Any]],
    locator_index: int,
    auth_count: int,
) -> tuple[dict[str, Any] | None, int, bool]:
    if reason or locator_index >= len(locators):
        return None, locator_index, locator_index < auth_count
    locator = locators[locator_index]
    next_index = locator_index + 1
    return locator, next_index, next_index <= auth_count


def _attach_recovery(last_failed: dict[str, Any] | None, step: dict[str, Any]) -> dict[str, Any] | None:
    if last_failed is None or step.get("type") not in {"browser_action", "eval_helper", "api_call"}:
        return last_failed
    last_failed["recovered_by"] = step["id"]
    step["fallback_for"] = last_failed["id"]
    return None


def validators_from_workflow(summary: dict[str, Any], criteria: list[str], steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    validators: list[dict[str, Any]] = []
    for item in criteria:
        if item.startswith("title =="):
            validators.append({"type": "page_title", "expected": item.split("==", 1)[1].strip().strip('"')})
        elif item.startswith("url contains "):
            validators.append({"type": "url_query_key", "key": item.split(" ", 2)[-1]})
        else:
            validators.append({"type": "checkpoint", "text": item})

    if any(step.get("type") in {"api_call", "artifact"} for step in steps):
        validators.append(
            {
                "type": "artifact",
                "assertions": ["exists", "non_empty"],
                "source": "captured download or generated artifact step",
            }
        )

    last_state = summary.get("last_state") if isinstance(summary.get("last_state"), dict) else {}
    if last_state.get("title") and not any(item.get("type") == "page_title" for item in validators):
        validators.append({"type": "page_title_observed", "expected": last_state["title"]})
    return validators


def workflow_step_lines(steps: list[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for step in steps:
        if step.get("branch") == "auth":
            continue
        text = str(step.get("description") or step.get("id") or step.get("type") or "step")
        if step.get("fallback_for"):
            text += " (fallback)"
        rows.append(text)
    return rows


def step_locator(step: dict[str, Any]) -> dict[str, Any] | None:
    locator = step.get("locator")
    return locator if isinstance(locator, dict) else None


def replayable_step_actions(workflow: dict[str, Any], *, live: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    steps = workflow.get("workflow_steps")
    if not isinstance(steps, list):
        return []
    requires_auth = _live_requires_auth(live, workflow.get("auth") if isinstance(workflow.get("auth"), dict) else None)
    actions: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("branch") == "auth" and not requires_auth:
            continue
        if step.get("type") == "fallback":
            continue
        action = action_from_step(step, workflow)
        if action:
            actions.append(action)
    return actions


def action_from_step(step: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any] | None:
    step_type = str(step.get("type") or "")
    if step_type == "browser_action":
        locator = step_locator(step)
        if not locator:
            return None
        return _action_from_locator(locator, workflow)
    if step_type == "wait_condition":
        return {"type": "wait"}
    if step_type in {"eval_helper", "api_call", "assertion"} and step.get("script"):
        action = {"type": "execute_js", "script": step.get("script") or ""}
        if step.get("require_confirm"):
            action["require_confirm"] = True
        return action
    return None


def _step_from_action(
    index: int,
    action_type: str,
    action: dict[str, Any],
    request: dict[str, Any],
    result: dict[str, Any],
    reason: str | None,
    locator: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if locator is not None:
        return {
            "id": _step_id(index, locator.get("step") or action_type or "action"),
            "type": "browser_action",
            "action": locator.get("action") or action_type,
            "locator": locator,
            "request": _public_request(request),
            "checkpoint": action.get("checkpoint"),
            "description": _browser_description(locator, request),
            "replay": True,
        }
    if action_type == "wait":
        return {
            "id": _step_id(index, "wait"),
            "type": "wait_condition",
            "condition": "stable",
            "description": "wait until the page is stable",
            "replay": True,
        }
    if action_type == "execute_js":
        return _execute_js_step(index, request, result)
    if action_type == "screenshot":
        return {
            "id": _step_id(index, "screenshot"),
            "type": "artifact",
            "artifact": "screenshot",
            "description": "capture a screenshot for visual inspection",
            "replay": False,
        }
    if action_type == "extract":
        return {
            "id": _step_id(index, "extract"),
            "type": "assertion",
            "description": "extract page content for verification",
            "replay": False,
        }
    if reason == "missing_target" and action_type:
        return {
            "id": _step_id(index, action_type),
            "type": "eval_helper" if request.get("script") else "browser_action_unresolved",
            "request": _public_request(request),
            "description": f"unresolved {action_type} action kept for repair",
            "replay": False,
        }
    return None


def _execute_js_step(index: int, request: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    script = str(request.get("script") or "")
    data = result.get("data")
    kind = _execute_js_kind(script, data)
    step: dict[str, Any] = {
        "id": _step_id(index, kind),
        "type": kind,
        "script": script,
        "request": _public_request(request),
        "result_preview": _result_preview(data),
        "description": _execute_js_description(kind, script, data),
        "replay": kind in {"eval_helper", "api_call", "assertion"},
    }
    if request.get("require_confirm") or kind == "api_call":
        step["require_confirm"] = bool(request.get("require_confirm"))
    if kind == "api_call" and _result_has_base64(data):
        step["artifact"] = {"encoding": "base64", "source": "page_fetch"}
    return step


def _execute_js_kind(script: str, data: Any) -> str:
    blob = f"{script} {_jsonish(data)}".lower()
    if "fetch(" in blob or "/download" in blob or "base64" in blob or "arraybuffer" in blob:
        return "api_call"
    if any(marker in blob for marker in (".click(", "dispatchEvent", "scrollTop", "querySelector", "getPropertyDescriptor")):
        return "eval_helper"
    return "assertion"


def _execute_js_description(kind: str, script: str, data: Any) -> str:
    if kind == "api_call":
        return "execute an authenticated page API call and capture its result"
    if kind == "eval_helper":
        return "run a DOM helper that cannot be represented as a stable locator"
    preview = _result_preview(data)
    if isinstance(preview, dict) and preview:
        return "assert page state from JavaScript result"
    if "document.title" in script:
        return "assert current page title"
    return "inspect page state with JavaScript"


def _fallback_step(index: int, request: dict[str, Any], result: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "id": _step_id(index, "fallback"),
        "type": "fallback",
        "reason": reason,
        "request": _public_request(request),
        "message": result.get("message"),
        "description": f"record failed {request.get('type') or result.get('type') or 'action'} for repair and fallback",
        "replay": False,
    }


def _browser_description(locator: dict[str, Any], request: dict[str, Any]) -> str:
    match = locator.get("match") if isinstance(locator.get("match"), dict) else {}
    label = match.get("text") or match.get("label") or match.get("placeholder") or match.get("name") or request.get("type") or "target"
    action = locator.get("action") or request.get("type") or "act"
    if locator.get("value") and action in {"input", "select", "open"}:
        return f"{action} `{label}` with `{locator['value']}`"
    within = locator.get("within") if isinstance(locator.get("within"), dict) else None
    scope = f" inside {within.get('role')} `{within.get('text')}`" if within else ""
    return f"{action} `{label}`{scope}"


def _public_request(request: dict[str, Any]) -> dict[str, Any]:
    keep = {"type", "match", "text", "option", "url", "direction", "amount", "key", "require_confirm"}
    public = {key: value for key, value in request.items() if key in keep and value not in (None, "")}
    if request.get("script"):
        public["script_kind"] = _script_kind(str(request.get("script") or ""))
    return public


def _action_from_locator(locator: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any] | None:
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
    if action == "scroll":
        return {"type": "scroll", "direction": locator.get("direction") or "down"}
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


def _live_requires_auth(live: dict[str, Any] | None, auth: dict[str, Any] | None) -> bool:
    if not live or not auth:
        return False
    blob = f"{live.get('url') or ''} {live.get('title') or ''}".lower()
    rules = auth.get("login_required_when") if isinstance(auth.get("login_required_when"), dict) else {}
    return any(str(value).lower() in blob for value in rules.get("title_contains") or []) or any(
        str(value).lower() in blob for value in rules.get("url_contains") or []
    )


def _script_kind(script: str) -> str:
    if len(script) > 500:
        return "long"
    if "fetch(" in script:
        return "fetch"
    if "querySelector" in script:
        return "dom"
    return "js"


def _result_preview(data: Any) -> Any:
    if isinstance(data, str):
        return _preview_string(data)
    if isinstance(data, dict):
        return _preview_dict(data)
    if isinstance(data, list):
        return [_result_preview(item) for item in data[:5]]
    return data


def _preview_string(data: str) -> Any:
    parsed = _parse_json(data)
    if parsed is not None:
        return _result_preview(parsed)
    return data[:200] + ("..." if len(data) > 200 else "")


def _preview_dict(data: dict[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for key, value in data.items():
        preview[key] = _preview_value(key, value)
    return preview


def _preview_value(key: str, value: Any) -> Any:
    if key == "base64":
        return f"<base64:{len(str(value))} chars>"
    if isinstance(value, str):
        return value[:160] + ("..." if len(value) > 160 else "")
    return value


def _result_has_base64(data: Any) -> bool:
    parsed = _parse_json(data) if isinstance(data, str) else data
    return isinstance(parsed, dict) and bool(parsed.get("base64") or parsed.get("response_body_base64"))


def _parse_json(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return None


def _jsonish(value: Any) -> str:
    if isinstance(value, str):
        return value[:1000]
    try:
        return json.dumps(value, ensure_ascii=False)[:1000]
    except Exception:
        return str(value)[:1000]


def _step_id(index: int, label: Any) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(label or "step").lower()).strip("_")
    return f"s{index}_{slug[:48] or 'step'}"
