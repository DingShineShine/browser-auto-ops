from pathlib import Path

from browser_auto_ops.forge import ForgeEngine
from browser_auto_ops.forge.tester import evaluate_skill
from browser_auto_ops.schemas import ElementLocator, PageState, StateElement


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "forge" / "wayfair_like_events.jsonl"


def test_tester_rejects_extract_shell(tmp_path: Path) -> None:
    skill = tmp_path / "old-shell"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "# old\n\n## Usage\n\n```bash\npython scripts/capability.py --mode tables\n```\n",
        encoding="utf-8",
    )
    (skill / "scripts" / "capability.py").write_text("print('ok')\n", encoding="utf-8")
    result = evaluate_skill(skill)
    assert result["ok"] is False
    names = {item["name"]: item["ok"] for item in result["checks"]}
    assert names["replay_steps_present"] is False


def test_tester_accepts_generated_replay_skill(tmp_path: Path) -> None:
    trace = tmp_path / "trace"
    trace.mkdir()
    (trace / "events.jsonl").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    skill = ForgeEngine(tmp_path / "skills").generate(
        trace,
        "wayfair-dropship-po-export",
        "export orders",
        install=False,
    )
    result = evaluate_skill(skill)
    assert result["ok"] is True
    names = {item["name"]: item for item in result["checks"]}
    assert names["replay_steps_present"]["ok"] is True
    assert names["no_ephemeral_index"]["ok"] is True
    assert names["live_inspect"]["ok"] is False
    assert names["live_inspect"]["reason"] == "no session"


def test_live_controls_only_checks_current_page_locators(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    evidence = skill / "evidence"
    evidence.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "# skill\n\n## 复跑流程\n\n1. click button `Clear All`\n\n## 查找元素\n\n- locator\n\n## 成功标准\n\n- title == \"Dropship Orders\"\n",
        encoding="utf-8",
    )
    (evidence / "workflow.json").write_text(
        """
{
  "locators": [
    {"action": "input", "match": {"role": "textbox", "placeholder": "Email"}},
    {"action": "click", "match": {"role": "button", "text": "August 14, 2026"}, "within": {"role": "dialog", "text": "Calendar"}},
    {"action": "click", "match": {"role": "button", "text": "Clear All"}, "live_current": true}
  ],
  "success_criteria": ["title == \\"Dropship Orders\\""]
}
""".strip(),
        encoding="utf-8",
    )
    state = PageState(
        session_id="s_test",
        url="https://partners.example.test/d/orders/dropship/po",
        title="Dropship Orders",
        elements=[
            StateElement(
                index=1,
                kind="button",
                tag="button",
                role="button",
                text="Clear All",
                locator=ElementLocator(type="xpath", value="//button[.='Clear All']"),
                clickable=True,
            )
        ],
    )
    result = evaluate_skill(skill, live={"url": state.url, "title": state.title}, state=state)

    assert result["ok"] is True
    controls = next(item for item in result["checks"] if item["name"] == "live_controls")
    assert controls["ok"] is True
    assert controls["checked"] == 1
