import json
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional


class _InterProcessFileLock:
    """Small cross-platform exclusive lock backed by a sibling lock file."""

    def __init__(self, path: Path):
        self.path = path
        self._file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+b")
        if os.name == "nt":
            import msvcrt

            self._file.seek(0)
            msvcrt.locking(self._file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._file is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None


class JsonlTraceStore:
    """Append-only JSONL store for replayable agent traces."""

    def __init__(
        self,
        path: str = "logs/agent_traces.jsonl",
        max_bytes: Optional[int] = None,
        backup_count: Optional[int] = None,
    ):
        self.path = Path(path)
        try:
            configured_max_bytes = int(
                max_bytes if max_bytes is not None else os.getenv("AGENT_TRACE_MAX_BYTES", "10485760")
            )
        except (TypeError, ValueError):
            configured_max_bytes = 10485760
        try:
            configured_backup_count = int(
                backup_count
                if backup_count is not None
                else os.getenv("AGENT_TRACE_BACKUP_COUNT", "3")
            )
        except (TypeError, ValueError):
            configured_backup_count = 3
        self.max_bytes = max(
            1024,
            configured_max_bytes,
        )
        self.backup_count = max(
            0,
            configured_backup_count,
        )
        self._lock = RLock()
        self._process_lock_path = self.path.with_name(f"{self.path.name}.lock")

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if not self.path.exists() or self.path.stat().st_size + incoming_bytes <= self.max_bytes:
            return
        if self.backup_count == 0:
            self.path.unlink(missing_ok=True)
            return
        oldest = self.path.with_name(f"{self.path.name}.{self.backup_count}")
        oldest.unlink(missing_ok=True)
        for index in range(self.backup_count - 1, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            if source.exists():
                source.replace(self.path.with_name(f"{self.path.name}.{index + 1}"))
        self.path.replace(self.path.with_name(f"{self.path.name}.1"))

    def append(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace": trace,
        }
        serialized = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with _InterProcessFileLock(self._process_lock_path):
                self._rotate_if_needed(len(serialized.encode("utf-8")))
                with self.path.open("a", encoding="utf-8") as file:
                    file.write(serialized)
        return record

    def tail(self, limit: int = 20) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []

        with self._lock:
            with _InterProcessFileLock(self._process_lock_path):
                if not self.path.exists():
                    return []
                lines = deque(maxlen=limit)
                with self.path.open("r", encoding="utf-8") as file:
                    for line in file:
                        if line.strip():
                            lines.append(line)

        records = []
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records
