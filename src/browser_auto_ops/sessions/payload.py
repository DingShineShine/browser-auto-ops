from __future__ import annotations

import json
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
    result_payload["data"] = _compact_result_data(result_payload.get("data"))
    if not include_state:
        result_payload.pop("verification", None)
    payload: dict[str, Any] = {
        "result": result_payload,
        "checkpoint": checkpoint_from_verification(result.verification),
    }
    if include_state and state is not None:
        payload["state"] = state.model_dump(mode="json")
    return payload


def _compact_result_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _compact_result_value(key, item) for key, item in value.items()}
    if isinstance(value, list):
        return [_compact_result_data(item) for item in value]
    if isinstance(value, str):
        parsed = _parse_json(value)
        if isinstance(parsed, (dict, list)) and _contains_large_artifact_payload(parsed):
            return json.dumps(_compact_result_data(parsed), ensure_ascii=False)
        if len(value) > 100_000:
            return value[:2_000] + f"...<truncated:{len(value)} chars>"
    return value


def _compact_result_value(key: Any, value: Any) -> Any:
    key_text = str(key).lower()
    if key_text in {"base64", "response_body_base64"} and isinstance(value, str):
        return f"<base64:{len(value)} chars>"
    return _compact_result_data(value)


def _contains_large_artifact_payload(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in {"base64", "response_body_base64"} and isinstance(item, str):
                return True
            if _contains_large_artifact_payload(item):
                return True
    if isinstance(value, list):
        return any(_contains_large_artifact_payload(item) for item in value)
    return False


def _parse_json(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return None
