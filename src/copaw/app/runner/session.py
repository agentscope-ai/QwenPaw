# -*- coding: utf-8 -*-
"""Safe JSON session with filename sanitization for cross-platform
compatibility.

Windows filenames cannot contain: \\ / : * ? " < > |
This module wraps agentscope's JSONSession so that session_id and user_id
are sanitized before being used as filenames.
"""
from __future__ import annotations

import json
import os
import re
import logging
from datetime import datetime, timezone
from pathlib import Path

from typing import Union, Sequence

from agentscope.session import JSONSession

from ..state_db import connect_state_db, ensure_state_db_schema
from ...utils.json_storage import (
    load_json_with_recovery,
    repair_json_file,
    save_json_atomically,
)

logger = logging.getLogger(__name__)


# Characters forbidden in Windows filenames
_UNSAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|]')


def sanitize_filename(name: str) -> str:
    """Replace characters that are illegal in Windows filenames with ``--``.

    >>> sanitize_filename('discord:dm:12345')
    'discord--dm--12345'
    >>> sanitize_filename('normal-name')
    'normal-name'
    """
    return _UNSAFE_FILENAME_RE.sub("--", name)


class SafeJSONSession(JSONSession):
    """JSONSession subclass that sanitizes session_id / user_id before
    building file paths.

    All other behaviour (save / load / state management) is inherited
    unchanged from :class:`JSONSession`.
    """

    def _get_save_path(self, session_id: str, user_id: str) -> str:
        """Return a filesystem-safe save path.

        Overrides the parent implementation to ensure the generated
        filename is valid on Windows, macOS and Linux.
        """
        os.makedirs(self.save_dir, exist_ok=True)
        safe_sid = sanitize_filename(session_id)
        safe_uid = sanitize_filename(user_id) if user_id else ""
        if safe_uid:
            file_path = f"{safe_uid}_{safe_sid}.json"
        else:
            file_path = f"{safe_sid}.json"
        return os.path.join(self.save_dir, file_path)

    async def update_session_state(
        self,
        session_id: str,
        key: Union[str, Sequence[str]],
        value,
        user_id: str = "",
        create_if_not_exist: bool = True,
    ) -> None:
        session_save_path = self._get_save_path(session_id, user_id=user_id)
        states = self._read_session_state(
            session_save_path,
            allow_not_exist=create_if_not_exist,
        )

        path = key.split(".") if isinstance(key, str) else list(key)
        if not path:
            raise ValueError("key path is empty")

        cur = states
        for k in path[:-1]:
            if k not in cur or not isinstance(cur[k], dict):
                cur[k] = {}
            cur = cur[k]

        cur[path[-1]] = value

        self._write_session_state(session_save_path, states)

        logger.info(
            "Updated session state key '%s' in %s successfully.",
            key,
            session_save_path,
        )

    async def get_session_state_dict(
        self,
        session_id: str,
        user_id: str = "",
        allow_not_exist: bool = True,
    ) -> dict:
        """Return the session state dict from the JSON file.

        Args:
            session_id (`str`):
                The session id.
            user_id (`str`, default to `""`):
                The user ID for the storage.
            allow_not_exist (`bool`, defaults to `True`):
                Whether to allow the session to not exist. If `False`, raises
                an error if the session does not exist.

        Returns:
            `dict`:
                The session state dict loaded from the JSON file. Returns an
                empty dict if the file does not exist and
                `allow_not_exist=True`.
        """
        session_save_path = self._get_save_path(session_id, user_id=user_id)
        states = self._read_session_state(
            session_save_path,
            allow_not_exist=allow_not_exist,
        )
        logger.info(
            "Get session state dict from %s successfully.",
            session_save_path,
        )
        return states

    async def save_session_state(
        self,
        session_id: str,
        user_id: str = "",
        **state_modules_mapping,
    ) -> None:
        state_dicts = {
            name: state_module.state_dict()
            for name, state_module in state_modules_mapping.items()
        }
        self._write_session_state(
            self._get_save_path(session_id, user_id=user_id),
            state_dicts,
        )

    async def load_session_state(
        self,
        session_id: str,
        user_id: str = "",
        allow_not_exist: bool = True,
        **state_modules_mapping,
    ) -> None:
        session_save_path = self._get_save_path(session_id, user_id=user_id)
        states = self._read_session_state(
            session_save_path,
            allow_not_exist=allow_not_exist,
        )

        for name, state_module in state_modules_mapping.items():
            if name in states:
                state_module.load_state_dict(states[name])
        logger.info(
            "Load session state from %s successfully.",
            session_save_path,
        )

    def _read_session_state(
        self,
        session_save_path: str,
        *,
        allow_not_exist: bool,
    ) -> dict:
        path = Path(session_save_path)
        if not path.exists():
            if allow_not_exist:
                logger.info(
                    "Session file %s does not exist. Return empty state dict.",
                    session_save_path,
                )
                return {}
            raise ValueError(
                f"Failed to get session state for file {session_save_path} "
                "because it does not exist.",
            )

        states = load_json_with_recovery(
            path,
            default_payload={},
            storage_name="session state",
            logger_=logger,
        )
        if isinstance(states, dict):
            return states

        repair_json_file(
            path,
            default_payload={},
            storage_name="session state",
            reason="state payload is not a JSON object",
            logger_=logger,
        )
        return {}

    def _write_session_state(
        self,
        session_save_path: str,
        states: dict,
    ) -> None:
        save_json_atomically(
            Path(session_save_path),
            states,
        )


