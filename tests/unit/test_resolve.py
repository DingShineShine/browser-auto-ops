import pytest

from browser_auto_ops.errors import ElementNotFoundError
from browser_auto_ops.schemas import ActionRequest, ElementLocator, ElementMatch, PageState, StateElement
from browser_auto_ops.snapshot.resolve import find_all, resolve_element


def _element(index: int, name: str, *, role: str = "button", ref: str | None = None, modal: bool = False) -> StateElement:
    return StateElement(
        index=index,
        ref=ref or f"@e{index}",
        kind="dialog" if modal else "button",
        tag="div" if modal else "button",
        role="dialog" if modal else role,
        name=name,
        text=name,
        locator=ElementLocator(type="xpath", value=f"//button[{index}]"),
        action_locator=ElementLocator(type="xpath", value=f"//button[{index}]"),
        modal=modal,
    )


def _state() -> PageState:
    return PageState(
        session_id="s",
        url="https://example.test",
        title="Example",
        elements=[_element(1, "Clear All"), _element(2, "Export"), _element(3, "Export")],
    )


def test_resolve_by_ref() -> None:
    state = _state()
    assert resolve_element(state, ActionRequest(type="click", ref="@e2")).index == 2


def test_resolve_by_role_and_name() -> None:
    state = _state()
    matches = find_all(state, ElementMatch(role="button", text="Clear All"))
    assert [item.index for item in matches] == [1]


def test_ambiguous_match_requires_scope() -> None:
    with pytest.raises(ElementNotFoundError, match="multiple elements"):
        resolve_element(_state(), ActionRequest(type="click", match=ElementMatch(role="button", text="Export")))


def test_occluded_flag_is_available_to_executor() -> None:
    state = _state()
    state.elements[0].occluded = True
    assert resolve_element(state, ActionRequest(type="click", ref="@e1")).occluded is True
