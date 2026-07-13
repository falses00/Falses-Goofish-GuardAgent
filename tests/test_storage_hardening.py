import json
import subprocess
import sys
import time
from pathlib import Path

from context_manager import ChatContextManager
from core.trace_store import JsonlTraceStore


def test_chat_context_uses_wal_and_busy_timeout(tmp_path):
    manager = ChatContextManager(db_path=str(tmp_path / "chat.db"))

    with manager._connect() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]

    assert journal_mode.lower() == "wal"
    assert busy_timeout == 30000


def test_chat_context_falls_back_from_invalid_busy_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_BUSY_TIMEOUT_MS", "invalid")

    manager = ChatContextManager(db_path=str(tmp_path / "chat.db"))

    assert manager.busy_timeout_ms == 30000


def test_trace_store_rotates_bounded_files(tmp_path):
    path = tmp_path / "agent_traces.jsonl"
    store = JsonlTraceStore(str(path), max_bytes=1024, backup_count=2)

    store.append({"chat_id": "first", "payload": "x" * 800})
    store.append({"chat_id": "second", "payload": "y" * 800})

    assert path.exists()
    assert path.with_name("agent_traces.jsonl.1").exists()
    assert store.tail(10)[0]["trace"]["chat_id"] == "second"


def test_trace_store_skips_partial_or_corrupt_records(tmp_path):
    path = tmp_path / "agent_traces.jsonl"
    valid = {"timestamp": "now", "trace": {"chat_id": "safe"}}
    path.write_text(
        json.dumps(valid) + "\n" + '{"timestamp":"partial"' + "\n",
        encoding="utf-8",
    )

    records = JsonlTraceStore(str(path)).tail(10)

    assert records == [valid]


def test_trace_store_falls_back_from_invalid_rotation_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_TRACE_MAX_BYTES", "invalid")
    monkeypatch.setenv("AGENT_TRACE_BACKUP_COUNT", "invalid")

    store = JsonlTraceStore(str(tmp_path / "agent_traces.jsonl"))

    assert store.max_bytes == 10485760
    assert store.backup_count == 3


def test_trace_rotation_is_safe_across_processes(tmp_path):
    path = tmp_path / "agent_traces.jsonl"
    start_gate = tmp_path / "start-gate"
    repo_root = Path(__file__).resolve().parents[1]
    script = (
        "import sys, time; "
        "from pathlib import Path; "
        "from core.trace_store import JsonlTraceStore; "
        "store=JsonlTraceStore(sys.argv[1], max_bytes=1024, backup_count=20); "
        "start=int(sys.argv[2]); "
        "gate=Path(sys.argv[3]); ready=Path(sys.argv[4]); ready.touch(); "
        "exec(\"while not gate.exists():\\n    time.sleep(0.001)\"); "
        "[store.append({'chat_id': f'chat-{i}', 'payload': 'x'*80}) "
        "for i in range(start, start+40)]"
    )
    ready_paths = [tmp_path / "ready-0", tmp_path / "ready-1"]
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(path),
                str(start),
                str(start_gate),
                str(ready_path),
            ],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for start, ready_path in zip((0, 40), ready_paths)
    ]

    deadline = time.monotonic() + 5
    while not all(ready_path.exists() for ready_path in ready_paths):
        assert time.monotonic() < deadline, "trace writer processes did not become ready"
        time.sleep(0.01)
    start_gate.touch()

    failures = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        if process.returncode != 0:
            failures.append(f"stdout={stdout}\nstderr={stderr}")
    assert not failures

    records = []
    trace_files = [path, *tmp_path.glob("agent_traces.jsonl.[0-9]*")]
    for trace_file in trace_files:
        for line in trace_file.read_text(encoding="utf-8").splitlines():
            records.append(json.loads(line))

    chat_ids = {record["trace"]["chat_id"] for record in records}
    assert chat_ids == {f"chat-{index}" for index in range(80)}
