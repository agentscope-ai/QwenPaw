# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
# pylint: disable=use-implicit-booleaness-not-comparison
"""Unit tests for the bounded Codex automation source readers.

``tests/unit/portability/test_codex_schedules.py`` drives the discovery
entry point end-to-end.  This file covers the reader primitives directly:
the project-root mapping parser, the TOML candidate scanner, the local
timezone resolver, the scalar normalizer, the bounded copy/signature
helpers, the WAL snapshot guard and the SQLite query limits.

Nothing here touches the network or the real ``~/.codex``; every store is
built inside ``tmp_path``.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from qwenpaw.portability.providers import codex_schedule_reader as reader


# --------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------- #


def _write_state(home: Path, payload: Any) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    path = home / ".codex-global-state.json"
    if isinstance(payload, bytes):
        path.write_bytes(payload)
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _create_database(path: Path, *, with_runs: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE automations ("
            "id TEXT PRIMARY KEY, name TEXT, prompt TEXT, status TEXT,"
            " updated_at INTEGER)",
        )
        if with_runs:
            connection.execute(
                "CREATE TABLE automation_runs ("
                "thread_id TEXT, automation_id TEXT, status TEXT)",
            )
        connection.commit()
    return path


def _insert_automation(
    path: Path,
    automation_id: Any,
    *,
    updated_at: int = 1,
) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "INSERT INTO automations"
            " (id, name, prompt, status, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (automation_id, "name", "prompt", "ACTIVE", updated_at),
        )
        connection.commit()


def _insert_run(path: Path, thread_id: Any) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "INSERT INTO automation_runs VALUES (?, ?, ?)",
            (thread_id, "auto", "COMPLETED"),
        )
        connection.commit()


def _write_toml(home: Path, directory: str, body: str) -> Path:
    path = home / "automations" / directory / "automation.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _run_noop() -> None:
    """Body for context managers that must be entered then raise."""


# --------------------------------------------------------------------- #
# _metadata_scalar
# --------------------------------------------------------------------- #


def test_metadata_scalar_normalizes_supported_types() -> None:
    moment = datetime(2026, 9, 20, 12, 0, 0)

    assert reader._metadata_scalar("  padded  ") == "padded"
    assert reader._metadata_scalar(moment) == moment.isoformat()
    assert reader._metadata_scalar(True) is True
    assert reader._metadata_scalar(7) == 7
    assert reader._metadata_scalar(1.5) == 1.5


def test_metadata_scalar_rejects_unsupported_values() -> None:
    assert reader._metadata_scalar(None) == ""
    assert reader._metadata_scalar(["a"]) == ""
    assert reader._metadata_scalar({"a": 1}) == ""
    assert reader._metadata_scalar(math.nan) == ""
    assert reader._metadata_scalar(math.inf) == ""
    assert reader._metadata_scalar(2**63) == ""


def test_metadata_scalar_bounds_long_text() -> None:
    value = "x" * (reader._MAX_SMALL_METADATA_STRING_CHARS + 40)

    result = reader._metadata_scalar(value)

    assert len(result) <= reader._MAX_SMALL_METADATA_STRING_CHARS


# --------------------------------------------------------------------- #
# _safe_rrule / _valid_timezone
# --------------------------------------------------------------------- #


def test_safe_rrule_accepts_plain_rule() -> None:
    value, audit, reason = reader._safe_rrule("  FREQ=DAILY;BYHOUR=9  ")

    assert value == "FREQ=DAILY;BYHOUR=9"
    assert audit == {}
    assert reason == ""


def test_safe_rrule_rejects_control_characters() -> None:
    value, audit, reason = reader._safe_rrule("FREQ=DAILY\x01;BYHOUR=9")

    assert value == ""
    assert reason == "source_rrule_unsafe"
    assert audit["disposition"] == "omitted"


def test_safe_rrule_rejects_oversized_rule() -> None:
    oversized = "F" * (reader._MAX_RRULE_CHARS + 1)

    value, _audit, reason = reader._safe_rrule(oversized)

    assert value == ""
    assert reason == "source_rrule_exceeds_limit"


def test_safe_rrule_tolerates_non_string_input() -> None:
    value, audit, reason = reader._safe_rrule(None)

    assert value == ""
    assert audit == {}
    assert reason == ""


def test_valid_timezone_rejects_unknown_zone() -> None:
    assert reader._valid_timezone("Europe/Paris") is True
    assert reader._valid_timezone("Not/AZone") is False
    assert reader._valid_timezone("") is False


# --------------------------------------------------------------------- #
# _local_timezone_name
# --------------------------------------------------------------------- #


def test_local_timezone_prefers_valid_environment(monkeypatch) -> None:
    monkeypatch.setenv("TZ", "Europe/Paris")

    assert reader._local_timezone_name() == ("Europe/Paris", "environment")


def test_local_timezone_ignores_invalid_environment(monkeypatch) -> None:
    monkeypatch.setenv("TZ", "Not/AZone")

    name, source = reader._local_timezone_name()

    assert source in {"system", "utc_fallback"}
    assert reader._valid_timezone(name)


def test_local_timezone_uses_tzinfo_key(monkeypatch) -> None:
    monkeypatch.delenv("TZ", raising=False)

    class _Now:
        def astimezone(self) -> Any:
            return SimpleNamespace(tzinfo=ZoneInfo("Asia/Tokyo"))

    monkeypatch.setattr(
        reader,
        "datetime",
        SimpleNamespace(now=staticmethod(_Now)),
    )

    assert reader._local_timezone_name() == ("Asia/Tokyo", "system")


def test_local_timezone_reads_localtime_zoneinfo(monkeypatch) -> None:
    """With no TZ and no key, /etc/localtime's zoneinfo path is used."""
    monkeypatch.delenv("TZ", raising=False)

    class _Now:
        def astimezone(self) -> Any:
            return SimpleNamespace(tzinfo=None)

    monkeypatch.setattr(
        reader,
        "datetime",
        SimpleNamespace(now=staticmethod(_Now)),
    )

    name, source = reader._local_timezone_name()

    assert source in {"system", "utc_fallback"}
    assert reader._valid_timezone(name)


