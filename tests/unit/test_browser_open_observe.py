from browser_auto_ops.cli import _open_result


def test_open_result_returns_url_and_title_without_login_hint() -> None:
    payload = _open_result({"session_id": "s_1", "name": "task"}, "https://example.test/signin", "Sign in")
    assert payload["url"] == "https://example.test/signin"
    assert payload["title"] == "Sign in"
    assert payload["session"]["session_id"] == "s_1"
    assert "login_hint" not in payload
