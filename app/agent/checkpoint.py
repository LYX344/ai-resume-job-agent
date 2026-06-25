from __future__ import annotations

import pickle
import time
from collections import defaultdict
from pathlib import Path
from threading import RLock, get_ident
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver


class LocalFileCheckpointSaver(InMemorySaver):
    """Persist LangGraph checkpoints to a local file for single-process demos.

    This saver keeps LangGraph's in-memory behavior, but snapshots the already
    serialized checkpoint storage to disk after writes. It is durable across
    local process restarts, but it is not a production multi-worker checkpointer.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = RLock()
        super().__init__()
        self._load_from_disk()

    def put(self, config, checkpoint, metadata, new_versions):
        with self._lock:
            next_config = super().put(config, checkpoint, metadata, new_versions)
            self._persist_to_disk()
            return next_config

    def put_writes(self, config, writes, task_id: str, task_path: str = "") -> None:
        with self._lock:
            super().put_writes(config, writes, task_id, task_path)
            self._persist_to_disk()

    def delete_thread(self, thread_id: str) -> None:
        with self._lock:
            super().delete_thread(thread_id)
            self._persist_to_disk()

    def _persist_to_disk(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(
            f"{self.path.name}.{get_ident()}.{uuid4().hex}.tmp"
        )
        payload = {
            "storage": _plain_storage(self.storage),
            "writes": dict(self.writes),
            "blobs": dict(self.blobs),
        }
        try:
            with tmp_path.open("wb") as file:
                pickle.dump(payload, file, protocol=pickle.HIGHEST_PROTOCOL)
            _replace_with_retry(tmp_path, self.path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def _load_from_disk(self) -> None:
        if not self.path.exists():
            return

        with self.path.open("rb") as file:
            payload: dict[str, Any] = pickle.load(file)

        self.storage = _restore_storage(payload.get("storage", {}))
        self.writes = defaultdict(dict, payload.get("writes", {}))
        self.blobs = dict(payload.get("blobs", {}))


def _plain_storage(storage: defaultdict) -> dict:
    return {
        thread_id: {
            namespace: dict(checkpoints)
            for namespace, checkpoints in namespaces.items()
        }
        for thread_id, namespaces in storage.items()
    }


def _restore_storage(storage: dict) -> defaultdict:
    restored = defaultdict(lambda: defaultdict(dict))
    for thread_id, namespaces in storage.items():
        restored[thread_id] = defaultdict(dict)
        for namespace, checkpoints in namespaces.items():
            restored[thread_id][namespace] = dict(checkpoints)
    return restored


def _replace_with_retry(source: Path, target: Path) -> None:
    for attempt in range(5):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.02 * (attempt + 1))