def test_local_timezone_falls_back_to_utc(monkeypatch) -> None:
    monkeypatch.delenv("TZ", raising=False)

    class _Now:
        def astimezone(self) -> Any:
            return SimpleNamespace(tzinfo=None)

    class _StubPath:
        def __init__(self, *_args: Any) -> None:
            pass

        def resolve(self, strict: bool = False) -> Path:
            raise OSError("no such file")

    monkeypatch.setattr(
        reader,
        "datetime",
        SimpleNamespace(now=staticmethod(_Now)),
    )
    monkeypatch.setattr(reader, "Path", _StubPath)

    assert reader._local_timezone_name() == ("UTC", "utc_fallback")


def test_local_timezone_skips_non_zoneinfo_localtime(monkeypatch) -> None:
    monkeypatch.delenv("TZ", raising=False)

    class _Now:
        def astimezone(self) -> Any:
            return SimpleNamespace(tzinfo=None)

    class _StubPath:
        def __init__(self, *_args: Any) -> None:
            pass

        def resolve(self, strict: bool = False) -> Path:
            return Path("/etc/hostname")

    monkeypatch.setattr(
        reader,
        "datetime",
        SimpleNamespace(now=staticmethod(_Now)),
    )
    monkeypatch.setattr(reader, "Path", _StubPath)

    assert reader._local_timezone_name() == ("UTC", "utc_fallback")


def test_local_timezone_rejects_invalid_tzinfo_key(monkeypatch) -> None:
    monkeypatch.delenv("TZ", raising=False)

    class _Now:
        def astimezone(self) -> Any:
            return SimpleNamespace(
                tzinfo=SimpleNamespace(key="Not/AZone"),
            )

    class _StubPath:
        def __init__(self, *_args: Any) -> None:
            pass

        def resolve(self, strict: bool = False) -> Path:
            raise OSError("absent")

    monkeypatch.setattr(
        reader,
        "datetime",
        SimpleNamespace(now=staticmethod(_Now)),
    )
    monkeypatch.setattr(reader, "Path", _StubPath)

    assert reader._local_timezone_name() == ("UTC", "utc_fallback")


# --------------------------------------------------------------------- #
# _read_project_roots
# --------------------------------------------------------------------- #


def test_read_project_roots_maps_ids_to_clean_roots(tmp_path) -> None:
    _write_state(
        tmp_path,
        {
            "local-projects": {
                "key-a": {
                    "id": "proj-a",
                    "rootPaths": ["/srv/a", "/srv/a", "/srv/b"],
                },
                "key-b": {"rootPaths": ["/srv/c"]},
            },
        },
    )
    warnings: list[str] = []

    roots = reader._read_project_roots(tmp_path, warnings)

    assert roots == {"proj-a": ["/srv/a", "/srv/b"], "key-b": ["/srv/c"]}
    assert warnings == []


def test_read_project_roots_returns_empty_without_state_file(tmp_path) -> None:
    warnings: list[str] = []

    assert reader._read_project_roots(tmp_path, warnings) == {}
    assert warnings == []


def test_read_project_roots_warns_on_invalid_json(tmp_path) -> None:
    _write_state(tmp_path, b"{not json")
    warnings: list[str] = []

    assert reader._read_project_roots(tmp_path, warnings) == {}
    assert len(warnings) == 1
    assert "Could not read Codex project-to-workspace mapping" in warnings[0]
    assert "JSONDecodeError" in warnings[0]


def test_read_project_roots_warns_on_invalid_utf8(tmp_path) -> None:
    _write_state(tmp_path, b'{"local-projects": "\xff\xfe"}')
    warnings: list[str] = []

    assert reader._read_project_roots(tmp_path, warnings) == {}
    assert len(warnings) == 1
    assert "UnicodeDecodeError" in warnings[0]


def test_read_project_roots_warns_when_state_is_too_large(
    tmp_path,
    monkeypatch,
) -> None:
    _write_state(tmp_path, {"local-projects": {}})
    monkeypatch.setattr(reader, "_MAX_STATE_BYTES", 4)
    warnings: list[str] = []

    assert reader._read_project_roots(tmp_path, warnings) == {}
    assert len(warnings) == 1
    assert "ValueError" in warnings[0]


def test_read_project_roots_ignores_non_dict_payload(tmp_path) -> None:
    _write_state(tmp_path, ["local-projects"])
    warnings: list[str] = []

    assert reader._read_project_roots(tmp_path, warnings) == {}
    assert warnings == []


