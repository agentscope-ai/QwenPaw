# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from qwenpaw.portability.providers import codex_schedules
from qwenpaw.portability.providers import codex_schedule_reader
from qwenpaw.portability.providers.codex_schedules import (
    discover_codex_scheduled_tasks,
)


def _write_automation(home: Path, automation_id: str, body: str) -> Path:
    path = home / "automations" / automation_id / "automation.toml"
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")
    return path


def _create_codex_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE automations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                next_run_at INTEGER,
                last_run_at INTEGER,
                cwds TEXT NOT NULL DEFAULT '[]',
                rrule TEXT NOT NULL,
                model TEXT,
                reasoning_effort TEXT,
                created_at INTEGER,
                updated_at INTEGER,
                target_type TEXT,
                project_id TEXT
            );
            CREATE TABLE automation_runs (
                thread_id TEXT PRIMARY KEY,
                automation_id TEXT NOT NULL,
                status TEXT NOT NULL,
                archived_user_message TEXT,
                archived_assistant_message TEXT
            );
            """,
        )


def _insert_automation(
    connection: sqlite3.Connection,
    automation_id: str,
    name: str,
    prompt: str | bytes,
    rrule: str,
    *,
    status: str = "ACTIVE",
    cwds: str = "[]",
    updated_at: int = 1,
) -> None:
    connection.execute(
        "INSERT INTO automations "
        "(id, name, prompt, status, cwds, rrule, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (automation_id, name, prompt, status, cwds, rrule, updated_at),
    )


@pytest.fixture(autouse=True)
def _stable_local_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        codex_schedules,
        "_local_timezone_name",
        lambda: ("Asia/Shanghai", "system"),
    )


def test_toml_wins_over_sqlite_and_run_ids_are_structured(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".codex"
    _write_automation(
        home,
        "daily",
        """
