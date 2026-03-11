# -*- coding: utf-8 -*-
"""SQLite state storage and legacy data migration helpers."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from .runner.models import ChatSpec
from .runner.repo.json_repo import JsonChatRepository
from .crons.models import CronJobSpec
from .crons.repo.json_repo import JsonJobRepository
from ..utils.json_storage import load_json_with_recovery, repair_json_file


logger = logging.getLogger(__name__)

_MIGRATION_CHATS = "legacy_chats_v1"
_MIGRATION_JOBS = "legacy_jobs_v1"
_MIGRATION_SESSIONS = "legacy_sessions_v1"


def connect_state_db(path: Path) -> sqlite3.Connection:
    """Open a SQLite connection configured for local concurrent use."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        path,
        timeout=30,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def ensure_state_db_schema(path: Path) -> None:
    """Create SQLite schema if it does not exist."""
    for attempt in range(20):
        try:
            with connect_state_db(path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS chats (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        channel TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        UNIQUE(session_id, user_id, channel)
                    );

                    CREATE INDEX IF NOT EXISTS idx_chats_user_channel_created
                    ON chats(user_id, channel, created_at, id);

                    CREATE TABLE IF NOT EXISTS jobs (
                        id TEXT PRIMARY KEY,
                        payload_json TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS sessions (
                        storage_key TEXT PRIMARY KEY,
                        payload_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """,
                )
                return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 19:
                raise
            time.sleep(0.1 * (attempt + 1))


async def initialize_state_db(
    db_path: Path,
    *,
    chats_path: Path,
    jobs_path: Path,
    sessions_dir: Path,
) -> None:
    """Ensure schema and perform one-time migration from legacy files."""
    ensure_state_db_schema(db_path)
    await _migrate_chats_if_needed(db_path, chats_path)
    await _migrate_jobs_if_needed(db_path, jobs_path)
    _migrate_sessions_if_needed(db_path, sessions_dir)


async def _migrate_chats_if_needed(db_path: Path, chats_path: Path) -> None:
    with connect_state_db(db_path) as conn:
        if _meta_exists(conn, _MIGRATION_CHATS):
            return
        if _table_has_rows(conn, "chats"):
            _set_meta(conn, _MIGRATION_CHATS, "existing-db-data")
            return

    legacy = await JsonChatRepository(chats_path).load()
    if legacy.chats:
        with connect_state_db(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                _replace_chats(conn, legacy.chats)
                _set_meta(conn, _MIGRATION_CHATS, "imported-json")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
    else:
        with connect_state_db(db_path) as conn:
            _set_meta(conn, _MIGRATION_CHATS, "empty-json")


async def _migrate_jobs_if_needed(db_path: Path, jobs_path: Path) -> None:
    with connect_state_db(db_path) as conn:
        if _meta_exists(conn, _MIGRATION_JOBS):
            return
        if _table_has_rows(conn, "jobs"):
            _set_meta(conn, _MIGRATION_JOBS, "existing-db-data")
            return

    legacy = await JsonJobRepository(jobs_path).load()
    if legacy.jobs:
        with connect_state_db(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                _replace_jobs(conn, legacy.jobs)
                _set_meta(conn, _MIGRATION_JOBS, "imported-json")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
    else:
        with connect_state_db(db_path) as conn:
            _set_meta(conn, _MIGRATION_JOBS, "empty-json")


def _migrate_sessions_if_needed(db_path: Path, sessions_dir: Path) -> None:
    with connect_state_db(db_path) as conn:
        if _meta_exists(conn, _MIGRATION_SESSIONS):
            return
        if _table_has_rows(conn, "sessions"):
            _set_meta(conn, _MIGRATION_SESSIONS, "existing-db-data")
            return

    if not sessions_dir.exists():
        with connect_state_db(db_path) as conn:
            _set_meta(conn, _MIGRATION_SESSIONS, "no-session-dir")
        return

    imported = 0
    with connect_state_db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for path in sorted(sessions_dir.glob("*.json")):
                payload = load_json_with_recovery(
                    path,
                    default_payload={},
                    storage_name="legacy session state",
                    logger_=logger,
                )
                if not isinstance(payload, dict):
                    repair_json_file(
                        path,
                        default_payload={},
                        storage_name="legacy session state",
                        reason="state payload is not a JSON object",
                        logger_=logger,
                    )
                    payload = {}

                storage_key = path.stem
                conn.execute(
                    """
                    INSERT OR REPLACE INTO sessions (
                        storage_key,
                        payload_json,
                        updated_at
                    ) VALUES (?, ?, ?)
                    """,
                    (
                        storage_key,
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        _utc_now(),
                    ),
                )
                imported += 1

            _set_meta(
                conn,
                _MIGRATION_SESSIONS,
                f"imported-files:{imported}",
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def load_chat_from_row(row: sqlite3.Row) -> ChatSpec:
    return ChatSpec.model_validate_json(row["payload_json"])


def load_job_from_row(row: sqlite3.Row) -> CronJobSpec:
    return CronJobSpec.model_validate_json(row["payload_json"])


def dump_model_payload(model) -> str:
    return json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
    )


def _replace_chats(conn: sqlite3.Connection, chats: list[ChatSpec]) -> None:
    conn.execute("DELETE FROM chats")
    conn.executemany(
        """
        INSERT INTO chats (
            id,
            session_id,
            user_id,
            channel,
            created_at,
            updated_at,
            payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                chat.id,
                chat.session_id,
                chat.user_id,
                chat.channel,
                _normalize_dt(chat.created_at),
                _normalize_dt(chat.updated_at),
                dump_model_payload(chat),
            )
            for chat in chats
        ],
    )


def _replace_jobs(conn: sqlite3.Connection, jobs: list[CronJobSpec]) -> None:
    conn.execute("DELETE FROM jobs")
    conn.executemany(
        """
        INSERT INTO jobs (id, payload_json)
        VALUES (?, ?)
        """,
        [(job.id, dump_model_payload(job)) for job in jobs],
    )


def _meta_exists(conn: sqlite3.Connection, key: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM metadata WHERE key = ?",
        (key,),
    ).fetchone()
    return row is not None


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO metadata (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _table_has_rows(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        f"SELECT 1 FROM {table_name} LIMIT 1",
    ).fetchone()
    return row is not None


def _normalize_dt(value) -> str:
    if isinstance(value, str):
        return value
    return value.isoformat()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
