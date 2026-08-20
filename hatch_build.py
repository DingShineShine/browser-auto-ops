"""Optional Cython wheel hook. Not used by the default development install.

Keep this file for a later compiled release. `uv tool install git+...` must stay
pure Python so other machines do not need MSVC or zig.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

COMPILE_MODULES: tuple[tuple[str, str], ...] = (
    ("browser_auto_ops.snapshot.scanner", "src/browser_auto_ops/snapshot/scanner.py"),
    ("browser_auto_ops.actions.executor", "src/browser_auto_ops/actions/executor.py"),
    ("browser_auto_ops.providers.chrome_direct", "src/browser_auto_ops/providers/chrome_direct.py"),
    ("browser_auto_ops.providers.raw_cdp", "src/browser_auto_ops/providers/raw_cdp.py"),
    ("browser_auto_ops.providers.adspower_cdp", "src/browser_auto_ops/providers/adspower_cdp.py"),
    ("browser_auto_ops.sessions.manager", "src/browser_auto_ops/sessions/manager.py"),
)


try:
    from hatchling.builders.hooks.plugin.interface import BuildHookInterface
except ImportError:  # pragma: no cover - compile-only environments
    BuildHookInterface = object  # type: ignore[misc,assignment]


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        if self.target_name != "wheel" or version == "editable":
            return

        artifacts = collect_artifacts(Path(self.root))
        force_include = build_data.setdefault("force_include", {})
        for source, dest in artifacts:
            force_include[str(source)] = dest
        build_data["pure_python"] = False
        build_data["infer_tag"] = True


def collect_artifacts(root: Path) -> list[tuple[Path, str]]:
    try:
        return _compile_modules(root)
    except Exception as compile_error:
        prebuilt = _prebuilt_artifacts(root)
        if prebuilt:
            return prebuilt
        raise RuntimeError(
            "Cython compile failed and no prebuilt extensions were found.\n"
            "Install Visual Studio 2022 Build Tools, or run:\n"
            "  uv pip install cython setuptools ziglang\n"
            "  python hatch_build.py\n"
            f"Original error: {compile_error}"
        ) from compile_error


def _ext_suffix() -> str:
    return sysconfig.get_config_var("EXT_SUFFIX") or ".pyd"


def _dest_for(module: str, pyd_name: str) -> str:
    return str(Path(*module.split(".")).with_name(pyd_name))


def _prebuilt_artifacts(root: Path) -> list[tuple[Path, str]]:
    suffix = _ext_suffix()
    found: list[tuple[Path, str]] = []
    for module, rel in COMPILE_MODULES:
        pyd_name = module.split(".")[-1] + suffix
        candidate = (root / rel).with_name(pyd_name)
        if candidate.is_file():
            found.append((candidate, _dest_for(module, pyd_name)))
    if len(found) == len(COMPILE_MODULES):
        return found
    return []


def _compile_modules(root: Path) -> list[tuple[Path, str]]:
    work = Path(tempfile.mkdtemp(prefix="bao-cython-"))
    suffix = _ext_suffix()
    compiled: list[tuple[Path, str]] = []
    errors: list[str] = []

    for module, rel in COMPILE_MODULES:
        py_path = root / rel
        if not py_path.is_file():
            raise FileNotFoundError(f"cannot compile missing module source: {rel}")
        c_path = work / f"{module}.c"
        pyd_name = module.split(".")[-1] + suffix
        pyd_path = work / pyd_name
        try:
            _cythonize(py_path, c_path)
            _link_extension(c_path, pyd_path)
        except Exception as exc:  # pragma: no cover - surfaced to the build backend
            errors.append(f"{module}: {exc}")
            continue
        compiled.append((pyd_path, _dest_for(module, pyd_name)))

    if errors:
        raise RuntimeError("\n".join(errors))
    return compiled


def compile_inplace(root: Path | None = None) -> list[Path]:
    root = root or Path(__file__).resolve().parent
    artifacts = _compile_modules(root)
    written: list[Path] = []
    for source, dest in artifacts:
        target = root / "src" / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        written.append(target)
        print(target)
    return written


def _cythonize(py_path: Path, c_path: Path) -> None:
    cmd = [
        sys.executable,
        "-m",
        "cython",
        "-3",
        "-X",
        "annotation_typing=False",
        "-o",
        str(c_path),
        str(py_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(detail or str(exc)) from exc


def _link_extension(c_path: Path, output: Path) -> None:
    errors: list[str] = []
    if shutil.which("cl.exe"):
        msvc_error = _try_setuptools_link(c_path, output)
        if output.is_file():
            return
        errors.append(f"MSVC: {msvc_error}")
    else:
        errors.append("MSVC: cl.exe not on PATH")
    zig_error = _try_zig_link(c_path, output)
    if output.is_file():
        return
    errors.append(f"zig: {zig_error}")
    raise RuntimeError("; ".join(errors))


def _try_setuptools_link(c_path: Path, output: Path) -> str:
    try:
        from setuptools import Distribution, Extension
        from setuptools.command.build_ext import build_ext
    except Exception as exc:  # pragma: no cover
        return f"setuptools unavailable ({exc})"

    module_name = output.stem.split(".")[0]
    ext = Extension(module_name, sources=[str(c_path)])
    build_dir = output.parent / "msvc-build"
    build_dir.mkdir(parents=True, exist_ok=True)
    dist = Distribution({"name": "browser_auto_ops_ext", "ext_modules": [ext]})
    cmd = build_ext(dist)
    cmd.build_lib = str(build_dir)
    cmd.build_temp = str(build_dir / "tmp")
    cmd.inplace = False
    try:
        cmd.ensure_finalized()
        cmd.run()
    except Exception as exc:
        return str(exc)
    produced = list(build_dir.rglob(output.name)) or list(build_dir.rglob(f"{module_name}.*"))
    produced = [path for path in produced if path.suffix in {".pyd", ".so"}]
    if not produced:
        return "setuptools produced no extension module"
    shutil.copy2(produced[0], output)
    return ""


def _try_zig_link(c_path: Path, output: Path) -> str:
    zig = _zig_executable()
    if zig is None:
        return "zig executable not found"
    include = sysconfig.get_path("include")
    libdir = Path(sys.base_prefix) / "libs"
    py_lib = f"python{sys.version_info.major}{sys.version_info.minor}"
    cmd = [
        zig,
        "cc",
        "-shared",
        "-O2",
        f"-I{include}",
        str(c_path),
        "-o",
        str(output),
        f"-L{libdir}",
        f"-l{py_lib}",
    ]
    if os.name == "nt":
        cmd[2:2] = ["-target", "x86_64-windows-gnu"]
    try:
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
        del completed
    except subprocess.CalledProcessError as exc:
        return (exc.stderr or exc.stdout or str(exc))[:800]
    except Exception as exc:
        return str(exc)[:800]
    return ""


def _zig_executable() -> str | None:
    for candidate in ("zig", "zig.exe"):
        path = shutil.which(candidate)
        if path:
            return path
    try:
        import ziglang  # type: ignore

        package_dir = Path(ziglang.__file__).resolve().parent
        for name in ("zig.exe", "zig"):
            binary = package_dir / name
            if binary.is_file():
                return str(binary)
            nested = next(package_dir.rglob(name), None)
            if nested:
                return str(nested)
    except Exception:
        return None
    return None


if __name__ == "__main__":
    compile_inplace()