def test_read_project_roots_ignores_non_dict_projects(tmp_path) -> None:
    _write_state(tmp_path, {"local-projects": ["a"]})
    warnings: list[str] = []

    assert reader._read_project_roots(tmp_path, warnings) == {}
    assert warnings == []


def test_read_project_roots_skips_non_dict_entries(tmp_path) -> None:
    _write_state(tmp_path, {"local-projects": {"a": "nope"}})
    warnings: list[str] = []

    assert reader._read_project_roots(tmp_path, warnings) == {}
    assert warnings == []


def test_read_project_roots_warns_on_unsafe_project_id(tmp_path) -> None:
    _write_state(
        tmp_path,
        {"local-projects": {"\x01bad": {"rootPaths": ["/srv/a"]}}},
    )
    warnings: list[str] = []

    assert reader._read_project_roots(tmp_path, warnings) == {}
    assert warnings == [
        "Skipped one Codex project mapping with an unsafe id.",
    ]


def test_read_project_roots_skips_non_list_roots(tmp_path) -> None:
    _write_state(tmp_path, {"local-projects": {"a": {"rootPaths": "/srv"}}})
    warnings: list[str] = []

    assert reader._read_project_roots(tmp_path, warnings) == {}
    assert warnings == []


def test_read_project_roots_drops_unsafe_and_extra_roots(tmp_path) -> None:
    roots = ["/srv/keep"] + [
        f"/srv/pad{i}" for i in range(reader._MAX_METADATA_LIST_ITEMS + 3)
    ]
    _write_state(
        tmp_path,
        {
            "local-projects": {
                "a": {"rootPaths": ["/srv/x\x01y", *roots]},
            },
        },
    )
    warnings: list[str] = []

    result = reader._read_project_roots(tmp_path, warnings)

    cap = reader._MAX_METADATA_LIST_ITEMS
    assert warnings == []
    # The list is truncated to _MAX_METADATA_LIST_ITEMS *before* filtering,
    # so the dropped unsafe entry consumes one of the 16 slots.
    assert result["a"] == [
        "/srv/keep",
        *[f"/srv/pad{i}" for i in range(cap - 2)],
    ]
    assert len(result["a"]) == cap - 1
    assert all("/srv/x" not in item for item in result["a"])


def test_read_project_roots_omits_projects_without_clean_roots(
    tmp_path,
) -> None:
    _write_state(
        tmp_path,
        {"local-projects": {"a": {"rootPaths": ["\x01unsafe"]}}},
    )
    warnings: list[str] = []

    assert reader._read_project_roots(tmp_path, warnings) == {}
    assert warnings == []


def test_read_project_roots_rejects_symlinked_state(tmp_path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"local-projects": {}}), encoding="utf-8")
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / ".codex-global-state.json").symlink_to(outside)
    warnings: list[str] = []

    assert reader._read_project_roots(tmp_path, warnings) == {}
    assert len(warnings) == 1
    assert "ValueError" in warnings[0]


# --------------------------------------------------------------------- #
# _read_toml_candidates
# --------------------------------------------------------------------- #


def test_read_toml_candidates_reads_valid_definition(tmp_path) -> None:
    _write_toml(
        tmp_path,
        "dir-a",
        '[automation]\nid = "auto-a"\nname = "A"\n',
    )
    warnings: list[str] = []

    records, discovered = reader._read_toml_candidates(tmp_path, warnings)

    assert warnings == []
    assert set(records) == {"auto-a"}
    record, path = records["auto-a"]
    assert record["name"] == "A"
    assert path.name == "automation.toml"
    assert discovered == {"auto-a"}


def test_read_toml_candidates_returns_empty_without_root(tmp_path) -> None:
    warnings: list[str] = []

    assert reader._read_toml_candidates(tmp_path, warnings) == ({}, set())
    assert warnings == []


def test_read_toml_candidates_rejects_symlinked_root(tmp_path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "automations").symlink_to(real)
    warnings: list[str] = []

    records, discovered = reader._read_toml_candidates(tmp_path, warnings)

    assert (records, discovered) == ({}, set())
    assert warnings == [
        "Skipped unsafe Codex automations path (expected a directory).",
    ]


def test_read_toml_candidates_rejects_file_root(tmp_path) -> None:
    (tmp_path / "automations").write_text("nope", encoding="utf-8")
    warnings: list[str] = []

    records, discovered = reader._read_toml_candidates(tmp_path, warnings)

    assert (records, discovered) == ({}, set())
    assert warnings == [
        "Skipped unsafe Codex automations path (expected a directory).",
    ]


def test_read_toml_candidates_warns_when_listing_fails(
    tmp_path,
    monkeypatch,
) -> None:
    _write_toml(tmp_path, "dir-a", '[automation]\nid = "auto-a"\n')

    def _boom(self: Path) -> Any:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "iterdir", _boom)
    warnings: list[str] = []

    records, discovered = reader._read_toml_candidates(tmp_path, warnings)

    assert (records, discovered) == ({}, set())
    assert len(warnings) == 1
    assert "Could not list Codex automation definitions" in warnings[0]
    assert "permission denied" in warnings[0]


