# -*- coding: utf-8 -*-
"""SQLite backup consistency and cancellation regressions."""

# pylint: disable=protected-access

import sqlite3
import subprocess
import sys
import threading
import zipfile
from types import SimpleNamespace

import pytest

from qwenpaw.backup._ops.create_helpers import add_agent_workspaces
from qwenpaw.backup._ops import sqlite_snapshot
from qwenpaw.backup._utils.constants import PREFIX_WORKSPACES


def test_live_wal_snapshot_restores_committed_data(tmp_path):
    # One filename covers nesting, custom extensions and URI escaping on
    # Windows too (unlike '?', '#' is a valid Windows filename character).
    filename = "nested/custom memory#name"
    ws = tmp_path / "workspace"
    source = ws / filename
    source.parent.mkdir(parents=True)
    conn = sqlite3.connect(source)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("CREATE TABLE events(value)")
        conn.execute("INSERT INTO events VALUES ('committed')")
        conn.commit()
        conn.execute("INSERT INTO events VALUES ('uncommitted')")
        with zipfile.ZipFile(tmp_path / "backup.zip", "w") as archive:
            assert add_agent_workspaces(
                archive,
                [("agent", SimpleNamespace(workspace_dir=ws))],
            )
            assert archive.namelist() == [
                f"{PREFIX_WORKSPACES}agent/{filename}",
            ]
            restored = tmp_path / "restored.db"
            restored.write_bytes(archive.read(archive.namelist()[0]))
        with sqlite3.connect(restored) as snapshot:
            assert snapshot.execute("PRAGMA integrity_check").fetchone() == (
                "ok",
            )
            assert snapshot.execute("SELECT * FROM events").fetchall() == [
                ("committed",),
            ]
            assert snapshot.execute("PRAGMA journal_mode").fetchone() == (
                "delete",
            )
        assert conn.execute("SELECT count(*) FROM events").fetchone() == (2,)
    finally:
        conn.close()


@pytest.mark.parametrize("header", [b"SQLite format 3\0", b"broken header!!!"])
def test_corrupt_sqlite_aborts_instead_of_archiving_raw_file(tmp_path, header):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "history.db").write_bytes(header + b"x" * 4096)
    (ws / "history.db-shm").write_bytes(b"x" * 32768)
    with zipfile.ZipFile(tmp_path / "backup.zip", "w") as archive:
        with pytest.raises(RuntimeError, match="SQLite snapshot failed"):
            add_agent_workspaces(
                archive,
                [("agent", SimpleNamespace(workspace_dir=ws))],
            )
        assert archive.namelist() == []


def test_cancel_during_locked_database_snapshot(tmp_path):
    source = tmp_path / "history.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE events(value)")
    conn.commit()
    conn.execute("BEGIN EXCLUSIVE")
    staging = tmp_path / "staging"
    staging.mkdir()
    event = threading.Event()
    timer = threading.Timer(0.3, event.set)
    timer.start()
    try:
        assert (
            sqlite_snapshot.stage_databases([source], staging, event) is None
        )
    finally:
        timer.cancel()
        conn.close()


def test_snapshot_deadline_interrupts_busy_retry(tmp_path, monkeypatch):
    source = tmp_path / "history.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE events(value)")
    conn.commit()
    conn.execute("BEGIN EXCLUSIVE")
    monkeypatch.setattr(sqlite_snapshot, "_SNAPSHOT_TIMEOUT_SECONDS", 0)
    try:
        with pytest.raises(TimeoutError, match="SQLite snapshot timed out"):
            sqlite_snapshot._snapshot(source, tmp_path / "snapshot.db")
    finally:
        conn.close()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux POSIX DMS lock")
def test_backup_preserves_live_sqlite_dms_lock(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    source = ws / "history.db"
    conn = sqlite3.connect(source)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE events(value)")
        conn.commit()
        probe = """
import fcntl, sys
with open(sys.argv[1], 'rb+') as handle:
    try:
        fcntl.lockf(handle, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 128)
    except BlockingIOError:
        sys.exit(0)
sys.exit(1)
"""

        def assert_locked():
            result = subprocess.run(
                [sys.executable, "-c", probe, str(source) + "-shm"],
                capture_output=True,
                timeout=10,
                check=False,
            )
            assert result.returncode == 0, result.stderr

        assert_locked()
        with zipfile.ZipFile(tmp_path / "backup.zip", "w") as archive:
            assert add_agent_workspaces(
                archive,
                [("agent", SimpleNamespace(workspace_dir=ws))],
            )
        assert_locked()
        conn.execute("INSERT INTO events VALUES (1)")
        conn.commit()
    finally:
        conn.close()
