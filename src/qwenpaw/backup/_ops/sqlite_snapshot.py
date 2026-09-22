# -*- coding: utf-8 -*-
"""Stage SQLite snapshots without ordinary file reads in the app process.

This module is also a standalone stdlib-only worker. Even opening a database
just to inspect its header and closing it can release the application's POSIX
locks, so both identification and snapshotting run in a fresh interpreter.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from collections.abc import Sequence
from threading import Event

_SNAPSHOT_TIMEOUT_SECONDS = 60
_WORKER_TIMEOUT_SECONDS = 1800
_SIDECARS = ("-wal", "-shm", "-journal")


def stage_databases(
    entries: Sequence[Path],
    staging: Path,
    stop_event: Event | None = None,
) -> tuple[dict[str, str], set[str]] | None:
    """Return (snapshot mapping, excluded sidecars), or None on cancellation.

    Fail closed: callers must never fall back to raw copies after a worker
    failure. The caller owns the staging directory's lifetime.
    """
    if stop_event and stop_event.is_set():
        return None
    if not entries:
        return {}, set()
    manifest = staging / "manifest.json"
    manifest.write_text(
        json.dumps([str(p) for p in entries]),
        encoding="utf-8",
    )
    with (staging / "worker.err").open("w+", encoding="utf-8") as errors:
        with subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), str(manifest)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=errors,
        ) as process:
            deadline = time.monotonic() + _WORKER_TIMEOUT_SECONDS
            try:
                while True:
                    if stop_event and stop_event.is_set():
                        return None
                    if time.monotonic() >= deadline:
                        raise TimeoutError("SQLite backup worker timed out")
                    try:
                        code = process.wait(timeout=0.1)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if code:
                    errors.seek(0)
                    raise RuntimeError(
                        f"SQLite snapshot failed: {errors.read()}",
                    )
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
    result = json.loads(manifest.read_text(encoding="utf-8"))
    return result["snapshots"], set(result["sidecars"])


def _snapshot(source: Path, destination: Path) -> None:
    deadline = time.monotonic() + _SNAPSHOT_TIMEOUT_SECONDS

    def progress(_status, _remaining, _total):
        if time.monotonic() >= deadline:
            raise TimeoutError(f"SQLite snapshot timed out: {source}")

    src = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(destination)
        try:
            src.backup(dst, pages=256, progress=progress, sleep=0.05)
            # A restored database must be self-contained, with no sidecars.
            dst.execute("PRAGMA journal_mode=DELETE")
        finally:
            dst.close()
    finally:
        src.close()


def _stage(manifest: Path) -> None:
    entries = [
        Path(p) for p in json.loads(manifest.read_text(encoding="utf-8"))
    ]
    databases = []
    for entry in entries:
        try:
            with entry.open("rb") as handle:
                header = handle.read(16)
        except OSError:
            # Preserve best-effort handling of unrelated inaccessible files,
            # but never silently omit a likely database.
            if entry.suffix.lower() in (".db", ".sqlite", ".sqlite3"):
                raise
            continue
        # Sidecars also identify a database whose header is damaged or not
        # initialized yet. Let SQLite validate it; never copy it raw.
        has_sidecars = any(
            Path(str(entry) + suffix).exists() for suffix in _SIDECARS
        )
        if header == b"SQLite format 3\0" or has_sidecars:
            databases.append(entry)
    snapshots = {}
    sidecars: list[str] = []
    for index, source in enumerate(databases):
        destination = manifest.parent / f"snapshot-{index}.db"
        _snapshot(source, destination)
        snapshots[str(source)] = str(destination)
        sidecars.extend(str(source) + suffix for suffix in _SIDECARS)
    manifest.write_text(
        json.dumps({"snapshots": snapshots, "sidecars": sidecars}),
        encoding="utf-8",
    )


if __name__ == "__main__":
    _stage(Path(sys.argv[1]))
