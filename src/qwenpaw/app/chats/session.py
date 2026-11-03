# -*- coding: utf-8 -*-
"""Safe JSON session with filename sanitization for cross-platform
compatibility.

Windows filenames cannot contain: \\ / : * ? " < > |
"""

import asyncio
import json
import os
import re
import logging
import shutil
import sqlite3
from copy import deepcopy

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Sequence, Union

from agentscope.message import Msg

from qwenpaw.exceptions import ConfigurationException, LegacyMigrationError
from ...schemas import Message
from ...constant import WORKING_DIR
from ...exceptions import AgentStateError
from ...config.history_path import resolve_history_db_path
from ...utils.io_utils import (
    get_path_lock,
    run_sync_io,
    write_json_atomic_async,
)
from ...utils.json_utils import safe_json_loads as _safe_json_loads
from .legacy_reconstruction import read_legacy_timeline
from .provider_migration import (
    recover_codex_boundaries,
    recover_qoder_boundaries,
)
from .utils import agentscope_msg_to_message

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .transcript_catalog import TranscriptCatalog


@dataclass(frozen=True)
class LegacyConversationSnapshot:
    """Read-only view of one legacy JSON session."""

    state: dict[str, Any]
    messages: list[Message]


def _legacy_current_usage(state: dict[str, Any]) -> dict[str, Any] | None:
    """Read the latest persisted usage projection from an old snapshot."""
    context = ((state.get("agent") or {}).get("state") or {}).get("context")
    if not isinstance(context, list):
        return None
    for message in reversed(context):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        metadata = message.get("metadata")
        if not isinstance(metadata, dict):
            continue
        usage = metadata.get("qwenpaw_turn_usage")
        if isinstance(usage, dict):
            return usage
    return None


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


def session_filename(session_id: str, user_id: str = "") -> str:
    """Return the filename used by ``SafeJSONSession`` for one conversation."""
    if not session_id:
        raise ValueError("session_id must not be None or empty")

    safe_sid = sanitize_filename(session_id)
    safe_uid = sanitize_filename(user_id) if user_id else ""
    if safe_uid and safe_uid == safe_sid:
        safe_uid = ""
    return f"{safe_uid}_{safe_sid}.json" if safe_uid else f"{safe_sid}.json"


def session_relative_paths(
    session_id: str,
    user_id: str = "",
    channel: str = "",
) -> set[str]:
    """Return current and legacy paths relative to a sessions directory.

    The returned paths are pure relative POSIX paths so startup migration can
    compare them directly with ``Path.relative_to(...).as_posix``.
    """
    filename = session_filename(session_id, user_id)
    paths = {filename}
    if channel:
        safe_channel = sanitize_filename(channel)
        if safe_channel in {".", ".."}:
            raise ValueError(f"invalid session channel: {channel!r}")
        relative = PurePosixPath(safe_channel, filename)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(
                f"session path escapes save directory: {channel!r}",
            )
        paths.add(relative.as_posix())
    return paths


# Marker used by ``sanitize_filename`` for the historical ``weixin:`` and
# canonical ``wechat:`` session_id prefixes.
_LEGACY_WEIXIN_SAFE_PREFIX = "weixin--"
_CANONICAL_WECHAT_SAFE_PREFIX = "wechat--"

# Sub-directory inside ``save_dir`` where the original legacy weixin
# session files are archived after migration. Keeping a copy preserves
# user data for manual recovery; the archive directory is excluded from
# regular session scans because callers list ``*.json`` non-recursively.
_WEIXIN_LEGACY_ARCHIVE_DIR = ".weixin-legacy"


def _read_session_json(path: str, *, strict: bool = False) -> dict:
    """Read and parse one session snapshot in a worker thread."""
    content = Path(path).read_text(
        encoding="utf-8",
        errors="surrogatepass",
    )
    if strict:
        try:
            state = json.loads(content)
        except json.JSONDecodeError:
            state, _ = json.JSONDecoder().raw_decode(content.lstrip())
        if not isinstance(state, dict):
            raise ValueError("legacy session snapshot must be an object")
        return state
    return _safe_json_loads(content, path)


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


