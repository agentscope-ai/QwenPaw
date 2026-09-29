# -*- coding: utf-8 -*-
"""Workspace catalog and per-session durable transcript stores."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .transcript import (
    RuntimeSnapshot,
    TranscriptCursor,
    TranscriptPage,
    TranscriptStore,
)

logger = logging.getLogger(__name__)

_BUSY_TIMEOUT_MS = 5_000


class _SessionHandle:
    """One session store with lease accounting."""

    def __init__(self, store: TranscriptStore) -> None:
        self.store = store
        self.active = 0
        self.running_turns: set[str] = set()

    def close(self) -> None:
        """Close the session database."""
        self.store.close()


class TranscriptCatalog:
    """Route transcript operations to independent per-session databases."""

    def __init__(
        self,
        workspace_dir: str | Path,
        *,
        recover_orphaned_turns: bool = True,
    ) -> None:
        self._workspace_dir = Path(workspace_dir).expanduser()
        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._workspace_dir / "transcript_catalog.db"
        self._transcript_dir = self._workspace_dir / "transcripts"
        self._transcript_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._closed = False
        self._recover_orphaned_turns = recover_orphaned_turns
        self._handles: dict[str, _SessionHandle] = {}
        self._conn = sqlite3.connect(
            str(self._path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        self._conn.execute("PRAGMA journal_mode=DELETE")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS transcript_files (
                    session_id       TEXT PRIMARY KEY,
                    user_id          TEXT NOT NULL,
                    channel          TEXT NOT NULL,
                    file_key         TEXT NOT NULL UNIQUE
                );

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

    def _ensure_catalog_session(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        create: bool,
    ) -> sqlite3.Row | None:
        row = self._catalog_row(session_id)
        if row is not None:
            self._assert_identity(row, user_id=user_id, channel=channel)
            return row

        if not create:
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
            target.unlink()
        with self._conn:
            self._conn.execute(
                "INSERT INTO transcript_files("
                "session_id, user_id, channel, file_key) "
                "VALUES (?, ?, ?, ?)",
                (
                    session_id,
                    user_id,
                    channel,
                    file_key,
                ),
            )
        return self._catalog_row(session_id)

    @contextmanager
    def _lease(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        create: bool,
    ) -> Iterator[_SessionHandle | None]:
        handle: _SessionHandle | None = None
        with self._condition:
            if self._closed:
                raise RuntimeError("transcript catalog is closed")
            row = self._ensure_catalog_session(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                create=create,
            )
            if row is not None:
                handle = self._handles.get(session_id)
                if handle is None:
                    path = self._store_path(str(row["file_key"]))
                    path.parent.mkdir(parents=True, exist_ok=True)
                    handle = _SessionHandle(
                        TranscriptStore(
                            path,
                            initialize_schema=not path.exists(),
                        ),
                    )
                    if self._recover_orphaned_turns:
                        handle.store.recover_running_turns()
                    self._handles[session_id] = handle
                handle.active += 1
        if handle is None:
            yield None
            return
        try:
            yield handle
        finally:
            with self._condition:
                handle.active -= 1
                if handle.active == 0 and not handle.running_turns:
                    self._handles.pop(session_id, None)
                    handle.close()
                self._condition.notify_all()

    def _release_turn(self, session_id: str, turn_id: str) -> None:
        with self._condition:
            handle = self._handles.get(session_id)
            if handle is None:
                return
            handle.running_turns.discard(turn_id)
            if handle.active == 0 and not handle.running_turns:
                self._handles.pop(session_id, None)
                handle.close()
            self._condition.notify_all()

    def _identity_for_session(self, session_id: str) -> tuple[str, str] | None:
        with self._lock:
            row = self._catalog_row(session_id)
            if row is not None:
                return str(row["user_id"]), str(row["channel"])
            return None

    def start_turn(self, **kwargs: Any) -> None:
        """Create a turn in its session-owned database."""
        with self._lease(
            session_id=kwargs["session_id"],
            user_id=kwargs["user_id"],
            channel=kwargs["channel"],
            create=True,
        ) as handle:
            if handle is None:
                raise RuntimeError("failed to create transcript session")
            handle.store.start_turn(**kwargs)
            with self._condition:
                handle.running_turns.add(str(kwargs["turn_id"]))

    def has_session(self, **kwargs: Any) -> bool:
        """Return whether a durable transcript session already exists."""
        with self._lease(create=False, **kwargs) as handle:
            if handle is None:
                return False
            return handle.store.has_session(**kwargs)

    def import_legacy_messages(self, **kwargs: Any) -> bool:
        """Seed a new session database from legacy display history."""
        with self._lease(
            session_id=kwargs["session_id"],
            user_id=kwargs["user_id"],
            channel=kwargs["channel"],
            create=True,
        ) as handle:
            if handle is None:
                raise RuntimeError("failed to create transcript session")
            return handle.store.import_legacy_messages(**kwargs)

    def read_runtime_state(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> RuntimeSnapshot | None:
        """Read one session's authoritative runtime snapshot."""
        with self._lease(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            create=False,
        ) as handle:
            if handle is None:
                return None
            return handle.store.read_runtime_state(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            )

    def write_runtime_state(self, **kwargs: Any) -> tuple[int, bool]:
        """Persist one session's runtime snapshot."""
        with self._lease(
            session_id=kwargs["session_id"],
            user_id=kwargs["user_id"],
            channel=kwargs["channel"],
            create=True,
        ) as handle:
            if handle is None:
                raise RuntimeError("failed to create runtime session")
            return handle.store.write_runtime_state(**kwargs)

    def update_runtime_state(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        path: list[str],
        value: Any,
        create_if_missing: bool,
    ) -> None:
        """Update one nested runtime value under the session lock."""
        with self._lease(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            create=create_if_missing,
        ) as handle:
            if handle is None:
                raise KeyError(session_id)
            try:
                handle.store.update_runtime_state(
                    session_id=session_id,
                    path=path,
                    value=value,
                )
            except KeyError:
                if not create_if_missing:
                    raise
                handle.store.write_runtime_state(
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                    state={},
                )
                handle.store.update_runtime_state(
                    session_id=session_id,
                    path=path,
                    value=value,
                )

    def replace_runtime_state(self, **kwargs: Any) -> None:
        """Replace one session's runtime snapshot exactly."""
        with self._lease(
            session_id=kwargs["session_id"],
            user_id=kwargs["user_id"],
            channel=kwargs["channel"],
            create=True,
        ) as handle:
            if handle is None:
                raise RuntimeError("failed to create runtime session")
            handle.store.replace_runtime_state(**kwargs)

    def set_current_usage(self, **kwargs: Any) -> None:
        """Update the current context projection for one session."""
        self._write_existing("set_current_usage", **kwargs)

    def export_session_database(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> bytes:
        """Export one session database for a checkpoint."""
        with self._lease(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            create=False,
        ) as handle:
            if handle is None:
                raise KeyError(session_id)
            return handle.store.export_database(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            )

    def restore_session_database(
        self,
        blob: bytes,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> None:
        """Restore one session database from a checkpoint."""
        with self._lease(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            create=False,
        ) as handle:
            if handle is None:
                raise KeyError(session_id)
            handle.store.restore_database(
                blob,
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            )

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
            method = getattr(handle.store, method_name)
            try:
                return method(**kwargs)
            except BaseException:
                turn_id = kwargs.get("turn_id")
                if turn_id is not None:
                    self._release_turn(session_id, str(turn_id))
                raise

    def upsert_message(self, **kwargs: Any) -> None:
        self._write_existing("upsert_message", **kwargs)

    def finish_turn(self, **kwargs: Any) -> None:
        self._write_existing("finish_turn", **kwargs)
        self._release_turn(
            str(kwargs["session_id"]),
            str(kwargs["turn_id"]),
        )

    def attach_turn_usage(self, **kwargs: Any) -> bool:
        return bool(self._write_existing("attach_turn_usage", **kwargs))

    def get_page(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        before: TranscriptCursor | None = None,
        limit: int = 20,
        max_bytes: int = 2 * 1024 * 1024,
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

    def clone_session(
        self,
        *,
        source_session_id: str,
        source_user_id: str,
        source_channel: str,
        target_session_id: str,
        target_user_id: str,
        target_channel: str,
    ) -> bool:
        """Clone completed history and agent runtime into a new session."""
        with self._lock:
            target_existed = self._catalog_row(target_session_id) is not None
        try:
            with self._lease(
                session_id=source_session_id,
                user_id=source_user_id,
                channel=source_channel,
                create=False,
            ) as source:
                if source is None:
                    return False
                with self._lease(
                    session_id=target_session_id,
                    user_id=target_user_id,
                    channel=target_channel,
                    create=True,
                ) as target:
                    if target is None:
                        raise RuntimeError("failed to create fork session")
                    return target.store.clone_completed_session_from(
                        source_path=source.store.path,
                        source_session_id=source_session_id,
                        target_session_id=target_session_id,
                        target_user_id=target_user_id,
                        target_channel=target_channel,
                    )
        except BaseException:
            if not target_existed:
                self.delete_session(target_session_id)
            raise

    def session_message_payloads(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> list[tuple[str, str, list[dict[str, Any]]]]:
        """Return persisted messages grouped by session and channel."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id, user_id, channel "
                "FROM transcript_files ORDER BY session_id",
            ).fetchall()
        result: list[tuple[str, str, list[dict[str, Any]]]] = []
        for row in rows:
            session_id = str(row["session_id"])
            with self._lease(
                session_id=session_id,
                user_id=str(row["user_id"]),
                channel=str(row["channel"]),
                create=False,
            ) as handle:
                if handle is None:
                    continue
                messages = handle.store.message_payloads(
                    session_id=session_id,
                    start_date=start_date,
                    end_date=end_date,
                )
            if messages:
                result.append((session_id, str(row["channel"]), messages))
        return result

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

    def delete_session(self, session_id: str) -> bool:
        """Close and delete one session-owned database."""
        with self._condition:
            row = self._catalog_row(session_id)
            if row is None:
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
            with self._conn:
                self._conn.execute(
                    "DELETE FROM transcript_files WHERE session_id = ?",
                    (session_id,),
                )
            path.unlink(missing_ok=True)
            self._condition.notify_all()
            return True

    def close(self) -> None:
        """Close all per-session stores and the catalog."""
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()
            while any(handle.active > 0 for handle in self._handles.values()):
                self._condition.wait()
            handles = list(self._handles.values())
            self._handles.clear()
        for handle in handles:
            handle.close()
        with self._lock:
            self._conn.close()


__all__ = ["TranscriptCatalog"]