class SQLiteSession(JSONSession):
    """Session store backed by the shared SQLite state database."""

    def __init__(self, *, save_dir: str, db_path: str):
        super().__init__(save_dir=save_dir)
        self._db_path = Path(db_path).expanduser()
        ensure_state_db_schema(self._db_path)

    def _get_save_path(self, session_id: str, user_id: str) -> str:
        return os.path.join(
            self.save_dir,
            f"{self._storage_key(session_id, user_id)}.json",
        )

    async def save_session_state(
        self,
        session_id: str,
        user_id: str = "",
        **state_modules_mapping,
    ) -> None:
        state_dicts = {
            name: state_module.state_dict()
            for name, state_module in state_modules_mapping.items()
        }
        self._write_session_state(
            storage_key=self._storage_key(session_id, user_id),
            states=state_dicts,
        )

    async def load_session_state(
        self,
        session_id: str,
        user_id: str = "",
        allow_not_exist: bool = True,
        **state_modules_mapping,
    ) -> None:
        states = self._read_session_state(
            storage_key=self._storage_key(session_id, user_id),
            allow_not_exist=allow_not_exist,
        )
        for name, state_module in state_modules_mapping.items():
            if name in states:
                state_module.load_state_dict(states[name])
        logger.info(
            "Load session state for session_id=%s user_id=%s successfully.",
            session_id,
            user_id,
        )

    async def update_session_state(
        self,
        session_id: str,
        key: Union[str, Sequence[str]],
        value,
        user_id: str = "",
        create_if_not_exist: bool = True,
    ) -> None:
        path = key.split(".") if isinstance(key, str) else list(key)
        if not path:
            raise ValueError("key path is empty")

        storage_key = self._storage_key(session_id, user_id)
        with connect_state_db(self._db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                states = self._read_session_state_from_conn(
                    conn,
                    storage_key=storage_key,
                    allow_not_exist=create_if_not_exist,
                )

                cur = states
                for part in path[:-1]:
                    if part not in cur or not isinstance(cur[part], dict):
                        cur[part] = {}
                    cur = cur[part]
                cur[path[-1]] = value

                self._write_session_state_to_conn(conn, storage_key, states)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        logger.info(
            "Updated session state key '%s' for storage_key=%s successfully.",
            key,
            storage_key,
        )

    async def get_session_state_dict(
        self,
        session_id: str,
        user_id: str = "",
        allow_not_exist: bool = True,
    ) -> dict:
        storage_key = self._storage_key(session_id, user_id)
        states = self._read_session_state(
            storage_key=storage_key,
            allow_not_exist=allow_not_exist,
        )
        logger.info(
            "Get session state dict for storage_key=%s successfully.",
            storage_key,
        )
        return states

    def _read_session_state(
        self,
        *,
        storage_key: str,
        allow_not_exist: bool,
    ) -> dict:
        with connect_state_db(self._db_path) as conn:
            return self._read_session_state_from_conn(
                conn,
                storage_key=storage_key,
                allow_not_exist=allow_not_exist,
            )

    def _read_session_state_from_conn(
        self,
        conn,
        *,
        storage_key: str,
        allow_not_exist: bool,
    ) -> dict:
        row = conn.execute(
            "SELECT payload_json FROM sessions WHERE storage_key = ?",
            (storage_key,),
        ).fetchone()
        if row is None:
            if allow_not_exist:
                return {}
            raise ValueError(
                "Failed to get session state for "
                f"storage_key={storage_key} because it does not exist.",
            )

        states = json.loads(row["payload_json"])
        if isinstance(states, dict):
            return states

        self._write_session_state_to_conn(conn, storage_key, {})
        return {}

    def _write_session_state(
        self,
        *,
        storage_key: str,
        states: dict,
    ) -> None:
        with connect_state_db(self._db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._write_session_state_to_conn(conn, storage_key, states)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _write_session_state_to_conn(
        self,
        conn,
        storage_key: str,
        states: dict,
    ) -> None:
        conn.execute(
            """
            INSERT INTO sessions (storage_key, payload_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(storage_key) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (
                storage_key,
                json.dumps(states, ensure_ascii=False, sort_keys=True),
                _utc_now(),
            ),
        )

    def _storage_key(self, session_id: str, user_id: str) -> str:
        safe_sid = sanitize_filename(session_id)
        safe_uid = sanitize_filename(user_id) if user_id else ""
        if safe_uid:
            return f"{safe_uid}_{safe_sid}"
        return safe_sid


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
