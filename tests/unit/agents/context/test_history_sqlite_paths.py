# -*- coding: utf-8 -*-
"""SQLite paths used by the desktop runtime and history maintenance."""

import os
import shutil
from pathlib import Path, PurePosixPath, PureWindowsPath
import sqlite3
import subprocess
import sys

import pytest

from qwenpaw.agents.context.scroll.history import (
    HistoryStore,
    backup_history_database,
    validate_history_database,
)
from qwenpaw.agents.context.types import LogEntry
from qwenpaw.agents.context.scroll.memoryspace import MemorySpace
from qwenpaw.backup._ops.sqlite_snapshot import _snapshot
from qwenpaw.utils.sqlite_uri import sqlite_uri


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (PurePosixPath("/tmp/history.db"), "file:///tmp/history.db"),
        (
            PurePosixPath("/tmp/history ?#%.db"),
            "file:///tmp/history%20%3F%23%25.db",
        ),
        (
            PureWindowsPath(r"C:\Users\runneradmin\history.db"),
            "file:///C:/Users/runneradmin/history.db",
        ),
        (
            PureWindowsPath(r"\\?\C:\Users\runneradmin\history.db"),
            "file:///C:/Users/runneradmin/history.db",
        ),
        (
            PureWindowsPath(r"\\?\C:\记忆 #%.db"),
            "file:///C:/%E8%AE%B0%E5%BF%86%20%23%25.db",
        ),
        (
            PureWindowsPath(r"\\server\share\history.db"),
            "file:////server/share/history.db",
        ),
        (
            PureWindowsPath(r"\\?\UNC\server\share\history.db"),
            "file:////server/share/history.db",
        ),
        (
            PureWindowsPath(r"\\?\unc\server\share\history.db"),
            "file:////server/share/history.db",
        ),
    ],
)
def test_sqlite_uri_handles_filesystem_paths(path, expected):
    assert sqlite_uri(path, "rw") == expected + "?mode=rw"


def test_sqlite_uri_rejects_relative_paths():
    """A relative path would land in the URI authority slot."""
    for relative in (
        PurePosixPath("history.db"),
        PureWindowsPath("history.db"),
        PureWindowsPath("logs/history.db"),
    ):
        with pytest.raises(ValueError, match="absolute path"):
            sqlite_uri(relative, "ro")


def test_sqlite_uri_rejects_verbatim_volume_paths():
    """Dropping ``\\?\\`` would leave a name that no longer hits the volume."""
    for raw in (
        r"\\?\Volume{dad3333c-0000-0000-0000-500600000000}\history.db",
        r"\\?\GLOBALROOT\Device\HarddiskVolume3\history.db",
        r"\\?\volume{lower-case-guid}\history.db",
    ):
        with pytest.raises(ValueError, match="verbatim path"):
            sqlite_uri(PureWindowsPath(raw), "ro")


@pytest.mark.parametrize("mode", ["ro", "rw", "rwc"])
def test_sqlite_uri_preserves_connection_modes(tmp_path, mode):
    path = tmp_path / "history.db"
    uri = sqlite_uri(path, mode)
    if mode != "rwc":
        with pytest.raises(sqlite3.OperationalError):
            sqlite3.connect(uri, uri=True)
        assert not path.exists()
    with sqlite3.connect(sqlite_uri(path, "rwc"), uri=True) as connection:
        connection.execute("CREATE TABLE probe (value TEXT)")
    connection.close()
    assert path.exists()
    connection = sqlite3.connect(uri, uri=True)
    try:
        assert connection.execute("SELECT * FROM probe").fetchall() == []
        if mode == "ro":
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                connection.execute("INSERT INTO probe VALUES ('test')")
        else:
            connection.execute("INSERT INTO probe VALUES ('test')")
    finally:
        connection.close()


@pytest.mark.parametrize(
    "verbatim",
    [
        False,
        pytest.param(
            True,
            marks=pytest.mark.skipif(
                os.name != "nt",
                reason="Verbatim filesystem paths require Windows",
            ),
        ),
    ],
)
def test_history_connections_support_special_paths(tmp_path, verbatim):
    root = tmp_path.resolve()
    if verbatim and not str(root).startswith("\\\\?\\"):
        root = Path("\\\\?\\" + str(root))
    source = root / "记忆 #%.db"
    destination = root / "snapshot #%.db"
    store = HistoryStore(source)
    try:
        store.append(
            session_id="test",
            dedup_key="one",
            entry=LogEntry(kind="model_turn", role="user", content="hello"),
        )
        assert validate_history_database(source) == 1
        recall = MemorySpace(history_db_path=source, session_id="test")
        try:
            rows = recall.sql_query(
                "SELECT content FROM hist.conversation_history",
            )
            assert rows[0]["content"] == "hello"
        finally:
            recall.close()
        maintenance = HistoryStore(source, initialize=False)
        try:
            assert maintenance.count("test") == 1
        finally:
            maintenance.close()
        assert backup_history_database(source, destination) == destination
        snapshot = HistoryStore(destination, initialize=False)
        try:
            assert snapshot.count("test") == 1
        finally:
            snapshot.close()
        worker_destination = root / "worker snapshot #%.db"
        _snapshot(source, worker_destination)
        assert validate_history_database(worker_destination) == 1
    finally:
        store.close()


def test_history_maintenance_open_does_not_create_database(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        HistoryStore(path, initialize=False)
    assert not path.exists()


def test_standalone_recall_and_backup_need_only_stdlib(tmp_path):
    source = tmp_path / "history #%.db"
    store = HistoryStore(source)
    try:
        store.append(
            session_id="test",
            dedup_key="one",
            entry=LogEntry(kind="model_turn", role="user", content="hello"),
        )
    finally:
        store.close()
    package = tmp_path / "bundle/qwenpaw"
    source_root = Path(__file__).resolve().parents[4] / "src/qwenpaw"
    for relative in (
        "agents/context/scroll/memoryspace.py",
        "backup/_ops/sqlite_snapshot.py",
        "utils/sqlite_uri.py",
    ):
        target = package / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_root / relative, target)
    script = (
        "import runpy, sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(package / 'agents/context/scroll')!r})\n"
        "from memoryspace import MemorySpace\n"
        f"space = MemorySpace(history_db_path={str(source)!r})\n"
        "assert space.sql_query('SELECT content FROM "
        "hist.conversation_history')[0]['content'] == 'hello'\n"
        "space.close()\n"
        f"worker = runpy.run_path({str(package / 'backup/_ops/sqlite_snapshot.py')!r})\n"
        f"worker['_snapshot'](Path({str(source)!r}), "
        f"Path({str(tmp_path / 'snapshot.db')!r}))\n"
        "assert 'qwenpaw' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert validate_history_database(tmp_path / "snapshot.db") == 1
