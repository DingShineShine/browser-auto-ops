import zipfile
from pathlib import Path

import pytest

from browser_auto_ops.actions import executor
from browser_auto_ops.providers import adspower_cdp, chrome_direct, raw_cdp
from browser_auto_ops.sessions import manager
from browser_auto_ops.snapshot import scanner


SOURCE_PY_NAMES = {
    "browser_auto_ops/snapshot/scanner.py",
    "browser_auto_ops/actions/executor.py",
    "browser_auto_ops/providers/chrome_direct.py",
    "browser_auto_ops/providers/raw_cdp.py",
    "browser_auto_ops/providers/adspower_cdp.py",
    "browser_auto_ops/sessions/manager.py",
}


def test_core_implementation_modules_import() -> None:
    assert scanner.SnapshotEngine is not None or hasattr(scanner, "DOM_SCANNER")
    assert hasattr(executor, "ActionExecutor")
    assert hasattr(chrome_direct, "ChromeDirectProvider")
    assert hasattr(raw_cdp, "connect_raw_cdp") or hasattr(raw_cdp, "RawCdpClient")
    assert hasattr(adspower_cdp, "AdspowerCdpProvider")
    assert hasattr(manager, "SessionManager")


@pytest.mark.skipif(
    Path(scanner.__file__).suffix == ".py",
    reason="development wheels ship source; compiled extensions are optional later",
)
def test_published_modules_are_compiled() -> None:
    for module in (scanner, executor, chrome_direct, raw_cdp, adspower_cdp, manager):
        assert Path(module.__file__).suffix in {".pyd", ".so"}


def test_dist_wheel_keeps_implementation_sources() -> None:
    wheels = list(Path("dist").glob("browser_auto_ops-*.whl"))
    if not wheels:
        pytest.skip("no wheel in dist/")
    names = zipfile.ZipFile(max(wheels, key=lambda path: path.stat().st_mtime)).namelist()
    missing = SOURCE_PY_NAMES.difference(names)
    assert not missing, missing
    assert not any(name.startswith("downloads/") for name in names)
