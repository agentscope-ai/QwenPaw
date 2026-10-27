# -*- coding: utf-8 -*-
"""Tests for the stable QwenPaw Hub database shape."""

import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from qwenpaw.hub import database as database_module
from qwenpaw.hub.database import (
    HubExtensionStore,
    connect_hub_database,
    initialize_hub_database,
)
from qwenpaw.hub.registry import RuntimeRegistry
from tests.unit.hub.factories import runtime_record


def _columns(database: Path, table: str) -> set[str]:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _assert_closed(connection: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_connection_context_commits_and_closes(tmp_path: Path) -> None:
    database = tmp_path / "control.db"
    connection = connect_hub_database(database)

    with connection:
        connection.execute("CREATE TABLE example(value TEXT)")
        connection.execute("INSERT INTO example VALUES ('committed')")

    _assert_closed(connection)
    with closing(sqlite3.connect(database)) as probe:
        rows = probe.execute("SELECT value FROM example").fetchall()
    assert rows == [("committed",)]


def test_connection_context_rolls_back_and_closes(tmp_path: Path) -> None:
    database = tmp_path / "control.db"
    with connect_hub_database(database) as setup:
        setup.execute("CREATE TABLE example(value TEXT)")
    connection = connect_hub_database(database)

    with pytest.raises(RuntimeError, match="rollback"):
        with connection:
            connection.execute("INSERT INTO example VALUES ('discarded')")
            raise RuntimeError("rollback")

    _assert_closed(connection)
    with closing(sqlite3.connect(database)) as probe:
        rows = probe.execute("SELECT value FROM example").fetchall()
    assert rows == []


def test_connection_closes_when_configuration_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    connection = MagicMock()
    connection.execute.side_effect = sqlite3.OperationalError("pragma failed")
    monkeypatch.setattr(
        database_module.sqlite3,
        "connect",
        MagicMock(return_value=connection),
    )

    with pytest.raises(sqlite3.OperationalError, match="pragma failed"):
        connect_hub_database(tmp_path / "control.db")

    connection.close.assert_called_once_with()


def test_runtime_schema_uses_versioned_documents_for_variable_data(
    tmp_path: Path,
) -> None:
    database = tmp_path / "control.db"

    initialize_hub_database(database)

    columns = _columns(database, "runtimes")
    assert {
        "endpoint_json",
        "storage_json",
        "config_json",
        "status_json",
        "metadata_json",
        "desired_state",
        "observed_state",
        "revision",
    } <= columns
    assert {"host", "port", "pid", "working_dir"}.isdisjoint(columns)


def test_extension_documents_update_without_changing_core_tables(
    tmp_path: Path,
) -> None:
    store = HubExtensionStore(tmp_path / "control.db")

    first_revision = store.put(
        resource_type="runtime",
        resource_id="runtime-a",
        namespace="qwenpaw.monitoring",
        key="prometheus",
        value={"enabled": True},
        schema_version=1,
    )
    second_revision = store.put(
        resource_type="runtime",
        resource_id="runtime-a",
        namespace="qwenpaw.monitoring",
        key="prometheus",
        value={"enabled": True, "path": "/metrics"},
        schema_version=2,
    )

    assert first_revision == 1
    assert second_revision == 2
    loaded = store.get(
        resource_type="runtime",
        resource_id="runtime-a",
        namespace="qwenpaw.monitoring",
        key="prometheus",
    )
    assert loaded is not None
    assert loaded["value"] == {"enabled": True, "path": "/metrics"}
    assert loaded["schema_version"] == 2
    assert loaded["revision"] == 2


def test_unpublished_legacy_schema_is_rejected_without_rewriting(
    tmp_path: Path,
) -> None:
    database = tmp_path / "control.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE runtimes(runtime_id TEXT PRIMARY KEY, host TEXT)",
        )
        connection.execute(
            "INSERT INTO runtimes(runtime_id, host) VALUES ('one', 'local')",
        )

    with pytest.raises(RuntimeError, match="Unsupported pre-release"):
        initialize_hub_database(database)

    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT * FROM runtimes").fetchone()
    assert row == ("one", "local")


def test_runtime_revision_rejects_lost_updates(tmp_path: Path) -> None:
    registry = RuntimeRegistry(tmp_path / "control.db")
    record = registry.create(runtime_record(tmp_path, port=8001))
    stale = registry.get(record.runtime_id)
    assert stale is not None

    updated = registry.save(record)

    assert updated.revision == 2
    with pytest.raises(RuntimeError, match="changed concurrently"):
        registry.save(stale)