id = "daily"
name = "TOML task"
prompt = "Read the TOML definition"
status = "ACTIVE"
kind = "heartbeat"
rrule = "FREQ=DAILY;BYHOUR=9;BYMINUTE=30"
cwd = "/toml/project"
""",
    )
    database = home / "sqlite" / "codex-dev.db"
    _create_codex_database(database)
    with sqlite3.connect(database) as connection:
        _insert_automation(
            connection,
            "daily",
            "stale DB task",
            "stale prompt",
            "FREQ=HOURLY;INTERVAL=2;BYMINUTE=0",
            status="PAUSED",
            cwds='["/sqlite/project"]',
        )
        _insert_automation(
            connection,
            "weekly",
            "DB task",
            "Read the DB definition",
            "FREQ=WEEKLY;BYDAY=MO,WE,FR;BYHOUR=8;BYMINUTE=0",
            status="PAUSED",
            cwds='["/sqlite/project"]',
            updated_at=2,
        )
        connection.execute(
            "INSERT INTO automation_runs VALUES (?, ?, ?, ?, ?)",
            (
                "automation-thread-1",
                "weekly",
                "COMPLETED",
                "must not be loaded",
                "must not be loaded",
            ),
        )

    before = database.read_bytes()
    (
        tasks,
        warnings,
        discovered_count,
        run_ids,
    ) = discover_codex_scheduled_tasks(home)

    assert [task.source_id for task in tasks] == ["daily", "weekly"]
    daily, weekly = tasks
    assert daily.name == "TOML task"
    assert daily.prompt == "Read the TOML definition"
    assert daily.cron == "30 9 * * *"
    assert daily.cwd == "/toml/project"
    assert daily.enabled is True
    assert daily.metadata["source_format"] == "toml"
    assert weekly.cron == "0 8 * * mon,wed,fri"
    assert weekly.enabled is False
    assert weekly.metadata["source_format"] == "sqlite"
    assert discovered_count == 2
    assert run_ids == {"automation-thread-1"}
    assert any("inferred local IANA timezone" in item for item in warnings)
    assert database.read_bytes() == before
    assert not database.with_name(database.name + "-journal").exists()


def test_live_wal_is_read_from_private_snapshot_without_source_writes(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".codex"
    database = home / "sqlite" / "codex-dev.db"
    _create_codex_database(database)
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        connection.execute("PRAGMA wal_autocheckpoint = 0")
        _insert_automation(
            connection,
            "wal-only",
            "WAL task",
            "Read the committed WAL state",
            "FREQ=DAILY;BYHOUR=11;BYMINUTE=25",
            updated_at=3,
        )
        connection.execute(
            "INSERT INTO automation_runs VALUES (?, ?, ?, ?, ?)",
            ("wal-thread", "wal-only", "COMPLETED", "secret", "secret"),
        )
        connection.commit()

        wal = database.with_name(database.name + "-wal")
        shm = database.with_name(database.name + "-shm")
        assert wal.stat().st_size > 0
        source_before = {
            path.name: path.read_bytes() for path in (database, wal, shm)
        }

        immutable_uri = f"{database.resolve().as_uri()}?mode=ro&immutable=1"
        with sqlite3.connect(immutable_uri, uri=True) as stale_connection:
            assert (
                stale_connection.execute(
                    "SELECT COUNT(*) FROM automations",
                ).fetchone()[0]
                == 0
            )

        (
            tasks,
            warnings,
            discovered_count,
            run_ids,
        ) = discover_codex_scheduled_tasks(home)

        assert [task.source_id for task in tasks] == ["wal-only"]
        assert tasks[0].cron == "25 11 * * *"
        assert discovered_count == 1
        assert run_ids == {"wal-thread"}
        assert not any("Could not read" in item for item in warnings)
        assert {
            path.name: path.read_bytes() for path in (database, wal, shm)
        } == source_before
    finally:
        connection.close()


def test_symlinked_wal_is_rejected_without_following_it(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".codex"
    database = home / "sqlite" / "codex-dev.db"
    _create_codex_database(database)
    outside = tmp_path / "outside-wal"
    outside.write_bytes(b"untrusted")
    database.with_name(database.name + "-wal").symlink_to(outside)

    (
        tasks,
        warnings,
        discovered_count,
        run_ids,
    ) = discover_codex_scheduled_tasks(home)

    assert not tasks
    assert discovered_count == 0
    assert not run_ids
    assert outside.read_bytes() == b"untrusted"
    assert any("is not a regular file" in item for item in warnings)


@pytest.mark.parametrize(
    ("prompt", "reason"),
    [
        (
            "PROMPT_MUST_NOT_LEAK_"
            + "x" * (codex_schedule_reader._MAX_PROMPT_CHARS + 1),
            "source_prompt_exceeds_limit",
        ),
        ("PROMPT_MUST_NOT_LEAK_\x01tail", "source_prompt_unsafe"),
    ],
)
def test_unsafe_prompt_is_omitted_audited_and_never_scheduled(
    tmp_path: Path,
    prompt: str,
    reason: str,
) -> None:
    home = tmp_path / ".codex"
    database = home / "sqlite" / "codex-dev.db"
    _create_codex_database(database)
    with sqlite3.connect(database) as connection:
        _insert_automation(
            connection,
            "unsafe-prompt",
            "Safe title",
            prompt,
            "FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
        )

    tasks, warnings, discovered_count, _ = discover_codex_scheduled_tasks(home)

    assert discovered_count == 1
    assert len(tasks) == 1
    task = tasks[0]
    assert task.prompt == ""
    assert task.schedule_type == "unsupported"
    assert task.cron == ""
    assert task.run_at is None
    assert task.metadata["unsupported_reason"] == reason
    audit = task.metadata["prompt_audit"]
    encoded = prompt.encode("utf-8")
    assert audit == {
        "disposition": "omitted",
        "original_chars": len(prompt),
        "original_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }
    exported = json.dumps(task.model_dump(mode="json"), ensure_ascii=False)
    assert "PROMPT_MUST_NOT_LEAK" not in exported
    assert "PROMPT_MUST_NOT_LEAK" not in "\n".join(warnings)


def test_untrusted_fields_are_bounded_before_entering_task_metadata(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".codex"
    database = home / "sqlite" / "codex-dev.db"
    database.parent.mkdir(parents=True)
    huge_rrule = "FREQ=DAILY;" + "X" * (
        codex_schedule_reader._MAX_RRULE_CHARS + 1
    )
    unsafe_cwd = "/tmp/CWD_MUST_NOT_LEAK\x00tail"
    unsafe_timezone = "Z" * (codex_schedule_reader._MAX_TIMEZONE_CHARS + 1)
    cwd_values = [f"/workspace/{index}" for index in range(30)]
    cwd_values.append("/unsafe\x02path")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE automations ("
            "id TEXT, name TEXT, prompt TEXT, status TEXT, cwd TEXT, "
            "cwds TEXT, rrule TEXT, timezone TEXT, model TEXT, "
            "next_run_at TEXT)",
        )
        connection.execute(
            "INSERT INTO automations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "bounded-fields",
                "Title\x01" + "T" * 500,
                "Safe prompt",
                "ACTIVE",
                unsafe_cwd,
                json.dumps(cwd_values),
                huge_rrule,
                unsafe_timezone,
                "M" * 10_000 + "\x03",
                "N" * 10_000,
            ),
        )
        connection.execute("CREATE TABLE automation_runs (thread_id TEXT)")
        connection.execute(
            "INSERT INTO automation_runs VALUES (?)",
            ("unsafe-thread\x04",),
        )

    (
        tasks,
        warnings,
        discovered_count,
        run_ids,
    ) = discover_codex_scheduled_tasks(home)

    assert discovered_count == 1
    assert not run_ids
    assert len(tasks) == 1
    task = tasks[0]
    assert task.schedule_type == "unsupported"
    assert task.cron == ""
    assert task.cwd == "/workspace/0"
    assert len(task.name) <= codex_schedule_reader._MAX_TITLE_CHARS
    assert not codex_schedule_reader._contains_control(task.name)
    assert task.metadata["source_rrule"] == ""
    assert (
        task.metadata["rrule_audit"]["sha256"]
        == hashlib.sha256(huge_rrule.encode("utf-8")).hexdigest()
    )
    assert (
        task.metadata["cwd_audit"]["sha256"]
        == hashlib.sha256(unsafe_cwd.encode("utf-8")).hexdigest()
    )
    assert task.metadata["timezone_audit"]["original_chars"] == len(
        unsafe_timezone,
    )
    assert len(task.metadata["source_cwds"]) <= 16
    assert len(task.metadata["model"]) <= 256
    assert len(task.metadata["source_next_run_at"]) <= 256
    exported = json.dumps(task.model_dump(mode="json"), ensure_ascii=False)
    assert "CWD_MUST_NOT_LEAK" not in exported
    assert not any(
        codex_schedule_reader._contains_control(value)
        for value in task.metadata.values()
        if isinstance(value, str)
    )
    assert any("unsafe values" in item for item in warnings)


def test_unsafe_source_ids_are_skipped_but_counted_without_leaking(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".codex"
    oversized_id = "OVERSIZED_ID_MUST_NOT_LEAK_" + "x" * (
        codex_schedule_reader._MAX_SOURCE_ID_CHARS + 1
    )
    _write_automation(
        home,
        "unsafe-toml-record",
        f'id = "{oversized_id}"\n'
        'name = "Unsafe"\nprompt = "Do it"\nstatus = "ACTIVE"\n'
        'rrule = "FREQ=DAILY;BYHOUR=9;BYMINUTE=0"\n',
    )
    database = home / "sqlite" / "codex-dev.db"
    _create_codex_database(database)
    unsafe_sqlite_id = "SQLITE_ID_MUST_NOT_LEAK\x01"
    with sqlite3.connect(database) as connection:
        _insert_automation(
            connection,
            unsafe_sqlite_id,
            "Unsafe",
            "Do it",
            "FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
        )

    tasks, warnings, discovered_count, _ = discover_codex_scheduled_tasks(home)

    assert not tasks
    assert discovered_count == 2
    warning_text = "\n".join(warnings)
    assert "unsafe or oversized" in warning_text
    assert "OVERSIZED_ID_MUST_NOT_LEAK" not in warning_text
    assert "SQLITE_ID_MUST_NOT_LEAK" not in warning_text
