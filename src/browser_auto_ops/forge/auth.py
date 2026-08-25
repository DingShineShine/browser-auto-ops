from __future__ import annotations

from typing import Any


AUTH_TITLE_MARKERS = ("sign in", "login")
AUTH_URL_MARKERS = ("/auth/", "login", "openid-connect")
AUTH_REQUIRED_STEP_TYPES = ("api_call", "eval_helper")


def build_auth_precheck(steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    required_for = sorted(
        {
            str(step.get("type"))
            for step in steps
            if isinstance(step, dict)
            and step.get("replay") is not False
            and step.get("type") in AUTH_REQUIRED_STEP_TYPES
        }
    )
    if not required_for:
        return None
    return {
        "required_for": required_for,
        "login_required_when": {
            "title_contains": list(AUTH_TITLE_MARKERS),
            "url_contains": list(AUTH_URL_MARKERS),
        },
        "on_missing_auth_branch": "fail_fast",
    }


def auth_gate_failure(workflow: dict[str, Any], live: dict[str, Any] | None) -> dict[str, Any] | None:
    precheck = workflow.get("auth_precheck") if isinstance(workflow.get("auth_precheck"), dict) else None
    if not precheck or precheck.get("on_missing_auth_branch") != "fail_fast":
        return None
    if isinstance(workflow.get("auth"), dict):
        return None
    if not live_login_required(live, precheck):
        return None
    return {
        "reason": "login_required",
        "message": "Authentication is required before API replay. Open/login the browser profile first, then rerun forge run.",
        "auth_precheck": precheck,
    }


def live_login_required(live: dict[str, Any] | None, precheck: dict[str, Any]) -> bool:
    if not live:
        return False
    rules = precheck.get("login_required_when") if isinstance(precheck.get("login_required_when"), dict) else {}
    title = str(live.get("title") or "").lower()
    url = str(live.get("url") or "").lower()
    for marker in rules.get("title_contains") or []:
        if str(marker).lower() in title:
            return True
    for marker in rules.get("url_contains") or []:
        if str(marker).lower() in url:
            return True
    return False
