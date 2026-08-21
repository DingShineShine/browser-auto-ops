from pathlib import Path

from browser_auto_ops.forge.install import install_skill, sanitize_text


def test_install_copies_sanitized_skill(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime" / "demo"
    (runtime / "scripts").mkdir(parents=True)
    (runtime / "SKILL.md").write_text(
        "# demo\n\npassword=Shinebed202603!\nads_user_id=k1fvr63o\nclick Clear All\n",
        encoding="utf-8",
    )
    (runtime / "scripts" / "extract.py").write_text("print('ok')\n", encoding="utf-8")
    agents = install_skill(runtime, tmp_path / ".agents" / "skills")
    text = (agents / "SKILL.md").read_text(encoding="utf-8")
    assert "Shinebed202603!" not in text
    assert "k1fvr63o" not in text
    assert "<ads-user-id>" in text
    assert (agents / "scripts" / "extract.py").exists()


def test_sanitize_text_redacts_secrets() -> None:
    text = sanitize_text("password: hunter2\nuser_id=abc123")
    assert "hunter2" not in text
    assert "abc123" not in text
