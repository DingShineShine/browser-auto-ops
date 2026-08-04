from __future__ import annotations

import re
from typing import Any

from browser_auto_ops.safety import is_dangerous_text
from browser_auto_ops.schemas import ActionPlan, ActionRequest, ObserveCandidate, PageState, PlannedAction, PlannerResult


class ObserveService:
    def observe(self, state: PageState, goal: str) -> list[ObserveCandidate]:
        tokens = _tokens(goal)
        candidates: list[ObserveCandidate] = []
        for element in state.elements:
            haystack = " ".join(
                [
                    element.kind,
                    element.role or "",
                    element.name,
                    element.text,
                    element.placeholder,
                    " ".join(element.attributes.values()),
                ]
            ).lower()
            score = sum(1 for token in tokens if token and token in haystack)
            if score == 0 and _kind_hint(goal, element.kind):
                score = 1
            if score == 0:
                continue
            action = _suggest_action(goal, element)
            confidence = min(0.95, 0.45 + score * 0.15)
            candidates.append(
                ObserveCandidate(
                    index=element.index,
                    action=action,
                    confidence=confidence,
                    reason=f"matched {score} goal token(s) against {element.kind}",
                )
            )
        candidates.sort(key=lambda item: item.confidence, reverse=True)
        return candidates[:10]


class ActService:
    def plan_result(
        self,
        state: PageState,
        goal: str,
        *,
        allow_dangerous: bool = False,
        require_confirm: bool = False,
    ) -> PlannerResult:
        actions = self.plan(
            state,
            goal,
            allow_dangerous=allow_dangerous,
            require_confirm=require_confirm,
        )
        planned = [
            PlannedAction(
                type=action.type,
                index=action.index,
                text=action.text,
                option=action.option,
                require_confirm=action.require_confirm,
                reason="heuristic state match",
            )
            for action in actions
        ]
        warnings = []
        if not planned:
            warnings.append("no action candidates matched the current state")
        return PlannerResult(
            goal=goal,
            planner="heuristic",
            plan=ActionPlan(goal=goal, reason="fallback heuristic planner", actions=planned),
            warnings=warnings,
        )

    def plan(
        self,
        state: PageState,
        goal: str,
        *,
        allow_dangerous: bool = False,
        require_confirm: bool = False,
    ) -> list[ActionRequest]:
        if is_dangerous_text(goal) and not allow_dangerous:
            return []
        candidates = ObserveService().observe(state, goal)
        if not candidates:
            return []
        best = candidates[0]
        if best.action == "input_text":
            text = _quoted_text(goal) or _after_keyword(goal, ["\u641c\u7d22", "\u8f93\u5165", "search", "type"]) or goal
            return [ActionRequest(type="input_text", index=best.index, text=text, require_confirm=require_confirm)]
        if best.action == "click":
            return [ActionRequest(type="click", index=best.index, require_confirm=require_confirm)]
        if best.action == "select_option":
            return [
                ActionRequest(
                    type="select_option",
                    index=best.index,
                    option=_quoted_text(goal) or goal,
                    require_confirm=require_confirm,
                )
            ]
        return [ActionRequest(type=best.action, index=best.index, require_confirm=require_confirm)]


class ExtractService:
    async def extract(self, page, goal: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        data = await page.evaluate(
            """
            () => {
              const tables = Array.from(document.querySelectorAll('table')).map(table => {
                const rows = Array.from(table.querySelectorAll('tr')).map(row =>
                  Array.from(row.querySelectorAll('th,td')).map(cell => cell.innerText.trim())
                );
                return rows.filter(row => row.length);
              });
              const lists = Array.from(document.querySelectorAll('ul,ol')).slice(0, 20).map(list =>
                Array.from(list.querySelectorAll('li')).map(item => item.innerText.trim()).filter(Boolean)
              ).filter(list => list.length);
              const text = document.body ? document.body.innerText.trim().slice(0, 20000) : '';
              return {tables, lists, text};
            }
            """
        )
        return {"goal": goal, "schema": schema or {}, "data": data}


def _tokens(goal: str) -> list[str]:
    parts = re.split(r"[\s,，。:：;；\"'“”‘’]+", goal.lower())
    return [part for part in parts if len(part) >= 2]


def _suggest_action(goal: str, element) -> str:
    lower = goal.lower()
    if element.fillable or "\u8f93\u5165" in lower or "\u641c\u7d22" in lower or "type" in lower or "search" in lower:
        if element.fillable:
            return "input_text"
    if element.selectable or "\u9009\u62e9" in lower or "select" in lower:
        return "select_option"
    return "click"


def _kind_hint(goal: str, kind: str) -> bool:
    lower = goal.lower()
    return (
        (kind == "input" and any(word in lower for word in ["input", "search", "\u8f93\u5165", "\u641c\u7d22\u6846"]))
        or (kind == "button" and any(word in lower for word in ["button", "click", "\u6309\u94ae", "\u70b9\u51fb"]))
        or (kind == "link" and any(word in lower for word in ["link", "\u94fe\u63a5"]))
    )


def _quoted_text(goal: str) -> str | None:
    match = re.search(r"[\"“]([^\"”]+)[\"”]", goal)
    return match.group(1).strip() if match else None


def _after_keyword(goal: str, keywords: list[str]) -> str | None:
    for keyword in keywords:
        idx = goal.lower().find(keyword.lower())
        if idx >= 0:
            text = goal[idx + len(keyword) :].strip(" ：:")
            return text or None
    return None
