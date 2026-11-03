# -*- coding: utf-8 -*-
"""SQLite consistency guarantees for instance backup and restore."""

# pylint: disable=protected-access
from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.types import LogEntry
from qwenpaw.backup._ops import restore
from qwenpaw.backup._ops.create_helpers import add_agent_workspaces
from qwenpaw.backup.models import BackupValidationError


def _agent_json(db_filename: str = "history.db") -> str:
    return json.dumps(
        {
            "running": {
                "light_context_config": {
                    "scroll_config": {"db_filename": db_filename},
                },
            },
        },
    )


def test_workspace_backup_uses_verified_history_snapshot(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    db_path = tmp_path / f"external.db"
    workspace.mkdir()
    live_config = _agent_json(str(db_path))
    (workspace / f"agent.json").write_text(live_config, encoding=f"utf-8")
    (workspace / f"history.db").write_bytes(b"unrelated file")
    store = HistoryStore(db_path)
    store.append(
        session_id="session",
        agent_id="agent",
        dedup_key="one",
        entry=LogEntry(kind="model_turn", content="durable row"),
    )
    assert Path(str(db_path) + "-wal").exists()

    archive_path = tmp_path / "backup.zip"
    try:
        with zipfile.ZipFile(
            archive_path,
            "w",
            zipfile.ZIP_DEFLATED,
        ) as zf:
            assert add_agent_workspaces(
                zf,
                [
                    (
                        "agent",
                        SimpleNamespace(workspace_dir=str(workspace)),
                    ),
                ],
            )
    finally:
        store.close()

    with zipfile.ZipFile(archive_path, "r") as zf:
        names = set(zf.namelist())
        db_entry = f"data/workspaces/agent/history-1.db"
        archived_config = json.loads(
            zf.read(f"data/workspaces/agent/agent.json"),
        )
        assert (
            archived_config[f"running"][f"light_context_config"][
                f"scroll_config"
            ][f"db_filename"]
            == f"history-1.db"
        )
        assert (workspace / f"agent.json").read_text(
            encoding=f"utf-8",
        ) == live_config
        assert (
            zf.read(f"data/workspaces/agent/history.db") == b"unrelated file"
        )
        destination = tmp_path / f"restored-workspace"
        restore._stage_agents(
            zf,
            [f"agent"],
            {f"agent"},
            {f"agent": (destination, True)},
            [],
            {},
            [],
        )
        assert db_entry in names
        assert db_entry + "-wal" not in names
        assert db_entry + "-shm" not in names
        restored = (
            destination.with_name(f"{destination.name}.restore_tmp")
            / f"history-1.db"
        )

    conn = sqlite3.connect(restored)
    try:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert (
            conn.execute(
                "SELECT content FROM conversation_history",
            ).fetchone()[0]
            == "durable row"
        )
    finally:
        conn.close()


def test_workspace_backup_fails_when_history_is_invalid(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "agent.json").write_text(
        _agent_json(),
        encoding="utf-8",
    )
    (workspace / "history.db").write_bytes(b"not sqlite")

    with zipfile.ZipFile(io.BytesIO(), "w") as zf:
        with pytest.raises(sqlite3.DatabaseError):
            add_agent_workspaces(
                zf,
                [
                    (
                        "agent",
                        SimpleNamespace(workspace_dir=str(workspace)),
                    ),
                ],
            )


def test_restore_rejects_invalid_history_before_commit(
    tmp_path: Path,
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            "data/workspaces/agent/agent.json",
            _agent_json(),
        )
        zf.writestr(
            "data/workspaces/agent/history.db",
            b"not sqlite",
        )
    buffer.seek(0)

    destination = tmp_path / "workspace"
    staged_dirs: list[Path] = []
    with zipfile.ZipFile(buffer, "r") as zf:
        with pytest.raises(BackupValidationError) as exc_info:
            restore._stage_agents(
                zf,
                ["agent"],
                {"agent"},
                {"agent": (destination, True)},
                staged_dirs,
                {},
                [],
            )

    assert exc_info.value.code == "history_database_invalid"
    assert not staged_dirs
    assert not destination.with_name(
        destination.name + ".restore_tmp",
    ).exists()


def test_restore_rejects_history_path_escape_before_commit(
    tmp_path: Path,
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            "data/workspaces/agent/agent.json",
            _agent_json("../history.db"),
        )
    buffer.seek(0)

    destination = tmp_path / "workspace"
    staged_dirs: list[Path] = []
    with zipfile.ZipFile(buffer, "r") as zf:
        with pytest.raises(BackupValidationError) as exc_info:
            restore._stage_agents(
                zf,
                ["agent"],
                {"agent"},
                {"agent": (destination, True)},
                staged_dirs,
                {},
                [],
            )

    assert exc_info.value.code == "history_database_path_invalid"
    assert not staged_dirs
    assert not destination.with_name(
        destination.name + ".restore_tmp",
    ).exists()
