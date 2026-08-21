import json
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from browser_auto_ops import cli as cli_module
from browser_auto_ops import server as server_module
from browser_auto_ops.browsers import BrowserStore
from browser_auto_ops.cli import app
from browser_auto_ops.schemas import BrowserIdentity, ProviderConfig
from browser_auto_ops.server import app as server_app


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


def test_browsers_api_round_trip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(server_module, "browser_store", BrowserStore(tmp_path))
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


def test_browser_commands_fail_when_daemon_home_mismatches(tmp_path: Path, monkeypatch) -> None:
    current_root = tmp_path / "current" / ".bao"
    remote_root = tmp_path / "remote" / ".bao"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BAO_HOME", str(current_root))
    BrowserStore().save(
        BrowserIdentity(
            name="ads-local",
            type="ads",
            provider_config=ProviderConfig(
                provider="adspower-cdp",
                ads_base_url="http://127.0.0.1:50325",
                ads_user_id="profile-local",
            ),
        )
    )

    def fake_request(method: str, path: str, payload=None, **kwargs):
        if path == "/health":
            return {
                "ok": True,
                "data_root": str(remote_root.resolve()),
                "import_path": str(Path("browser_auto_ops") / "server.py"),
            }
        raise AssertionError(f"unexpected {method} {path}")

    monkeypatch.setattr("browser_auto_ops.cli._daemon_request", fake_request)

    commands = [
        ["browser", "list"],
        ["browser", "delete", "ads-local"],
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
    ]
    for command in commands:
        result = runner.invoke(app, command)
        assert result.exit_code != 0
        assert "daemon data_root" in result.output

    assert BrowserStore().get("ads-local") is not None
    assert BrowserStore().get("ads-daemon") is None


def test_daemon_stop_uses_health_data_root_pid_file(tmp_path: Path, monkeypatch) -> None:
    current_root = tmp_path / "current" / ".bao"
    remote_root = tmp_path / "remote" / ".bao"
    remote_root.mkdir(parents=True)
    (remote_root / "daemon.json").write_text(
        json.dumps({"pid": 4242, "url": "http://127.0.0.1:8765", "data_root": str(remote_root.resolve())}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BAO_HOME", str(current_root))
    monkeypatch.setattr(
        cli_module,
        "_daemon_health",
        lambda timeout=1.0: {
            "ok": True,
            "data_root": str(remote_root.resolve()),
            "import_path": str(Path("browser_auto_ops") / "server.py"),
        },
    )
    monkeypatch.setattr(cli_module, "_wait_daemon_down", lambda timeout=5.0: True)
    killed: list[int] = []

    if os.name == "nt":
        def fake_run(command, **kwargs):
            killed.append(int(command[2]))
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(cli_module.subprocess, "run", fake_run)
    else:
        def fake_kill(pid: int, signal: int) -> None:
            killed.append(pid)

        monkeypatch.setattr(cli_module.os, "kill", fake_kill)

    result = runner.invoke(app, ["daemon", "stop"])

    assert result.exit_code == 0
    assert '"stopped": true' in result.stdout
    assert '"source": "health"' in result.stdout
    assert killed == [4242]
    assert not (remote_root / "daemon.json").exists()


def test_daemon_start_reuses_matching_daemon(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / ".bao"
    root.mkdir()
    (root / "daemon.json").write_text(
        json.dumps({"pid": 1111, "url": "http://127.0.0.1:8765", "data_root": str(root.resolve())}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BAO_HOME", str(root))
    monkeypatch.setattr(
        cli_module,
        "_daemon_health",
        lambda timeout=1.0: {"ok": True, "data_root": str(root.resolve())},
    )

    def fail_popen(*args, **kwargs):
        raise AssertionError("start should reuse the matching daemon")

    monkeypatch.setattr(cli_module.subprocess, "Popen", fail_popen)

    result = runner.invoke(app, ["daemon", "start"])

    assert result.exit_code == 0
    assert '"reused": true' in result.stdout
    assert '"pid": 1111' in result.stdout


def test_daemon_start_replaces_mismatched_daemon(tmp_path: Path, monkeypatch) -> None:
    current_root = tmp_path / "current" / ".bao"
    remote_root = tmp_path / "remote" / ".bao"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BAO_HOME", str(current_root))
    stopped: list[str] = []

    monkeypatch.setattr(
        cli_module,
        "_daemon_health",
        lambda timeout=1.0: {"ok": True, "data_root": str(remote_root.resolve())},
    )

    def fake_stop(health):
        stopped.append(str(health["data_root"]))
        return {"ok": True, "stopped": True, "pid": 1234}

    class FakeProcess:
        pid = 5678

        def poll(self):
            return None

    monkeypatch.setattr(cli_module, "_stop_daemon_from_health", fake_stop)
    monkeypatch.setattr(cli_module, "_wait_daemon_down", lambda timeout=5.0: True)
    monkeypatch.setattr(
        cli_module,
        "_wait_daemon_up",
        lambda root, timeout=5.0: {"ok": True, "data_root": str(root.resolve())},
    )
    monkeypatch.setattr(cli_module.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    result = runner.invoke(app, ["daemon", "start"])

    assert result.exit_code == 0
    assert stopped == [str(remote_root.resolve())]
    assert '"pid": 5678' in result.stdout
    assert (current_root / "daemon.json").exists()


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
