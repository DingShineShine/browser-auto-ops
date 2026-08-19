from pathlib import Path

from browser_auto_ops.forge.engine import load_trace_summary


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "forge" / "wayfair_like_events.jsonl"


def test_load_trace_summary_reads_action_graph(tmp_path: Path) -> None:
    trace = tmp_path / "trace"
    trace.mkdir()
    (trace / "events.jsonl").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    summary = load_trace_summary(trace)

    assert summary["events"] >= 10
    assert len(summary["actions"]) >= 6
    assert "action.request" in summary["event_types"]
    assert "orderDateFrom" in str(summary["last_state"]["url"])
    assert summary["actions"][0]["element"]["name"] == "Email"
    assert summary["actions"][3]["element"]["text"] == "Clear All"
