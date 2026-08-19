from browser_auto_ops.forge.locators import locator_for_element, locators_from_actions


def test_locator_uses_role_and_name() -> None:
    row = locator_for_element(
        {"kind": "button", "role": "button", "name": "Clear All", "text": "Clear All", "clickable": True},
        action="click",
    )
    assert row["match"]["role"] == "button"
    assert row["match"]["text"] == "Clear All"
    assert "index" not in row
    assert "index" not in row["match"]


def test_duplicate_name_is_scoped_to_dialog() -> None:
    elements = [
        {"index": 14, "kind": "button", "role": "button", "name": "Export", "text": "Export", "clickable": True},
        {"index": 40, "kind": "dialog", "role": "dialog", "name": "Export orders", "text": "Export orders", "modal": True},
        {"index": 15, "kind": "button", "role": "button", "name": "Export", "text": "Export", "clickable": True},
    ]
    row = locator_for_element(elements[2], elements=elements, action="click")
    assert row["within"]["role"] == "dialog"
    assert row["within"]["text"] == "Export orders"


def test_locators_skip_observation_actions() -> None:
    rows = locators_from_actions(
        [
            {"request": {"type": "execute_js", "script": "document.title"}},
            {"request": {"type": "wait"}},
            {
                "request": {"type": "click", "index": 10},
                "element": {"kind": "button", "role": "button", "name": "Clear All", "text": "Clear All", "clickable": True},
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0]["match"]["text"] == "Clear All"


def test_locators_from_actions_keep_element_not_index() -> None:
    rows = locators_from_actions(
        [
            {
                "request": {"type": "click", "index": 122},
                "element": {"kind": "button", "role": "button", "name": "Clear All", "text": "Clear All", "clickable": True},
                "elements": [{"kind": "button", "role": "button", "name": "Clear All", "text": "Clear All", "clickable": True}],
            }
        ]
    )
    assert rows[0]["match"]["text"] == "Clear All"
    assert "122" not in str(rows[0]["match"])
