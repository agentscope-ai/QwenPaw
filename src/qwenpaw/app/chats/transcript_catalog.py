# -*- coding: utf-8 -*-
"""Workspace catalog and per-session durable transcript stores."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import os
import sqlite3
import threading
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .transcript import TranscriptCursor, TranscriptPage, TranscriptStore

logger = logging.getLogger(__name__)

_CATALOG_SCHEMA_VERSION = 2
_BUSY_TIMEOUT_MS = 5_000
_DEFAULT_MAX_OPEN_STORES = 32


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _SessionHandle:
    """One session store with ordered writes and lease accounting."""

    def __init__(self, store: TranscriptStore) -> None:
        self.store = store
        self.writer = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="transcript-writer",
        )
        self.active = 0
        self.closing = False
        self.pending_delete = False

    def write(self, method_name: str, **kwargs: Any) -> Any:
        """Run one mutation after all prior mutations for this session."""
        method = getattr(self.store, method_name)
        return self.writer.submit(method, **kwargs).result()

    def close(self) -> None:
        """Drain writes, checkpoint the WAL, and close the connection."""
        if self.closing:
            return
        self.closing = True
        self.writer.shutdown(wait=True)
        self.store.close()


class TranscriptCatalog:
    """Route transcript operations to independent per-session databases."""

    def __init__(
        self,
        workspace_dir: str | Path,
        retention_days: int = 30,
        max_open_stores: int = _DEFAULT_MAX_OPEN_STORES,
    ) -> None:
        if max_open_stores < 1:
            raise ValueError("max_open_stores must be positive")
        self._workspace_dir = Path(workspace_dir).expanduser()
        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._workspace_dir / "transcript_catalog.db"
        self._legacy_path = self._workspace_dir / "transcript.db"
        self._transcript_dir = self._workspace_dir / "transcripts"
        self._transcript_dir.mkdir(parents=True, exist_ok=True)
        self._retention_days = retention_days
        self._max_open_stores = max_open_stores
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._closed = False
        self._handles: OrderedDict[str, _SessionHandle] = OrderedDict()
        self._publishing: set[str] = set()
        self._cleanup_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="transcript-catalog-cleanup",
        )
        self._conn = sqlite3.connect(
            str(self._path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()
        self._resume_deleted_cleanup()

    @property
    def path(self) -> Path:
        """Return the low-frequency catalog database path."""
        return self._path

    @property
    def closed(self) -> bool:
        """Return whether the catalog was intentionally closed."""
        return self._closed

    def _migrate(self) -> None:
        with self._conn:
            version = int(
                self._conn.execute("PRAGMA user_version").fetchone()[0],
            )
            if version > _CATALOG_SCHEMA_VERSION:
                raise RuntimeError(
                    f"transcript catalog schema {version} is newer than "
                    f"supported version {_CATALOG_SCHEMA_VERSION}",
                )
            if version == 0:
                self._conn.executescript(
                    """
                    CREATE TABLE transcript_files (
                        session_id       TEXT PRIMARY KEY,
                        user_id          TEXT NOT NULL,
                        channel          TEXT NOT NULL,
                        file_key         TEXT NOT NULL UNIQUE,
                        migration_state  TEXT NOT NULL DEFAULT 'native'
                                         CHECK(migration_state IN (
                                             'native', 'migrating',
                                             'migrated_v3', 'failed'
                                         )),
                        origin           TEXT NOT NULL DEFAULT 'native'
                                         CHECK(origin IN (
                                             'native', 'legacy_v3',
                                             'conversation_branch'
                                         )),
                        parent_session_id TEXT,
                        root_session_id  TEXT,
                        fork_turn_seq    INTEGER,
                        fork_ordinal     INTEGER,
                        source_revision  INTEGER,
                        source_turn_count INTEGER,
                        source_message_count INTEGER,
                        migration_started_at TEXT,
                        migration_finished_at TEXT,
                        migration_error TEXT,
                        created_at       TEXT NOT NULL,
                        updated_at       TEXT NOT NULL,
                        deleted_at       TEXT,
                        purged_at        TEXT
                    );

                    CREATE INDEX transcript_files_deleted
                        ON transcript_files(deleted_at);

                    CREATE TABLE transcript_imports (
                        source_kind      TEXT NOT NULL,
                        source_identity  TEXT NOT NULL,
                        fingerprint      TEXT NOT NULL,
                        schema_version   INTEGER NOT NULL,
                        imported_at      TEXT NOT NULL,
                        result_json      TEXT NOT NULL,
                        PRIMARY KEY(
                            source_kind,
                            source_identity,
                            fingerprint,
                            schema_version
                        )
                    );
                    """,
                )
                version = 2
            if version == 1:
                self._migrate_catalog_v2()
            self._conn.execute(
                f"PRAGMA user_version={_CATALOG_SCHEMA_VERSION}",
            )

    def _migrate_catalog_v2(self) -> None:
        """Add lineage and recoverable migration state to a v1 catalog."""
        self._conn.executescript(
            """
            ALTER TABLE transcript_files RENAME TO transcript_files_v1;

            CREATE TABLE transcript_files (
                session_id       TEXT PRIMARY KEY,
                user_id          TEXT NOT NULL,
                channel          TEXT NOT NULL,
                file_key         TEXT NOT NULL UNIQUE,
                migration_state  TEXT NOT NULL DEFAULT 'native'
                                 CHECK(migration_state IN (
                                     'native', 'migrating',
                                     'migrated_v3', 'failed'
                                 )),
                origin           TEXT NOT NULL DEFAULT 'native'
                                 CHECK(origin IN (
                                     'native', 'legacy_v3',
                                     'conversation_branch'
                                 )),
                parent_session_id TEXT,
                root_session_id  TEXT,
                fork_turn_seq    INTEGER,
                fork_ordinal     INTEGER,
                source_revision  INTEGER,
                source_turn_count INTEGER,
                source_message_count INTEGER,
                migration_started_at TEXT,
                migration_finished_at TEXT,
                migration_error TEXT,
                created_at       TEXT NOT NULL,
                updated_at       TEXT NOT NULL,
                deleted_at       TEXT,
                purged_at        TEXT
            );

            INSERT INTO transcript_files(
                session_id, user_id, channel, file_key, migration_state,
                origin, created_at, updated_at, deleted_at, purged_at
            )
            SELECT session_id, user_id, channel, file_key, migration_state,
                   CASE migration_state
                       WHEN 'migrated_v3' THEN 'legacy_v3'
                       ELSE 'native'
                   END,
                   created_at, updated_at, deleted_at, purged_at
            FROM transcript_files_v1;

            DROP TABLE transcript_files_v1;

            CREATE INDEX transcript_files_deleted
                ON transcript_files(deleted_at);
            """,
        )

    @staticmethod
    def _file_key(
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> str:
        canonical = json.dumps(
            [channel, user_id, session_id],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _store_path(self, file_key: str) -> Path:
        return self._transcript_dir / file_key[:2] / f"{file_key}.db"

    @staticmethod
    def _assert_database_integrity(path: Path) -> None:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            result = connection.execute("PRAGMA quick_check").fetchone()
            if result is None or result[0] != "ok":
                raise RuntimeError(
                    "transcript database integrity check failed",
                )
        finally:
            connection.close()

    def _catalog_row(self, session_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM transcript_files WHERE session_id = ?",
            (session_id,),
        ).fetchone()

    @staticmethod
    def _assert_identity(
        row: sqlite3.Row,
        *,
        user_id: str,
        channel: str,
    ) -> None:
        if row["user_id"] != user_id or row["channel"] != channel:
            raise ValueError("transcript session identity mismatch")

    def _legacy_session(
        self,
        session_id: str,
    ) -> tuple[sqlite3.Connection, sqlite3.Row] | None:
        if not self._legacy_path.is_file():
            return None
        uri = f"file:{self._legacy_path}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT * FROM transcript_sessions WHERE session_id = ? "
                "AND deleted_at IS NULL",
                (session_id,),
            ).fetchone()
        except sqlite3.DatabaseError:
            connection.close()
            return None
        if row is None:
            connection.close()
            return None
        return connection, row

    def _copy_legacy_session(
        self,
        connection: sqlite3.Connection,
        session: sqlite3.Row,
        target: Path,
    ) -> tuple[int, int, int]:
        target.parent.mkdir(parents=True, exist_ok=True)
        session_id = str(session["session_id"])
        turns = connection.execute(
            "SELECT * FROM transcript_turns WHERE session_id = ? "
            "ORDER BY turn_seq",
            (session_id,),
        ).fetchall()
        messages = connection.execute(
            "SELECT * FROM transcript_messages WHERE session_id = ? "
            "ORDER BY turn_id, ordinal",
            (session_id,),
        ).fetchall()
        source_revision = int(session["revision"])
        source_counts = (len(turns), len(messages))
        if target.exists():
            existing: TranscriptStore | None = None
            try:
                existing = TranscriptStore(
                    target,
                    retention_days=0,
                    background_cleanup=False,
                )
                if existing.has_session(session_id):
                    watermark = existing.session_watermark(session_id)
                    expected = (
                        source_revision,
                        source_counts[0],
                        source_counts[1],
                    )
                    if watermark == expected:
                        self._assert_database_integrity(target)
                        return watermark
            except (OSError, sqlite3.DatabaseError, RuntimeError, ValueError):
                logger.warning(
                    "Discarding incomplete migration for session %s",
                    session_id,
                    exc_info=True,
                )
            finally:
                if existing is not None:
                    existing.close()
            self._delete_files(target)

        staging = target.with_name(
            f".{target.name}.{uuid.uuid4().hex}.migrating",
        )
        store = TranscriptStore(
            staging,
            retention_days=0,
            background_cleanup=False,
        )
        try:
            with store._transaction():  # pylint: disable=protected-access
                store._conn.execute(  # pylint: disable=protected-access
                    "INSERT INTO transcript_sessions VALUES "
                    "(:session_id, :user_id, :channel, :revision, "
                    ":next_turn_seq, :completeness, :created_at, "
                    ":updated_at, :deleted_at)",
                    dict(session),
                )
                for row in turns:
                    columns = list(row.keys())
                    placeholders = ", ".join(f":{name}" for name in columns)
                    store._conn.execute(  # pylint: disable=protected-access
                        "INSERT INTO transcript_turns("
                        + ", ".join(columns)
                        + f") VALUES ({placeholders})",
                        dict(row),
                    )
                for row in messages:
                    columns = list(row.keys())
                    placeholders = ", ".join(f":{name}" for name in columns)
                    store._conn.execute(  # pylint: disable=protected-access
                        "INSERT INTO transcript_messages("
                        + ", ".join(columns)
                        + f") VALUES ({placeholders})",
                        dict(row),
                    )
            store._conn.execute(  # pylint: disable=protected-access
                "PRAGMA wal_checkpoint(TRUNCATE)",
            ).fetchone()
        finally:
            store.close()
        os.replace(staging, target)
        self._delete_files(staging)
        copied = TranscriptStore(
            target,
            retention_days=0,
            background_cleanup=False,
        )
        try:
            target_watermark = copied.session_watermark(
                str(session["session_id"]),
            )
            expected = (
                source_revision,
                source_counts[0],
                source_counts[1],
            )
            if target_watermark != expected:
                self._delete_files(target)
                raise RuntimeError(
                    f"transcript migration watermark mismatch: "
                    f"source={expected}, target={target_watermark}",
                )
        finally:
            copied.close()
        self._assert_database_integrity(target)
        return source_revision, source_counts[0], source_counts[1]

    def _ensure_catalog_session(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        create: bool,
    ) -> sqlite3.Row | None:
        if session_id in self._publishing:
            raise ValueError("transcript session is being published")
        row = self._catalog_row(session_id)
        if row is not None:
            self._assert_identity(row, user_id=user_id, channel=channel)
            state = str(row["migration_state"])
            if row["deleted_at"] is not None or state == "failed":
                return None
            path = self._store_path(str(row["file_key"]))
            if state == "native" or (
                state == "migrated_v3" and path.is_file()
            ):
                return row

        legacy = self._legacy_session(session_id)
        if legacy is not None:
            connection, legacy_row = legacy
            try:
                self._assert_identity(
                    legacy_row,
                    user_id=user_id,
                    channel=channel,
                )
                file_key = self._file_key(
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                )
                timestamp = _utc_now()
                with self._conn:
                    self._conn.execute(
                        "INSERT INTO transcript_files("
                        "session_id, user_id, channel, file_key, "
                        "migration_state, origin, migration_started_at, "
                        "created_at, updated_at) VALUES "
                        "(?, ?, ?, ?, 'migrating', 'legacy_v3', ?, ?, ?) "
                        "ON CONFLICT(session_id) DO UPDATE SET "
                        "migration_state = 'migrating', "
                        "migration_started_at = excluded.updated_at, "
                        "migration_error = NULL, "
                        "updated_at = excluded.updated_at",
                        (
                            session_id,
                            user_id,
                            channel,
                            file_key,
                            timestamp,
                            timestamp,
                            timestamp,
                        ),
                    )
                watermark = self._copy_legacy_session(
                    connection,
                    legacy_row,
                    self._store_path(file_key),
                )
                finished_at = _utc_now()
                with self._conn:
                    self._conn.execute(
                        "UPDATE transcript_files SET "
                        "migration_state = 'migrated_v3', "
                        "source_revision = ?, source_turn_count = ?, "
                        "source_message_count = ?, "
                        "migration_finished_at = ?, updated_at = ? "
                        "WHERE session_id = ?",
                        (
                            *watermark,
                            finished_at,
                            finished_at,
                            session_id,
                        ),
                    )
            except Exception as exc:
                failed_at = _utc_now()
                with self._conn:
                    self._conn.execute(
                        "UPDATE transcript_files SET "
                        "migration_state = 'failed', "
                        "migration_error = ?, updated_at = ? "
                        "WHERE session_id = ?",
                        (str(exc)[:2_000], failed_at, session_id),
                    )
                logger.warning(
                    "Transcript migration failed for session %s",
                    session_id,
                    exc_info=True,
                )
                if create:
                    raise
                return None
            finally:
                connection.close()
            return self._catalog_row(session_id)

        if row is not None or not create:
            return None
        file_key = self._file_key(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        target = self._store_path(file_key)
        if target.exists():
            logger.warning(
                "Removing orphan transcript file for session %s",
                session_id,
            )
            self._delete_files(target)
        timestamp = _utc_now()
        with self._conn:
            self._conn.execute(
                "INSERT INTO transcript_files("
                "session_id, user_id, channel, file_key, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    user_id,
                    channel,
                    file_key,
                    timestamp,
                    timestamp,
                ),
            )
        return self._catalog_row(session_id)

    def _close_handles(self, handles: list[_SessionHandle]) -> None:
        for handle in handles:
            handle.close()

    def _evict_idle_locked(self) -> list[_SessionHandle]:
        evicted: list[_SessionHandle] = []
        while len(self._handles) > self._max_open_stores:
            candidate_id = next(
                (
                    session_id
                    for session_id, handle in self._handles.items()
                    if handle.active == 0 and not handle.pending_delete
                ),
                None,
            )
            if candidate_id is None:
                break
            evicted.append(self._handles.pop(candidate_id))
        return evicted

    @contextmanager
    def _lease(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        create: bool,
    ) -> Iterator[_SessionHandle | None]:
        evicted: list[_SessionHandle] = []
        with self._condition:
            if self._closed:
                raise RuntimeError("transcript catalog is closed")
            row = self._ensure_catalog_session(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                create=create,
            )
            if row is None:
                yield None
                return
            handle = self._handles.get(session_id)
            if handle is None:
                path = self._store_path(str(row["file_key"]))
                path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    store = TranscriptStore(
                        path,
                        retention_days=self._retention_days,
                        background_cleanup=False,
                    )
                except (OSError, sqlite3.DatabaseError, RuntimeError):
                    if row["migration_state"] != "migrated_v3":
                        raise
                    logger.warning(
                        "Recovering migrated transcript for session %s",
                        session_id,
                        exc_info=True,
                    )
                    self._delete_files(path)
                    with self._conn:
                        self._conn.execute(
                            "UPDATE transcript_files SET "
                            "migration_state = 'migrating', "
                            "updated_at = ? WHERE session_id = ?",
                            (_utc_now(), session_id),
                        )
                    recovered = self._ensure_catalog_session(
                        session_id=session_id,
                        user_id=user_id,
                        channel=channel,
                        create=create,
                    )
                    if recovered is None:
                        yield None
                        return
                    store = TranscriptStore(
                        path,
                        retention_days=self._retention_days,
                        background_cleanup=False,
                    )
                handle = _SessionHandle(store)
                self._handles[session_id] = handle
            else:
                self._handles.move_to_end(session_id)
            handle.active += 1
            evicted = self._evict_idle_locked()
        self._close_handles(evicted)
        try:
            yield handle
        finally:
            with self._condition:
                handle.active -= 1
                self._condition.notify_all()
                evicted = self._evict_idle_locked()
            self._close_handles(evicted)

    def _identity_for_session(self, session_id: str) -> tuple[str, str] | None:
        with self._lock:
            row = self._catalog_row(session_id)
            if row is not None:
                if row["deleted_at"] is None:
                    return str(row["user_id"]), str(row["channel"])
                return None
            legacy = self._legacy_session(session_id)
            if legacy is None:
                return None
            connection, legacy_row = legacy
            try:
                return str(legacy_row["user_id"]), str(legacy_row["channel"])
            finally:
                connection.close()

    def start_turn(self, **kwargs: Any) -> int:
        """Create a turn in its session-owned database."""
        with self._lease(
            session_id=kwargs["session_id"],
            user_id=kwargs["user_id"],
            channel=kwargs["channel"],
            create=True,
        ) as handle:
            assert handle is not None
            return int(handle.write("start_turn", **kwargs))

    def import_history_if_missing(self, **kwargs: Any) -> bool:
        """Import one session into its independent database."""
        with self._lease(
            session_id=kwargs["session_id"],
            user_id=kwargs["user_id"],
            channel=kwargs["channel"],
            create=True,
        ) as handle:
            assert handle is not None
            return bool(handle.write("import_history_if_missing", **kwargs))

    def _write_existing(self, method_name: str, **kwargs: Any) -> Any:
        session_id = str(kwargs["session_id"])
        identity = self._identity_for_session(session_id)
        if identity is None:
            raise ValueError("transcript session does not exist")
        user_id, channel = identity
        with self._lease(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            create=False,
        ) as handle:
            if handle is None:
                raise ValueError("transcript session does not exist")
            return handle.write(method_name, **kwargs)

    def upsert_message(self, **kwargs: Any) -> int:
        return int(self._write_existing("upsert_message", **kwargs))

    def finish_turn(self, **kwargs: Any) -> int:
        return int(self._write_existing("finish_turn", **kwargs))

    def attach_turn_usage(self, **kwargs: Any) -> int | None:
        value = self._write_existing("attach_turn_usage", **kwargs)
        return int(value) if value is not None else None

    def get_page(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        before: TranscriptCursor | int | None = None,
        limit: int = 50,
        max_bytes: int = 512 * 1024,
    ) -> TranscriptPage | None:
        """Read one page without holding a workspace-wide message lock."""
        with self._lease(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            create=False,
        ) as handle:
            if handle is None:
                return None
            return handle.store.get_page(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                before=before,
                limit=limit,
                max_bytes=max_bytes,
            )

    def fork_session(
        self,
        *,
        parent_session_id: str,
        child_session_id: str,
        child_user_id: str,
        child_channel: str,
        anchor: TranscriptCursor | None = None,
    ) -> TranscriptCursor | None:
        """Publish a conversation branch without invoking subagent fork."""
        parent_identity = self._identity_for_session(parent_session_id)
        if parent_identity is None:
            raise ValueError("parent transcript session does not exist")
        with self._condition:
            if self._catalog_row(child_session_id) is not None:
                raise ValueError("child transcript session already exists")
            if self._legacy_session(child_session_id) is not None:
                raise ValueError("child transcript session already exists")
            if child_session_id in self._publishing:
                raise ValueError("child transcript session is being published")
            self._publishing.add(child_session_id)

        file_key = self._file_key(
            session_id=child_session_id,
            user_id=child_user_id,
            channel=child_channel,
        )
        target = self._store_path(file_key)
        staging = target.with_name(
            f".{target.name}.{uuid.uuid4().hex}.forking",
        )
        try:
            with self._lease(
                session_id=parent_session_id,
                user_id=parent_identity[0],
                channel=parent_identity[1],
                create=False,
            ) as parent:
                if parent is None:
                    raise ValueError(
                        "parent transcript session does not exist",
                    )
                result = parent.write(
                    "fork_snapshot",
                    parent_session_id=parent_session_id,
                    child_session_id=child_session_id,
                    child_user_id=child_user_id,
                    child_channel=child_channel,
                    target_path=staging,
                    anchor=anchor,
                )
            resolved_anchor, turn_count, message_count = result
            self._assert_database_integrity(staging)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, target)
            self._delete_files(staging)
            timestamp = _utc_now()
            with self._condition, self._conn:
                parent_row = self._catalog_row(parent_session_id)
                parent_root = None
                if parent_row is not None:
                    parent_root = parent_row["root_session_id"]
                root_session_id = str(parent_root or parent_session_id)
                self._conn.execute(
                    "INSERT INTO transcript_files("
                    "session_id, user_id, channel, file_key, "
                    "migration_state, origin, parent_session_id, "
                    "root_session_id, fork_turn_seq, fork_ordinal, "
                    "source_turn_count, source_message_count, "
                    "created_at, updated_at) VALUES "
                    "(?, ?, ?, ?, 'native', 'conversation_branch', "
                    "?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        child_session_id,
                        child_user_id,
                        child_channel,
                        file_key,
                        parent_session_id,
                        root_session_id,
                        (
                            resolved_anchor.turn_seq
                            if resolved_anchor is not None
                            else None
                        ),
                        (
                            resolved_anchor.ordinal
                            if resolved_anchor is not None
                            else None
                        ),
                        turn_count,
                        message_count,
                        timestamp,
                        timestamp,
                    ),
                )
            return resolved_anchor
        except BaseException:
            self._delete_files(staging)
            if self._catalog_row(child_session_id) is None:
                self._delete_files(target)
            raise
        finally:
            with self._condition:
                self._publishing.discard(child_session_id)
                self._condition.notify_all()

    def find_turn_for_message(self, **kwargs: Any) -> str | None:
        session_id = str(kwargs["session_id"])
        identity = self._identity_for_session(session_id)
        if identity is None:
            return None
        with self._lease(
            session_id=session_id,
            user_id=identity[0],
            channel=identity[1],
            create=False,
        ) as handle:
            if handle is None:
                return None
            return handle.store.find_turn_for_message(**kwargs)

    def has_session(self, session_id: str) -> bool:
        """Return whether an active catalog or legacy session exists."""
        return self._identity_for_session(session_id) is not None

    def purge_if_due(
        self,
        *,
        session_id: str | None = None,
        now: datetime | None = None,
    ) -> int:
        """Apply retention only to the session touched by the current turn."""
        if session_id is None:
            return 0
        identity = self._identity_for_session(session_id)
        if identity is None:
            return 0
        with self._lease(
            session_id=session_id,
            user_id=identity[0],
            channel=identity[1],
            create=False,
        ) as handle:
            if handle is None:
                return 0
            return int(handle.write("purge_if_due", now=now))

    def has_import(
        self,
        *,
        source_kind: str,
        source_identity: str,
        fingerprint: str,
        schema_version: int,
    ) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM transcript_imports WHERE source_kind = ? "
                "AND source_identity = ? AND fingerprint = ? "
                "AND schema_version = ?",
                (
                    source_kind,
                    source_identity,
                    fingerprint,
                    schema_version,
                ),
            ).fetchone()
            return row is not None

    def record_import(
        self,
        *,
        source_kind: str,
        source_identity: str,
        fingerprint: str,
        schema_version: int,
        result: dict[str, Any],
    ) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT INTO transcript_imports("
                "source_kind, source_identity, fingerprint, schema_version, "
                "imported_at, result_json) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT DO NOTHING",
                (
                    source_kind,
                    source_identity,
                    fingerprint,
                    schema_version,
                    _utc_now(),
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                ),
            )
            return bool(cursor.rowcount)

    def mark_session_deleted(self, session_id: str) -> bool:
        """Persist a catalog tombstone before any physical deletion."""
        with self._condition, self._conn:
            row = self._catalog_row(session_id)
            if row is None:
                identity = self._identity_for_session(session_id)
                if identity is None:
                    return False
                row = self._ensure_catalog_session(
                    session_id=session_id,
                    user_id=identity[0],
                    channel=identity[1],
                    create=False,
                )
            if row is None or row["deleted_at"] is not None:
                return False
            timestamp = _utc_now()
            self._conn.execute(
                "UPDATE transcript_files SET deleted_at = ?, updated_at = ? "
                "WHERE session_id = ?",
                (timestamp, timestamp, session_id),
            )
            handle = self._handles.get(session_id)
            if handle is not None:
                handle.pending_delete = True
            return True

    def _delete_files(self, path: Path) -> None:
        for candidate in (
            path,
            path.with_name(path.name + "-wal"),
            path.with_name(path.name + "-shm"),
        ):
            candidate.unlink(missing_ok=True)

    def _purge_deleted_session(self, session_id: str) -> bool:
        with self._condition:
            row = self._catalog_row(session_id)
            if row is None:
                return False
            deleted = row["deleted_at"] is not None
            pending = deleted and row["purged_at"] is None
            if not pending:
                return False
            handle = self._handles.get(session_id)
            while handle is not None and handle.active > 0:
                self._condition.wait()
                handle = self._handles.get(session_id)
            if handle is not None:
                self._handles.pop(session_id, None)
            path = self._store_path(str(row["file_key"]))
        if handle is not None:
            handle.close()
        self._delete_files(path)
        with self._condition, self._conn:
            timestamp = _utc_now()
            cursor = self._conn.execute(
                "UPDATE transcript_files SET purged_at = ?, updated_at = ? "
                "WHERE session_id = ? AND deleted_at IS NOT NULL "
                "AND purged_at IS NULL",
                (timestamp, timestamp, session_id),
            )
            self._condition.notify_all()
            return bool(cursor.rowcount)

    def _submit_cleanup(
        self,
        session_id: str,
    ) -> concurrent.futures.Future[bool] | None:
        with self._lock:
            if self._closed:
                return None
            future = self._cleanup_executor.submit(
                self._purge_deleted_session,
                session_id,
            )

        def _log_failure(
            completed: concurrent.futures.Future[bool],
        ) -> None:
            try:
                completed.result()
            except Exception:
                logger.warning(
                    "Transcript catalog cleanup failed for session %s",
                    session_id,
                    exc_info=True,
                )

        future.add_done_callback(_log_failure)
        return future

    def schedule_delete_session(self, session_id: str) -> bool:
        """Hide a session immediately and remove its files asynchronously."""
        if not self.mark_session_deleted(session_id):
            return False
        self._submit_cleanup(session_id)
        return True

    def delete_session(self, session_id: str) -> bool:
        """Hide and synchronously remove one session transcript."""
        if not self.mark_session_deleted(session_id):
            return False
        return self._purge_deleted_session(session_id)

    def _resume_deleted_cleanup(self) -> None:
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id FROM transcript_files "
                "WHERE deleted_at IS NOT NULL AND purged_at IS NULL",
            ).fetchall()
        for row in rows:
            self._submit_cleanup(str(row["session_id"]))

    def close(self) -> None:
        """Stop cleanup and close all per-session stores and the catalog."""
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()
        self._cleanup_executor.shutdown(wait=True)
        with self._condition:
            while any(handle.active > 0 for handle in self._handles.values()):
                self._condition.wait()
            handles = list(self._handles.values())
            self._handles.clear()
        self._close_handles(handles)
        with self._lock:
            self._conn.close()


__all__ = ["TranscriptCatalog"]
