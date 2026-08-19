from pathlib import Path

from typer.testing import CliRunner

from browser_auto_ops.cli import app


runner = CliRunner()


def test_forge_generate_requires_session_or_trace() -> None:
    result = runner.invoke(app, ["forge", "generate", "--name", "demo"])
    assert result.exit_code != 0


def test_forge_generate_from_session_hits_daemon(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[tuple[str, str]] = []

    def fake_request(method: str, path: str, payload=None, **kwargs):
        calls.append((method, path))
        if path == "/health":
            return {"ok": True, "data_root": str((tmp_path / ".bao").resolve())}
        if path == "/forge/generate":
            return {"skill_path": str(tmp_path / "skill"), "generation_report": {"actions": {"included": 1}}}
        raise AssertionError(path)

    monkeypatch.setattr("browser_auto_ops.cli._daemon_request", fake_request)
    result = runner.invoke(
        app,
        ["forge", "generate", "--session", "wayfair-po", "--name", "wayfair-dropship-po-export", "--goal", "export"],
    )
    assert result.exit_code == 0
    assert ("POST", "/forge/generate") in calls
    assert "skill_path" in result.stdout
    assert "generation_report" in result.stdout


def test_forge_explore_appends_via_daemon(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    def fake_request(method: str, path: str, payload=None, **kwargs):
        if path == "/health":
            return {"ok": True, "data_root": str((tmp_path / ".bao").resolve())}
        if path.endswith("/forge/explore"):
            assert payload == {"goal": "export orders"}
            return {"trace_dir": str(tmp_path / "trace" / "s_live")}
        raise AssertionError(path)

    monkeypatch.setattr("browser_auto_ops.cli._daemon_request", fake_request)
    result = runner.invoke(app, ["forge", "explore", "wayfair-po", "--goal", "export orders"])
    assert result.exit_code == 0
    assert "s_live" in result.stdout
