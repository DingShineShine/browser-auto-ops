from browser_auto_ops.cli import _attach_checkpoint
from browser_auto_ops.schemas import ActionResult
from browser_auto_ops.sessions.payload import compact_action_payload


def test_action_payload_exposes_compact_checkpoint() -> None:
    payload = {
        "result": {
            "success": True,
            "verification": {
                "before": {"url": "https://example.test/a", "title": "A"},
                "after": {"url": "https://example.test/b", "title": "B"},
                "url_changed": True,
                "title_changed": True,
            },
        }
    }
    attached = _attach_checkpoint(payload)
    assert attached["checkpoint"] == {
        "url": "https://example.test/b",
        "title": "B",
        "url_changed": True,
        "title_changed": True,
        "state_stale": True,
    }
    assert "recent_network" not in attached


def test_compact_action_payload_omits_state_and_verification_by_default() -> None:
    result = ActionResult(
        type="click",
        success=True,
        verification={
            "after": {"url": "https://example.test/a", "title": "A"},
            "url_changed": False,
            "title_changed": False,
        },
    )
    payload = compact_action_payload(result)
    assert "state" not in payload
    assert "verification" not in payload["result"]
    assert payload["checkpoint"] == {
        "url": "https://example.test/a",
        "title": "A",
        "url_changed": False,
        "title_changed": False,
    }
