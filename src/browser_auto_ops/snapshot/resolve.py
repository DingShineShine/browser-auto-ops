from __future__ import annotations

import re
from typing import Iterable

from browser_auto_ops.errors import ElementNotFoundError
from browser_auto_ops.schemas import ActionRequest, ElementMatch, PageState, StateElement


def parse_ref(value: str | None) -> int | None:
    if not value:
        return None
    match = re.fullmatch(r"@?e?(\d+)", value.strip(), flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def resolve_action_request(state: PageState, request: ActionRequest) -> ActionRequest:
    element = resolve_element(state, request)
    return request.model_copy(update={"index": element.index, "ref": element.ref})


def resolve_element(state: PageState, request: ActionRequest) -> StateElement:
    if request.match:
        matches = find_all(state, request.match)
        if not matches:
            raise ElementNotFoundError(_no_match_message(state, request.match))
        if len(matches) > 1:
            raise ElementNotFoundError(_ambiguous_message(matches, request.match))
        return matches[0]
    if request.ref:
        element = _by_ref(state, request.ref)
        if element:
            return element
        raise ElementNotFoundError(f"element ref {request.ref!r} not found in current state; run `bao state` again")
    if request.index is not None:
        for element in state.elements:
            if element.index == request.index:
                return element
        raise ElementNotFoundError(f"element index {request.index} not found in current state")
    raise ElementNotFoundError("action requires index, ref, or match")


def find_all(state: PageState, match: ElementMatch | dict) -> list[StateElement]:
    criteria = match if isinstance(match, ElementMatch) else ElementMatch.model_validate(match)
    candidates = [element for element in state.elements if _matches(element, criteria)]
    if criteria.within_role or criteria.within_text:
        candidates = [element for element in candidates if _within_matches(state, element, criteria)]
    return candidates


def accessible_name(element: StateElement) -> str:
    for value in (element.name, element.text, element.placeholder, element.value):
        cleaned = _clean(value)
        if cleaned and cleaned.lower() not in {"login", "submit", "button"}:
            return cleaned
    for value in (element.name, element.text, element.placeholder, element.value):
        cleaned = _clean(value)
        if cleaned:
            return cleaned
    for key in ("aria-label", "aria_label", "label"):
        cleaned = _clean(element.attributes.get(key))
        if cleaned:
            return cleaned
    return ""


def role_of(element: StateElement) -> str:
    role = _clean(element.role).lower()
    if role:
        return role
    kind = _clean(element.kind).lower()
    tag = _clean(element.tag).lower()
    if kind in {"button", "link", "checkbox", "radio", "tab", "dialog", "textbox"}:
        return kind
    if tag == "a":
        return "link"
    if tag == "input":
        input_type = _clean(element.attributes.get("type")).lower()
        if input_type in {"checkbox", "radio"}:
            return input_type
        return "textbox"
    if tag == "textarea":
        return "textbox"
    return kind or tag or "element"


def _matches(element: StateElement, criteria: ElementMatch) -> bool:
    if criteria.role and role_of(element) != _clean(criteria.role).lower():
        return False
    if criteria.kind and _clean(element.kind).lower() != _clean(criteria.kind).lower():
        return False
    if criteria.placeholder and not _text_match(element.placeholder, criteria.placeholder):
        return False
    wanted_label = criteria.label or criteria.name or criteria.text
    if wanted_label:
        haystacks = [accessible_name(element), element.name, element.text, element.placeholder, element.value]
        if not any(_text_match(value, wanted_label) for value in haystacks):
            return False
    return True


def _within_matches(state: PageState, element: StateElement, criteria: ElementMatch) -> bool:
    containers = [
        item
        for item in state.elements
        if item.modal or role_of(item) in {"dialog", "alertdialog", "menu", "listbox"} or item.kind in {"dialog", "modal"}
    ]
    containers = [item for item in containers if item.index != element.index]
    if not containers:
        return False
    container = containers[-1]
    if criteria.within_role and role_of(container) != _clean(criteria.within_role).lower():
        return False
    if criteria.within_text and not _text_match(accessible_name(container) or container.text, criteria.within_text):
        return False
    return True


def _by_ref(state: PageState, ref: str) -> StateElement | None:
    parsed = parse_ref(ref)
    normalized = f"@e{parsed}" if parsed is not None else ref
    for element in state.elements:
        if element.ref == normalized:
            return element
    return None


def _no_match_message(state: PageState, match: ElementMatch) -> str:
    candidates = _candidate_summaries(state.elements[:10])
    return f"no element matched {match.model_dump(exclude_none=True)}; candidates: {candidates}"


def _ambiguous_message(matches: Iterable[StateElement], match: ElementMatch) -> str:
    return f"multiple elements matched {match.model_dump(exclude_none=True)}; narrow with within: {_candidate_summaries(matches)}"


def _candidate_summaries(elements: Iterable[StateElement]) -> list[dict[str, str | int | None]]:
    return [
        {"index": item.index, "ref": item.ref, "role": role_of(item), "name": accessible_name(item)}
        for item in elements
    ]


def _text_match(value: str | None, expected: str | None) -> bool:
    left = _clean(value).lower()
    right = _clean(expected).lower()
    return bool(right) and right in left


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
