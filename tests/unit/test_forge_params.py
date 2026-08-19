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