class SafeJSONSession:
    """Filename-safe JSON session store with async file I/O."""

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
        if not session_id:
            logger.error(
                "session_id is None or empty, cannot construct save path",
            )
            raise ValueError("session_id must not be None or empty")

        filename = session_filename(session_id, user_id)

        if channel:
            safe_channel = sanitize_filename(channel)
            if safe_channel in {".", ".."}:
                raise ValueError(f"invalid session channel: {channel!r}")
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
        session_save_path = await run_sync_io(
            self._get_save_path,
            session_id,
            user_id,
            channel,
        )
        async with get_path_lock(session_save_path):
            await write_json_atomic_async(
                session_save_path,
                state_dicts,
                indent=None,
            )

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
        session_save_path = await run_sync_io(
            self._get_save_path,
            session_id,
            user_id,
            channel,
        )
        try:
            states = await run_sync_io(
                _read_session_json,
                session_save_path,
            )
        except FileNotFoundError:
            states = None
        if states is not None:
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
        session_save_path = await run_sync_io(
            self._get_save_path,
            session_id,
            user_id,
            channel,
        )

        path = key.split(".") if isinstance(key, str) else list(key)
        if not path:
            raise ConfigurationException(
                config_key="session.key",
                message="key path is empty",
            )

        async with get_path_lock(session_save_path):
            try:
                states = await run_sync_io(
                    _read_session_json,
                    session_save_path,
                )
            except FileNotFoundError as exc:
                if not create_if_not_exist:
                    raise AgentStateError(
                        session_id=session_id,
                        message=(
                            f"Session file {session_save_path}"
                            f" does not exist"
                        ),
                    ) from exc
                states = {}

            cur = states
            for k in path[:-1]:
                if k not in cur or not isinstance(cur[k], dict):
                    cur[k] = {}
                cur = cur[k]

            cur[path[-1]] = value

            await write_json_atomic_async(
                session_save_path,
                states,
                indent=None,
            )

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
        session_save_path = await run_sync_io(
            self._get_save_path,
            session_id,
            user_id,
            channel,
        )
        try:
            states = await run_sync_io(
                _read_session_json,
                session_save_path,
            )
        except FileNotFoundError:
            states = None
        if states is not None:
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

    async def delete_session_state(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
    ) -> bool:
        """Delete one persisted session snapshot if it exists."""
        session_save_path = await run_sync_io(
            self._get_save_path,
            session_id,
            user_id,
            channel,
        )
        async with get_path_lock(session_save_path):
            try:
                await run_sync_io(Path(session_save_path).unlink)
            except FileNotFoundError:
                return False
        return True


