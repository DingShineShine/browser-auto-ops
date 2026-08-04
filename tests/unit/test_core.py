import json
import subprocess
import sys
from pathlib import Path

import pytest

from browser_auto_ops.actions import ActionExecutor
from browser_auto_ops.forge import ForgeEngine
from browser_auto_ops.intelligence import ActService, ObserveService
from browser_auto_ops.providers.registry import provider_for
from browser_auto_ops.safety import action_requires_confirmation, confirmation_reason
from browser_auto_ops.schemas import (
    ActionRequest,
    BrowserSession,
    ElementLocator,
    ElementRect,
    PageState,
    ProviderConfig,
    StateElement,
)
from browser_auto_ops.sessions import SessionStore
from browser_auto_ops.trace import TraceRecorder
from browser_auto_ops.trace.redaction import redact


def test_provider_registry() -> None:
    assert provider_for("cdp").name == "cdp"
    assert provider_for("local-chrome").name == "local-chrome"
    assert provider_for("adspower-cdp").name == "adspower-cdp"


def test_session_store_roundtrip(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session = BrowserSession(
        provider="cdp",
        cdp_url="http://127.0.0.1:9222",
        provider_config=ProviderConfig(provider="cdp", cdp_url="http://127.0.0.1:9222"),
    )
    store.save(session)
    loaded = store.get(session.session_id)
    assert loaded is not None
    assert loaded.cdp_url == "http://127.0.0.1:9222"
    store.delete(session.session_id)
    assert store.get(session.session_id) is None


def test_redaction() -> None:
    payload = {
        "headers": {"Authorization": "Bearer secret", "Content-Type": "application/json"},
        "api_key": "secret",
        "nested": {"cookie": "a=b"},
    }
    result = redact(payload)
    assert result["headers"]["Authorization"] == "[REDACTED]"
    assert result["headers"]["Content-Type"] == "application/json"
    assert result["api_key"] == "[REDACTED]"
    assert result["nested"]["cookie"] == "[REDACTED]"


def test_observe_ranks_matching_element() -> None:
    candidates = ObserveService().observe(_sample_state(), "find Search products search box")
    assert candidates
    assert candidates[0].index == 1
    assert candidates[0].action == "input_text"


def test_safety_requires_confirmation_for_dangerous_button() -> None:
    state = _sample_state()
    request = ActionRequest(type="click", index=2)
    element = state.elements[1]

    assert action_requires_confirmation(request, element)
    assert confirmation_reason(request, element)


def test_act_dangerous_goal_blocks_until_confirmed() -> None:
    state = _sample_state()

    assert ActService().plan(state, "delete order") == []

    actions = ActService().plan(state, "delete order", allow_dangerous=True, require_confirm=True)
    assert actions
    assert actions[0].type == "click"
    assert actions[0].index == 2
    assert actions[0].require_confirm is True


@pytest.mark.asyncio
async def test_executor_blocks_dangerous_action_without_confirm() -> None:
    result = await ActionExecutor().execute(
        object(),
        _sample_state(),
        ActionRequest(type="click", index=2),
    )
    assert result.success is False
    assert "confirm" in result.message


def test_trace_recorder_writes_summary(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path, "s_test")
    recorder.event("state.capture", {"url": "https://example.test", "api_key": "secret"})

    summary_path = tmp_path / "trace" / "s_test" / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["session_id"] == "s_test"
    assert summary["events"] == 1
    assert summary["event_types"]["state.capture"] == 1
    assert summary["last_event_type"] == "state.capture"


def test_forge_generates_trace_informed_skill(tmp_path: Path) -> None:
    trace = tmp_path / "trace" / "s_test"
    trace.mkdir(parents=True)
    event = {
        "type": "state.capture",
        "payload": _sample_state().model_dump(mode="json"),
    }
    (trace / "events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")

    skill = ForgeEngine(tmp_path / "skills").generate(trace, "tt-orders", "extract orders")

    assert (skill / "SKILL.md").exists()
    assert (skill / "scripts" / "capability.py").exists()
    assert (skill / "tests" / "smoke.json").exists()
    script = (skill / "scripts" / "capability.py").read_text(encoding="utf-8")
    assert "--mode" in script
    assert "collectTables" in script
    assert "TRACE_HINTS" in script
    run = subprocess.run(
        [sys.executable, str(skill / "scripts" / "capability.py"), "--mode", "links", "--query", "order"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0
    assert "collectLinks" in run.stdout

    evidence = json.loads((skill / "evidence" / "trace-summary.json").read_text(encoding="utf-8"))
    assert evidence["last_state"]["title"] == "test"
    assert evidence["last_state"]["element_count"] == 2


def _sample_state() -> PageState:
    return PageState(
        session_id="s_test",
        url="https://example.test",
        title="test",
        elements=[
            StateElement(
                index=1,
                kind="input",
                tag="input",
                name="Search products",
                placeholder="Search products",
                locator=ElementLocator(type="xpath", value="//*[@id='q']"),
                rect=ElementRect(x=1, y=2, width=100, height=30),
                fillable=True,
            ),
            StateElement(
                index=2,
                kind="button",
                tag="button",
                name="Delete",
                locator=ElementLocator(type="xpath", value="//*[@id='delete']"),
                rect=ElementRect(x=1, y=40, width=100, height=30),
                clickable=True,
            ),
        ],
    )