def test_read_toml_candidates_skips_non_directory_entries(tmp_path) -> None:
    root = tmp_path / "automations"
    root.mkdir()
    (root / "stray.txt").write_text("ignored", encoding="utf-8")
    (root / "linked").symlink_to(root / "stray.txt")
    _write_toml(tmp_path, "dir-a", '[automation]\nid = "auto-a"\n')
    warnings: list[str] = []

    records, discovered = reader._read_toml_candidates(tmp_path, warnings)

    assert set(records) == {"auto-a"}
    assert warnings == []
    assert discovered == {"auto-a"}


def test_read_toml_candidates_skips_directory_without_toml(tmp_path) -> None:
    (tmp_path / "automations" / "empty-dir").mkdir(parents=True)
    warnings: list[str] = []

    records, discovered = reader._read_toml_candidates(tmp_path, warnings)

    assert (records, discovered) == ({}, set())
    assert warnings == []


def test_read_toml_candidates_warns_on_unreadable_toml(tmp_path) -> None:
    directory = tmp_path / "automations" / "dir-a"
    directory.mkdir(parents=True)
    outside = tmp_path / "outside.toml"
    outside.write_text('[automation]\nid = "x"\n', encoding="utf-8")
    (directory / "automation.toml").symlink_to(outside)
    warnings: list[str] = []

    records, discovered = reader._read_toml_candidates(tmp_path, warnings)

    assert records == {}
    assert len(discovered) == 1
    assert len(warnings) == 1
    assert "Could not parse Codex automation 'dir-a'" in warnings[0]
    assert "ValueError" in warnings[0]


@pytest.mark.skipif(
    os.name == "nt",
    reason="control-character names are creatable on POSIX but not on "
    "Windows, where the filesystem rejects them at mkdir time",
)
def test_read_toml_candidates_masks_unsafe_directory_name(tmp_path) -> None:
    directory = tmp_path / "automations" / "\x01unsafe"
    directory.mkdir(parents=True)
    outside = tmp_path / "outside.toml"
    outside.write_text("body", encoding="utf-8")
    (directory / "automation.toml").symlink_to(outside)
    warnings: list[str] = []

    records, _discovered = reader._read_toml_candidates(tmp_path, warnings)

    assert records == {}
    assert "Could not parse Codex automation '<unsafe-id>'" in warnings[0]
    assert "\x01" not in warnings[0]


def test_read_toml_candidates_warns_on_malformed_toml(tmp_path) -> None:
    _write_toml(tmp_path, "dir-a", "this is = = not toml\n")
    warnings: list[str] = []

    records, discovered = reader._read_toml_candidates(tmp_path, warnings)

    assert records == {}
    assert discovered == {"dir-a"}
    assert len(warnings) == 1
    assert "Could not parse Codex automation 'dir-a'" in warnings[0]
    assert "TOMLDecodeError" in warnings[0]


def test_read_toml_candidates_warns_on_unsafe_source_id(tmp_path) -> None:
    _write_toml(
        tmp_path,
        "dir-a",
        '[automation]\nid = "auto\\u0001a"\nname = "A"\n',
    )
    warnings: list[str] = []

    records, discovered = reader._read_toml_candidates(tmp_path, warnings)

    assert records == {}
    assert discovered == {"dir-a"}
    assert warnings == [
        "Skipped Codex TOML automation with an unsafe or oversized "
        "source id.",
    ]


# --------------------------------------------------------------------- #
# _table_columns / _quoted_identifier
# --------------------------------------------------------------------- #


def test_table_columns_returns_empty_for_missing_table(tmp_path) -> None:
    database = _create_database(tmp_path / "sqlite" / "a.db")

    with closing(sqlite3.connect(database)) as connection:
        assert reader._table_columns(connection, "automations") == [
            "id",
            "name",
            "prompt",
            "status",
            "updated_at",
        ]
        assert reader._table_columns(connection, "absent") == []


def test_quoted_identifier_escapes_double_quotes() -> None:
    assert reader._quoted_identifier('we"ird') == '"we""ird"'


# --------------------------------------------------------------------- #
# _regular_file_signature / _copy_bounded_regular_file
# --------------------------------------------------------------------- #


def test_regular_file_signature_reports_change_fields(tmp_path) -> None:
    target = tmp_path / "a.bin"
    target.write_bytes(b"payload")

    signature = reader._regular_file_signature(target, 64)

    info = target.lstat()
    assert signature == (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
    )


def test_regular_file_signature_rejects_oversized_file(tmp_path) -> None:
    target = tmp_path / "a.bin"
    target.write_bytes(b"0123456789")

    with pytest.raises(ValueError, match="read safety limit"):
        reader._regular_file_signature(target, 4)


def test_regular_file_signature_rejects_non_regular_file(tmp_path) -> None:
    with pytest.raises(ValueError, match="is not a regular file"):
        reader._regular_file_signature(tmp_path, 1024)


def test_copy_bounded_regular_file_copies_bytes(tmp_path) -> None:
    source = tmp_path / "source.bin"
    target = tmp_path / "target.bin"
    source.write_bytes(b"\x00\x01\x02binary")

    reader._copy_bounded_regular_file(source, target, 1024)

    assert target.read_bytes() == b"\x00\x01\x02binary"
    if os.name != "nt":
        # Windows ignores the mode bits passed to os.open.
        assert (target.stat().st_mode & 0o777) == 0o600


