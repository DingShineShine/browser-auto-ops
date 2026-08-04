from __future__ import annotations

import os
from pathlib import Path


def project_data_dir() -> Path:
    raw = os.environ.get("BAO_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd() / ".bao"


def ensure_data_dirs(base: Path | None = None) -> Path:
    root = base or project_data_dir()
    for child in ("trace", "screenshots", "skills"):
        (root / child).mkdir(parents=True, exist_ok=True)
    return root

