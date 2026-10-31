# -*- coding: utf-8 -*-
"""Helpers for creating backups: agents, global config, secrets, skill pool."""

from __future__ import annotations

import json
import logging
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .._utils.constants import (
    PREFIX_CONFIG,
    PREFIX_SECRETS,
    PREFIX_SKILL_POOL,
    PREFIX_WORKSPACES,
)
from .._utils.history_sqlite import (
    archive_history_db_filename,
    configured_history_db_path,
    history_agent_config_bytes,
    history_sidecar_paths,
)
from ...constant import CONFIG_FILE, SECRET_DIR, WORKING_DIR

logger = logging.getLogger(__name__)


class BackupCancelled(Exception):
    """Raised when cooperative cancellation stops archive creation."""


def _backup_session_database(
    source: Path,
    target: Path,
    *,
    check_cancelled: Any,
) -> None:
    """Create and verify a transactionally consistent SQLite snapshot."""
    source_connection = sqlite3.connect(
        source.resolve().as_uri() + "?mode=ro",
        uri=True,
    )
    target_connection = sqlite3.connect(str(target))
    try:
        source_connection.backup(
            target_connection,
            pages=128,
            progress=lambda _status, _remaining, _total: check_cancelled(),
        )
        result = target_connection.execute("PRAGMA quick_check").fetchone()
        if result is None or result[0] != "ok":
            raise sqlite3.DatabaseError("conversation backup check failed")
    finally:
        target_connection.close()
        source_connection.close()


def _session_manifest(workspace: Path) -> tuple:
    """Capture directory metadata so concurrent changes fail the backup."""
    paths = frozenset((workspace / "transcripts").glob("*.db"))
    catalog = workspace / "transcript_catalog.db"
    rows: tuple[tuple[str, str, str, str], ...] = ()
    if catalog.exists():
        connection = sqlite3.connect(
            catalog.resolve().as_uri() + "?mode=ro",
            uri=True,
        )
        try:
            rows = tuple(
                connection.execute(
                    "SELECT storage_id, session_id, user_id, channel "
                    "FROM transcript_files ORDER BY storage_id",
                ),
            )
        finally:
            connection.close()
        if any(
            workspace / "transcripts" / (row[0] + ".db") not in paths
            for row in rows
        ):
            raise RuntimeError("conversation catalog references missing DB")
    chats = workspace / "chats.json"
    chat_bytes = chats.read_bytes() if chats.exists() else None
    if chat_bytes is not None:
        by_identity = {tuple(row[1:]): row[0] for row in rows}
        for chat in json.loads(chat_bytes).get("chats", []):
            identity = (
                chat.get("session_id", ""),
                chat.get("user_id", ""),
                chat.get("channel", "console"),
            )
            storage_id = by_identity.get(identity)
            if storage_id is not None and chat.get("storage_id") != storage_id:
                raise RuntimeError("chat directory and catalog disagree")
    return paths, catalog.exists(), rows, chat_bytes


def _snapshot_session_databases(
    zf: zipfile.ZipFile,
    *,
    workspace: Path,
    agent_id: str,
    snapshot_dir: str,
    check_cancelled: Any,
    manifest: tuple,
) -> tuple[set[Path], set[Path], int]:
    """Add consistent session DB snapshots and return paths to skip."""
    databases = sorted(manifest[0])
    catalog = workspace / "transcript_catalog.db"
    if manifest[1]:
        databases.append(catalog)
    paths = {database.resolve() for database in databases}
    sidecars = {
        sidecar.resolve()
        for database in databases
        for sidecar in history_sidecar_paths(database)
    }
    for index, database in enumerate(databases):
        relative = database.relative_to(workspace)
        snapshot = Path(snapshot_dir) / f"session-{index}-{database.name}"
        _backup_session_database(
            database,
            snapshot,
            check_cancelled=check_cancelled,
        )
        connection = sqlite3.connect(str(snapshot))
        try:
            if database == catalog:
                rows = tuple(
                    connection.execute(
                        "SELECT storage_id, session_id, user_id, channel "
                        "FROM transcript_files ORDER BY storage_id",
                    ),
                )
                if rows != manifest[2]:
                    raise RuntimeError("conversation catalog changed")
            else:
                expected = next(
                    (row for row in manifest[2] if row[0] == database.stem),
                    None,
                )
                if expected is not None:
                    actual = connection.execute(
                        "SELECT storage_id, session_id, user_id, channel "
                        "FROM transcript_sessions",
                    ).fetchall()
                    if actual != [expected]:
                        raise RuntimeError("conversation DB identity mismatch")
        finally:
            connection.close()
        zf.write(
            snapshot,
            f"{PREFIX_WORKSPACES}{agent_id}/{relative.as_posix()}",
        )
    return paths, sidecars, len(databases)


