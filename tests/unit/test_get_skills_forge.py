from typer.testing import CliRunner

from browser_auto_ops.cli import app


runner = CliRunner()


def test_get_skills_forge_describes_generate_from_session() -> None:
    result = runner.invoke(app, ["get-skills", "forge"])
    assert result.exit_code == 0
    stdout = result.stdout.lower()
    assert "describe" in stdout
    assert "explore" in stdout
    assert "generate" in stdout
    assert "self-test" in stdout or "forge test" in stdout
    assert "forge generate --session" in stdout
    assert "data_root" in stdout
    assert ".agents/skills" in stdout
    assert "password" in stdout


def test_get_skills_core_points_to_explore_and_forge() -> None:
    result = runner.invoke(app, ["get-skills", "core"])
    assert result.exit_code == 0
    assert "get-skills explore" in result.stdout
    assert "get-skills forge" in result.stdout