def test_copy_bounded_regular_file_rejects_oversized_source(
    tmp_path,
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"0123456789")

    with pytest.raises(ValueError, match="exceeds the read safety limit"):
        reader._copy_bounded_regular_file(source, tmp_path / "target.bin", 4)

    assert not (tmp_path / "target.bin").exists()


def test_copy_bounded_regular_file_rejects_non_regular_source(
    tmp_path,
) -> None:
    if os.name == "nt":
        # A directory can be opened for reading on Windows, so the
        # not-a-regular-file guard is only reachable on POSIX.
        pytest.skip("directories are openable on Windows")
    with pytest.raises(ValueError, match="is not a regular file"):
        reader._copy_bounded_regular_file(
            tmp_path,
            tmp_path / "target.bin",
            1024,
        )


def test_copy_bounded_regular_file_rejects_existing_target(tmp_path) -> None:
    source = tmp_path / "source.bin"
    target = tmp_path / "target.bin"
    source.write_bytes(b"payload")
    target.write_bytes(b"already here")

    with pytest.raises(FileExistsError):
        reader._copy_bounded_regular_file(source, target, 1024)

    assert target.read_bytes() == b"already here"


def test_copy_bounded_regular_file_detects_growth(
    tmp_path,
    monkeypatch,
) -> None:
    """A source that grows past the limit mid-copy must be rejected."""
    source = tmp_path / "source.bin"
    source.write_bytes(b"small")
    real_read = os.read

    def _growing_read(fd: int, size: int) -> bytes:
        chunk = real_read(fd, size)
        if chunk:
            return chunk + b"x" * size
        return chunk

    monkeypatch.setattr(reader.os, "read", _growing_read)

    with pytest.raises(ValueError, match="grew beyond the read safety"):
        reader._copy_bounded_regular_file(source, tmp_path / "t.bin", 16)


# --------------------------------------------------------------------- #
# _safe_sqlite_read_target
# --------------------------------------------------------------------- #


def test_safe_sqlite_read_target_without_wal_reads_source(
    tmp_path,
) -> None:
    database = _create_database(tmp_path / "sqlite" / "a.db")

    with reader._safe_sqlite_read_target(database) as (target, immutable):
        assert target == database
        assert immutable is True


def test_safe_sqlite_read_target_rejects_changed_database(tmp_path) -> None:
    database = _create_database(tmp_path / "sqlite" / "a.db")

    with pytest.raises(ValueError, match="changed while being read"):
        with reader._safe_sqlite_read_target(database):
            database.write_bytes(b"x" * (database.stat().st_size + 4096))


def test_safe_sqlite_read_target_rejects_late_wal(tmp_path) -> None:
    database = _create_database(tmp_path / "sqlite" / "a.db")

    with pytest.raises(ValueError, match="appeared while"):
        with reader._safe_sqlite_read_target(database):
            database.with_name(database.name + "-wal").write_bytes(b"wal")


def test_safe_sqlite_read_target_snapshots_wal_and_shm(tmp_path) -> None:
    database = _create_database(tmp_path / "sqlite" / "a.db")
    _insert_automation(database, "auto-1")
    wal = database.with_name(database.name + "-wal")
    shm = database.with_name(database.name + "-shm")
    wal.write_bytes(b"wal-payload")
    shm.write_bytes(b"shm-payload")

    with reader._safe_sqlite_read_target(database) as (target, immutable):
        assert immutable is False
        assert target.name == "snapshot.db"
        assert target.read_bytes() == database.read_bytes()
        assert (
            target.with_name(target.name + "-wal").read_bytes()
            == b"wal-payload"
        )
        assert (
            target.with_name(target.name + "-shm").read_bytes()
            == b"shm-payload"
        )
        if os.name != "nt":
            # Windows ignores the mode bits passed to os.chmod.
            assert (target.parent.stat().st_mode & 0o777) == 0o700

    assert not target.parent.exists()


def test_safe_sqlite_read_target_reports_missing_database(
    tmp_path,
    monkeypatch,
) -> None:
    # A WAL must exist, otherwise the immutable branch reads the source
    # in place and never reaches the copy step.
    database = _create_database(tmp_path / "sqlite" / "a.db")
    database.with_name(database.name + "-wal").write_bytes(b"wal")
    real_copy = reader._copy_bounded_regular_file

    def _vanished(source: Path, target: Path, limit: int) -> None:
        if source == database:
            raise FileNotFoundError(source)
        real_copy(source, target, limit)

    monkeypatch.setattr(reader, "_copy_bounded_regular_file", _vanished)

    with pytest.raises(ValueError, match="a.db disappeared"):
        with reader._safe_sqlite_read_target(database):
            _run_noop()


def test_safe_sqlite_read_target_reports_missing_sidecar(
    tmp_path,
    monkeypatch,
) -> None:
    database = _create_database(tmp_path / "sqlite" / "a.db")
    database.with_name(database.name + "-wal").write_bytes(b"wal")
    real_copy = reader._copy_bounded_regular_file

    def _vanished(source: Path, target: Path, limit: int) -> None:
        if source.name.endswith("-wal"):
            raise FileNotFoundError(source)
        real_copy(source, target, limit)

    monkeypatch.setattr(reader, "_copy_bounded_regular_file", _vanished)

    with pytest.raises(ValueError, match="a.db-wal disappeared"):
        with reader._safe_sqlite_read_target(database):
            pass


