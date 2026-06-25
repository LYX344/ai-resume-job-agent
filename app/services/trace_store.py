"""Local, file-based agent run trace store (no LangSmith cloud dependency).

Each agent/multi-agent run appends one JSON line to a local JSONL file with the
node flow, intent, latency, token usage and model. This keeps the "run-level
trace, replayable" interview point while staying fully offline / domestic-
friendly. Production could swap the backend for Redis/Postgres/OTel.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.models.trace import TraceRecord


class TraceStore:
    def __init__(self, file_path: str) -> None:
        self._path = Path(file_path)

    @classmethod
    def from_settings(cls) -> "TraceStore":
        return cls(settings.trace_path)

    def append(self, record: TraceRecord) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")

    def list_recent(self, limit: int = 20) -> list[TraceRecord]:
        records = self._read_all()
        return list(reversed(records))[: max(0, limit)]

    def get(self, trace_id: str) -> TraceRecord | None:
        for record in reversed(self._read_all()):
            if record.trace_id == trace_id:
                return record
        return None

    def _read_all(self) -> list[TraceRecord]:
        if not self._path.exists():
            return []
        records: list[TraceRecord] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(TraceRecord.model_validate_json(stripped))
            except ValueError:
                continue
        return records
