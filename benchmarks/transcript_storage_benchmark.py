# -*- coding: utf-8 -*-
"""Reproducible transcript storage benchmark.

This is an opt-in engineering benchmark, not a wall-clock CI test. It compares
the production SQLite store with a session-per-file JSONL prototype whose
indexes are rebuilt at open time.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import tempfile
import threading
import time
import tracemalloc
from pathlib import Path
from typing import Any, Callable

import psutil

from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.schemas import Message, Role, TextContent

_SESSION_ID = "benchmark-session"
_USER_ID = "benchmark-user"
_CHANNEL = "console"
_TIMESTAMP = "2026-01-01T00:00:00+00:00"


def _message_dict(index: int, role: str, text_size: int) -> dict[str, Any]:
    message_id = f"message-{index:09d}-{role}"
    metadata: dict[str, Any] = {"timestamp": _TIMESTAMP}
    if role == "user":
        metadata["qwenpaw_client_message_id"] = f"client-{index:09d}"
    return {
        "id": message_id,
        "type": "message",
        "role": role,
        "content": [{"type": "text", "text": "x" * text_size}],
        "status": "completed",
        "metadata": metadata,
    }


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * percentile)))
    return ordered[index]


def _measure(
    operation: Callable[[], Any],
    *,
    samples: int,
) -> dict[str, float]:
    timings = []
    for _ in range(samples):
        started = time.perf_counter()
        operation()
        timings.append((time.perf_counter() - started) * 1000)
    return {
        "p50_ms": round(statistics.median(timings), 3),
        "p95_ms": round(_percentile(timings, 0.95), 3),
        "max_ms": round(max(timings), 3),
    }


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(
        item.stat().st_size for item in path.rglob("*") if item.is_file()
    )


def _run_concurrently(
    read: Callable[[], Any],
    write: Callable[[], Any],
    *,
    reads: int = 20,
    writes: int = 10,
) -> dict[str, Any]:
    errors: list[str] = []

    def run_many(operation: Callable[[], Any], count: int) -> None:
        for _ in range(count):
            try:
                operation()
            except Exception as exc:  # pylint: disable=broad-except
                errors.append(type(exc).__name__)

    threads = [
        threading.Thread(target=run_many, args=(read, reads)) for _ in range(4)
    ]
    threads.append(threading.Thread(target=run_many, args=(write, writes)))
    started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return {
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "errors": errors,
        "read_operations": reads * 4,
        "write_operations": writes,
    }


def _populate_sqlite(
    path: Path,
    message_count: int,
    text_size: int,
) -> None:
    store = TranscriptStore(path, retention_days=0)
    turn_count = message_count // 2
    batch_size = 5_000
    with store._transaction():  # pylint: disable=protected-access
        store._conn.execute(  # pylint: disable=protected-access
            "INSERT INTO transcript_sessions("
            "session_id, user_id, channel, revision, next_turn_seq, "
            "completeness, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'complete', ?, ?)",
            (
                _SESSION_ID,
                _USER_ID,
                _CHANNEL,
                message_count,
                turn_count + 1,
                _TIMESTAMP,
                _TIMESTAMP,
            ),
        )
        for start in range(0, turn_count, batch_size):
            stop = min(turn_count, start + batch_size)
            turns = []
            messages = []
            for index in range(start, stop):
                turn_id = f"turn-{index:09d}"
                turns.append(
                    (
                        _SESSION_ID,
                        index + 1,
                        turn_id,
                        "completed",
                        "benchmark",
                        _TIMESTAMP,
                        _TIMESTAMP,
                    ),
                )
                for ordinal, role in enumerate(("user", "assistant")):
                    payload = _message_dict(index, role, text_size)
                    messages.append(
                        (
                            _SESSION_ID,
                            turn_id,
                            payload["id"],
                            ordinal,
                            role,
                            "message",
                            json.dumps(payload, separators=(",", ":")),
                            "completed",
                            _TIMESTAMP,
                            _TIMESTAMP,
                            (payload.get("metadata") or {}).get(
                                "qwenpaw_client_message_id",
                            ),
                        ),
                    )
            store._conn.executemany(  # pylint: disable=protected-access
                "INSERT INTO transcript_turns("
                "session_id, turn_seq, turn_id, status, source, created_at, "
                "finished_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                turns,
            )
            store._conn.executemany(  # pylint: disable=protected-access
                "INSERT INTO transcript_messages("
                "session_id, turn_id, message_id, ordinal, role, kind, "
                "payload_json, status, created_at, finished_at, "
                "client_message_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                messages,
            )
    store.close()


def _downgrade_sqlite_fixture_to_v2(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute("DROP INDEX transcript_messages_client")
    connection.execute(
        "ALTER TABLE transcript_messages DROP COLUMN client_message_id",
    )
    connection.execute("PRAGMA user_version=2")
    connection.commit()
    connection.close()


class JsonlIndex:
    """Minimal JSONL candidate with indexes rebuilt at every cold open."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.offsets: list[int] = []
        self.message_turns: dict[str, str] = {}
        self.client_turns: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        with self.path.open("rb") as handle:
            while True:
                offset = handle.tell()
                line = handle.readline()
                if not line:
                    break
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    break
                self.offsets.append(offset)
                turn_id = str(record["turn_id"])
                for message in record["messages"]:
                    self.message_turns[str(message["id"])] = turn_id
                    client_id = (message.get("metadata") or {}).get(
                        "qwenpaw_client_message_id",
                    )
                    if client_id:
                        self.client_turns[str(client_id)] = turn_id

    def get_page(self, before: int | None = None, limit: int = 50) -> list:
        end = len(self.offsets) if before is None else before
        start = max(0, end - limit)
        records = []
        with self._lock, self.path.open("rb") as handle:
            for offset in self.offsets[start:end]:
                handle.seek(offset)
                records.append(json.loads(handle.readline()))
        return records

    def append(self, record: dict[str, Any]) -> None:
        encoded = json.dumps(record, separators=(",", ":")).encode() + b"\n"
        with self._lock, self.path.open("ab") as handle:
            offset = handle.tell()
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        self.offsets.append(offset)
        turn_id = str(record["turn_id"])
        for message in record["messages"]:
            self.message_turns[str(message["id"])] = turn_id
            client_id = (message.get("metadata") or {}).get(
                "qwenpaw_client_message_id",
            )
            if client_id:
                self.client_turns[str(client_id)] = turn_id


