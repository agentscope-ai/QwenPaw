# -*- coding: utf-8 -*-
"""Workspace catalog and per-session durable transcript stores."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from .transcript import (
    RuntimeSnapshot,
    TranscriptCursor,
    TranscriptPage,
    TranscriptStore,
    TranscriptUserMessagePage,
)

logger = logging.getLogger(__name__)

_BUSY_TIMEOUT_MS = 5_000


def resolve_session_database_path(
    workspace_dir: str | Path,
    *,
    session_id: str,
    user_id: str,
    channel: str,
) -> Path | None:
    """Resolve one exact conversation identity without creating storage."""
    workspace = Path(workspace_dir).expanduser()
    catalog_path = workspace / "transcript_catalog.db"
    if not catalog_path.is_file():
        return None
    uri = f"{catalog_path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        row = connection.execute(
            "SELECT storage_id FROM transcript_files "
            "WHERE session_id = ? AND user_id = ? AND channel = ?",
            (session_id, user_id, channel),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    path = workspace / "transcripts" / f"{row[0]}.db"
    return path if path.is_file() else None


class _SessionHandle:
    """One session store with lease accounting."""

    def __init__(self, store: TranscriptStore) -> None:
        self.store = store
        self.active = 0
        self.running_turns: set[str] = set()

    def close(self) -> None:
        """Close the session database."""
        self.store.close()


# pylint: disable=too-many-public-methods
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
        self._rebuild_from_chats()

    def _create_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS transcript_files (
                    storage_id       TEXT PRIMARY KEY,
                    session_id       TEXT NOT NULL,
                    user_id          TEXT NOT NULL,
                    channel          TEXT NOT NULL,
                    UNIQUE(channel, user_id, session_id)
                );
                PRAGMA user_version=1;
                """,
            )
        columns = {
            str(row[1])
            for row in self._conn.execute(
                "PRAGMA table_info(transcript_files)",
            ).fetchall()
        }
        expected = {"storage_id", "session_id", "user_id", "channel"}
        if columns != expected:
            raise ValueError("unsupported transcript catalog schema")

    def _store_path(self, storage_id: str) -> Path:
        return self._transcript_dir / f"{storage_id}.db"

    def _rebuild_from_chats(self) -> None:
        """Rebuild missing catalog rows from chats.json and DB identity."""
        path = self._workspace_dir / "chats.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return
        for chat in raw.get("chats", []):
            if not isinstance(chat, dict):
                continue
            storage_id = chat.get("storage_id")
            session_id = chat.get("session_id")
            user_id = chat.get("user_id")
            channel = chat.get("channel")
            if not (
                isinstance(storage_id, str)
                and storage_id
                and isinstance(session_id, str)
                and session_id
                and isinstance(user_id, str)
                and user_id
                and isinstance(channel, str)
                and channel
            ):
                continue
            db_path = self._store_path(storage_id)
            if not db_path.is_file():
                continue
            store = TranscriptStore(db_path, storage_id=storage_id)
            try:
                if not store.has_session(
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                ):
                    raise ValueError("chat database identity mismatch")
            finally:
                store.close()
            with self._conn:
                self._conn.execute(
                    "INSERT INTO transcript_files("
                    "storage_id, session_id, user_id, channel) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(storage_id) DO UPDATE SET "
                    "session_id = excluded.session_id, "
                    "user_id = excluded.user_id, channel = excluded.channel",
                    (storage_id, session_id, user_id, channel),
                )

    def _catalog_row(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM transcript_files WHERE session_id = ? "
            "AND user_id = ? AND channel = ?",
            (session_id, user_id, channel),
        ).fetchone()

    def _chat_storage_id(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> str | None:
        path = self._workspace_dir / "chats.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        for chat in raw.get("chats", []):
            if not isinstance(chat, dict):
                continue
            if (
                chat.get("session_id") == session_id
                and chat.get("user_id") == user_id
                and chat.get("channel") == channel
            ):
                value = chat.get("storage_id")
                if not value:
                    raise ValueError("chat storage_id is missing")
                return str(value)
        return None

    def _ensure_catalog_session(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        create: bool,
        storage_id: str | None = None,
    ) -> sqlite3.Row | None:
        row = self._catalog_row(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        if row is not None:
            return row

        if not create:
            return None
        storage_id = (
            storage_id
            or self._chat_storage_id(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            )
            or str(uuid4())
        )
        target = self._store_path(storage_id)
        if target.exists():
            store = TranscriptStore(target, storage_id=storage_id)
            try:
                if not store.has_session(
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                ):
                    raise ValueError("orphan transcript identity mismatch")
            finally:
                store.close()
        with self._conn:
            self._conn.execute(
                "INSERT INTO transcript_files("
                "session_id, user_id, channel, storage_id) "
                "VALUES (?, ?, ?, ?)",
                (
                    session_id,
                    user_id,
                    channel,
                    storage_id,
                ),
            )
        return self._catalog_row(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )

    @contextmanager
    def _lease(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        create: bool,
        storage_id: str | None = None,
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
                storage_id=storage_id,
            )
            if row is not None:
                storage_id = str(row["storage_id"])
                handle = self._handles.get(storage_id)
                if handle is None:
                    path = self._store_path(storage_id)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    handle = _SessionHandle(
                        TranscriptStore(
                            path,
                            storage_id=storage_id,
                        ),
                    )
                    if self._recover_orphaned_turns:
                        handle.store.recover_running_turns()
                    self._handles[storage_id] = handle
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
                    if storage_id is not None:
                        self._handles.pop(storage_id, None)
                    handle.close()
                self._condition.notify_all()

    def _resolve_catalog_row(
        self,
        *,
        session_id: str,
        user_id: str | None = None,
        channel: str | None = None,
    ) -> sqlite3.Row | None:
        if user_id is not None and channel is not None:
            return self._catalog_row(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            )
        rows = self._conn.execute(
            "SELECT * FROM transcript_files WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        if len(rows) > 1:
            raise ValueError("ambiguous transcript session identity")
        return rows[0] if rows else None

    def _release_turn(
        self,
        session_id: str,
        turn_id: str,
        *,
        user_id: str | None = None,
        channel: str | None = None,
    ) -> None:
        with self._condition:
            row = self._resolve_catalog_row(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            )
            if row is None:
                return
            storage_id = str(row["storage_id"])
            handle = self._handles.get(storage_id)
            if handle is None:
                return
            handle.running_turns.discard(turn_id)
            if handle.active == 0 and not handle.running_turns:
                self._handles.pop(storage_id, None)
                handle.close()
            self._condition.notify_all()

    def _identity_for_session(
        self,
        session_id: str,
        *,
        user_id: str | None = None,
        channel: str | None = None,
    ) -> tuple[str, str] | None:
        with self._lock:
            row = self._resolve_catalog_row(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            )
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

    def read_provider_state(self, **identity: Any) -> dict[str, Any]:
        """Read native session and Turn bindings for one conversation."""
        with self._lease(create=False, **identity) as handle:
            if handle is None:
                return {
                    "binding": None,
                    "boundaries": {},
                    "has_history": False,
                }
            return handle.store.read_provider_state(
                session_id=identity["session_id"],
            )

    def read_legacy_turn_blocks(self, **identity: Any) -> dict:
        """Read imported turns under the conversation identity lease."""
        with self._lease(create=False, **identity) as handle:
            if handle is None:
                return {}
            return handle.store.read_legacy_turn_blocks(
                session_id=identity["session_id"],
            )

    def record_provider_fact(
        self,
        *,
        kind: str,
        data: dict[str, Any],
        turn_id: str | None = None,
        **identity: Any,
    ) -> None:
        """Persist provider facts in the session-owned event database."""
        with self._lease(create=False, **identity) as handle:
            if handle is None:
                raise ValueError("provider conversation database is missing")
            handle.store.record_provider_fact(
                session_id=identity["session_id"],
                kind=kind,
                data=data,
                turn_id=turn_id,
            )

    def has_session(self, **kwargs: Any) -> bool:
        """Return whether a durable transcript session already exists."""
        with self._lease(create=False, **kwargs) as handle:
            if handle is None:
                return False
            return handle.store.has_session(**kwargs)

    def storage_id_for(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> str:
        """Return the immutable physical identity for a logical session."""
        with self._lock:
            row = self._catalog_row(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            )
            if row is None:
                raise KeyError(session_id)
            return str(row["storage_id"])

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

    def ensure_session_database(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> None:
        """Create the empty destination before legacy Recall import."""
        with self._lease(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            create=True,
        ):
            pass

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

    def read_current_usage(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> tuple[int, dict[str, Any] | None] | None:
        """Read context usage without decoding the runtime state."""
        with self._lease(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            create=False,
        ) as handle:
            if handle is None:
                return None
            return handle.store.read_current_usage(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            )

    def record_legacy_migration(self, **kwargs: Any) -> bool:
        """Record migration progress under the conversation lease."""
        with self._lease(
            session_id=kwargs["session_id"],
            user_id=kwargs["user_id"],
            channel=kwargs["channel"],
            create=True,
        ) as handle:
            if handle is None:
                raise RuntimeError("failed to create migration session")
            return handle.store.record_legacy_migration(**kwargs)

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

    def read_turn_context(self, **kwargs: Any) -> RuntimeSnapshot | None:
        """Read a committed turn context under the session identity lease."""
        with self._lease(
            session_id=kwargs["session_id"],
            user_id=kwargs["user_id"],
            channel=kwargs["channel"],
            create=False,
        ) as handle:
            if handle is None:
                return None
            return handle.store.read_turn_context(**kwargs)

    def update_runtime_state(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        path: list[str],
        value: Any,
        create_if_missing: bool,
        delete: bool = False,
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
                    delete=delete,
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
                    delete=delete,
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
        route_user = kwargs.pop("user_id", None)
        route_channel = kwargs.pop("channel", None)
        identity = self._identity_for_session(
            session_id,
            user_id=route_user,
            channel=route_channel,
        )
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
                    self._release_turn(
                        session_id,
                        str(turn_id),
                        user_id=user_id,
                        channel=channel,
                    )
                raise

    def upsert_message(self, **kwargs: Any) -> None:
        self._write_existing("upsert_message", **kwargs)

    def finish_turn(self, **kwargs: Any) -> None:
        self._write_existing("finish_turn", **kwargs)
        self._release_turn(
            str(kwargs["session_id"]),
            str(kwargs["turn_id"]),
            user_id=kwargs.get("user_id"),
            channel=kwargs.get("channel"),
        )

    def read_replay_page(self, **kwargs: Any) -> list[tuple[int, str]]:
        """Read a bounded committed replay page under a session lease."""
        session_id = str(kwargs["session_id"])
        route_user = kwargs.pop("user_id", None)
        route_channel = kwargs.pop("channel", None)
        identity = self._identity_for_session(
            session_id,
            user_id=route_user,
            channel=route_channel,
        )
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
            return handle.store.read_replay_page(**kwargs)

    def attach_turn_usage(self, **kwargs: Any) -> bool:
        return bool(self._write_existing("attach_turn_usage", **kwargs))

    def get_page(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        before: TranscriptCursor | None = None,
        after_message_id: str | None = None,
        limit: int = 20,
        max_bytes: int = 2 * 1024 * 1024,
        max_content_blocks: int = 40,
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
                after_message_id=after_message_id,
                limit=limit,
                max_bytes=max_bytes,
                max_content_blocks=max_content_blocks,
            )

    def get_user_message_text(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        message_id: str,
    ) -> str | None:
        """Read one user input through the session lease."""
        with self._lease(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            create=False,
        ) as handle:
            if handle is None:
                return None
            return handle.store.get_user_message_text(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                message_id=message_id,
            )

    def get_user_message_page(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        before: TranscriptCursor | None = None,
        limit: int = 200,
    ) -> TranscriptUserMessagePage | None:
        """Read one lightweight user-message navigation page."""
        with self._lease(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            create=False,
        ) as handle:
            if handle is None:
                return None
            return handle.store.get_user_message_page(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                before=before,
                limit=limit,
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
        target_storage_id: str | None = None,
    ) -> bool:
        """Clone completed history and agent runtime into a new session."""
        with self._lock:
            target_existed = (
                self._catalog_row(
                    session_id=target_session_id,
                    user_id=target_user_id,
                    channel=target_channel,
                )
                is not None
            )
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
                    storage_id=target_storage_id,
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
                self.delete_session(
                    target_session_id,
                    target_user_id,
                    target_channel,
                )
            raise

    def fork_at_turn(
        self,
        *,
        source_session_id: str,
        source_user_id: str,
        source_channel: str,
        source_chat_id: str,
        turn_id: str,
        target_session_id: str,
        target_user_id: str,
        target_channel: str,
        target_storage_id: str,
        native_context: bool = False,
    ) -> int:
        """Create one independently rebuildable conversation at a turn."""
        with self._lock:
            target_existed = (
                self._catalog_row(
                    session_id=target_session_id,
                    user_id=target_user_id,
                    channel=target_channel,
                )
                is not None
            )
        try:
            with self._lease(
                session_id=source_session_id,
                user_id=source_user_id,
                channel=source_channel,
                create=False,
            ) as source:
                if source is None:
                    raise KeyError("source transcript session not found")
                with self._lease(
                    session_id=target_session_id,
                    user_id=target_user_id,
                    channel=target_channel,
                    create=True,
                    storage_id=target_storage_id,
                ) as target:
                    if target is None:
                        raise RuntimeError("failed to create fork session")
                    return target.store.fork_completed_turn_from(
                        source_path=source.store.path,
                        source_session_id=source_session_id,
                        source_chat_id=source_chat_id,
                        turn_id=turn_id,
                        target_session_id=target_session_id,
                        target_user_id=target_user_id,
                        target_channel=target_channel,
                        native_context=native_context,
                    )
        except BaseException:
            if not target_existed:
                self.delete_session(
                    target_session_id,
                    target_user_id,
                    target_channel,
                )
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

    def session_runtime_payloads(
        self,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        """Return runtime states grouped by session and channel."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id, user_id, channel "
                "FROM transcript_files ORDER BY session_id",
            ).fetchall()
        result: list[tuple[str, str, dict[str, Any]]] = []
        for row in rows:
            session_id = str(row["session_id"])
            user_id = str(row["user_id"])
            channel = str(row["channel"])
            with self._lease(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                create=False,
            ) as handle:
                if handle is None:
                    continue
                snapshot = handle.store.read_runtime_state(
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                )
            if snapshot is not None:
                result.append((session_id, channel, snapshot.state))
        return result

    def find_turn_for_message(self, **kwargs: Any) -> str | None:
        session_id = str(kwargs["session_id"])
        route_user = kwargs.pop("user_id", None)
        route_channel = kwargs.pop("channel", None)
        identity = self._identity_for_session(
            session_id,
            user_id=route_user,
            channel=route_channel,
        )
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

    def delete_session(
        self,
        session_id: str,
        user_id: str | None = None,
        channel: str | None = None,
    ) -> bool:
        """Close and delete one session-owned database."""
        with self._condition:
            row = self._resolve_catalog_row(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            )
            if row is None:
                return False
            storage_id = str(row["storage_id"])
            handle = self._handles.get(storage_id)
            while handle is not None and handle.active > 0:
                self._condition.wait()
                handle = self._handles.get(storage_id)
            if handle is not None:
                self._handles.pop(storage_id, None)
            path = self._store_path(storage_id)
            if handle is not None:
                handle.close()
            path.unlink(missing_ok=True)
            path.with_name(f"{path.name}-wal").unlink(missing_ok=True)
            path.with_name(f"{path.name}-shm").unlink(missing_ok=True)
            with self._conn:
                self._conn.execute(
                    "DELETE FROM transcript_files WHERE storage_id = ?",
                    (storage_id,),
                )
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


__all__ = ["TranscriptCatalog", "resolve_session_database_path"]
