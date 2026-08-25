from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from browser_auto_ops.forge.auth import AUTH_TITLE_MARKERS, AUTH_URL_MARKERS, build_auth_precheck
from browser_auto_ops.forge.capability import apply_capability_plan, discover_capabilities
from browser_auto_ops.forge.ir import build_workflow_steps, validators_from_workflow, workflow_step_lines
from browser_auto_ops.forge.locators import _SKIP_ACTION_TYPES, accessible_name, locators_from_actions
from browser_auto_ops.forge.params import extract_parameter_candidates, extract_parameters

_AUTH_TITLE_MARKERS = AUTH_TITLE_MARKERS
_AUTH_URL_MARKERS = AUTH_URL_MARKERS
_AUTH_ACTION_MARKERS = ("email", "password", "log in", "login", "sign in", "signin")
_ISO_DATE_TEXT = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
_US_DATE_TEXT = re.compile(r"(?<!\d)\d{1,2}/\d{1,2}/\d{4}(?!\d)")
_LONG_DATE_TEXT = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b")
_FILENAME_TEMPLATE = "{filename}"
_OUTPUT_DIR_TEMPLATE = "{output_dir}"


def build_workflow(summary: dict[str, Any], name: str, goal: str) -> dict[str, Any]:
    raw_actions = summary.get("actions") or []
    actions, dropped_actions = clean_actions(raw_actions)
    locators = locators_from_actions(actions)
    auth_count = _auth_locator_count(actions, locators)
    _mark_live_current(locators, auth_count)
    parameters = extract_parameters(summary, goal)
    parameter_candidates = extract_parameter_candidates(summary, goal)
    parameters = _augment_template_parameters(parameters, parameter_candidates)
    criteria = success_criteria(summary, actions)
    last_state = summary.get("last_state") if isinstance(summary.get("last_state"), dict) else {}
    workflow_steps = build_workflow_steps(raw_actions, locators, _drop_reason, auth_count=auth_count)
    capability_plan = discover_capabilities(summary, goal, parameters)
    workflow_steps = apply_capability_plan(workflow_steps, capability_plan)
    _bind_parameters_to_steps(workflow_steps, parameters, parameter_candidates)
    _bind_runtime_outputs(workflow_steps)
    _append_artifact_steps(workflow_steps, parameters, goal)
    _mark_superseded_poll_attempts(workflow_steps)
    legacy_steps = _steps(actions, locators)
    steps = workflow_step_lines(workflow_steps) or legacy_steps
    auth_steps = legacy_steps[:auth_count]
    main_steps = steps or legacy_steps[auth_count:]
    validators = validators_from_workflow(summary, criteria, workflow_steps)
    auth = _auth_branch(locators[:auth_count], auth_steps) if auth_count else None
    auth_precheck = build_auth_precheck(workflow_steps)
    return {
        "name": name,
        "goal": goal,
        "schema_version": 2,
        "environment_hint": _environment_hint(summary),
        "session_hint": summary.get("session_name") or name,
        "start_url": _start_url(summary, actions, last_state),
        "parameters": parameters,
        "parameter_candidates": parameter_candidates,
        "requires_parameter_review": any(item.get("requires_confirmation") for item in parameter_candidates),
        "workflow_steps": workflow_steps,
        "artifacts": _artifact_contracts(workflow_steps),
        "capability_discovery": capability_plan,
        "validators": validators,
        "locators": locators,
        "steps": steps,
        "main_steps": main_steps,
        "dropped_actions": dropped_actions,
        "auth": auth,
        "auth_precheck": auth_precheck,
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
    final_title = str(last_state.get("title") or "")
    if final_title:
        rows = [item for item in rows if not item.startswith("title ==") or item == f'title == "{final_title}"']
    if not rows and (actions or summary.get("actions")):
        rows.append("recorded step checkpoints succeeded")
    return rows


def render_skill(workflow: dict[str, Any]) -> str:
    name = workflow["name"]
    goal = workflow["goal"]
    description = _yaml_string(f"Generated by browser-auto-ops Forge. Goal: {goal}")
    params_lines = "\n".join(
        _render_param(item)
        for item in workflow.get("parameters") or []
    ) or "- none extracted from this trace"
    candidate_lines = "\n".join(_render_param_candidate(item) for item in workflow.get("parameter_candidates") or [])
    candidate_block = (
        "\n\nParameter review candidates:\n"
        f"{candidate_lines}\n"
        if candidate_lines
        else ""
    )
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
    auth_precheck = workflow.get("auth_precheck") if isinstance(workflow.get("auth_precheck"), dict) else None
    auth_precheck_block = _auth_precheck_block(auth_precheck, auth)
    auth_block = _auth_block(auth)
    step_lines = []
    for index, step in enumerate(workflow.get("main_steps") or workflow.get("steps") or [], start=1):
        step_lines.append(f"{index}. {step}")
    steps_block = "\n".join(step_lines) or "- no recorded actions; use `scripts/extract.py` only to read the page"
    criteria = "\n".join(f"- {item}" for item in workflow.get("success_criteria") or []) or "- recorded step checkpoints succeeded"
    validator_lines = "\n".join(_render_validator(item) for item in workflow.get("validators") or [])
    validator_block = f"\n\nValidation layers:\n{validator_lines}" if validator_lines else ""
    api_lines = "\n".join(f"- `python scripts/{item}`" for item in workflow.get("api_scripts") or [])
    api_block = (
        f"\n## API paths\n\nIf the same network shape is still valid, prefer these captured API scripts:\n\n{api_lines}\n"
        if api_lines
        else ""
    )
    component_lines = "\n".join(f"- `python scripts/{item}`" for item in workflow.get("component_scripts") or [])
    component_block = (
        "\n## Component scripts\n\n"
        "Use these scripts as atomic helpers for parameter resolution or artifact saving. "
        "The replay workflow above remains the primary control path.\n\n"
        f"{component_lines}\n"
        if component_lines
        else ""
    )
    artifact_lines = "\n".join(_render_artifact(item) for item in workflow.get("artifacts") or [])
    artifact_block = (
        "\n## Artifact Contract\n\n"
        "Forge run should return and validate these artifacts:\n\n"
        f"{artifact_lines}\n"
        if artifact_lines
        else ""
    )
    start_url = workflow.get("start_url") or ""
    return f"""---
name: {name}
description: {description}
allowed-tools: Bash(bao:*)
metadata:
  forge_skill: true
  forge_trace: true
---

# {name}

## 目标

{goal}

## 运行参数

- Suggested session name: `{workflow.get("session_hint") or name}`
- Browser identity: pass at runtime as `<browser-name-or-id>`; do not hard-code local Chrome vs ADS/AdsPower selection in this skill.
- Start from: `{start_url}`
- For ADS/AdsPower, provide the profile id only when registering the browser identity, for example `bao browser create --type ads --name <browser-name> --ads-base-url <ads-base-url> --ads-user-id <ads-user-id>`.
- Open the browser for replay with `bao --session <name> browser open <browser-name-or-id> <start-url> --confirm`.

## 前置检查

1. Run `bao get-skills core`, then `bao get-skills explore` for observation commands and `bao get-skills forge` before generating another skill.
2. Confirm `bao daemon status` `data_root` is this repo's `.bao`.
3. Open the named session and read the returned `url` / `title` (or `bao get title`) before deciding whether credentials are needed.
4. Re-run `bao --session <name> state` after navigation. Indexes are ephemeral; do not reuse an old index.
{auth_precheck_block}
{auth_block}

## 参数

{params_lines}
{candidate_block}

## 复跑流程

{steps_block}

## 查找元素

Match role + accessible name / label / placeholder. Narrow with a container role when the same name appears more than once. Never treat a numeric index as a stable selector.

{locator_block}

## 成功标准

{criteria}
{validator_block}

## 安全

- Do not write passwords, cookies, or Ads profile ids into this skill.
- Login and other account-changing actions require `--confirm` after explicit user approval.
- `scripts/extract.py` (and legacy `capability.py`) only read the page. Do not use them as the replay path.
{artifact_block}
{component_block}
{api_block}
"""


def _yaml_string(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _render_param(item: dict[str, Any]) -> str:
    kind = f", type `{item['type']}`" if item.get("type") else ""
    details = []
    if item.get("offset_days") is not None:
        details.append(f"offset_days `{item['offset_days']}`")
    if item.get("format_hints"):
        details.append("formats " + ", ".join(f"`{value}`" for value in item["format_hints"]))
    suffix = f" — {'; '.join(details)}" if details else ""
    return f"- `--{item['name']}` (from {item['source']}{kind}): `{item['value']}`{suffix}"


def _render_param_candidate(item: dict[str, Any]) -> str:
    name = item.get("name") or "candidate"
    value = item.get("value") or ""
    binding = item.get("recommended_binding") or "recorded_constant"
    reason = item.get("reason") or ""
    return f"- `{name}` -> `{value}` ({binding}) {reason}".strip()


def _render_artifact(item: dict[str, Any]) -> str:
    name = item.get("name") or "artifact"
    filename = item.get("filename_template") or _FILENAME_TEMPLATE
    output_dir = item.get("output_dir") or _OUTPUT_DIR_TEMPLATE
    validators = item.get("validators") if isinstance(item.get("validators"), list) else []
    validator_names = ", ".join(str(validator.get("type")) for validator in validators if isinstance(validator, dict))
    suffix = f"; validators: {validator_names}" if validator_names else ""
    return f"- `{name}` from `{item.get('from_step')}` -> `{output_dir}/{filename}`{suffix}"


def _environment_hint(summary: dict[str, Any]) -> dict[str, str]:
    hint: dict[str, str] = {}
    raw_hint = summary.get("environment_hint")
    if isinstance(raw_hint, dict):
        for key in ("observed_browser_type", "observed_provider"):
            value = raw_hint.get(key)
            if value:
                hint[key] = str(value)
    if summary.get("browser_type") and "observed_browser_type" not in hint:
        hint["observed_browser_type"] = str(summary["browser_type"])
    if summary.get("provider") and "observed_provider" not in hint:
        hint["observed_provider"] = str(summary["provider"])
    return hint


def _render_validator(item: dict[str, Any]) -> str:
    kind = item.get("type") or "validator"
    if kind == "artifact":
        return "- artifact: exists and non-empty"
    if item.get("expected"):
        return f"- {kind}: `{item['expected']}`"
    if item.get("key"):
        return f"- {kind}: `{item['key']}`"
    return f"- {kind}"


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
    steps = workflow.get("workflow_steps") if isinstance(workflow.get("workflow_steps"), list) else []
    locators = workflow.get("locators") if isinstance(workflow.get("locators"), list) else []
    preserved, excluded = _classify_dropped_actions(dropped, steps)
    dropped_by_reason: dict[str, int] = {}
    for item in excluded:
        reason = str(item.get("reason") or "unknown")
        dropped_by_reason[reason] = dropped_by_reason.get(reason, 0) + 1
    replay_plan = _replay_plan(steps)
    locator_table = _locator_table(locators)
    return {
        "actions": {
            "total": len(raw_actions),
            "included": replay_plan["executable_steps"],
            "dropped": len(excluded),
            "dropped_by_reason": dropped_by_reason,
            "workflow_steps": replay_plan["total_steps"],
        },
        "replay_plan": replay_plan,
        "locator_table": locator_table,
        "workflow_schema_version": workflow.get("schema_version"),
        "validators": len(workflow.get("validators") or []),
        "parameters": workflow.get("parameters") or [],
        "parameter_candidates": workflow.get("parameter_candidates") or [],
        "requires_parameter_review": bool(workflow.get("requires_parameter_review")),
        "capability_discovery": workflow.get("capability_discovery") or {},
        "artifacts": workflow.get("artifacts") or [],
        "environment_hint": workflow.get("environment_hint") or {},
        "auth_branch": bool(workflow.get("auth")),
        "api_hints": api_scripts,
        "agents_skill_path": agents_path,
        "secrets": {
            "agents_copy_sanitized": bool(agents_path),
            "password_values_written": False,
        },
        "preserved_as_workflow_step": preserved[:20],
        "excluded_from_replay": excluded[:20],
        "dropped_actions": excluded[:20],
    }


def _replay_plan(steps: list[Any]) -> dict[str, int]:
    counts = {
        "total_steps": 0,
        "executable_steps": 0,
        "browser_actions": 0,
        "eval_helpers": 0,
        "api_calls": 0,
        "wait_conditions": 0,
        "artifact_steps": 0,
    }
    for step in steps:
        if not isinstance(step, dict):
            continue
        counts["total_steps"] += 1
        step_type = str(step.get("type") or "")
        if step_type != "fallback" and step.get("replay") is not False:
            counts["executable_steps"] += 1
        if step_type == "browser_action":
            counts["browser_actions"] += 1
        elif step_type == "eval_helper":
            counts["eval_helpers"] += 1
        elif step_type == "api_call":
            counts["api_calls"] += 1
        elif step_type == "wait_condition":
            counts["wait_conditions"] += 1
        if step_type == "artifact" or step.get("artifact"):
            counts["artifact_steps"] += 1
    return counts


def _locator_table(locators: list[Any]) -> dict[str, int]:
    rows = [item for item in locators if isinstance(item, dict)]
    live_current = [item for item in rows if item.get("live_current")]
    return {
        "strict_locators": len(rows),
        "live_current_locators": len(live_current),
        "validation_only_locators": len(rows) - len(live_current),
    }


def _classify_dropped_actions(dropped: list[Any], steps: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    replay_step_indexes = {_step_index(step) for step in steps if isinstance(step, dict) and step.get("type") != "fallback"}
    preserved: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for item in dropped:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        if row.get("index") in replay_step_indexes and row.get("reason") == "noise_action":
            row["reason"] = "preserved_as_workflow_step"
            preserved.append(row)
        else:
            excluded.append(row)
    return preserved, excluded


def _step_index(step: dict[str, Any]) -> int | None:
    raw = str(step.get("id") or "")
    match = re.match(r"s(\d+)_", raw)
    return int(match.group(1)) if match else None


def _augment_template_parameters(parameters: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = list(parameters)
    if not any(item.get("name") == "report_name" for item in rows if isinstance(item, dict)):
        template = _report_name_template(candidates, rows)
        if template:
            rows.append(
                {
                    "name": "report_name",
                    "value": template,
                    "template": template,
                    "source": "parameter_candidates",
                    "type": "template",
                }
            )
    return rows


def _report_name_template(candidates: list[dict[str, Any]], parameters: list[dict[str, Any]]) -> str:
    date_ref = _preferred_date_param(parameters, preferred="end_date")
    for item in candidates:
        if not isinstance(item, dict) or item.get("kind") != "artifact_stem":
            continue
        if item.get("binding_scope") not in {"goal_parameter", "action_input"}:
            continue
        value = str(item.get("value") or "")
        if not value:
            continue
        if not date_ref and _ISO_DATE_TEXT.search(value):
            date_ref = "end_date"
        date_match = _ISO_DATE_TEXT.search(value)
        if date_ref and date_match:
            return value.replace(date_match.group(0), f"{{{date_ref}.iso}}", 1)
        return value
    return ""


def _preferred_date_param(parameters: list[dict[str, Any]], *, preferred: str) -> str:
    date_names = [str(item.get("name")) for item in parameters if isinstance(item, dict) and item.get("type") == "date_offset" and item.get("name")]
    if preferred in date_names:
        return preferred
    return date_names[-1] if date_names else ""


def _bind_parameters_to_steps(steps: list[dict[str, Any]], parameters: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> None:
    replacements = _parameter_replacements(parameters, candidates)
    if not replacements:
        return
    replacements.sort(key=lambda item: len(item[0]), reverse=True)
    for step in steps:
        if not isinstance(step, dict):
            continue
        _bind_parameters_to_step(step, replacements)


def _bind_parameters_to_step(step: dict[str, Any], replacements: list[tuple[str, str, str]]) -> None:
    uses: dict[str, str] = {}
    _replace_step_text_fields(step, replacements, uses)
    _replace_step_request_fields(step, replacements, uses)
    if "result_preview" in step:
        step["result_preview"] = _replace_parameter_value(step["result_preview"], replacements, uses)
    if uses:
        step["uses"] = {**(step.get("uses") if isinstance(step.get("uses"), dict) else {}), **uses}


def _replace_step_text_fields(step: dict[str, Any], replacements: list[tuple[str, str, str]], uses: dict[str, str]) -> None:
    for key in ("script", "intent", "description"):
        raw = step.get(key)
        if isinstance(raw, str):
            step[key] = _replace_parameter_literals(raw, replacements, uses)


def _replace_step_request_fields(step: dict[str, Any], replacements: list[tuple[str, str, str]], uses: dict[str, str]) -> None:
    request = step.get("request")
    if not isinstance(request, dict):
        return
    for key, raw in request.items():
        if isinstance(raw, str):
            request[key] = _replace_parameter_literals(raw, replacements, uses)


def _parameter_replacements(parameters: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    rows.extend(_date_parameter_replacements(parameters, candidates))
    if any(isinstance(item, dict) and item.get("name") == "report_name" for item in parameters):
        for candidate in candidates:
            if not isinstance(candidate, dict) or candidate.get("kind") != "artifact_stem":
                continue
            if candidate.get("binding_scope") not in {"goal_parameter", "action_input"}:
                continue
            value = str(candidate.get("value") or "")
            if value:
                rows.append((value, "{report_name}", "report_name"))
    return _dedupe_replacements(rows)


def _date_parameter_replacements(parameters: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    date_names = [str(item.get("name")) for item in parameters if isinstance(item, dict) and item.get("type") == "date_offset" and item.get("name")]
    if not date_names:
        return []
    counters: dict[str, int] = {}
    rows: list[tuple[str, str, str]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("kind") != "date" or candidate.get("binding_scope") != "action_input":
            continue
        value = str(candidate.get("value") or "")
        fmt = _date_format(value)
        if not fmt:
            continue
        offset = counters.get(fmt, 0)
        counters[fmt] = offset + 1
        param_name = date_names[min(offset, len(date_names) - 1)]
        rows.append((value, f"{{{param_name}.{fmt}}}", f"{param_name}_{fmt}"))
    return rows


def _date_format(value: str) -> str:
    if _LONG_DATE_TEXT.fullmatch(value):
        return "long_en"
    if _US_DATE_TEXT.fullmatch(value):
        return "us"
    if _ISO_DATE_TEXT.fullmatch(value):
        return "iso"
    if re.fullmatch(r"\d{8}", value):
        return "compact"
    return ""


def _dedupe_replacements(rows: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str, str]] = []
    for literal, ref, name in rows:
        if literal in seen:
            continue
        seen.add(literal)
        result.append((literal, ref, name))
    return result


def _replace_parameter_literals(value: str, replacements: list[tuple[str, str, str]], uses: dict[str, str]) -> str:
    replaced = value
    for literal, ref, name in replacements:
        if literal in replaced:
            replaced = replaced.replace(literal, ref)
            uses[name] = ref
    return replaced


def _replace_parameter_value(value: Any, replacements: list[tuple[str, str, str]], uses: dict[str, str]) -> Any:
    if isinstance(value, str):
        return _replace_parameter_literals(value, replacements, uses)
    if isinstance(value, dict):
        return {key: _replace_parameter_value(item, replacements, uses) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_parameter_value(item, replacements, uses) for item in value]
    return value


def _append_artifact_steps(steps: list[dict[str, Any]], parameters: list[dict[str, Any]], goal: str) -> None:
    if any(isinstance(step, dict) and step.get("artifact") for step in steps):
        return
    if not _goal_expects_artifact(goal) and not _workflow_suggests_artifact(steps):
        return
    source_step, uses = _artifact_runtime_source(steps)
    if source_step is None and not _goal_expects_artifact(goal):
        return
    extension = _artifact_extension(goal)
    filename_template = _artifact_filename_template(parameters, extension)
    step_id = _next_artifact_step_id(steps)
    artifact = {
        "source": "browser_download",
        "source_step": source_step.get("id") if source_step else None,
        "filename_template": filename_template,
        "output_dir": _OUTPUT_DIR_TEMPLATE,
        "validators": _artifact_validators(extension),
    }
    steps.append(
        {
            "id": step_id,
            "type": "artifact",
            "artifact": artifact,
            "uses": uses,
            "intent": "download artifact to output directory",
            "description": "download generated artifact and save it to output directory",
            "replay": True,
            "purpose": "artifact",
        }
    )


def _goal_expects_artifact(goal: str) -> bool:
    lowered = (goal or "").lower()
    return any(marker in lowered for marker in ("download", "export", "save", "csv", "xlsx", "excel", "pdf", "zip"))


def _workflow_suggests_artifact(steps: list[dict[str, Any]]) -> bool:
    blob = " ".join(str(step.get(key) or "") for step in steps if isinstance(step, dict) for key in ("script", "intent", "description"))
    return any(marker in blob for marker in ("downloadReady", "download_url", "downloadUrl", "latestId"))


def _artifact_runtime_source(steps: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, str]]:
    for step in reversed(steps):
        outputs = step.get("outputs") if isinstance(step, dict) and isinstance(step.get("outputs"), dict) else {}
        uses: dict[str, str] = {}
        for name in ("download_url", "report_id", "filename"):
            if name in outputs:
                uses[name] = f"{{outputs.{step.get('id')}.{name}}}"
        if uses:
            return step, uses
    return None, {}


def _artifact_extension(goal: str) -> str:
    lowered = (goal or "").lower()
    if "csv" in lowered:
        return ".csv"
    if "xlsx" in lowered or "excel" in lowered:
        return ".xlsx"
    if "pdf" in lowered:
        return ".pdf"
    if "zip" in lowered:
        return ".zip"
    return ""


def _artifact_filename_template(parameters: list[dict[str, Any]], extension: str) -> str:
    if any(isinstance(item, dict) and item.get("name") == "report_name" for item in parameters):
        return "{report_name}" + extension
    return _FILENAME_TEMPLATE


def _artifact_validators(extension: str) -> list[dict[str, Any]]:
    rows = [{"type": "exists"}, {"type": "non_empty"}]
    if extension:
        rows.append({"type": "extension", "value": extension})
    return rows


def _next_artifact_step_id(steps: list[dict[str, Any]]) -> str:
    indexes = [_step_index(step) or 0 for step in steps if isinstance(step, dict)]
    return f"s{(max(indexes) if indexes else len(steps)) + 1}_download_artifact"


def _mark_superseded_poll_attempts(steps: list[dict[str, Any]]) -> None:
    for index, step in enumerate(steps):
        if not _is_poll_step_without_outputs(step):
            continue
        step["purpose"] = "diagnostic"
        _mark_previous_generate_diagnostic(steps, index)


def _is_poll_step_without_outputs(step: Any) -> bool:
    if not isinstance(step, dict):
        return False
    intent = str(step.get("intent") or "")
    return "poll generated row status" in intent and not step.get("outputs")


def _mark_previous_generate_diagnostic(steps: list[dict[str, Any]], poll_index: int) -> None:
    for offset in range(poll_index - 1, -1, -1):
        candidate = steps[offset]
        if not isinstance(candidate, dict):
            continue
        intent = str(candidate.get("intent") or "")
        if "poll generated row status" in intent:
            return
        if intent == "click `Generate Report`":
            candidate["purpose"] = "diagnostic"
            return


def _bind_runtime_outputs(steps: list[dict[str, Any]]) -> None:
    samples: list[tuple[str, str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        _bind_step_to_samples(step, samples)
        step_id = str(step.get("id") or "")
        output_samples = step.get("output_samples") if isinstance(step.get("output_samples"), dict) else {}
        for name, value in output_samples.items():
            if isinstance(value, str) and value:
                samples.append((step_id, str(name), value))


def _bind_step_to_samples(step: dict[str, Any], samples: list[tuple[str, str, Any]]) -> None:
    if not samples:
        return
    uses: dict[str, str] = {}
    _bind_script_to_samples(step, samples, uses)
    _bind_request_to_samples(step, samples, uses)
    if uses:
        step["uses"] = {**(step.get("uses") if isinstance(step.get("uses"), dict) else {}), **uses}


def _bind_script_to_samples(step: dict[str, Any], samples: list[tuple[str, str, Any]], uses: dict[str, str]) -> None:
    script = step.get("script")
    if not isinstance(script, str):
        return
    step["script"] = _replace_samples(script, samples, uses)


def _bind_request_to_samples(step: dict[str, Any], samples: list[tuple[str, str, Any]], uses: dict[str, str]) -> None:
    request = step.get("request")
    if not isinstance(request, dict):
        return
    for key, raw in request.items():
        if isinstance(raw, str):
            request[key] = _replace_samples(raw, samples, uses)


def _replace_samples(value: str, samples: list[tuple[str, str, Any]], uses: dict[str, str]) -> str:
    replaced = value
    for source_step, name, sample in samples:
        if sample in replaced:
            ref = f"{{outputs.{source_step}.{name}}}"
            replaced = replaced.replace(sample, ref)
            uses[name] = ref
    return replaced


def _artifact_contracts(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("artifact"), dict):
            continue
        artifact = step["artifact"]
        name = "download"
        outputs = step.get("outputs") if isinstance(step.get("outputs"), dict) else {}
        if "filename" in outputs:
            name = "download_artifact"
        artifacts.append(
            {
                "name": artifact.get("name") or name,
                "source": artifact.get("source") or step.get("type") or "runtime_output",
                "from_step": step.get("id"),
                "source_step": artifact.get("source_step"),
                "filename_template": artifact.get("filename_template") or _FILENAME_TEMPLATE,
                "output_dir": artifact.get("output_dir") or _OUTPUT_DIR_TEMPLATE,
                "validators": artifact.get("validators")
                if isinstance(artifact.get("validators"), list)
                else [{"type": "exists"}, {"type": "non_empty"}],
            }
        )
    return artifacts


def _drop_reason(action: Any) -> str | None:
    if not isinstance(action, dict):
        return "invalid_action"
    request = action.get("request") if isinstance(action.get("request"), dict) else {}
    action_type = str(request.get("type") or "")
    result = action.get("result") if isinstance(action.get("result"), dict) else {}
    if result and (result.get("success") is False or _result_semantic_failure(result.get("data"))):
        return "failed_action"
    if action_type in _SKIP_ACTION_TYPES:
        return "noise_action"
    element = action.get("element") if isinstance(action.get("element"), dict) else {}
    match = request.get("match") if isinstance(request.get("match"), dict) else None
    if action_type != "goto_url" and not element and not match:
        return "missing_target"
    return None


def _result_semantic_failure(data: Any) -> bool:
    parsed = _parse_json(data) if isinstance(data, str) else data
    if not isinstance(parsed, dict):
        return False
    return parsed.get("error") is True or parsed.get("ok") is False or parsed.get("success") is False


def _parse_json(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
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
    step_lines = "\n".join(f"{idx}. {_sanitize_auth_step(str(step))}" for idx, step in enumerate(auth.get("steps") or [], start=1))
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


def _auth_precheck_block(auth_precheck: dict[str, Any] | None, auth: dict[str, Any] | None) -> str:
    if not auth_precheck:
        return ""
    if auth:
        return """
5. If the page title or URL indicates sign-in/login, use only the captured `登录分支` below with runtime credentials. Do not invent a new login flow.
"""
    return """
5. If the page title or URL indicates sign-in/login, STOP. This skill has no captured login branch; ask the user to open a logged-in browser profile or regenerate the skill with login evidence. Do not click around or attempt an improvised login.
"""


def _sanitize_auth_step(step: str) -> str:
    lowered = step.lower()
    if "password" in lowered:
        return "input password with runtime credential"
    if "email" in lowered or "@" in step:
        return "input Email with runtime credential"
    return step


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
    goto_urls, candidates = _start_url_candidates(summary, actions, last_state)
    for url in [*goto_urls, *candidates]:
        if url and not _is_ephemeral_auth(url):
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return candidates[0] if candidates else ""


def _start_url_candidates(summary: dict[str, Any], actions: list[dict[str, Any]], last_state: dict[str, Any]) -> tuple[list[str], list[str]]:
    goto_urls: list[str] = []
    candidates: list[str] = []
    for action in actions:
        request = action.get("request") if isinstance(action.get("request"), dict) else {}
        if request.get("type") == "goto_url" and request.get("url"):
            goto_urls.append(str(request["url"]))
        for key in ("before_url", "after_url"):
            value = action.get(key)
            if value:
                candidates.append(str(value))
    if last_state.get("url"):
        candidates.append(str(last_state["url"]))
    if summary.get("start_url"):
        candidates.append(str(summary["start_url"]))
    return goto_urls, candidates


def _is_ephemeral_auth(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in ("openid-connect", "/auth/realms/", "/protocol/openid", "/login", "sign-in", "signin"))


def _new_query_keys(before: str, after: str) -> list[str]:
    if not after:
        return []
    before_keys = set(parse_qs(urlparse(before).query))
    after_keys = parse_qs(urlparse(after).query)
    return [key for key in after_keys if key not in before_keys]