def _jsonl_record(index: int, text_size: int) -> dict[str, Any]:
    return {
        "turn_seq": index + 1,
        "turn_id": f"turn-{index:09d}",
        "status": "completed",
        "messages": [
            _message_dict(index, "user", text_size),
            _message_dict(index, "assistant", text_size),
        ],
    }


def _populate_jsonl(path: Path, message_count: int, text_size: int) -> None:
    with path.open("wb") as handle:
        for index in range(message_count // 2):
            record = _jsonl_record(index, text_size)
            handle.write(
                json.dumps(record, separators=(",", ":")).encode() + b"\n",
            )


def _benchmark_sqlite(
    root: Path,
    message_count: int,
    text_size: int,
    samples: int,
    secure_delete: str = "ON",
) -> dict[str, Any]:
    path = root / "session.db"
    build_started = time.perf_counter()
    _populate_sqlite(path, message_count, text_size)
    build_ms = (time.perf_counter() - build_started) * 1000
    _downgrade_sqlite_fixture_to_v2(path)
    migration_started = time.perf_counter()
    migrated = TranscriptStore(path, retention_days=0)
    migrated.close()
    migration_ms = (time.perf_counter() - migration_started) * 1000
    process = psutil.Process()
    rss_before = process.memory_info().rss
    tracemalloc.start()
    open_started = time.perf_counter()
    store = TranscriptStore(path, retention_days=0)
    store._conn.execute(  # pylint: disable=protected-access
        f"PRAGMA secure_delete={secure_delete}",
    )
    open_ms = (time.perf_counter() - open_started) * 1000
    _, open_python_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_delta = process.memory_info().rss - rss_before
    turn_count = message_count // 2
    middle = max(1, turn_count // 2)
    append_index = turn_count + 1

    def append_turn() -> None:
        nonlocal append_index
        index = append_index
        append_index += 1
        turn_id = f"append-{index:09d}"
        store.start_turn(
            session_id=_SESSION_ID,
            user_id=_USER_ID,
            channel=_CHANNEL,
            turn_id=turn_id,
            source="benchmark",
        )
        for ordinal, role in enumerate((Role.USER, Role.ASSISTANT)):
            message = Message(
                id=f"append-message-{index:09d}-{role.value}",
                role=role,
                content=[TextContent(text="x" * text_size)],
            ).completed()
            store.upsert_message(
                session_id=_SESSION_ID,
                turn_id=turn_id,
                message=message,
                ordinal=ordinal,
            )
        store.finish_turn(
            session_id=_SESSION_ID,
            turn_id=turn_id,
            status="completed",
        )

    result = {
        "fixture_build_ms": round(build_ms, 3),
        "migration_v2_to_v3_ms": round(migration_ms, 3),
        "disk_bytes": _path_size(root),
        "open_ms": round(open_ms, 3),
        "open_rss_delta_bytes": rss_delta,
        "open_python_peak_bytes": open_python_peak,
        "append_turn": _measure(append_turn, samples=samples),
        "latest_page": _measure(
            lambda: store.get_page(
                session_id=_SESSION_ID,
                user_id=_USER_ID,
                channel=_CHANNEL,
            ),
            samples=samples,
        ),
        "middle_page": _measure(
            lambda: store.get_page(
                session_id=_SESSION_ID,
                user_id=_USER_ID,
                channel=_CHANNEL,
                before=middle,
            ),
            samples=samples,
        ),
        "message_anchor": _measure(
            lambda: store.find_turn_for_message(
                session_id=_SESSION_ID,
                message_id=f"message-{middle:09d}-user",
            ),
            samples=samples,
        ),
        "client_anchor": _measure(
            lambda: store.find_turn_for_message(
                session_id=_SESSION_ID,
                client_message_id=f"client-{middle:09d}",
            ),
            samples=samples,
        ),
        "fork_anchor_page": _measure(
            lambda: (
                store.find_turn_for_message(
                    session_id=_SESSION_ID,
                    message_id=f"message-{middle:09d}-user",
                ),
                store.get_page(
                    session_id=_SESSION_ID,
                    user_id=_USER_ID,
                    channel=_CHANNEL,
                    before=middle,
                ),
            ),
            samples=samples,
        ),
    }
    result["concurrent_io"] = _run_concurrently(
        lambda: store.get_page(
            session_id=_SESSION_ID,
            user_id=_USER_ID,
            channel=_CHANNEL,
        ),
        append_turn,
    )
    rolled_back = False
    try:
        with store._transaction():  # pylint: disable=protected-access
            store._conn.execute(  # pylint: disable=protected-access
                "UPDATE transcript_sessions SET revision = -1 "
                "WHERE session_id = ?",
                (_SESSION_ID,),
            )
            raise RuntimeError("simulated interruption")
    except RuntimeError:
        revision = store._conn.execute(  # pylint: disable=protected-access
            "SELECT revision FROM transcript_sessions WHERE session_id = ?",
            (_SESSION_ID,),
        ).fetchone()[0]
        rolled_back = revision != -1
    result["interrupted_write_recovered"] = rolled_back
    store.close()
    delete_store = TranscriptStore(path, retention_days=0)
    delete_store._conn.execute(  # pylint: disable=protected-access
        f"PRAGMA secure_delete={secure_delete}",
    )
    result["delete_ack"] = _measure(
        lambda: delete_store.schedule_delete_session(_SESSION_ID),
        samples=1,
    )
    cleanup_started = time.perf_counter()
    delete_store.close()
    result["delete_cleanup_wait_ms"] = round(
        (time.perf_counter() - cleanup_started) * 1000,
        3,
    )
    return result


def _benchmark_jsonl(
    root: Path,
    message_count: int,
    text_size: int,
    samples: int,
) -> dict[str, Any]:
    path = root / "transcript.jsonl"
    build_started = time.perf_counter()
    _populate_jsonl(path, message_count, text_size)
    build_ms = (time.perf_counter() - build_started) * 1000
    process = psutil.Process()
    rss_before = process.memory_info().rss
    tracemalloc.start()
    open_started = time.perf_counter()
    store = JsonlIndex(path)
    open_ms = (time.perf_counter() - open_started) * 1000
    _, open_python_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_delta = process.memory_info().rss - rss_before
    turn_count = message_count // 2
    middle = max(1, turn_count // 2)
    append_index = turn_count + 1

    def append_turn() -> None:
        nonlocal append_index
        store.append(_jsonl_record(append_index, text_size))
        append_index += 1

    result = {
        "fixture_build_ms": round(build_ms, 3),
        "disk_bytes": _path_size(root),
        "open_ms": round(open_ms, 3),
        "open_rss_delta_bytes": rss_delta,
        "open_python_peak_bytes": open_python_peak,
        "append_turn": _measure(append_turn, samples=samples),
        "latest_page": _measure(
            lambda: store.get_page(limit=50),
            samples=samples,
        ),
        "middle_page": _measure(
            lambda: store.get_page(before=middle, limit=50),
            samples=samples,
        ),
        "message_anchor": _measure(
            lambda: store.message_turns.get(f"message-{middle:09d}-user"),
            samples=samples,
        ),
        "client_anchor": _measure(
            lambda: store.client_turns.get(f"client-{middle:09d}"),
            samples=samples,
        ),
        "fork_anchor_page": _measure(
            lambda: (
                store.message_turns.get(f"message-{middle:09d}-user"),
                store.get_page(before=middle, limit=50),
            ),
            samples=samples,
        ),
    }
    result["concurrent_io"] = _run_concurrently(
        lambda: store.get_page(limit=50),
        append_turn,
    )
    turn_count_before = len(store.offsets)
    with path.open("ab") as handle:
        handle.write(b'{"turn_id":"truncated')
        handle.flush()
        os.fsync(handle.fileno())
    recovered = JsonlIndex(path)
    recovered.append(_jsonl_record(turn_count_before + 1, text_size))
    reopened = JsonlIndex(path)
    result["interrupted_write_recovered"] = (
        len(reopened.offsets) == turn_count_before + 1
    )
    result["delete_ack"] = _measure(path.unlink, samples=1)
    result["delete_cleanup_wait_ms"] = 0.0
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sizes",
        type=int,
        nargs="+",
        default=[1_000, 100_000, 1_000_000],
    )
    parser.add_argument("--text-size", type=int, default=128)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument(
        "--sqlite-secure-delete",
        choices=("ON", "FAST", "OFF"),
        default="ON",
    )
    parser.add_argument(
        "--backends",
        nargs="+",
        choices=("sqlite", "jsonl"),
        default=["sqlite", "jsonl"],
    )
    args = parser.parse_args()
    report: dict[str, Any] = {
        "platform": os.uname().sysname if hasattr(os, "uname") else os.name,
        "text_size": args.text_size,
        "samples": args.samples,
        "sqlite_secure_delete": args.sqlite_secure_delete,
        "results": {},
    }
    for size in args.sizes:
        report["results"][str(size)] = {}
        for backend in args.backends:
            with tempfile.TemporaryDirectory(
                prefix=f"transcript-{backend}-{size}-",
            ) as temporary:
                runner_args = (
                    Path(temporary),
                    size,
                    args.text_size,
                    args.samples,
                )
                if backend == "sqlite":
                    result = _benchmark_sqlite(
                        *runner_args,
                        secure_delete=args.sqlite_secure_delete,
                    )
                else:
                    result = _benchmark_jsonl(*runner_args)
                report["results"][str(size)][backend] = result
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
