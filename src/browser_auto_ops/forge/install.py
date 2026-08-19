from __future__ import annotations

import re
import shutil
from pathlib import Path

_SECRET_KEYS = {"password", "passwd", "secret", "cookie", "authorization", "api_key", "api-key"}
_ADS_KEYS = {"ads_user_id", "ads-user-id", "user_id"}
_PASSWORD_TOKEN = re.compile(r"(?i)(password|passwd)\s+\S+")


def install_skill(runtime_root: Path, agents_root: Path) -> Path:
    agents_root.mkdir(parents=True, exist_ok=True)
    target = agents_root / runtime_root.name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    skill = runtime_root / "SKILL.md"
    if skill.exists():
        (target / "SKILL.md").write_text(sanitize_text(skill.read_text(encoding="utf-8")), encoding="utf-8")
    scripts = runtime_root / "scripts"
    if scripts.exists():
        dest = target / "scripts"
        dest.mkdir(parents=True, exist_ok=True)
        for path in scripts.iterdir():
            if path.is_file() and path.suffix == ".py":
                dest.joinpath(path.name).write_text(sanitize_text(path.read_text(encoding="utf-8")), encoding="utf-8")
    return target


def sanitize_text(text: str) -> str:
    cleaned = "\n".join(_sanitize_line(line) for line in text.splitlines())
    cleaned = _PASSWORD_TOKEN.sub(lambda match: f"{match.group(1)} [REDACTED]", cleaned)
    return cleaned


def _sanitize_line(line: str) -> str:
    parsed = _simple_kv_prefix(line)
    if not parsed:
        return line
    prefix, key = parsed
    normalized = key.strip("\"'").lower()
    if normalized in _SECRET_KEYS:
        return f"{prefix}[REDACTED]"
    if normalized in _ADS_KEYS:
        return f"{prefix}<ads-user-id>"
    return line


def _simple_kv_prefix(line: str) -> tuple[str, str] | None:
    stripped = line.lstrip()
    indent = line[: len(line) - len(stripped)]
    for separator in (":", "="):
        if separator not in stripped:
            continue
        key, _value = stripped.split(separator, 1)
        if not key.strip() or any(char in key for char in "[]()."):
            return None
        return indent + key + separator, key.strip()
    return None
