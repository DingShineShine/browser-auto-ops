from browser_auto_ops.forge.workflow import success_criteria


def test_success_criteria_uses_new_query_keys_only() -> None:
    rows = success_criteria(
        {},
        [
            {
                "before_url": "https://example.test/orders",
                "after_url": "https://example.test/orders?orderDateFrom=2026-08-13&orderDateTo=2026-08-14",
                "before_title": "Orders",
                "after_title": "Orders",
            }
        ],
    )
    assert "url contains orderDateFrom" in rows
    assert "url contains orderDateTo" in rows


def test_title_change_becomes_criterion() -> None:
    rows = success_criteria(
        {},
        [
            {
                "before_url": "https://example.test/login",
                "after_url": "https://example.test/home",
                "before_title": "Sign in",
                "after_title": "Home",
            }
        ],
    )
    assert 'title == "Home"' in rows
