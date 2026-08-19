from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from browser_auto_ops.forge.locators import _SKIP_ACTION_TYPES, accessible_name, locators_from_actions
from browser_auto_ops.forge.params import extract_parameters

_AUTH_TITLE_MARKERS = ("sign in", "login")
_AUTH_URL_MARKERS = ("/auth/", "login", "openid-connect")
_AUTH_ACTION_MARKERS = ("email", "password", "log in", "login", "sign in", "signin")


def build_workflow(summary: dict[str, Any], name: str, goal: str) -> dict[str, Any]:
    actions, dropped_actions = clean_actions(summary.get("actions") or [])
    locators = locators_from_actions(actions)
    auth_count = _auth_locator_count(actions, locators)
    _mark_live_current(locators, auth_count)
    parameters = extract_parameters(summary, goal)
    criteria = success_criteria(summary, actions)
    last_state = summary.get("last_state") if isinstance(summary.get("last_state"), dict) else {}
    steps = _steps(actions, locators)
    auth_steps = steps[:auth_count]
    main_steps = steps[auth_count:]
    return {
        "name": name,
        "goal": goal,
        "browser_type": summary.get("browser_type") or summary.get("provider") or "ads",
        "session_hint": summary.get("session_name") or name,
        "start_url": _start_url(summary, actions, last_state),
        "parameters": parameters,
        "locators": locators,
        "steps": steps,
        "main_steps": main_steps,
        "dropped_actions": dropped_actions,
        "auth": _auth_branch(locators[:auth_count], auth_steps) if auth_count else None,
        "success_criteria": criteria,
        "api_scripts": summary.get("api_scripts") or [],
        "has_actions": bool(actions),
        "last_url": last_state.get("url"),
        "last_title": last_state.get("title"),
    }


