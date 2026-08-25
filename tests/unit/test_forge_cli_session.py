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


def test_forge_run_hits_daemon_with_generated_skill(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    skill = tmp_path / ".bao" / "skills" / "wayfair-ads-product-report"
    skill.mkdir(parents=True)
    calls: list[tuple[str, str, dict | None]] = []

    def fake_request(method: str, path: str, payload=None, **kwargs):
        calls.append((method, path, payload))
        if path == "/health":
            return {"ok": True, "data_root": str((tmp_path / ".bao").resolve())}
        if path == "/forge/run":
            assert payload["session"] == "wayfair-ads"
            assert Path(payload["skill_dir"]) == skill
            return {"ok": True, "steps": 3, "results": []}
        raise AssertionError(path)

    monkeypatch.setattr("browser_auto_ops.cli._daemon_request", fake_request)
    result = runner.invoke(app, ["forge", "run", "wayfair-ads-product-report", "--session", "wayfair-ads"])

    assert result.exit_code == 0
    assert (
        "POST",
        "/forge/run",
        {
            "skill_dir": str(skill),
            "session": "wayfair-ads",
            "include_state": False,
            "params": {},
            "output_dir": None,
        },
    ) in calls
    assert '"ok": true' in result.stdout.lower()


def test_forge_params_review_prints_candidates(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    skill = tmp_path / ".bao" / "skills" / "report"
    evidence = skill / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "workflow.json").write_text(
        '{"requires_parameter_review": true, "parameters": [], "parameter_candidates": [{"name": "date_1", "requires_confirmation": true}, {"name": "report_id", "binding_scope": "runtime_output"}]}',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["forge", "params", "review", "report"])

    assert result.exit_code == 0
    assert "parameter_candidates" in result.stdout
    assert "unresolved" in result.stdout
    assert "runtime_outputs" in result.stdout