def test_safe_sqlite_read_target_reports_changed_signature(
    tmp_path,
    monkeypatch,
) -> None:
    database = _create_database(tmp_path / "sqlite" / "a.db")
    database.with_name(database.name + "-wal").write_bytes(b"wal")
    real_signature = reader._regular_file_signature
    calls: list[Path] = []

    def _unstable(path: Path, limit: int) -> tuple[int, ...]:
        calls.append(path)
        signature = real_signature(path, limit)
        # The verification pass is the last signature taken for each path.
        if calls.count(path) > 1:
            return (*signature[:-1], signature[-1] + 1)
        return signature

    monkeypatch.setattr(reader, "_regular_file_signature", _unstable)

    with pytest.raises(ValueError, match="changed while being copied"):
        with reader._safe_sqlite_read_target(database):
            _run_noop()


def test_safe_sqlite_read_target_reports_vanished_sidecar(
    tmp_path,
    monkeypatch,
) -> None:
    database = _create_database(tmp_path / "sqlite" / "a.db")
    database.with_name(database.name + "-wal").write_bytes(b"wal")
    real_signature = reader._regular_file_signature
    calls: list[Path] = []

    def _vanishing(path: Path, limit: int) -> tuple[int, ...]:
        calls.append(path)
        if calls.count(path) > 1:
            raise FileNotFoundError(path)
        return real_signature(path, limit)

    monkeypatch.setattr(reader, "_regular_file_signature", _vanishing)

    with pytest.raises(ValueError, match="disappeared while being copied"):
        with reader._safe_sqlite_read_target(database):
            _run_noop()


def test_safe_sqlite_read_target_rejects_late_shm(
    tmp_path,
    monkeypatch,
) -> None:
    database = _create_database(tmp_path / "sqlite" / "a.db")
    database.with_name(database.name + "-wal").write_bytes(b"wal")
    shm = database.with_name(database.name + "-shm")
    real_copy = reader._copy_bounded_regular_file

    def _late_shm(source: Path, target: Path, limit: int) -> None:
        real_copy(source, target, limit)
        if not shm.exists():
            shm.write_bytes(b"late")

    monkeypatch.setattr(reader, "_copy_bounded_regular_file", _late_shm)

    with pytest.raises(ValueError, match="appeared while"):
        with reader._safe_sqlite_read_target(database):
            _run_noop()


# --------------------------------------------------------------------- #
# _read_sqlite_target
# --------------------------------------------------------------------- #


def test_read_sqlite_target_selects_only_safe_columns(tmp_path) -> None:
    database = _create_database(tmp_path / "sqlite" / "a.db")
    _insert_automation(database, "auto-1", updated_at=9)

    rows, run_ids, warnings = reader._read_sqlite_target(
        database,
        source_name="a.db",
        immutable=True,
    )

    assert warnings == []
    assert run_ids == set()
    assert rows == [
        {
            "id": "auto-1",
            "name": "name",
            "prompt": "prompt",
            "status": "ACTIVE",
            "updated_at": 9,
        },
    ]


def test_read_sqlite_target_warns_without_id_column(tmp_path) -> None:
    database = tmp_path / "sqlite" / "a.db"
    database.parent.mkdir(parents=True)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "CREATE TABLE automations (name TEXT, status TEXT)",
        )
        connection.commit()

    rows, _run_ids, warnings = reader._read_sqlite_target(
        database,
        source_name="a.db",
        immutable=True,
    )

    assert rows == []
    assert warnings == [
        "Ignored automation table without an id column in a.db.",
    ]


def test_read_sqlite_target_lowercases_mixed_case_columns(tmp_path) -> None:
    database = tmp_path / "sqlite" / "a.db"
    database.parent.mkdir(parents=True)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            'CREATE TABLE automations ("ID" TEXT, "Name" TEXT)',
        )
        connection.execute(
            'INSERT INTO automations ("ID", "Name") VALUES (?, ?)',
            ("auto-1", "Title"),
        )
        connection.commit()

    rows, _run_ids, warnings = reader._read_sqlite_target(
        database,
        source_name="a.db",
        immutable=True,
    )

    assert warnings == []
    assert rows == [{"id": "auto-1", "name": "Title"}]


def test_read_sqlite_target_caps_task_rows(tmp_path, monkeypatch) -> None:
    database = _create_database(tmp_path / "sqlite" / "a.db")
    for index in range(3):
        _insert_automation(database, f"auto-{index}", updated_at=index)
    monkeypatch.setattr(reader, "_MAX_SQLITE_TASKS", 2)

    rows, _run_ids, warnings = reader._read_sqlite_target(
        database,
        source_name="a.db",
        immutable=True,
    )

    assert len(rows) == 2
    assert warnings == [
        "Codex automation safety limit (2) was reached in a.db.",
    ]


def test_read_sqlite_target_collects_run_thread_ids(tmp_path) -> None:
    database = _create_database(tmp_path / "sqlite" / "a.db", with_runs=True)
    _insert_run(database, "thread-1")
    _insert_run(database, None)
    _insert_run(database, "bad\x01thread")
    _insert_run(database, "bad\x02thread")

    _rows, run_ids, warnings = reader._read_sqlite_target(
        database,
        source_name="a.db",
        immutable=True,
    )

    assert run_ids == {"thread-1"}
    assert warnings == [
        "Skipped 2 Codex automation-run thread id(s) with unsafe values "
        "in a.db.",
    ]


