from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from browser_auto_ops.trace.redaction import redact


class TraceRecorder:
    def __init__(self, root: Path, session_id: str) -> None:
        self.root = root / "trace" / session_id
        self.session_id = session_id
        self.events_path = self.root / "events.jsonl"
        self.summary_path = self.root / "summary.json"
        self.states_dir = self.root / "states"
        self.screenshots_dir = self.root / "screenshots"
        self.network_dir = self.root / "network"
        for path in (self.root, self.states_dir, self.screenshots_dir, self.network_dir):
            path.mkdir(parents=True, exist_ok=True)

    def event(self, event_type: str, payload: Any) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "type": event_type,
            "payload": redact(_jsonable(payload)),
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._update_summary(event_type, record["ts"])

    def save_json(self, folder: str, name: str, payload: Any) -> Path:
        target_dir = self.root / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / name
        path.write_text(
            json.dumps(redact(_jsonable(payload)), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def _update_summary(self, event_type: str, timestamp: str) -> None:
        summary = _read_summary(self.summary_path, self.session_id)
        summary["events"] = int(summary.get("events", 0)) + 1
        event_types = summary.setdefault("event_types", {})
        event_types[event_type] = int(event_types.get(event_type, 0)) + 1
        summary["last_event_type"] = event_type
        summary["updated_at"] = timestamp
        summary["paths"] = {
            "events": str(self.events_path),
            "states": str(self.states_dir),
            "screenshots": str(self.screenshots_dir),
            "network": str(self.network_dir),
        }
        self.summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _read_summary(path: Path, session_id: str) -> dict[str, Any]:
    if not path.exists():
        return {
            "session_id": session_id,
            "events": 0,
            "event_types": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data.setdefault("session_id", session_id)
    data.setdefault("events", 0)
    data.setdefault("event_types", {})
    return data