class DatabaseSession:
    """Agent runtime snapshots stored in each conversation database."""

    def __init__(
        self,
        *,
        catalog: "TranscriptCatalog",
        legacy_save_dir: str,
        history_db_filename: str = "history.db",
    ) -> None:
        self._catalog = catalog
        self._legacy_save_dir = Path(legacy_save_dir)
        self._history_db_filename = history_db_filename
        self._migration_lock = asyncio.Lock()
        self._migration_tasks: dict[
            tuple[str, str, str],
            asyncio.Task[bool],
        ] = {}
        self._legacy_snapshot_tasks: dict[
            tuple[str, str, str],
            asyncio.Task[LegacyConversationSnapshot | None],
        ] = {}
        self._deleted_sessions: set[tuple[str, str, str]] = set()

    async def _legacy_path(
        self,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> Path:
        if session_id.startswith("pawapp-storage:"):
            app_id = session_id.removeprefix("pawapp-storage:")
            return Path(WORKING_DIR) / session_filename(f"pawapp:{app_id}")
        filename = session_filename(session_id, user_id)
        if channel:
            safe_channel = sanitize_filename(channel)
            if safe_channel in {".", ".."}:
                raise ValueError(f"invalid session channel: {channel!r}")
            channel_path = self._legacy_save_dir / safe_channel / filename
            if await run_sync_io(channel_path.exists):
                return channel_path
        return self._legacy_save_dir / filename

    async def _load_legacy_snapshot(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> LegacyConversationSnapshot | None:
        path = await self._legacy_path(session_id, user_id, channel)
        try:
            state = await run_sync_io(
                _read_session_json,
                str(path),
                strict=True,
            )
        except FileNotFoundError:
            return None
        if not state:
            return None

        from .utils import session_state_to_messages

        messages = await run_sync_io(session_state_to_messages, state)
        return LegacyConversationSnapshot(state=state, messages=messages)

    async def get_legacy_snapshot(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> LegacyConversationSnapshot | None:
        """Read legacy JSON without creating or changing database data."""
        key = (session_id, user_id, channel)
        async with self._migration_lock:
            if key in self._deleted_sessions:
                return None
            task = self._legacy_snapshot_tasks.get(key)
            if task is None:
                task = asyncio.create_task(
                    self._load_legacy_snapshot(
                        session_id=session_id,
                        user_id=user_id,
                        channel=channel,
                    ),
                )
                self._legacy_snapshot_tasks[key] = task
        try:
            snapshot = await asyncio.shield(task)
        except BaseException:
            async with self._migration_lock:
                if self._legacy_snapshot_tasks.get(key) is task:
                    self._legacy_snapshot_tasks.pop(key, None)
            raise
        if snapshot is None:
            async with self._migration_lock:
                if self._legacy_snapshot_tasks.get(key) is task:
                    self._legacy_snapshot_tasks.pop(key, None)
        if key in self._deleted_sessions:
            return None
        return snapshot

    async def _migrate_legacy_snapshot(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        snapshot: LegacyConversationSnapshot,
    ) -> bool:
        history_path = resolve_history_db_path(
            self._legacy_save_dir.parent,
            self._history_db_filename,
        )
        messages, approximate = await run_sync_io(
            read_legacy_timeline,
            path=history_path,
            session_id=session_id,
            state=snapshot.state,
            fallback=snapshot.messages,
        )
        restore_runtime = await run_sync_io(
            self._catalog.record_legacy_migration,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        if messages:
            await run_sync_io(
                self._catalog.import_legacy_messages,
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                messages=messages,
            )
        await run_sync_io(
            self._import_legacy_history,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            messages=messages,
        )
        if restore_runtime:
            states = iter(approximate)
            turn_seq = 0
            while (state := await run_sync_io(next, states, None)) is not None:
                turn_seq += 1
                existing = await run_sync_io(
                    self._catalog.read_turn_context,
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                    turn_id=f"legacy:{turn_seq}",
                )
                if existing is not None:
                    continue
                await run_sync_io(
                    self._catalog.write_runtime_state,
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                    state=state,
                    turn_id=f"legacy:{turn_seq}",
                    migration_approximate=True,
                    exact_current_usage=True,
                    legacy_import=True,
                )
        _, inserted = await run_sync_io(
            self._catalog.write_runtime_state,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            state=snapshot.state,
            current_usage=_legacy_current_usage(snapshot.state),
            only_if_missing=not restore_runtime,
            migration_anchor=True,
            legacy_import=True,
        )
        await run_sync_io(
            self._import_legacy_provider_binding,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        await run_sync_io(
            recover_qoder_boundaries,
            self._catalog,
            dict(session_id=session_id, user_id=user_id, channel=channel),
        )
        config_path = self._legacy_save_dir.parent / "agent.json"
        config = (
            await run_sync_io(_read_session_json, str(config_path))
            if await run_sync_io(config_path.is_file)
            else {}
        )
        try:
            await recover_codex_boundaries(
                self._catalog,
                dict(session_id=session_id, user_id=user_id, channel=channel),
                binary=(config.get("backend_settings") or {}).get("binary"),
            )
        except (OSError, ValueError, RuntimeError):
            logger.warning("Cannot recover Codex boundaries", exc_info=True)
        await run_sync_io(
            self._catalog.record_legacy_migration,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            complete=True,
        )
        return inserted

    def _import_legacy_provider_binding(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> None:
        """Import an exact old binding once; never infer Turn boundaries."""
        identity = {
            "session_id": session_id,
            "user_id": user_id,
            "channel": channel,
        }
        if self._catalog.read_provider_state(**identity)["binding"]:
            return
        bindings = []
        for provider, filename in (
            ("codex", "codex_sessions.json"),
            ("qoder", "qoder_sessions.json"),
        ):
            path = self._legacy_save_dir.parent / "harnesses" / filename
            if not path.is_file():
                continue
            external_id = _read_session_json(str(path)).get(session_id)
            if external_id:
                bindings.append(
                    {
                        "provider": provider,
                        "external_session_id": str(external_id),
                    },
                )
        if len(bindings) > 1:
            config_path = self._legacy_save_dir.parent / "agent.json"
            config = (
                _read_session_json(str(config_path))
                if config_path.is_file()
                else {}
            )
            bindings = [
                binding
                for binding in bindings
                if binding["provider"] == config.get("backend")
            ]
            if len(bindings) != 1:
                raise ValueError("ambiguous legacy provider session binding")
        if bindings:
            self._catalog.record_provider_fact(
                **identity,
                kind="session_bound",
                data=bindings[0],
            )

    def _import_legacy_history(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        messages: list[Message],
    ) -> None:
        """Import old recall only while the JSON session is migrating."""
        from ...agents.context.scroll.history import HistoryStore
        from .transcript_catalog import resolve_session_database_path

        source = resolve_history_db_path(
            self._legacy_save_dir.parent,
            self._history_db_filename,
        )
        self._catalog.ensure_session_database(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        target = resolve_session_database_path(
            self._legacy_save_dir.parent,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        if target is None:
            raise FileNotFoundError("conversation database is missing")
        turn_by_key: dict[str, str] = {}
        turn_seq = 0
        for message in messages:
            if turn_seq == 0 or getattr(message.role, "value", None) == "user":
                turn_seq += 1
            turn_id = f"legacy:{turn_seq}"
            turn_by_key[str(message.id)] = turn_id
            original_id = (message.metadata or {}).get("original_id")
            if original_id:
                turn_by_key[str(original_id)] = turn_id
            for block in message.content:
                call_id = (
                    block.get("id") or block.get("tool_call_id")
                    if isinstance(block, dict)
                    else getattr(block, "id", None)
                    or getattr(block, "tool_call_id", None)
                )
                if call_id:
                    turn_by_key[str(call_id)] = turn_id
        history = HistoryStore(target)
        try:
            history.import_legacy_database(
                source,
                session_id=session_id,
                turn_by_key=turn_by_key,
            )
        finally:
            history.close()

    def _migration_finished(
        self,
        key: tuple[str, str, str],
        task: asyncio.Task[bool],
    ) -> None:
        if self._migration_tasks.get(key) is task:
            self._migration_tasks.pop(key, None)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.warning(
                "Failed to migrate legacy session %s",
                key[0],
                exc_info=True,
            )
            return
        self._legacy_snapshot_tasks.pop(key, None)

    async def _get_migration_task(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        snapshot: LegacyConversationSnapshot,
    ) -> asyncio.Task[bool] | None:
        key = (session_id, user_id, channel)
        async with self._migration_lock:
            if key in self._deleted_sessions:
                return None
            if await run_sync_io(
                self._migration_complete,
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            ):
                return None
            task = self._migration_tasks.get(key)
            if task is None:
                task = asyncio.create_task(
                    self._migrate_legacy_snapshot(
                        session_id=session_id,
                        user_id=user_id,
                        channel=channel,
                        snapshot=snapshot,
                    ),
                )
                self._migration_tasks[key] = task
                task.add_done_callback(
                    lambda finished: self._migration_finished(key, finished),
                )
            return task

    async def start_legacy_migration(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        snapshot: LegacyConversationSnapshot | None = None,
        wait_for_projection: bool = False,
    ) -> bool:
        """Start shared migration, optionally waiting for display projection."""
        legacy = snapshot or await self.get_legacy_snapshot(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        if legacy is None:
            return False
        task = await self._get_migration_task(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            snapshot=legacy,
        )
        if task is None:
            return False
        if wait_for_projection:
            while not task.done():
                page = await run_sync_io(
                    self._catalog.get_page,
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                    limit=1,
                    max_content_blocks=1,
                )
                if page is not None:
                    return True
                await asyncio.wait({task}, timeout=0.1)
            task.result()
        return True

    async def ensure_legacy_migrated(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> bool:
        """Wait for a legacy migration before a conversation can continue."""
        try:
            current = await run_sync_io(
                self._catalog.read_runtime_state,
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            )
            if current is not None and await run_sync_io(
                self._migration_complete,
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            ):
                return False
            snapshot = await self.get_legacy_snapshot(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            )
            if snapshot is None:
                return False
            task = await self._get_migration_task(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                snapshot=snapshot,
            )
            if task is None:
                return False
            return await asyncio.shield(task)
        except Exception as exc:
            raise LegacyMigrationError(session_id) from exc

    def _migration_complete(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> bool:
        """Check the durable marker before skipping an old JSON import."""
        from .transcript_catalog import resolve_session_database_path

        target = resolve_session_database_path(
            self._legacy_save_dir.parent,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        if target is None:
            return False
        uri = f"{target.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            row = connection.execute(
                "SELECT 1 FROM event_log WHERE idempotency_key = ?",
                (f"migration:completed:{session_id}",),
            ).fetchone()
        return row is not None

    async def _import_legacy(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> bool:
        return await self.ensure_legacy_migrated(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )

    async def import_session_history(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        state: dict[str, Any],
    ) -> None:
        """Seed imported display history and resumable turn revisions."""
        context = state["agent"]["state"]["context"]
        messages = agentscope_msg_to_message(
            [Msg.model_validate(raw) for raw in context],
        )
        identity = dict(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        async with self._migration_lock:
            await run_sync_io(
                self._catalog.import_legacy_messages,
                **identity,
                messages=messages,
            )
            boundaries = [
                index
                for index, raw in enumerate(context)
                if index and raw.get("role") == "user"
            ] + [len(context)]
            for turn_seq, end in enumerate(boundaries, start=1):
                turn_id = f"legacy:{turn_seq}"
                existing = await run_sync_io(
                    self._catalog.read_turn_context,
                    **identity,
                    turn_id=turn_id,
                )
                if existing is not None:
                    continue
                snapshot = deepcopy(state)
                snapshot["agent"]["state"]["context"] = context[:end]
                await run_sync_io(
                    self._catalog.write_runtime_state,
                    **identity,
                    state=snapshot,
                    turn_id=turn_id,
                    migration_approximate=True,
                )

    async def save_session_state(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        **state_modules_mapping: Any,
    ) -> None:
        """Persist module snapshots into the session database."""
        state = {
            name: state_module.state_dict()
            for name, state_module in state_modules_mapping.items()
        }
        await run_sync_io(
            self._catalog.write_runtime_state,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            state=state,
        )

    async def save_turn_session_state(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        turn_id: str,
        reset_context: bool = False,
        pending_commit: dict[str, Any] | None = None,
        **state_modules_mapping: Any,
    ) -> None:
        """Save runtime and its immutable turn revision in one transaction."""
        state = {
            name: module.state_dict()
            for name, module in state_modules_mapping.items()
        }
        if pending_commit is not None:
            pending_commit["runtime"] = {
                "state": deepcopy(state),
                "reset_context": reset_context,
            }
            return
        await run_sync_io(
            self._catalog.write_runtime_state,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            state=state,
            turn_id=turn_id,
            reset_context=reset_context,
        )

    async def reset_session_state(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        **state_modules_mapping: Any,
    ) -> int:
        """Persist a clean state and advance the context generation."""
        state = {
            name: state_module.state_dict()
            for name, state_module in state_modules_mapping.items()
        }
        generation, _ = await run_sync_io(
            self._catalog.write_runtime_state,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            state=state,
            reset_context=True,
        )
        return generation

    async def load_session_state(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        allow_not_exist: bool = True,
        **state_modules_mapping: Any,
    ) -> None:
        """Load module snapshots from the session database."""
        state = await self.get_session_state_dict(
            session_id,
            user_id,
            channel,
            allow_not_exist=allow_not_exist,
        )
        for name, state_module in state_modules_mapping.items():
            if name in state:
                module_state = state[name]
                if name == "agent" and isinstance(module_state, dict):
                    module_state = dict(module_state)
                    module_state["_context_generation"] = state.get(
                        "_context_generation",
                        0,
                    )
                state_module.load_state_dict(module_state)

    async def get_session_state_dict(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        allow_not_exist: bool = True,
    ) -> dict[str, Any]:
        """Return the authoritative runtime state and context generation."""
        await self.ensure_legacy_migrated(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        snapshot = await run_sync_io(
            self._catalog.read_runtime_state,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        if snapshot is None:
            if allow_not_exist:
                return {}
            raise AgentStateError(
                session_id=session_id,
                message="Session runtime state does not exist",
            )
        state = dict(snapshot.state)
        state["_context_generation"] = snapshot.context_generation
        return state

    async def update_session_state(
        self,
        session_id: str,
        key: Union[str, Sequence[str]],
        value: Any,
        user_id: str = "",
        channel: str = "",
        create_if_not_exist: bool = True,
        delete: bool = False,
    ) -> None:
        """Update one nested runtime-state value."""
        path = key.split(".") if isinstance(key, str) else list(key)
        if not path:
            raise ConfigurationException(
                config_key="session.key",
                message="key path is empty",
            )
        snapshot = await run_sync_io(
            self._catalog.read_runtime_state,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        if snapshot is None:
            await self._import_legacy(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            )
        try:
            await run_sync_io(
                self._catalog.update_runtime_state,
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                path=path,
                value=value,
                create_if_missing=create_if_not_exist,
                delete=delete,
            )
        except KeyError as exc:
            raise AgentStateError(
                session_id=session_id,
                message="Session runtime state does not exist",
            ) from exc

    async def set_current_usage(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        usage: dict[str, Any] | None,
        context_usage: dict[str, Any] | None,
    ) -> None:
        """Persist the current context usage projection."""
        await run_sync_io(
            self._catalog.set_current_usage,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            usage=usage,
            context_usage=context_usage,
        )

    async def get_current_usage(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> tuple[int, dict[str, Any] | None]:
        """Return current context generation and usage projection."""
        projection = await run_sync_io(
            self._catalog.read_current_usage,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        if projection is None:
            await self._import_legacy(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            )
            projection = await run_sync_io(
                self._catalog.read_current_usage,
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            )
        if projection is None:
            return 0, None
        return projection

    async def delete_session_state(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        *,
        deleting_channels: tuple[str, ...] = (),
    ) -> bool:
        """Delete the session database and any unimported JSON snapshot."""
        key = (session_id, user_id, channel)
        async with self._migration_lock:
            self._deleted_sessions.add(key)
            self._legacy_snapshot_tasks.pop(key, None)
            migration = self._migration_tasks.get(key)
        if migration is not None:
            try:
                await asyncio.shield(migration)
            except Exception:
                pass
        deleted = await run_sync_io(
            self._catalog.delete_session,
            session_id,
            user_id,
            channel,
        )
        filename = session_filename(session_id, user_id)
        paths = []
        shared_root = await run_sync_io(
            self._legacy_root_shared,
            session_id,
            user_id,
            channel,
            deleting_channels,
        )
        if not shared_root:
            paths.append(self._legacy_save_dir / filename)
        if channel:
            safe_channel = sanitize_filename(channel)
            if safe_channel in {".", ".."}:
                raise ValueError(f"invalid session channel: {channel!r}")
            paths.append(self._legacy_save_dir / safe_channel / filename)
        for path in paths:
            try:
                await run_sync_io(path.unlink)
                deleted = True
            except FileNotFoundError:
                pass
        return deleted

    def _legacy_root_shared(
        self,
        session_id: str,
        user_id: str,
        channel: str,
        deleting_channels: tuple[str, ...],
    ) -> bool:
        """Keep the root fallback while another channel still uses it."""
        path = self._legacy_save_dir.parent / "chats.json"
        try:
            chats = _read_session_json(str(path)).get("chats", [])
        except (FileNotFoundError, OSError):
            return False
        return any(
            isinstance(chat, dict)
            and chat.get("session_id") == session_id
            and chat.get("user_id") == user_id
            and chat.get("channel") != channel
            and chat.get("channel") not in deleting_channels
            for chat in chats
        )