def test_read_sqlite_target_caps_run_rows(tmp_path, monkeypatch) -> None:
    database = _create_database(tmp_path / "sqlite" / "a.db", with_runs=True)
    for index in range(3):
        _insert_run(database, f"thread-{index}")
    monkeypatch.setattr(reader, "_MAX_AUTOMATION_RUNS", 2)

    _rows, run_ids, warnings = reader._read_sqlite_target(
        database,
        source_name="a.db",
        immutable=True,
    )

    assert len(run_ids) == 2
    assert warnings == [
        "Codex automation-run safety limit (2) was reached in a.db.",
    ]


def test_read_sqlite_target_ignores_missing_table(tmp_path) -> None:
    database = tmp_path / "sqlite" / "a.db"
    database.parent.mkdir(parents=True)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.commit()

    rows, run_ids, warnings = reader._read_sqlite_target(
        database,
        source_name="a.db",
        immutable=True,
    )

    assert (rows, run_ids, warnings) == ([], set(), [])


def test_read_sqlite_target_reports_corrupt_database(tmp_path) -> None:
    database = tmp_path / "sqlite" / "a.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"this is definitely not a sqlite database")

    rows, run_ids, warnings = reader._read_sqlite_target(
        database,
        source_name="a.db",
        immutable=True,
    )

    assert (rows, run_ids) == ([], set())
    assert len(warnings) == 1
    assert "Could not read Codex automation database a.db" in warnings[0]


@pytest.mark.skipif(
    os.name == "nt",
    reason="control-character names are creatable on POSIX but not on "
    "Windows, where the filesystem rejects them at open time",
)
def test_read_sqlite_database_masks_unsafe_name(tmp_path) -> None:
    database = tmp_path / "sqlite" / "\x01bad.db"
    _create_database(database)
    _insert_automation(database, "auto-1")

    rows, _run_ids, warnings = reader._read_sqlite_database(database)

    assert len(rows) == 1
    assert warnings == []
    assert "\x01" not in json.dumps(warnings)


def test_read_sqlite_database_reports_unreadable_store(tmp_path) -> None:
    database = tmp_path / "sqlite" / "a.db"
    database.parent.mkdir(parents=True)
    outside = tmp_path / "outside.db"
    outside.write_bytes(b"payload")
    database.symlink_to(outside)

    rows, run_ids, warnings = reader._read_sqlite_database(database)

    assert (rows, run_ids) == ([], set())
    assert len(warnings) == 1
    assert "Could not read Codex automation database a.db" in warnings[0]


# --------------------------------------------------------------------- #
# _read_sqlite_candidates
# --------------------------------------------------------------------- #


def test_read_sqlite_candidates_collects_rows(tmp_path) -> None:
    database = _create_database(tmp_path / "sqlite" / "a.db")
    _insert_automation(database, "auto-1")
    warnings: list[str] = []

    candidates, discovered, run_ids = reader._read_sqlite_candidates(
        tmp_path,
        warnings,
    )

    assert warnings == []
    assert run_ids == set()
    assert set(candidates) == {"auto-1"}
    assert candidates["auto-1"][1] == database
    assert discovered == {"auto-1"}


def test_read_sqlite_candidates_returns_empty_without_root(tmp_path) -> None:
    warnings: list[str] = []

    assert reader._read_sqlite_candidates(tmp_path, warnings) == (
        {},
        set(),
        set(),
    )
    assert warnings == []


def test_read_sqlite_candidates_rejects_symlinked_root(tmp_path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "sqlite").symlink_to(real)
    warnings: list[str] = []

    assert reader._read_sqlite_candidates(tmp_path, warnings) == (
        {},
        set(),
        set(),
    )
    assert warnings == []


def test_read_sqlite_candidates_warns_when_globbing_fails(
    tmp_path,
    monkeypatch,
) -> None:
    (tmp_path / "sqlite").mkdir()

    def _boom(self: Path, *_args: Any, **_kwargs: Any) -> Any:
        raise OSError("device busy")

    monkeypatch.setattr(Path, "glob", _boom)
    warnings: list[str] = []

    assert reader._read_sqlite_candidates(tmp_path, warnings) == (
        {},
        set(),
        set(),
    )
    assert warnings == ["Could not list Codex SQLite stores: device busy"]


@pytest.mark.skipif(
    os.name == "nt",
    reason="os.mkfifo and unprivileged symlinks are unavailable on Windows",
)
def test_read_sqlite_candidates_skips_unsafe_paths(tmp_path) -> None:
    root = tmp_path / "sqlite"
    root.mkdir()
    outside = tmp_path / "outside.db"
    outside.write_bytes(b"untrusted")
    (root / "linked.db").symlink_to(outside)
    (root / "empty.db").touch()
    (root / "empty.db").unlink()
    os.mkfifo(root / "fifo.db")
    warnings: list[str] = []

    candidates, discovered, _run_ids = reader._read_sqlite_candidates(
        tmp_path,
        warnings,
    )

    assert (candidates, discovered) == ({}, set())
    assert "Skipped unsafe Codex SQLite path 'linked.db'." in warnings
    assert "Skipped unsafe Codex SQLite path 'fifo.db'." in warnings
    assert outside.read_bytes() == b"untrusted"


