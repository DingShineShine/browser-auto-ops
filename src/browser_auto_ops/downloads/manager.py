from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from browser_auto_ops.config import ensure_data_dirs
from browser_auto_ops.schemas import DownloadRecord


class DownloadManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = ensure_data_dirs(root)
        self.download_root = self.root / "downloads"
        self.download_root.mkdir(parents=True, exist_ok=True)
        self.records_path = self.download_root / "downloads.json"

    def list(self, session_id: str | None = None) -> list[DownloadRecord]:
        records = list(self._read().values())
        if session_id:
            records = [record for record in records if record.session_id == session_id]
        return records

    def save(self, record: DownloadRecord) -> None:
        records = self._read()
        records[record.download_id] = record
        self._write(records)

    async def download_url(
        self,
        *,
        session_id: str,
        url: str,
        browser_id: str | None = None,
        output_dir: Path | None = None,
    ) -> DownloadRecord:
        filename = _filename_from_url(url)
        target_dir = output_dir or self.download_root / session_id
        target_dir = target_dir.expanduser().resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        record = DownloadRecord(
            session_id=session_id,
            browser_id=browser_id,
            source_url=url,
            suggested_filename=filename,
            final_path=str(target),
            status="running",
        )
        self.save(record)
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=120.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                target.write_bytes(response.content)
            record.status = "completed"
            record.finished_at = datetime.now(timezone.utc)
        except Exception as exc:
            record.status = "failed"
            record.error = str(exc)
            record.finished_at = datetime.now(timezone.utc)
        self.save(record)
        return record

    def _read(self) -> dict[str, DownloadRecord]:
        if not self.records_path.exists():
            return {}
        try:
            raw = json.loads(self.records_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return {key: DownloadRecord.model_validate(value) for key, value in raw.items()}

    def _write(self, records: dict[str, DownloadRecord]) -> None:
        payload = {key: record.model_dump(mode="json") for key, record in records.items()}
        self.records_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _filename_from_url(url: str) -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name
    return name or "download.bin"
