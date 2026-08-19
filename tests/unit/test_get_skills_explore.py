from typer.testing import CliRunner

from browser_auto_ops.cli import app


runner = CliRunner()


def test_get_skills_explore_lists_existing_commands() -> None:
    result = runner.invoke(app, ["get-skills", "explore"])
    assert result.exit_code == 0
    stdout = result.stdout.lower()
    assert "wait" in stdout
    assert "state" in stdout
    assert "get title" in stdout
    assert "screenshot" in stdout
    assert "network requests" in stdout
    assert "login_required" not in stdout
    assert "login_hint" not in stdout
    assert "日历" not in result.stdout
    assert "t-5" not in stdout
    assert "bao network har" not in stdout
    assert "there is no `network har`" in stdout
    assert "--filter graphql" not in stdout
    assert "--filter <url-substring-from-results>" in stdout
    assert "matches url text only" in stdout
