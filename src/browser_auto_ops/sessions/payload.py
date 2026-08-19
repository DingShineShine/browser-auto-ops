from __future__ import annotations

from typing import Any

from browser_auto_ops.schemas import ActionResult, PageState


def checkpoint_from_verification(verification: dict[str, Any] | None) -> dict[str, Any]:
    payload = verification if isinstance(verification, dict) else {}
    after = payload.get("after") if isinstance(payload.get("after"), dict) else {}
    checkpoint = {
        "url": after.get("url"),
        "title": after.get("title"),
        "url_changed": bool(payload.get("url_changed")),
        "title_changed": bool(payload.get("title_changed")),
    }
    if checkpoint["url_changed"]:
        checkpoint["state_stale"] = True
    return checkpoint


def compact_action_payload(
    result: ActionResult,
    state: PageState | None = None,
    *,
    include_state: bool = False,
) -> dict[str, Any]:
    result_payload = result.model_dump(mode="json")
    if not include_state:
        result_payload.pop("verification", None)
    payload: dict[str, Any] = {
        "result": result_payload,
        "checkpoint": checkpoint_from_verification(result.verification),
    }
    if include_state and state is not None:
        payload["state"] = state.model_dump(mode="json")
    return payload
