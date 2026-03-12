# -*- coding: utf-8 -*-
"""Safe JSON session with filename sanitization for cross-platform
compatibility.

Windows filenames cannot contain: \\ / : * ? " < > |
This module wraps agentscope's SessionBase so that session_id and user_id
are sanitized before being used as filenames.
"""
import asyncio
import json
import logging
import os
import re
import uuid

from typing import Union, Sequence

import aiofiles
from agentscope.session import SessionBase

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


class SafeJSONSession(SessionBase):
    """SessionBase subclass with filename sanitization and async file I/O.

    Overrides all file-reading/writing methods to use :mod:`aiofiles` so
    that disk I/O does not block the event loop.
    """

    _file_locks: dict[str, asyncio.Lock] = {}

    def __init__(
        self,
        save_dir: str = "./",
    ) -> None:
        """Initialize the JSON session class.

        Args:
            save_dir (`str`, defaults to `"./"):
                The directory to save the session state.
        """
        self.save_dir = save_dir

    def _get_file_lock(self, session_save_path: str) -> asyncio.Lock:
        lock = type(self)._file_locks.get(session_save_path)
        if lock is None:
            lock = asyncio.Lock()
            type(self)._file_locks.setdefault(session_save_path, lock)
        return type(self)._file_locks[session_save_path]

    async def _read_state_dict_unlocked(
        self,
        session_save_path: str,
    ) -> dict:
        async with aiofiles.open(
            session_save_path,
            "r",
            encoding="utf-8",
            errors="surrogatepass",
        ) as file:
            content = await file.read()

        if not content.strip():
            logger.warning(
                "Session file %s is empty. Treating it as an empty state.",
                session_save_path,
            )
            return {}

        try:
            states = json.loads(content)
        except json.JSONDecodeError:
            logger.warning(
                "Session file %s contains invalid JSON. Treating it as an "
                "empty state.",
                session_save_path,
                exc_info=True,
            )
            return {}

        if not isinstance(states, dict):
            logger.warning(
                "Session file %s does not contain a JSON object. Treating "
                "it as an empty state.",
                session_save_path,
            )
            return {}

        return states

    async def _read_state_dict(
        self,
        session_save_path: str,
    ) -> dict:
        async with self._get_file_lock(session_save_path):
            return await self._read_state_dict_unlocked(session_save_path)

    async def _write_state_dict_unlocked(
        self,
        session_save_path: str,
        states: dict,
    ) -> None:
        payload = json.dumps(states, ensure_ascii=False)
        temp_path = f"{session_save_path}.{uuid.uuid4().hex}.tmp"
        try:
            async with aiofiles.open(
                temp_path,
                "w",
                encoding="utf-8",
                errors="surrogatepass",
            ) as file:
                await file.write(payload)
                await file.flush()
            os.replace(temp_path, session_save_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

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

    async def save_session_state(
        self,
        session_id: str,
        user_id: str = "",
        **state_modules_mapping,
    ) -> None:
        """Save state modules to a JSON file using async I/O."""
        state_dicts = {
            name: state_module.state_dict()
            for name, state_module in state_modules_mapping.items()
        }
        session_save_path = self._get_save_path(session_id, user_id=user_id)
        async with self._get_file_lock(session_save_path):
            await self._write_state_dict_unlocked(session_save_path, state_dicts)

        logger.info(
            "Saved session state to %s successfully.",
            session_save_path,
        )

    async def load_session_state(
        self,
        session_id: str,
        user_id: str = "",
        allow_not_exist: bool = True,
        **state_modules_mapping,
    ) -> None:
        """Load state modules from a JSON file using async I/O."""
        session_save_path = self._get_save_path(session_id, user_id=user_id)
        if os.path.exists(session_save_path):
            states = await self._read_state_dict(session_save_path)

            for name, state_module in state_modules_mapping.items():
                if name in states:
                    state_module.load_state_dict(states[name])
            logger.info(
                "Load session state from %s successfully.",
                session_save_path,
            )

        elif allow_not_exist:
            logger.info(
                "Session file %s does not exist. Skip loading session state.",
                session_save_path,
            )

        else:
            raise ValueError(
                f"Failed to load session state for file {session_save_path} "
                "because it does not exist.",
            )

    async def update_session_state(
        self,
        session_id: str,
        key: Union[str, Sequence[str]],
        value,
        user_id: str = "",
        create_if_not_exist: bool = True,
    ) -> None:
        session_save_path = self._get_save_path(session_id, user_id=user_id)
        path = key.split(".") if isinstance(key, str) else list(key)
        if not path:
            raise ValueError("key path is empty")

        async with self._get_file_lock(session_save_path):
            if os.path.exists(session_save_path):
                states = await self._read_state_dict_unlocked(session_save_path)
            else:
                if not create_if_not_exist:
                    raise ValueError(
                        f"Session file {session_save_path} does not exist.",
                    )
                states = {}

            cur = states
            for k in path[:-1]:
                if k not in cur or not isinstance(cur[k], dict):
                    cur[k] = {}
                cur = cur[k]

            cur[path[-1]] = value
            await self._write_state_dict_unlocked(session_save_path, states)

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
        if os.path.exists(session_save_path):
            states = await self._read_state_dict(session_save_path)

            logger.info(
                "Get session state dict from %s successfully.",
                session_save_path,
            )
            return states

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