def add_agent_workspaces(  # pylint: disable=too-many-branches
    zf: zipfile.ZipFile,
    valid_agents: list[tuple[str, Any]],
    progress_callback=None,
    stop_event=None,
) -> bool:
    """Add each agent's workspace directory to the zip.

    Returns:
        False if stop_event was set (cancelled), True otherwise.

    Raises:
        BackupCancelled: If cancellation interrupts a history snapshot.
    """

    def check_cancelled() -> None:
        if stop_event and stop_event.is_set():
            raise BackupCancelled()

    total = len(valid_agents)
    logger.info(
        "Backing up %d agent(s): %s",
        total,
        [aid for aid, _ in valid_agents],
    )

    for i, (aid, ref) in enumerate(valid_agents):
        if stop_event and stop_event.is_set():
            return False

        if progress_callback:
            progress_callback(i, total, aid)

        ws = Path(ref.workspace_dir).expanduser().resolve()
        if ws.is_dir():
            manifest = _session_manifest(ws)
            file_count = 0
            skipped = 0
            history_db = configured_history_db_path(ws)
            sidecars = history_sidecar_paths(history_db)
            history_filename = archive_history_db_filename(ws, history_db)
            with tempfile.TemporaryDirectory(
                prefix=f"qwenpaw-history-{aid}-",
            ) as snapshot_dir:
                history_snapshot = Path(snapshot_dir) / "history.db"
                if history_db.is_file():
                    from ...agents.context.scroll.history import (
                        backup_history_database,
                    )

                    backup_history_database(
                        history_db,
                        history_snapshot,
                        check_cancelled=check_cancelled,
                    )
                    zf.write(
                        history_snapshot,
                        f"{PREFIX_WORKSPACES}{aid}/{history_filename}",
                    )
                    file_count += 1
                (
                    session_paths,
                    session_sidecars,
                    snapshot_count,
                ) = _snapshot_session_databases(
                    zf,
                    workspace=ws,
                    agent_id=aid,
                    snapshot_dir=snapshot_dir,
                    check_cancelled=check_cancelled,
                    manifest=manifest,
                )
                file_count += snapshot_count
                if manifest[3] is not None:
                    zf.writestr(
                        f"{PREFIX_WORKSPACES}{aid}/chats.json",
                        manifest[3],
                    )
                    file_count += 1
                for entry in sorted(ws.rglob("*")):
                    if stop_event and stop_event.is_set():
                        return False
                    resolved_entry = entry.resolve()
                    if (
                        not entry.is_file()
                        or resolved_entry in sidecars
                        or resolved_entry == history_db
                        or resolved_entry in session_paths
                        or resolved_entry == ws / "chats.json"
                        or resolved_entry in session_sidecars
                    ):
                        continue
                    relative = entry.relative_to(ws)
                    if relative.parent == Path(
                        "transcripts",
                    ) and entry.name.endswith((".db", "-wal", "-shm")):
                        raise RuntimeError("conversation DB set changed")
                    rel = relative.as_posix()
                    arcname = f"{PREFIX_WORKSPACES}{aid}/{rel}"
                    try:
                        if rel == "agent.json":
                            zf.writestr(
                                arcname,
                                history_agent_config_bytes(
                                    ws,
                                    history_filename,
                                ),
                            )
                        else:
                            zf.write(entry, arcname)
                    except (PermissionError, OSError) as exc:
                        # A file that can't be added (e.g. an open Chromium
                        # cache file the backend has locked) must not abort
                        # the whole backup; skip it and continue (#4916).
                        skipped += 1
                        logger.warning(
                            "Skipping %s (could not be added to backup): %s",
                            entry,
                            exc,
                        )
                        continue
                    file_count += 1
                if _session_manifest(ws) != manifest:
                    raise RuntimeError(
                        "conversation metadata changed; retry backup",
                    )
            if skipped:
                logger.warning(
                    "Agent '%s': skipped %d file(s) that could not be "
                    "added to the backup",
                    aid,
                    skipped,
                )
            logger.debug(
                "Agent '%s': %d file(s) added from %s",
                aid,
                file_count,
                ws,
            )
        else:
            logger.warning(
                "Agent '%s' workspace directory not found: %s",
                aid,
                ws,
            )

    return not (stop_event and stop_event.is_set())


