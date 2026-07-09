import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


class JsonlTraceStore:
    """Append-only JSONL store for replayable agent traces."""

    def __init__(self, path: str = "logs/agent_traces.jsonl"):
        self.path = Path(path)

    def append(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace": trace,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def tail(self, limit: int = 20) -> List[Dict[str, Any]]:
        if limit <= 0 or not self.path.exists():
            return []

        lines = self.path.read_text(encoding="utf-8").splitlines()
        records = []
        for line in lines[-limit:]:
            if not line.strip():
                continue
            records.append(json.loads(line))
        return records
