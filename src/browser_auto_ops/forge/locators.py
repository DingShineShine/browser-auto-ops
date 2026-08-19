from __future__ import annotations

import re
from typing import Any

_CONTAINER_ROLES = {"dialog", "alertdialog", "menu", "listbox"}
_CONTAINER_KINDS = {"dialog", "modal"}


def accessible_name(element: dict[str, Any]) -> str:
    for key in ("name", "text", "placeholder", "value"):
        value = _clean(element.get(key))
        if value and value.lower() not in {"login", "submit", "button"}:
            return value
    for key in ("name", "text", "placeholder", "value"):
        value = _clean(element.get(key))
        if value:
            return value
    attributes = element.get("attributes")
    if isinstance(attributes, dict):
        for key in ("aria-label", "aria_label", "label"):
            value = _clean(attributes.get(key))
            if value:
                return value
    return ""


def role_of(element: dict[str, Any]) -> str:
    role = _clean(element.get("role")).lower()
    if role:
        return role
    kind = _clean(element.get("kind")).lower()
    tag = _clean(element.get("tag")).lower()
    if kind in {"label", "button", "link", "checkbox", "radio", "tab", "dialog", "textbox"}:
        return kind
    if tag == "label":
        return "label"
    if tag in {"button", "a", "input", "select", "textarea", "dialog"}:
        if tag == "a":
            return "link"
        if tag == "input":
            input_type = _clean((element.get("attributes") or {}).get("type") if isinstance(element.get("attributes"), dict) else None).lower()
            if input_type in {"checkbox", "radio"}:
                return input_type
            return "textbox"
        if tag == "textarea":
            return "textbox"
        return tag
    if element.get("fillable"):
        return "textbox"
    if element.get("clickable"):
        return "button"
    return kind or tag or "element"


def find_container(elements: list[dict[str, Any]], target: dict[str, Any] | None = None) -> dict[str, Any] | None:
    containers = [item for item in elements if isinstance(item, dict) and _is_container(item)]
    if target and target in containers:
        containers = [item for item in containers if item is not target]
    return containers[-1] if containers else None


def locator_for_element(
    element: dict[str, Any],
    *,
    elements: list[dict[str, Any]] | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    name = accessible_name(element)
    role = role_of(element)
    kind = _clean(element.get("kind")) or role
    match: dict[str, Any] = {"kind": kind}
    if role:
        match["role"] = role
    if element.get("fillable") and _clean(element.get("placeholder")):
        match["placeholder"] = _clean(element.get("placeholder"))
        match["placeholder_mode"] = "exact"
    elif element.get("fillable") and name:
        match["label"] = name
        match["label_mode"] = "exact"
    elif name:
        match["text"] = name
        match["text_mode"] = "exact"
    default_action = "click"
    if element.get("fillable"):
        default_action = "input"
    elif element.get("selectable"):
        default_action = "select"
    resolved_action = action or default_action
    locator: dict[str, Any] = {
        "step": _step_id(resolved_action, name or kind),
        "match": match,
        "action": resolved_action,
    }
    container = find_container(elements or [], element)
    if container and name:
        same_name = [
            item
            for item in (elements or [])
            if isinstance(item, dict) and accessible_name(item) == name and item is not container
        ]
        if len(same_name) > 1 or _is_container(container):
            locator["within"] = {
                "role": role_of(container),
                "text": accessible_name(container) or role_of(container),
                "text_mode": "contains",
            }
    return locator


_SKIP_ACTION_TYPES = {"wait", "execute_js", "screenshot", "extract"}


def locators_from_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for action in actions:
        request = action.get("request") if isinstance(action.get("request"), dict) else {}
        if str(request.get("type") or "") in _SKIP_ACTION_TYPES:
            continue
        element = action.get("element") if isinstance(action.get("element"), dict) else {}
        elements = action.get("elements") if isinstance(action.get("elements"), list) else []
        if not element and not request:
            continue
        action_type = str(request.get("type") or ("input_text" if element.get("fillable") else "click"))
        mapped = {
            "input_text": "input",
            "select_option": "select",
            "goto_url": "open",
        }.get(action_type, action_type.replace("_", " "))
        request_match = request.get("match") if isinstance(request.get("match"), dict) else None
        if element:
            row = locator_for_element(element, elements=elements, action=mapped)
        elif request_match:
            row = {
                "step": _step_id(mapped, _match_label(request_match) or mapped),
                "match": dict(request_match),
                "action": mapped,
            }
        elif request.get("type") == "goto_url" and request.get("url"):
            row = {
                "step": _step_id(mapped, str(request.get("url"))),
                "match": {"kind": mapped},
                "action": mapped,
            }
        else:
            continue
        if request.get("type") == "input_text" and not _is_secret_element(element):
            text = request.get("text")
            if text:
                row["value"] = text
        if request.get("type") == "select_option" and request.get("option"):
            row["value"] = request.get("option")
        if request.get("type") == "goto_url" and request.get("url"):
            row["value"] = request.get("url")
        checkpoint = action.get("checkpoint") or _checkpoint_from_action(action)
        if checkpoint:
            row["checkpoint"] = checkpoint
        rows.append(row)
    return rows


def _checkpoint_from_action(action: dict[str, Any]) -> dict[str, Any] | None:
    result = action.get("result") if isinstance(action.get("result"), dict) else {}
    verification = result.get("verification")
    if isinstance(verification, dict) and "url_changed" in verification:
        after = verification.get("after") if isinstance(verification.get("after"), dict) else {}
        return {
            "url": after.get("url"),
            "title": after.get("title"),
            "url_changed": bool(verification.get("url_changed")),
            "title_changed": bool(verification.get("title_changed")),
        }
    before_url = action.get("before_url")
    after_url = action.get("after_url")
    before_title = action.get("before_title")
    after_title = action.get("after_title")
    if before_url is None and after_url is None:
        return None
    return {
        "url": after_url,
        "title": after_title,
        "url_changed": bool(before_url and after_url and before_url != after_url),
        "title_changed": bool(before_title and after_title and before_title != after_title),
    }


def _is_container(element: dict[str, Any]) -> bool:
    role = role_of(element)
    kind = _clean(element.get("kind")).lower()
    return bool(element.get("modal") or role in _CONTAINER_ROLES or kind in _CONTAINER_KINDS)


def _is_secret_element(element: dict[str, Any]) -> bool:
    blob = " ".join(
        [
            accessible_name(element),
            _clean(element.get("placeholder")),
            _clean(element.get("kind")),
            str((element.get("attributes") or {}).get("type") if isinstance(element.get("attributes"), dict) else ""),
        ]
    ).lower()
    return any(marker in blob for marker in ("password", "passwd", "secret", "otp", "验证码"))


def _step_id(action: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", f"{action}_{name}".lower()).strip("_")
    return slug[:80] or action


def _match_label(match: dict[str, Any]) -> str:
    for key in ("text", "name", "label", "placeholder", "role", "kind"):
        value = _clean(match.get(key))
        if value:
            return value
    return ""


def _clean(value: Any) -> str:
    return str(value or "").replace("\n", " ").strip()