def add_global_config(zf: zipfile.ZipFile) -> None:
    """Add the global config file to the zip."""
    cfg_src = WORKING_DIR / CONFIG_FILE
    if cfg_src.is_file():
        zf.write(cfg_src, PREFIX_CONFIG)
        logger.info("Global config added to backup: %s", cfg_src)
    else:
        logger.warning(
            "include_global_config=True but config file not found: %s",
            cfg_src,
        )


def add_secrets(zf: zipfile.ZipFile, stop_event=None) -> bool:
    """Add all files from the secrets directory to the zip.

    Returns ``False`` if *stop_event* was set before or during the operation
    (cancelled), ``True`` otherwise.
    """
    if not SECRET_DIR.is_dir():
        logger.warning("Secrets directory not found")
        return True
    file_count = 0
    for entry in sorted(SECRET_DIR.rglob("*")):
        if stop_event and stop_event.is_set():
            return False
        if entry.is_file():
            arcname = (
                f"{PREFIX_SECRETS}{entry.relative_to(SECRET_DIR).as_posix()}"
            )
            zf.write(entry, arcname)
            file_count += 1
    logger.info("Secrets backed up: %d file(s)", file_count)
    return True


def add_skill_pool(zf: zipfile.ZipFile, stop_event=None) -> bool:
    """Add all files from the skill pool directory to the zip.

    Returns ``False`` if *stop_event* was set before or during the operation
    (cancelled), ``True`` otherwise.
    """
    from ...agents.skill_system.store import get_skill_pool_dir

    skill_pool_dir = get_skill_pool_dir()
    if not skill_pool_dir.is_dir():
        logger.warning("Skill pool directory not found: %s", skill_pool_dir)
        return True
    logger.info("Backing up skill pool from %s", skill_pool_dir)
    file_count = 0
    for entry in sorted(skill_pool_dir.rglob("*")):
        if stop_event and stop_event.is_set():
            return False
        if entry.is_file():
            rel = entry.relative_to(skill_pool_dir).as_posix()
            arcname = f"{PREFIX_SKILL_POOL}{rel}"
            logger.debug("  Adding %s", arcname)
            zf.write(entry, arcname)
            file_count += 1
    logger.info("Skill pool backed up: %d file(s)", file_count)
    return True


def add_files_to_zip(
    zf: zipfile.ZipFile,
    meta,
    progress_callback=None,
    stop_event=None,
    valid_agents=None,
) -> list[str]:
    """Add files to zip based on backup scope.

    Args:
        zf: ZipFile object to write to
        meta: Backup metadata with scope information
        progress_callback: Optional callback(current_index, total, agent_id)
        stop_event: Optional threading.Event to support cancellation
        valid_agents: Pre-computed ``(aid, ref)`` pairs to back up.
                      Empty list when meta.scope.include_agents is False.

    Returns:
        List of agent IDs that were backed up, or empty list if cancelled
    """
    if valid_agents is None:
        valid_agents = []

    if valid_agents and not add_agent_workspaces(
        zf,
        valid_agents,
        progress_callback,
        stop_event,
    ):
        return []

    if meta.scope.include_global_config:
        add_global_config(zf)
    if meta.scope.include_secrets:
        if not add_secrets(zf, stop_event):
            return []
    if meta.scope.include_skill_pool:
        if not add_skill_pool(zf, stop_event):
            return []

    return [aid for aid, _ in valid_agents]
