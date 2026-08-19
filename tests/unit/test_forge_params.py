from pathlib import Path

from browser_auto_ops.forge.params import extract_parameters


def test_extracts_goal_literals_without_timezone_defaults() -> None:
    params = extract_parameters(
        {
            "actions": [
                {"request": {"type": "input_text", "text": "2026-08-13"}, "element": {"name": "Order From"}},
                {"request": {"type": "input_text", "text": "placeholder-secret"}, "element": {"name": "Password", "placeholder": "Password"}},
            ]
        },
        'export orders from "warehouse-a" for operator@example.com',
    )
    values = {item["value"] for item in params}
    names = {item["name"] for item in params}
    assert "operator@example.com" in values
    assert "warehouse-a" in values
    assert "2026-08-13" in values
    assert "placeholder-secret" not in values
    assert "email" in names
    source = (Path(__file__).resolve().parents[2] / "src" / "browser_auto_ops" / "forge" / "params.py").read_text(encoding="utf-8")
    assert "America/New_York" not in source
    assert "from-offset" not in source


def test_extracts_relative_date_tokens_as_typed_params() -> None:
    params = extract_parameters({}, "download report from T-3 to T-2")

    assert params[0]["name"] == "start_date"
    assert params[0]["type"] == "date_offset"
    assert params[0]["value"] == "T-3"
    assert params[0]["offset_days"] == 3
    assert params[1]["name"] == "end_date"
    assert params[1]["type"] == "date_offset"
    assert params[1]["value"] == "T-2"
    assert params[1]["offset_days"] == 2
    assert "MM/DD/YYYY" in params[0]["format_hints"]