def clean_actions(raw_actions: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    included: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for index, action in enumerate(raw_actions, start=1):
        reason = _drop_reason(action)
        if reason:
            dropped.append(_dropped_action(index, action, reason))
        else:
            included.append(action)
    return included, dropped


def success_criteria(summary: dict[str, Any], actions: list[dict[str, Any]] | None = None) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for action in actions or summary.get("actions") or []:
        if not isinstance(action, dict):
            continue
        before = str(action.get("before_url") or "")
        after = str(action.get("after_url") or "")
        result = action.get("result") if isinstance(action.get("result"), dict) else {}
        verification = result.get("verification") if isinstance(result.get("verification"), dict) else {}
        after_facts = verification.get("after") if isinstance(verification.get("after"), dict) else {}
        after = str(after_facts.get("url") or after or "")
        before = str((verification.get("before") or {}).get("url") if isinstance(verification.get("before"), dict) else before)
        for key in _new_query_keys(before, after):
            line = f"url contains {key}"
            if line not in seen:
                seen.add(line)
                rows.append(line)
        before_title = str(action.get("before_title") or "")
        after_title = str(action.get("after_title") or after_facts.get("title") or "")
        if before_title and after_title and before_title != after_title:
            line = f'title == "{after_title}"'
            if line not in seen:
                seen.add(line)
                rows.append(line)
    last_state = summary.get("last_state") if isinstance(summary.get("last_state"), dict) else {}
    final_keys = set(parse_qs(urlparse(str(last_state.get("url") or "")).query))
    if final_keys:
        rows = [item for item in rows if not item.startswith("url contains ") or item.split(" ", 2)[-1] in final_keys]
    if not rows and (actions or summary.get("actions")):
        rows.append("recorded step checkpoints succeeded")
    return rows


def render_skill(workflow: dict[str, Any]) -> str:
    name = workflow["name"]
    goal = workflow["goal"]
    params_lines = "\n".join(
        f"- `--{item['name']}` (from {item['source']}): `{item['value']}`"
        for item in workflow.get("parameters") or []
    ) or "- none extracted from this trace"
    locator_lines = []
    for item in workflow.get("locators") or []:
        match = item.get("match") or {}
        within = item.get("within")
        scope = f" within {within.get('role')} `{within.get('text')}`" if within else ""
        locator_lines.append(
            f"- `{item.get('step')}`: {item.get('action')} {match.get('role') or match.get('kind')} "
            f"`{match.get('text') or match.get('label') or match.get('placeholder') or ''}`{scope}"
        )
    locator_block = "\n".join(locator_lines) or "- no recorded interactive steps"
    auth = workflow.get("auth") if isinstance(workflow.get("auth"), dict) else None
    auth_block = _auth_block(auth)
    step_lines = []
    for index, step in enumerate(workflow.get("main_steps") or workflow.get("steps") or [], start=1):
        step_lines.append(f"{index}. {step}")
    steps_block = "\n".join(step_lines) or "- no recorded actions; use `scripts/extract.py` only to read the page"
    criteria = "\n".join(f"- {item}" for item in workflow.get("success_criteria") or []) or "- recorded step checkpoints succeeded"
    api_lines = "\n".join(f"- `python scripts/{item}`" for item in workflow.get("api_scripts") or [])
    api_block = (
        f"\n## API paths\n\nIf the same network shape is still valid, prefer these captured API scripts:\n\n{api_lines}\n"
        if api_lines
        else ""
    )
    start_url = workflow.get("start_url") or ""
    return f"""---
name: {name}
description: Generated by browser-auto-ops Forge. Goal: {goal}
allowed-tools: Bash(bao:*)
metadata:
  forge_skill: true
  forge_trace: true
---

# {name}

## 目标

{goal}

## 已验证环境

- Suggested session name: `{workflow.get("session_hint") or name}`
- Browser type: `{workflow.get("browser_type") or "ads"}`
- Start from: `{start_url}`
- Ads profile id is a runtime flag (`--ads-user-id`), not a hard-coded replay prerequisite.

## 前置检查

1. Run `bao get-skills core`, then `bao get-skills explore` for observation commands and `bao get-skills forge` before generating another skill.
2. Confirm `bao daemon status` `data_root` is this repo's `.bao`.
3. Open the named session and read the returned `url` / `title` (or `bao get title`) before deciding whether credentials are needed.
4. Re-run `bao --session <name> state` after navigation. Indexes are ephemeral; do not reuse an old index.
{auth_block}

## 参数

{params_lines}

## 复跑流程

{steps_block}

## 查找元素

Match role + accessible name / label / placeholder. Narrow with a container role when the same name appears more than once. Never treat a numeric index as a stable selector.

{locator_block}

## 成功标准

{criteria}

## 安全

- Do not write passwords, cookies, or Ads profile ids into this skill.
- Login and other account-changing actions require `--confirm` after explicit user approval.
- `scripts/extract.py` (and legacy `capability.py`) only read the page. Do not use them as the replay path.
{api_block}
"""


def _steps(actions: list[dict[str, Any]], locators: list[dict[str, Any]]) -> list[str]:
    steps: list[str] = []
    for action, locator in zip(actions, locators):
        request = action.get("request") if isinstance(action.get("request"), dict) else {}
        match = locator.get("match") or {}
        label = match.get("text") or match.get("label") or match.get("placeholder") or request.get("type")
        verb = locator.get("action") or request.get("type") or "act"
        detail = ""
        if locator.get("value") and verb in {"input", "select", "open"}:
            detail = f" with `{locator['value']}`"
        elif request.get("type") == "wait":
            detail = " until the page is stable"
        within = locator.get("within")
        scope = f" inside {within.get('role')} `{within.get('text')}`" if within else ""
        steps.append(f"{verb} {match.get('role') or match.get('kind') or ''} `{label}`{scope}{detail}".strip())
        element = action.get("element") if isinstance(action.get("element"), dict) else {}
        if element:
            name = accessible_name(element)
            if name and name not in steps[-1]:
                steps[-1] = f"{verb} `{name}`{scope}{detail}".strip()
    return steps


def generation_report(
    summary: dict[str, Any],
    workflow: dict[str, Any],
    *,
    api_scripts: list[str],
    agents_path: str | None,
) -> dict[str, Any]:
    raw_actions = [item for item in (summary.get("actions") or []) if isinstance(item, dict)]
    dropped = workflow.get("dropped_actions") if isinstance(workflow.get("dropped_actions"), list) else []
    dropped_by_reason: dict[str, int] = {}
    for item in dropped:
        reason = str(item.get("reason") or "unknown")
        dropped_by_reason[reason] = dropped_by_reason.get(reason, 0) + 1
    return {
        "actions": {
            "total": len(raw_actions),
            "included": len(workflow.get("locators") or []),
            "dropped": len(dropped),
            "dropped_by_reason": dropped_by_reason,
        },
        "parameters": workflow.get("parameters") or [],
        "auth_branch": bool(workflow.get("auth")),
        "api_hints": api_scripts,
        "agents_skill_path": agents_path,
        "secrets": {
            "agents_copy_sanitized": bool(agents_path),
            "password_values_written": False,
        },
        "dropped_actions": dropped[:20],
    }


def _drop_reason(action: Any) -> str | None:
    if not isinstance(action, dict):
        return "invalid_action"
    request = action.get("request") if isinstance(action.get("request"), dict) else {}
    action_type = str(request.get("type") or "")
    if action_type in _SKIP_ACTION_TYPES:
        return "noise_action"
    result = action.get("result") if isinstance(action.get("result"), dict) else {}
    if result and result.get("success") is False:
        return "failed_action"
    element = action.get("element") if isinstance(action.get("element"), dict) else {}
    match = request.get("match") if isinstance(request.get("match"), dict) else None
    if action_type != "goto_url" and not element and not match:
        return "missing_target"
    return None


def _dropped_action(index: int, action: Any, reason: str) -> dict[str, Any]:
    request = action.get("request") if isinstance(action, dict) and isinstance(action.get("request"), dict) else {}
    result = action.get("result") if isinstance(action, dict) and isinstance(action.get("result"), dict) else {}
    return {
        "index": index,
        "reason": reason,
        "type": request.get("type") or result.get("type"),
        "message": result.get("message"),
    }


def _auth_locator_count(actions: list[dict[str, Any]], locators: list[dict[str, Any]]) -> int:
    count = 0
    auth_seen = False
    for index, action in enumerate(actions[: len(locators)]):
        if _action_looks_auth(action):
            auth_seen = True
            count = index + 1
        elif auth_seen and _before_looks_auth(action):
            count = index + 1
        elif auth_seen:
            break
        if auth_seen and _leaves_auth(action):
            break
    return count


def _auth_branch(locators: list[dict[str, Any]], steps: list[str]) -> dict[str, Any]:
    return {
        "login_required_when": {
            "title_contains": list(_AUTH_TITLE_MARKERS),
            "url_contains": list(_AUTH_URL_MARKERS),
        },
        "logged_in_when": {
            "title_not_contains": list(_AUTH_TITLE_MARKERS),
        },
        "locators": locators,
        "steps": steps,
    }


def _auth_block(auth: dict[str, Any] | None) -> str:
    if not auth:
        return ""
    step_lines = "\n".join(f"{idx}. {step}" for idx, step in enumerate(auth.get("steps") or [], start=1))
    if not step_lines:
        step_lines = "- no login steps captured"
    return f"""

## 登录分支

After opening the start URL, inspect `url` and `title`.

- If the page is already logged in, skip this section and start from `复跑流程`.
- If the page title or URL indicates sign-in/login, run the captured login steps with user-approved credentials.
- Do not persist passwords in this skill; provide them at runtime.

{step_lines}
"""


def _mark_live_current(locators: list[dict[str, Any]], auth_count: int) -> None:
    for index, locator in enumerate(locators):
        match = locator.get("match") if isinstance(locator.get("match"), dict) else {}
        is_main = index >= auth_count
        is_dialog_scoped = bool(locator.get("within"))
        is_stable_action = locator.get("action") == "click"
        role_or_kind = str(match.get("role") or match.get("kind") or "")
        locator["live_current"] = bool(is_main and is_stable_action and not is_dialog_scoped and role_or_kind in {"button", "link", "combobox"})


def _action_looks_auth(action: dict[str, Any]) -> bool:
    element = action.get("element") if isinstance(action.get("element"), dict) else {}
    request = action.get("request") if isinstance(action.get("request"), dict) else {}
    blob = " ".join(
        str(value or "")
        for value in [
            element.get("name"),
            element.get("text"),
            element.get("placeholder"),
            element.get("value"),
            request.get("text"),
            request.get("url"),
        ]
    ).lower()
    attrs = element.get("attributes") if isinstance(element.get("attributes"), dict) else {}
    blob += " " + " ".join(str(value or "") for value in attrs.values()).lower()
    return any(marker in blob for marker in _AUTH_ACTION_MARKERS)


def _before_looks_auth(action: dict[str, Any]) -> bool:
    return _facts_look_auth(action.get("before_url"), action.get("before_title")) or _verification_facts_look_auth(action, "before")


def _leaves_auth(action: dict[str, Any]) -> bool:
    return (_before_looks_auth(action) and _verification_has_non_auth_after(action)) or (
        _facts_look_auth(action.get("before_url"), action.get("before_title"))
        and not _facts_look_auth(action.get("after_url"), action.get("after_title"))
    )


def _verification_has_non_auth_after(action: dict[str, Any]) -> bool:
    result = action.get("result") if isinstance(action.get("result"), dict) else {}
    verification = result.get("verification") if isinstance(result.get("verification"), dict) else {}
    after = verification.get("after") if isinstance(verification.get("after"), dict) else {}
    return bool(after) and not _facts_look_auth(after.get("url"), after.get("title"))


def _verification_facts_look_auth(action: dict[str, Any], key: str) -> bool:
    result = action.get("result") if isinstance(action.get("result"), dict) else {}
    verification = result.get("verification") if isinstance(result.get("verification"), dict) else {}
    facts = verification.get(key) if isinstance(verification.get(key), dict) else {}
    return _facts_look_auth(facts.get("url"), facts.get("title"))


def _facts_look_auth(url: Any, title: Any) -> bool:
    blob = f"{url or ''} {title or ''}".lower()
    return any(marker in blob for marker in (*_AUTH_TITLE_MARKERS, "signin", *_AUTH_URL_MARKERS))


def _start_url(summary: dict[str, Any], actions: list[dict[str, Any]], last_state: dict[str, Any]) -> str:
    candidates: list[str] = []
    for action in actions:
        request = action.get("request") if isinstance(action.get("request"), dict) else {}
        if request.get("type") == "goto_url" and request.get("url"):
            candidates.append(str(request["url"]))
        for key in ("before_url", "after_url"):
            value = action.get(key)
            if value:
                candidates.append(str(value))
    if last_state.get("url"):
        candidates.append(str(last_state["url"]))
    if summary.get("start_url"):
        candidates.append(str(summary["start_url"]))
    for url in candidates:
        if url and not _is_ephemeral_auth(url):
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return candidates[0] if candidates else ""


def _is_ephemeral_auth(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in ("openid-connect", "/auth/realms/", "/protocol/openid", "/login", "sign-in", "signin"))


def _new_query_keys(before: str, after: str) -> list[str]:
    if not after:
        return []
    before_keys = set(parse_qs(urlparse(before).query))
    after_keys = parse_qs(urlparse(after).query)
    return [key for key in after_keys if key not in before_keys]