@pytest.mark.skipif(
    os.name == "nt",
    reason="control-character names are creatable on POSIX but not on "
    "Windows, where the filesystem rejects them at open time",
)
def test_read_sqlite_candidates_masks_unsafe_database_name(tmp_path) -> None:
    database = _create_database(tmp_path / "sqlite" / "\x01bad.db")
    _insert_automation(database, "auto-1")
    (tmp_path / "sqlite" / "\x02worse.db").symlink_to(database)
    warnings: list[str] = []

    _candidates, _discovered, _run_ids = reader._read_sqlite_candidates(
        tmp_path,
        warnings,
    )

    assert any("Skipped unsafe Codex SQLite path" in item for item in warnings)
    assert not any("\x01" in item or "\x02" in item for item in warnings)


def test_read_sqlite_candidates_warns_on_missing_and_unsafe_ids(
    tmp_path,
) -> None:
    database = _create_database(tmp_path / "sqlite" / "a.db")
    _insert_automation(database, None)
    _insert_automation(database, "")
    _insert_automation(database, "bad\x01id")
    warnings: list[str] = []

    candidates, discovered, _run_ids = reader._read_sqlite_candidates(
        tmp_path,
        warnings,
    )

    assert candidates == {}
    assert len(discovered) == 1
    assert (
        warnings.count(
            "Skipped one Codex automation without an id in a.db.",
        )
        == 2
    )
    assert any(
        item.startswith(
            "Skipped one Codex automation with an unsafe or oversized id",
        )
        for item in warnings
    )


def test_read_sqlite_candidates_keeps_newest_duplicate(tmp_path) -> None:
    older = _create_database(tmp_path / "sqlite" / "a.db")
    newer = _create_database(tmp_path / "sqlite" / "b.db")
    _insert_automation(older, "dup", updated_at=1)
    _insert_automation(newer, "dup", updated_at=9)
    warnings: list[str] = []

    candidates, discovered, _run_ids = reader._read_sqlite_candidates(
        tmp_path,
        warnings,
    )

    assert warnings == []
    assert discovered == {"dup"}
    assert candidates["dup"][1] == newer
    assert candidates["dup"][0]["updated_at"] == 9


def test_read_sqlite_candidates_skips_older_duplicate(tmp_path) -> None:
    newer = _create_database(tmp_path / "sqlite" / "a.db")
    older = _create_database(tmp_path / "sqlite" / "b.db")
    _insert_automation(newer, "dup", updated_at=9)
    _insert_automation(older, "dup", updated_at=1)
    warnings: list[str] = []

    candidates, _discovered, _run_ids = reader._read_sqlite_candidates(
        tmp_path,
        warnings,
    )

    assert warnings == []
    assert candidates["dup"][1] == newer


def test_read_sqlite_candidates_merges_run_thread_ids(tmp_path) -> None:
    database = _create_database(tmp_path / "sqlite" / "a.db", with_runs=True)
    _insert_run(database, "thread-1")
    warnings: list[str] = []

    _candidates, _discovered, run_ids = reader._read_sqlite_candidates(
        tmp_path,
        warnings,
    )

    assert run_ids == {"thread-1"}


def test_read_sqlite_candidates_reports_unreadable_store(tmp_path) -> None:
    database = tmp_path / "sqlite" / "a.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"not a database at all")
    warnings: list[str] = []

    candidates, _discovered, _run_ids = reader._read_sqlite_candidates(
        tmp_path,
        warnings,
    )

    assert candidates == {}
    assert len(warnings) == 1
    assert "Could not read Codex automation database a.db" in warnings[0]


# --------------------------------------------------------------------- #
# _updated_score / _unsafe_identity_token
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ({"updated_at": 12}, 12.0),
        ({"updated_at": "3.5"}, 3.5),
        ({"updated_at": None}, float("-inf")),
        ({"updated_at": "not-a-number"}, float("-inf")),
        ({}, float("-inf")),
    ],
)
def test_updated_score_parses_numeric_values(record, expected) -> None:
    score = reader._updated_score(record)

    assert score == expected
    assert math.isinf(score) is math.isinf(expected)


def test_unsafe_identity_token_is_bounded_and_stable() -> None:
    unsafe = "x" * 4000 + "\x01"

    first = reader._unsafe_identity_token(unsafe, fallback="sqlite-row")
    second = reader._unsafe_identity_token(unsafe, fallback="sqlite-row")
    other = reader._unsafe_identity_token(unsafe, fallback="toml-directory")

    assert first == second
    assert first != other
    assert first.startswith("unsafe:")
    assert first.endswith(":sqlite-row")
    assert unsafe not in first
    assert len(first) < 128


def test_unsafe_identity_token_handles_non_string() -> None:
    token = reader._unsafe_identity_token(1234, fallback="sqlite-row")

    assert token.startswith("unsafe:")
    assert "1234" not in token


def test_warning_detail_falls_back_to_type_name() -> None:
    class _Silent(Exception):
        def __str__(self) -> str:
            return ""

    assert reader._warning_detail(_Silent()) == "_Silent"
    assert reader._warning_detail(ValueError("boom")) == "boom"
