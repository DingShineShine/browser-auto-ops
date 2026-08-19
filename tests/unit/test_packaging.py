import zipfile
from pathlib import Path

import pytest

from browser_auto_ops.actions import executor
from browser_auto_ops.providers import adspower_cdp, chrome_direct, raw_cdp
from browser_auto_ops.sessions import manager
from browser_auto_ops.snapshot import scanner


def test_core_implementation_modules_import() -> None:
    assert scanner.SnapshotEngine is not None or hasattr(scanner, "DOM_SCANNER")
    assert hasattr(executor, "ActionExecutor")
    assert hasattr(chrome_direct, "ChromeDirectProvider")
    assert hasattr(raw_cdp, "connect_raw_cdp") or hasattr(raw_cdp, "RawCdpClient")
    assert hasattr(adspower_cdp, "AdspowerCdpProvider")
    assert hasattr(manager, "SessionManager")


COMPILED_PY_NAMES = {
    "browser_auto_ops/snapshot/scanner.py",
    "browser_auto_ops/actions/executor.py",
    "browser_auto_ops/providers/chrome_direct.py",
    "browser_auto_ops/providers/raw_cdp.py",
    "browser_auto_ops/providers/adspower_cdp.py",
    "browser_auto_ops/sessions/manager.py",
}


@pytest.mark.skipif(
    Path(scanner.__file__).suffix == ".py",
    reason="source checkout still exposes .py; compiled wheels replace these modules",
)
def test_published_modules_are_compiled() -> None:
    for module in (scanner, executor, chrome_direct, raw_cdp, adspower_cdp, manager):
        assert Path(module.__file__).suffix in {".pyd", ".so"}


def test_dist_wheel_hides_compiled_sources() -> None:
    wheels = list(Path("dist").glob("browser_auto_ops-*.whl"))
    if not wheels:
        pytest.skip("no wheel in dist/")
    names = zipfile.ZipFile(wheels[-1]).namelist()
    hidden = COMPILED_PY_NAMES.intersection(names)
    assert not hidden, hidden
    assert any(name.endswith(".pyd") or name.endswith(".so") for name in names)
    assert not any(name.startswith("downloads/") for name in names)
