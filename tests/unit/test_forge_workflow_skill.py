from pathlib import Path

from browser_auto_ops.forge import ForgeEngine
from browser_auto_ops.forge.replay import workflow_actions


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "forge" / "wayfair_like_events.jsonl"


def _generate(tmp_path: Path) -> Path:
    trace = tmp_path / "trace"
    trace.mkdir()
    (trace / "events.jsonl").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    return ForgeEngine(tmp_path / "skills").generate(
        trace,
        "wayfair-dropship-po-export",
        "Clear filters, set dates, Export All, then Export",
        install=True,
        agents_root=tmp_path / ".agents" / "skills",
    )


def test_generated_skill_is_replay_not_extract_shell(tmp_path: Path) -> None:
    skill = _generate(tmp_path)
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    workflow = __import__("json").loads((skill / "evidence" / "workflow.json").read_text(encoding="utf-8"))
    report = __import__("json").loads((skill / "evidence" / "generation-report.json").read_text(encoding="utf-8"))
    assert "Clear All" in text
    assert "登录分支" in text
    assert "成功标准" in text
    assert "禁止" in text or "Never treat a numeric index" in text
    assert "click 122" not in text
    assert "placeholder-secret" not in text
    assert "python scripts/capability.py --mode tables" not in text.split("## 复跑流程", 1)[1].split("## ", 1)[0]
    assert workflow["auth"]
    assert "Email" not in "\n".join(workflow["main_steps"])
    assert report["auth_branch"] is True
    assert "Component scripts" in text
    assert "download-artifact.py" in workflow["component_scripts"]
    assert (skill / "scripts" / "download-artifact.py").exists()
    replay = workflow_actions(workflow, live={"url": workflow["last_url"], "title": "Dropship Orders"})
    assert replay
    assert all((item.get("match") or {}).get("placeholder") != "Email" for item in replay)


def test_engine_source_has_no_site_constants() -> None:
    engine = Path(__file__).resolve().parents[2] / "src" / "browser_auto_ops" / "forge" / "engine.py"
    workflow = Path(__file__).resolve().parents[2] / "src" / "browser_auto_ops" / "forge" / "workflow.py"
    blob = engine.read_text(encoding="utf-8") + workflow.read_text(encoding="utf-8")
    assert "orderDateFrom" not in blob
    assert "Dropship" not in blob
    assert "OrderListExportQuery" not in blob


def test_failed_actions_are_reported_not_rendered(tmp_path: Path) -> None:
    trace = tmp_path / "trace"
    trace.mkdir()
    events = [
        {
            "type": "state.capture",
            "payload": {
                "url": "https://example.test/orders",
                "title": "Orders",
                "elements": [
                    {
                        "index": 1,
                        "kind": "button",
                        "tag": "button",
                        "role": "button",
                        "text": "Clear All",
                        "clickable": True,
                        "locator": {"type": "xpath", "value": "//button[.='Clear All']"},
                    }
                ],
            },
        },
        {"type": "action.request", "payload": {"type": "click", "match": {"name": "Order From"}}},
        {"type": "action.result", "payload": {"type": "click", "success": False, "message": "multiple elements matched"}},
        {"type": "action.request", "payload": {"type": "click", "index": 1}},
        {"type": "action.result", "payload": {"type": "click", "success": True}},
    ]
    (trace / "events.jsonl").write_text("\n".join(__import__("json").dumps(item) for item in events), encoding="utf-8")

    skill = ForgeEngine(tmp_path / "skills").generate(trace, "orders", "clear filters", install=False)
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    workflow = __import__("json").loads((skill / "evidence" / "workflow.json").read_text(encoding="utf-8"))
    report = __import__("json").loads((skill / "evidence" / "generation-report.json").read_text(encoding="utf-8"))

    assert "click click" not in text
    assert len(workflow["locators"]) == 1
    assert report["actions"]["dropped_by_reason"]["failed_action"] == 1


def test_relative_date_goal_writes_date_component_script(tmp_path: Path) -> None:
    trace = tmp_path / "trace"
    trace.mkdir()
    (trace / "events.jsonl").write_text("", encoding="utf-8")

    skill = ForgeEngine(tmp_path / "skills").generate(
        trace,
        "date-report",
        "download report from T-3 to T-2",
        install=False,
    )
    workflow = __import__("json").loads((skill / "evidence" / "workflow.json").read_text(encoding="utf-8"))

    assert "date-params.py" in workflow["component_scripts"]
    assert (skill / "scripts" / "date-params.py").exists()
    assert "T-3" in (skill / "SKILL.md").read_text(encoding="utf-8")
