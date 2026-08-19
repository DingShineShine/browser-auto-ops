from pathlib import Path

from browser_auto_ops.config import ensure_data_dirs, project_data_dir


def test_project_data_dir_prefers_bao_home(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "custom-home"
    monkeypatch.setenv("BAO_HOME", str(home))
    assert project_data_dir() == home.resolve()


def test_project_data_dir_defaults_to_cwd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BAO_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    assert project_data_dir() == (tmp_path / ".bao").resolve()


def test_ensure_data_dirs_creates_children(tmp_path: Path) -> None:
    root = ensure_data_dirs(tmp_path / "bao")
    assert (root / "trace").is_dir()
    assert (root / "skills").is_dir()
    assert (root / "screenshots").is_dir()
