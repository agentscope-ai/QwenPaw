# -*- coding: utf-8 -*-
"""Safe JSON session with filename sanitization for cross-platform
compatibility.

Windows filenames cannot contain: \\ / : * ? " < > |
This module wraps agentscope's SessionBase so that session_id and user_id
are sanitized before being used as filenames.
"""
import os
import re
import json
import logging
import shutil

from typing import Union, Sequence

import aiofiles
from agentscope.session import SessionBase
from agentscope_runtime.engine.schemas.exception import ConfigurationException
from ...exceptions import AgentStateError

logger = logging.getLogger(__name__)


def _safe_json_loads(content: str, filepath: str = "") -> dict:
    """Parse JSON with corruption recovery.

    Attempts standard ``json.loads`` first.  If that fails due to
    trailing garbage (a common symptom of concurrent-write race
    conditions), falls back to ``raw_decode`` to extract the first
    valid JSON object.  If the file is completely unparseable, returns
    an empty dict and logs a warning so callers never crash.

    Args:
        content: Raw file content.
        filepath: Used only for log messages.

    Returns:
        Parsed dict, or ``{}`` when the content is beyond recovery.
    """
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try to extract the first valid JSON object.
    try:
        result, _ = json.JSONDecoder().raw_decode(content)
        logger.warning(
            "Session file %s had corrupted JSON. "
            "Recovered first valid object via raw_decode.",
            filepath,
        )
        return result
    except json.JSONDecodeError:
        logger.warning(
            "Session file %s is completely corrupted and could not "
            "be recovered. Returning empty dict.",
            filepath,
        )
        return {}


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


# Marker used by ``sanitize_filename`` for the historical ``weixin:`` and
# canonical ``wechat:`` session_id prefixes.
_LEGACY_WEIXIN_SAFE_PREFIX = "weixin--"
_CANONICAL_WECHAT_SAFE_PREFIX = "wechat--"

# Sub-directory inside ``save_dir`` where the original legacy weixin
# session files are archived after migration. Keeping a copy preserves
# user data for manual recovery; the archive directory is excluded from
# regular session scans because callers list ``*.json`` non-recursively.
_WEIXIN_LEGACY_ARCHIVE_DIR = ".weixin-legacy"


def migrate_legacy_weixin_session_files(save_dir: str) -> None:
    """Rename legacy ``weixin--`` session files to the ``wechat--`` form.

    Originals are moved to the ``.weixin-legacy/`` archive sub-dir so
    later startups skip the migration without extra bookkeeping. If a
    canonical file already exists, the legacy file is only archived.
    """
    if not save_dir or not os.path.isdir(save_dir):
        return
    try:
        entries = os.listdir(save_dir)
    except OSError:
        return
    legacy_files = [
        name
        for name in entries
        if name.endswith(".json")
        and _rewrite_weixin_in_session_filename(name) is not None
    ]
    if not legacy_files:
        return
    archive_dir = os.path.join(save_dir, _WEIXIN_LEGACY_ARCHIVE_DIR)
    try:
        os.makedirs(archive_dir, exist_ok=True)
    except OSError as exc:
        logger.error(
            "Failed to create weixin archive directory %s: %s",
            archive_dir,
            exc,
        )
        return
    for name in legacy_files:
        src = os.path.join(save_dir, name)
        new_name = _rewrite_weixin_in_session_filename(name)
        # ``new_name`` is non-None here (filtered above), but reassert for
        # the type checker.
        if new_name is None:
            continue
        dst = os.path.join(save_dir, new_name)
        archive_path = os.path.join(archive_dir, name)
        target_exists = os.path.exists(dst)
        try:
            if target_exists:
                # Canonical file already present: archive the legacy copy
                # and leave the live file untouched. ``shutil.move`` falls
                # back to copy+delete across filesystem boundaries.
                shutil.move(src, archive_path)
                logger.warning(
                    "Archived legacy weixin session file %s -> %s "
                    "(canonical %s already exists)",
                    src,
                    archive_path,
                    dst,
                )
            else:
                # Copy first, then archive the source. This keeps the
                # legacy file recoverable even if the move to ``dst`` is
                # interrupted.
                shutil.copy2(src, dst)
                shutil.move(src, archive_path)
                logger.warning(
                    "Migrated legacy weixin session file %s -> %s "
                    "(original archived to %s)",
                    src,
                    dst,
                    archive_path,
                )
        except OSError as exc:
            logger.error(
                "Failed to migrate session file %s -> %s: %s",
                src,
                dst,
                exc,
            )


def _rewrite_weixin_in_session_filename(name: str) -> str | None:
    """Return the canonical filename for a legacy weixin session file.

    File layout from ``_get_save_path`` is ``{safe_uid}_{safe_sid}.json``
    or ``{safe_sid}.json``. Returns ``None`` if the file does not match.

    NOTE: cannot use ``rsplit('_', 1)`` to find the boundary: WeChat
    user_ids contain ``_`` and session_ids end with ``@im.wechat``, so
    the rightmost ``_`` lives inside the session_id. Locate the literal
    ``_weixin--`` delimiter instead.
    """
    stem = name[: -len(".json")]
    delim = "_" + _LEGACY_WEIXIN_SAFE_PREFIX
    idx = stem.find(delim)
    if idx >= 0:
        safe_uid = stem[:idx]
        safe_sid_tail = stem[idx + len(delim) :]
        return (
            f"{safe_uid}_{_CANONICAL_WECHAT_SAFE_PREFIX}{safe_sid_tail}.json"
        )
    if stem.startswith(_LEGACY_WEIXIN_SAFE_PREFIX):
        return (
            _CANONICAL_WECHAT_SAFE_PREFIX
            + stem[len(_LEGACY_WEIXIN_SAFE_PREFIX) :]
            + ".json"
        )
    return None


