import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from browser_auto_ops.browsers import BrowserStore, provider_config_for_browser
from browser_auto_ops.cli import app
from browser_auto_ops.cdp_auto_allow_helper import is_allow_button_label, is_remote_debugging_dialog_text
from browser_auto_ops.downloads import DownloadManager
from browser_auto_ops.actions import ActionExecutor
from browser_auto_ops.errors import ProviderError
from browser_auto_ops.forge import ForgeEngine
from browser_auto_ops.intelligence import ActService, ObserveService
from browser_auto_ops.providers.registry import provider_for
from browser_auto_ops.providers.raw_cdp import _best_page_target, _expression, _resolve_page_target
from browser_auto_ops.safety import action_requires_confirmation, confirmation_reason, is_dangerous_text
from browser_auto_ops.schemas import (
    ActionRequest,
    ActionResult,
    BrowserIdentity,
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


runner = CliRunner()


def test_provider_registry() -> None:
    assert provider_for("cdp").name == "cdp"
    assert provider_for("local-chrome").name == "local-chrome"
    assert provider_for("chrome-direct").name == "chrome-direct"
    assert provider_for("adspower-cdp").name == "adspower-cdp"


@pytest.mark.asyncio
async def test_chrome_direct_requires_confirmation() -> None:
    provider = provider_for("chrome-direct")
    config = ProviderConfig(provider="chrome-direct")
    with pytest.raises(ProviderError, match="confirm_direct"):
        await provider.start(config)


@pytest.mark.asyncio
async def test_raw_cdp_resolves_existing_target_without_creating() -> None:
    client = _FakeCdpClient(
        [
            {
                "targetId": "target-1",
                "type": "page",
                "url": "https://www.baidu.com/",
            }
        ]
    )

    target = await _resolve_page_target(client, target_id="target-1", create_new=False)  # type: ignore[arg-type]

    assert target["targetId"] == "target-1"
    assert "Target.createTarget" not in client.calls


@pytest.mark.asyncio
async def test_raw_cdp_raises_for_missing_persisted_target() -> None:
    client = _FakeCdpClient([])

    with pytest.raises(ProviderError, match="no longer available"):
        await _resolve_page_target(client, target_id="missing", create_new=False)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_raw_cdp_creates_target_when_requested() -> None:
    client = _FakeCdpClient([])

    target = await _resolve_page_target(client, create_new=True)  # type: ignore[arg-type]

    assert target["targetId"] == "created-target"
    assert "Target.createTarget" in client.calls


def test_raw_cdp_prefers_related_web_target() -> None:
    target = _best_page_target(
        [
            {"targetId": "blank", "type": "page", "url": "about:blank"},
            {"targetId": "other", "type": "page", "url": "https://example.com/"},
            {
                "targetId": "related",
                "type": "page",
                "url": "https://top.baidu.com/board",
                "openerId": "source",
            },
        ],
        opener_target_id="source",
    )

    assert target["targetId"] == "related"


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


def test_session_store_gets_named_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session = BrowserSession(
        name="report-export",
        provider="cdp",
        cdp_url="http://127.0.0.1:9222",
        provider_config=ProviderConfig(provider="cdp", cdp_url="http://127.0.0.1:9222"),
    )
    store.save(session)

    loaded = store.get("report-export")

    assert loaded is not None
    assert loaded.session_id == session.session_id


def test_browser_store_roundtrip(tmp_path: Path) -> None:
    store = BrowserStore(tmp_path)
    browser = BrowserIdentity(
        type="ads",
        name="amazon-us-01",
        desc="VPS AdsPower profile",
        provider_config=ProviderConfig(
            provider="adspower-cdp",
            ads_base_url="http://127.0.0.1:50325",
            ads_user_id="profile-1",
        ),
        owner="ops",
        department="export",
        account_label="amazon-us",
        platform="amazon",
        allowed_domains=["sellercentral.amazon.com"],
        sidecar_url="http://127.0.0.1:8765",
    )
    store.save(browser)

    assert store.get(browser.browser_id) is not None
    assert store.get("amazon-us-01") is not None
    assert store.get("amazon-us-01").type == "ads"  # type: ignore[union-attr]
    assert store.get("amazon-us-01").allowed_domains == ["sellercentral.amazon.com"]  # type: ignore[union-attr]


def test_browser_store_replaces_existing_name(tmp_path: Path) -> None:
    store = BrowserStore(tmp_path)
    first = BrowserIdentity(
        type="ads",
        name="seller",
        provider_config=ProviderConfig(provider="adspower-cdp", ads_base_url="http://old", ads_user_id="old"),
    )
    second = BrowserIdentity(
        type="ads",
        name="seller",
        provider_config=ProviderConfig(provider="adspower-cdp", ads_base_url="http://new", ads_user_id="new"),
    )

    store.save(first)
    store.save(second)

    assert len(store.list()) == 1
    assert store.get("seller").browser_id == second.browser_id  # type: ignore[union-attr]


def test_public_ads_browser_maps_to_adspower_provider() -> None:
    browser = BrowserIdentity(
        type="ads",
        name="amazon-us-01",
        provider_config=ProviderConfig(
            provider="adspower-cdp",
            ads_base_url="http://127.0.0.1:50325",
            ads_user_id="profile-1",
        ),
    )

    config = provider_config_for_browser(browser, start_url="https://example.test")

    assert config.provider == "adspower-cdp"
    assert config.start_url == "https://example.test"


def test_chrome_direct_browser_requires_open_confirmation() -> None:
    browser = BrowserIdentity(
        type="chrome-direct",
        name="local",
        confirm_before_use=True,
        provider_config=ProviderConfig(provider="chrome-direct"),
    )

    with pytest.raises(ProviderError, match="confirmation"):
        provider_config_for_browser(browser)

    config = provider_config_for_browser(browser, confirm=True)
    assert config.provider == "chrome-direct"
    assert config.confirm_direct is True


def test_get_skills_core_exposes_public_browser_types_only() -> None:
    result = runner.invoke(app, ["get-skills", "core"])

    assert result.exit_code == 0
    assert "chrome-direct" in result.stdout
    assert "ads" in result.stdout
    assert "local-chrome" not in result.stdout
    assert "generic cdp" not in result.stdout.lower()


def test_get_skills_specialized_pages() -> None:
    chrome = runner.invoke(app, ["get-skills", "chrome-direct"])
    ads = runner.invoke(app, ["get-skills", "ads"])
    safety = runner.invoke(app, ["get-skills", "safety"])

    assert chrome.exit_code == 0
    assert "bao chrome-direct authorize" in chrome.stdout
    assert ads.exit_code == 0
    assert "sidecar" in ads.stdout
    assert safety.exit_code == 0
    assert "--confirm" in safety.stdout


def test_cli_browser_create_and_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    create = runner.invoke(
        app,
        [
            "browser",
            "create",
            "--type",
            "ads",
            "--name",
            "amazon-us-01",
            "--desc",
            "VPS AdsPower profile",
            "--ads-base-url",
            "http://127.0.0.1:50325",
            "--ads-user-id",
            "profile-1",
        ],
    )
    listed = runner.invoke(app, ["browser", "list"])

    assert create.exit_code == 0
    assert listed.exit_code == 0
    assert "amazon-us-01" in listed.stdout
    assert '"type": "ads"' in listed.stdout


def test_browseract_compat_command_groups_are_registered() -> None:
    root = runner.invoke(app, ["--help"])
    network = runner.invoke(app, ["network", "har", "--help"])

    assert root.exit_code == 0
    for command in ["daemon", "chrome-direct", "tab", "cookies", "dialog", "downloads"]:
        assert command in root.stdout
    assert network.exit_code == 0
    assert "start" in network.stdout
    assert "stop" in network.stdout


def test_chrome_direct_dialog_text_matching() -> None:
    assert is_remote_debugging_dialog_text("要允许远程调试吗？")
    assert is_remote_debugging_dialog_text("Allow remote debugging?")
    assert is_allow_button_label("允许")
    assert is_allow_button_label("Allow")
    assert not is_allow_button_label("取消")


def test_raw_cdp_expression_does_not_wrap_iife_or_expression_arrow() -> None:
    assert _expression("(() => 1)()") == "(() => 1)()"
    assert _expression("JSON.stringify((() => ({ok:true}))())").startswith("JSON.stringify")
    assert _expression("() => 1") == "(() => 1)()"


def test_download_manager_records_download(tmp_path: Path) -> None:
    manager = DownloadManager(tmp_path)
    record = manager.list()

    assert record == []


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


def test_action_result_verification_field_defaults() -> None:
    result = ActionResult(type="click", success=True)

    assert result.verification == {}


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


def test_safety_does_not_block_safe_confirm_words() -> None:
    assert not is_dangerous_text("确认选择")
    assert not is_dangerous_text("确定")
    assert not is_dangerous_text("前往查看")
    assert not is_dangerous_text("开始筛选")
    assert not is_dangerous_text("保存当前模式")


def test_safety_still_blocks_high_risk_actions() -> None:
    assert is_dangerous_text("确认删除")
    assert is_dangerous_text("确认支付")
    assert is_dangerous_text("提交订单")
    assert is_dangerous_text("修改密码")


def test_act_dangerous_goal_blocks_until_confirmed() -> None:
    state = _sample_state()

    assert ActService().plan(state, "delete order") == []

    actions = ActService().plan(state, "delete order", allow_dangerous=True, require_confirm=True)
    assert actions
    assert actions[0].type == "click"
    assert actions[0].index == 2
    assert actions[0].require_confirm is True


def test_act_service_returns_structured_planner_result() -> None:
    result = ActService().plan_result(_sample_state(), "find Search products search box")

    assert result.planner == "heuristic"
    assert result.plan.actions
    assert result.plan.actions[0].type == "input_text"


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


class _FakeCdpClient:
    def __init__(self, targets: list[dict[str, object]]) -> None:
        self.targets = targets
        self.calls: list[str] = []

    async def send(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        self.calls.append(method)
        if method == "Target.getTargets":
            return {"targetInfos": self.targets}
        if method == "Target.createTarget":
            self.targets.append({"targetId": "created-target", "type": "page", "url": "about:blank"})
            return {"targetId": "created-target"}
        raise AssertionError(f"unexpected method: {method}")
