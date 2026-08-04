from __future__ import annotations

import json
from pathlib import Path

from browser_auto_ops.config import ensure_data_dirs
from browser_auto_ops.schemas import BrowserSession


class SessionStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = ensure_data_dirs(root)
        self.path = self.root / "sessions.json"

    def list(self) -> list[BrowserSession]:
        return list(self._read().values())

    def get(self, session_id: str) -> BrowserSession | None:
        sessions = self._read()
        if session_id in sessions:
            return sessions[session_id]
        for session in sessions.values():
            if session.name == session_id:
                return session
        return None

    def save(self, session: BrowserSession) -> None:
        sessions = self._read()
        sessions[session.session_id] = session
        self._write(sessions)

    def delete(self, session_id: str) -> None:
        sessions = self._read()
        sessions.pop(session_id, None)
        self._write(sessions)

    def _read(self) -> dict[str, BrowserSession]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {
            session_id: BrowserSession.model_validate(payload)
            for session_id, payload in raw.items()
        }

    def _write(self, sessions: dict[str, BrowserSession]) -> None:
        payload = {
            session_id: session.model_dump(mode="json")
            for session_id, session in sessions.items()
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