class SafeJSONSession(SessionBase):
    """SessionBase subclass with filename sanitization and async file I/O.

    Overrides all file-reading/writing methods to use :mod:`aiofiles` so
    that disk I/O does not block the event loop.
    """

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

    def _get_save_path(
        self,
        session_id: str,
        user_id: str,
        channel: str = "",
    ) -> str:
        """Return a filesystem-safe save path.

        Overrides the parent implementation to ensure the generated
        filename is valid on Windows, macOS and Linux.

        Args:
            session_id: Session identifier
            user_id: User identifier
            channel: Optional channel name for subdirectory separation

        Returns:
            Full path to the session file. If channel is provided,
            uses channels/{channel}/ subdirectory structure.
        """
        safe_sid = sanitize_filename(session_id)
        safe_uid = sanitize_filename(user_id) if user_id else ""

        if safe_uid:
            filename = f"{safe_uid}_{safe_sid}.json"
        else:
            filename = f"{safe_sid}.json"

        if channel:
            safe_channel = sanitize_filename(channel)
            target_dir = os.path.join(self.save_dir, safe_channel)
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, filename)

            legacy_path = os.path.join(self.save_dir, filename)
            if not os.path.exists(target_path) and os.path.exists(legacy_path):
                try:
                    shutil.copy2(legacy_path, target_path)
                    logger.info(
                        "Migrated session file from %s to %s",
                        legacy_path,
                        target_path,
                    )
                except OSError as exc:
                    logger.warning(
                        "Failed to migrate session file %s to %s: %s",
                        legacy_path,
                        target_path,
                        exc,
                    )

            return target_path

        os.makedirs(self.save_dir, exist_ok=True)
        return os.path.join(self.save_dir, filename)

    async def save_session_state(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        **state_modules_mapping,
    ) -> None:
        """Save state modules to a JSON file using async I/O."""
        state_dicts = {
            name: state_module.state_dict()
            for name, state_module in state_modules_mapping.items()
        }
        session_save_path = self._get_save_path(
            session_id,
            user_id=user_id,
            channel=channel,
        )
        with open(
            session_save_path,
            "w",
            encoding="utf-8",
        ) as f:
            f.write(json.dumps(state_dicts, ensure_ascii=False))

        logger.info(
            "Saved session state to %s successfully.",
            session_save_path,
        )

    async def load_session_state(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        allow_not_exist: bool = True,
        **state_modules_mapping,
    ) -> None:
        """Load state modules from a JSON file using async I/O."""
        session_save_path = self._get_save_path(
            session_id,
            user_id=user_id,
            channel=channel,
        )
        if os.path.exists(session_save_path):
            async with aiofiles.open(
                session_save_path,
                "r",
                encoding="utf-8",
                errors="surrogatepass",
            ) as f:
                content = await f.read()
                states = _safe_json_loads(content, session_save_path)

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
            raise AgentStateError(
                session_id=session_id,
                message=(
                    f"Failed to load session state for file "
                    f"{session_save_path} because it does not exist"
                ),
            )

    async def update_session_state(
        self,
        session_id: str,
        key: Union[str, Sequence[str]],
        value,
        user_id: str = "",
        channel: str = "",
        create_if_not_exist: bool = True,
    ) -> None:
        session_save_path = self._get_save_path(
            session_id,
            user_id=user_id,
            channel=channel,
        )

        if os.path.exists(session_save_path):
            async with aiofiles.open(
                session_save_path,
                "r",
                encoding="utf-8",
                errors="surrogatepass",
            ) as f:
                content = await f.read()
                states = _safe_json_loads(content, session_save_path)

        else:
            if not create_if_not_exist:
                raise AgentStateError(
                    session_id=session_id,
                    message=f"Session file {session_save_path} does not exist",
                )
            states = {}

        path = key.split(".") if isinstance(key, str) else list(key)
        if not path:
            raise ConfigurationException(
                config_key="session.key",
                message="key path is empty",
            )

        cur = states
        for k in path[:-1]:
            if k not in cur or not isinstance(cur[k], dict):
                cur[k] = {}
            cur = cur[k]

        cur[path[-1]] = value

        with open(
            session_save_path,
            "w",
            encoding="utf-8",
        ) as f:
            f.write(json.dumps(states, ensure_ascii=False))

        logger.info(
            "Updated session state key '%s' in %s successfully.",
            key,
            session_save_path,
        )

    async def get_session_state_dict(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        allow_not_exist: bool = True,
    ) -> dict:
        """Return the session state dict from the JSON file.

        Args:
            session_id (`str`):
                The session id.
            user_id (`str`, default to `""`):
                The user ID for the storage.
            channel (`str`, default to `""`):
                The channel name for subdirectory separation.
            allow_not_exist (`bool`, defaults to `True`):
                Whether to allow the session to not exist. If `False`, raises
                an error if the session does not exist.

        Returns:
            `dict`:
                The session state dict loaded from the JSON file. Returns an
                empty dict if the file does not exist and
                `allow_not_exist=True`.
        """
        session_save_path = self._get_save_path(
            session_id,
            user_id=user_id,
            channel=channel,
        )
        if os.path.exists(session_save_path):
            async with aiofiles.open(
                session_save_path,
                "r",
                encoding="utf-8",
                errors="surrogatepass",
            ) as file:
                content = await file.read()
                states = _safe_json_loads(content, session_save_path)

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

        raise AgentStateError(
            session_id=session_id,
            message=(
                f"Failed to get session state for file {session_save_path} "
                f"because it does not exist"
            ),
        )
