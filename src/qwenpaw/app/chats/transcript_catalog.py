# -*- coding: utf-8 -*-
"""Workspace catalog and per-session durable transcript stores."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .transcript import TranscriptCursor, TranscriptPage, TranscriptStore

logger = logging.getLogger(__name__)

_BUSY_TIMEOUT_MS = 5_000
_DEFAULT_MAX_OPEN_STORES = 32


class _SessionHandle:
    """One session store with lease accounting."""

    def __init__(self, store: TranscriptStore) -> None:
        self.store = store
        self.active = 0

    def write(self, method_name: str, **kwargs: Any) -> Any:
        """Run one mutation under the store's per-session lock."""
        method = getattr(self.store, method_name)
        return method(**kwargs)

    def close(self) -> None:
        """Close the session database."""
        self.store.close()


class TranscriptCatalog:
    """Route transcript operations to independent per-session databases."""

    def __init__(
        self,
        workspace_dir: str | Path,
        max_open_stores: int = _DEFAULT_MAX_OPEN_STORES,
    ) -> None:
        if max_open_stores < 1:
            raise ValueError("max_open_stores must be positive")
        self._workspace_dir = Path(workspace_dir).expanduser()
        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._workspace_dir / "transcript_catalog.db"
        self._transcript_dir = self._workspace_dir / "transcripts"
        self._transcript_dir.mkdir(parents=True, exist_ok=True)
        self._max_open_stores = max_open_stores
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._closed = False
        self._handles: OrderedDict[str, _SessionHandle] = OrderedDict()
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
                    if handle.active == 0
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
                store = TranscriptStore(path)
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
            assert handle is not None
            handle.write("start_turn", **kwargs)

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

    def upsert_message(self, **kwargs: Any) -> None:
        self._write_existing("upsert_message", **kwargs)

    def finish_turn(self, **kwargs: Any) -> None:
        self._write_existing("finish_turn", **kwargs)

    def attach_turn_usage(self, **kwargs: Any) -> bool:
        return bool(self._write_existing("attach_turn_usage", **kwargs))

    def get_page(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        before: TranscriptCursor | None = None,
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
        self._close_handles(handles)
        with self._lock:
            self._conn.close()


__all__ = ["TranscriptCatalog"]
