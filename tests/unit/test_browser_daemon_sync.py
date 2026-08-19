from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from browser_auto_ops.cli import app
from browser_auto_ops.schemas import BrowserIdentity, ProviderConfig
from browser_auto_ops.server import app as server_app
from browser_auto_ops import server as server_module
from browser_auto_ops.browsers import BrowserStore


runner = CliRunner()


def test_health_includes_data_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BAO_HOME", str(tmp_path))
    client = TestClient(server_app)
    payload = client.get("/health").json()
    assert payload["ok"] is True
    assert payload["data_root"] == str(tmp_path.resolve())
    assert "cwd" in payload
    assert "version" in payload
    assert "import_path" in payload


def test_browsers_api_round_trip(tmp_path: Path) -> None:
    server_module.browser_store = BrowserStore(tmp_path)
    client = TestClient(server_app)
    identity = BrowserIdentity(
        name="ads-one",
        type="ads",
        provider_config=ProviderConfig(
            provider="adspower-cdp",
            ads_base_url="http://127.0.0.1:50325",
            ads_user_id="profile-1",
        ),
    )
    created = client.post("/browsers", json=identity.model_dump(mode="json")).json()
    listed = client.get("/browsers").json()
    assert created["name"] == "ads-one"
    assert any(item["name"] == "ads-one" for item in listed)


def test_browser_create_uses_daemon_when_home_matches(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BAO_HOME", str(tmp_path / ".bao"))
    identity = {
        "browser_id": "b_test",
        "type": "ads",
        "name": "ads-daemon",
        "desc": "",
        "provider_config": {
            "provider": "adspower-cdp",
            "ads_base_url": "http://127.0.0.1:50325",
            "ads_user_id": "profile-1",
        },
    }

    def fake_request(method: str, path: str, payload=None, **kwargs):
        if path == "/health":
            return {"ok": True, "data_root": str((tmp_path / ".bao").resolve())}
        if method == "POST" and path == "/browsers":
            return payload
        if method == "GET" and path == "/browsers":
            return [identity]
        raise AssertionError(f"unexpected {method} {path}")

    monkeypatch.setattr("browser_auto_ops.cli._daemon_request", fake_request)
    create = runner.invoke(
        app,
        [
            "browser",
            "create",
            "--type",
            "ads",
            "--name",
            "ads-daemon",
            "--ads-base-url",
            "http://127.0.0.1:50325",
            "--ads-user-id",
            "profile-1",
        ],
    )
    listed = runner.invoke(app, ["browser", "list"])
    assert create.exit_code == 0
    assert listed.exit_code == 0
    assert "ads-daemon" in listed.stdout


def test_daemon_status_includes_cli_runtime(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    def fake_request(method: str, path: str, payload=None, **kwargs):
        if path == "/health":
            return {
                "ok": True,
                "data_root": str((tmp_path / ".bao").resolve()),
                "import_path": __file__,
                "version": "0.1.0",
            }
        raise AssertionError(path)

    monkeypatch.setattr("browser_auto_ops.cli._daemon_request", fake_request)
    result = runner.invoke(app, ["daemon", "status"])

    assert result.exit_code == 0
    assert '"cli"' in result.stdout
    assert "import_path" in result.stdout
    assert "version" in result.stdout
