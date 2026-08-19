from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable
import json
from urllib.parse import parse_qs, urlparse

from browser_auto_ops.schemas import ElementMatch, PageState
from browser_auto_ops.snapshot.resolve import find_all

_INDEX_IN_SKILL = re.compile(r"(?i)(?:\bclick\s+\d+\b|\bindex\s*[:=]\s*\d+)")


def evaluate_skill(
    skill_dir: Path,
    *,
    live: dict[str, Any] | None = None,
    state: PageState | dict[str, Any] | None = None,
    inspect: Callable[[], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    skill_md = skill_dir / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8") if skill_md.exists() else ""
    checks = [
        {"name": "skill_md_present", "ok": skill_md.exists()},
        {"name": "replay_steps_present", "ok": _has_replay(text)},
        {"name": "no_ephemeral_index", "ok": not _INDEX_IN_SKILL.search(text)},
        {"name": "success_criteria_present", "ok": "成功标准" in text or "success" in text.lower()},
        {"name": "locator_table_present", "ok": "查找元素" in text or "locator" in text.lower()},
    ]
    workflow = _load_workflow(skill_dir)
    criteria = _criteria_from_workflow_or_text(workflow, text)
    locators = workflow.get("locators") if isinstance(workflow.get("locators"), list) else []
    live_payload, live_reason = _resolve_live(live, inspect)
    if live_payload is not None:
        checks.extend(_live_checks(live_payload, criteria, locators, state))
    else:
        checks.append({"name": "live_inspect", "ok": False, "reason": live_reason})
    live_names = {"live_inspect", "live_url_criteria", "live_title_criteria", "live_controls"}
    static_ok = all(item["ok"] for item in checks if item["name"] not in live_names)
    live_ok = all(item["ok"] for item in checks if item["name"] in live_names) if live_payload is not None else True
    return {
        "ok": static_ok and live_ok,
        "skill_dir": str(skill_dir),
        "checks": checks,
    }


def _resolve_live(
    live: dict[str, Any] | None,
    inspect: Callable[[], dict[str, Any] | None] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    if live is not None or inspect is None:
        return live, "no session"
    try:
        payload = inspect()
        return payload, None if payload else "inspect returned empty"
    except Exception as exc:
        return None, str(exc)


def _live_checks(
    live_payload: dict[str, Any],
    criteria: list[str],
    locators: list[Any],
    state: PageState | dict[str, Any] | None,
) -> list[dict[str, Any]]:
    checks = [{"name": "live_inspect", "ok": bool(live_payload.get("url") or live_payload.get("title")), "reason": None}]
    checks.extend(_live_criteria_checks(criteria, live_payload))
    if state is not None:
        checks.append(_live_controls_check(locators, state))
    return checks


def _has_replay(text: str) -> bool:
    if "复跑流程" in text:
        section = text.split("## 复跑流程", 1)[1].split("## ", 1)[0]
    elif re.search(r"(?im)^##\s+replay", text):
        section = re.split(r"(?im)^##\s+replay.*$", text, maxsplit=1)[-1].split("## ", 1)[0]
    else:
        return False
    if "no recorded action" in section.lower():
        return False
    return bool(re.search(r"(?m)^\d+\.\s+\S+", section))


def _load_workflow(skill_dir: Path) -> dict[str, Any]:
    path = skill_dir / "evidence" / "workflow.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _criteria_from_workflow_or_text(workflow: dict[str, Any], text: str) -> list[str]:
    criteria = workflow.get("success_criteria")
    if isinstance(criteria, list):
        return [str(item) for item in criteria]
    if "## 成功标准" not in text:
        return []
    section = text.split("## 成功标准", 1)[1].split("## ", 1)[0]
    return [line.strip("- ").strip() for line in section.splitlines() if line.strip().startswith("-")]


def _live_criteria_checks(criteria: list[str], live: dict[str, Any]) -> list[dict[str, Any]]:
    url_checks = [item for item in criteria if item.startswith("url contains ")]
    title_checks = [item for item in criteria if item.startswith("title ==")]
    rows: list[dict[str, Any]] = []
    if url_checks:
        query = set(parse_qs(urlparse(str(live.get("url") or "")).query))
        missing = [item.split(" ", 2)[-1] for item in url_checks if item.split(" ", 2)[-1] not in query]
        rows.append({"name": "live_url_criteria", "ok": not missing, "reason": f"missing query keys: {missing}" if missing else None})
    if title_checks:
        expected = [item.split("==", 1)[1].strip().strip('"') for item in title_checks]
        title = str(live.get("title") or "")
        missing_titles = [item for item in expected if item != title]
        rows.append({"name": "live_title_criteria", "ok": not missing_titles, "reason": f"title {title!r} != {missing_titles}" if missing_titles else None})
    return rows


def _live_controls_check(locators: list[Any], state: PageState | dict[str, Any]) -> dict[str, Any]:
    page_state = state if isinstance(state, PageState) else PageState.model_validate(state)
    missing: list[dict[str, Any]] = []
    checked = 0
    for locator in locators:
        if not isinstance(locator, dict) or not isinstance(locator.get("match"), dict):
            continue
        if not locator.get("live_current"):
            continue
        checked += 1
        match_payload = dict(locator["match"])
        within = locator.get("within") if isinstance(locator.get("within"), dict) else None
        if within:
            match_payload["within_role"] = within.get("role")
            match_payload["within_text"] = within.get("text")
        match = ElementMatch.model_validate(match_payload)
        if not find_all(page_state, match):
            missing.append(match.model_dump(exclude_none=True))
    reason = f"missing controls: {missing}" if missing else None
    if checked == 0:
        reason = "no live_current locators"
    return {"name": "live_controls", "ok": not missing, "reason": reason, "checked": checked}
