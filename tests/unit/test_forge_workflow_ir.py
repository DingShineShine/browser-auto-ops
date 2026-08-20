from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

from browser_auto_ops.forge import ForgeEngine
from browser_auto_ops.forge.component_scripts import write_component_scripts
from browser_auto_ops.forge.locators import locator_for_element
from browser_auto_ops.forge.replay import workflow_actions
from browser_auto_ops.schemas import PageState
from browser_auto_ops.server import _write_replay_repair_suggestion

IR_V2_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "forge" / "ir_v2_events.jsonl"


def test_workflow_ir_preserves_wait_js_download_and_fallback(tmp_path: Path) -> None:
    trace = tmp_path / "trace"
    trace.mkdir()
    (trace / "events.jsonl").write_text(IR_V2_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    skill = ForgeEngine(tmp_path / "skills").generate(trace, "report", "download report", install=False)
    workflow = json.loads((skill / "evidence" / "workflow.json").read_text(encoding="utf-8"))
    step_types = [item["type"] for item in workflow["workflow_steps"]]

    assert workflow["schema_version"] == 2
    assert "wait_condition" in step_types
    assert "assertion" in step_types
    assert "api_call" in step_types
    assert "fallback" in step_types
    assert any(item.get("type") == "artifact" for item in workflow["validators"])
    assert "download-via-page-fetch.py" in workflow["component_scripts"]
    replay_types = [item["type"] for item in workflow_actions(workflow)]
    assert "wait" in replay_types
    assert "execute_js" in replay_types
    assert "click" in replay_types


def test_locator_ranking_records_actionability_and_shortest_unique_prefix() -> None:
    target = {"kind": "label", "tag": "label", "text": "Product Report", "visible": True, "enabled": True, "clickable": True}
    elements = [
        {"kind": "label", "tag": "label", "text": "Wayfair Sponsored Products Product Report", "clickable": True},
        target,
    ]

    row = locator_for_element(target, elements=elements, action="click")

    assert row["actionability"] == {"visible": True, "enabled": True, "not_occluded": True, "stable": True}
    assert row["locator_rank"]["unique"] is True
    assert row["match"]["text"] == "Product Report"
    assert row["match"]["text_mode"] == "exact"


def test_component_generator_writes_atomic_helpers_from_patterns(tmp_path: Path) -> None:
    written = write_component_scripts(
        tmp_path,
        {
            "parameters": [{"type": "date_offset", "name": "start", "value": "T-3", "offset_days": 3, "source": "goal"}],
            "locators": [
                {"action": "select", "match": {"role": "combobox", "text": "Group By"}},
                {"action": "input", "match": {"role": "textbox", "placeholder": "Report Name"}},
            ],
            "workflow_steps": [
                {"type": "wait_condition", "description": "poll generated row status"},
                {"type": "api_call", "script": "fetch('/download')"},
            ],
        },
    )

    assert {
        "date-params.py",
        "select-combobox.py",
        "select-calendar-day.py",
        "fill-react-input.py",
        "poll-row-status.py",
        "download-via-page-fetch.py",
        "download-artifact.py",
    }.issubset(set(written))


def test_repair_suggestion_is_written_as_evidence(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    state = PageState(session_id="s_test", url="https://example.test/reports", title="Reports")

    path = _write_replay_repair_suggestion(
        skill,
        3,
        {"type": "click", "match": {"role": "button", "text": "Generate"}},
        SimpleNamespace(message="element not found"),
        state,
    )
    payload = json.loads(Path(path).read_text(encoding="utf-8"))

    assert payload["step"] == 3
    assert payload["message"] == "element not found"
    assert payload["current_title"] == "Reports"
    assert (skill / "evidence" / "repair-suggestion.json").exists()
