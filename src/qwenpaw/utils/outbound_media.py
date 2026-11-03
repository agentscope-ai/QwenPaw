# -*- coding: utf-8 -*-
"""Host-owned snapshots created only by already-authorized media tools.

URL consumers must never call ``stage_outbound_file`` to authorize a URL.
Pending delivery pins survive restarts; quota exhaustion fails closed rather
than evicting a file whose platform result is unknown.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from pathlib import Path
import re
import stat
import time
import uuid

from .io_utils import get_sync_path_lock, run_sync_io, write_json_atomic
from .media_paths import local_media_path

OUTBOUND_MEDIA_TTL_SECONDS = 7 * 86400
OUTBOUND_MEDIA_MAX_BYTES = 512 * 1024 * 1024
OUTBOUND_MEDIA_MAX_FILES = 256
logger = logging.getLogger(__name__)


def _root(workspace: Path, *, create: bool = False) -> Path:
    workspace = workspace.resolve()
    if create:
        workspace.mkdir(parents=True, exist_ok=True)
    root = workspace / "media" / "outbound"
    for directory in (root.parent, root):
        if directory.is_symlink():
            raise ValueError("Outbound media directory must not be a symlink")
        if create:
            directory.mkdir(exist_ok=True)
    return root


def _read_state(directory: Path) -> dict:
    state_path = directory / ".state.json"
    if (
        not re.fullmatch(r"[0-9a-f]{32}", directory.name)
        or directory.is_symlink()
        or state_path.is_symlink()
    ):
        raise ValueError("Invalid outbound media state")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if (
        not isinstance(state, dict)
        or state.get("schema") != "qwenpaw.outbound-media.v1"
    ):
        raise ValueError("Invalid outbound media schema")
    name = state["name"]
    if (
        not isinstance(name, str)
        or name in {"", ".", ".."}
        or Path(name).name != name
    ):
        raise ValueError("Invalid outbound media filename")
    if not isinstance(state["pending"], list) or not all(
        isinstance(pin, str) for pin in state["pending"]
    ):
        raise ValueError("Invalid outbound media pins")
    if not isinstance(state["expires_at"], (int, float)) or not math.isfinite(
        state["expires_at"],
    ):
        raise ValueError("Invalid outbound media expiry")
    return state


def _remove(directory: Path, name: str) -> None:
    # Remove only our known files, never recursively sweep workspace media.
    if directory.is_symlink() or (directory / "data").is_symlink():
        raise ValueError("Invalid outbound media directory")
    for path in (
        directory / "data" / name,
        directory / ".part",
        directory / ".state.json",
    ):
        path.unlink(missing_ok=True)
    if (directory / "data").exists():
        (directory / "data").rmdir()
    directory.rmdir()


def _cleanup(root: Path) -> tuple[int, int]:
    total = count = 0
    if not root.exists():
        return total, count
    for directory in root.iterdir():
        if (
            directory.is_symlink()
            or not directory.is_dir()
            or not re.fullmatch(r"[0-9a-f]{32}", directory.name)
        ):
            continue
        try:
            state = _read_state(directory)
            if (directory / "data").is_symlink():
                raise ValueError("Invalid outbound media directory")
            path = directory / "data" / state["name"]
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                continue
            if not state["pending"] and state["expires_at"] <= time.time():
                _remove(directory, state["name"])
                continue
            total += info.st_size
            count += 1
        except (OSError, ValueError, KeyError, TypeError):
            # Corrupt state cannot establish that a pending send is settled.
            # Charge its files against admission without deleting anything.
            for base, dirs, files in os.walk(directory, followlinks=False):
                dirs[:] = [
                    name
                    for name in dirs
                    if not (Path(base) / name).is_symlink()
                ]
                for name in files:
                    path = Path(base) / name
                    if not path.is_symlink():
                        total += path.stat().st_size
            count += 1
    return total, count


def _stage(path: Path, workspace: Path, created: list[Path]) -> Path:
    name = path.name
    path = path.resolve(strict=True)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("Outbound media source must be a regular file")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    with os.fdopen(os.open(path, flags), "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            raise ValueError("Outbound media source must be a regular file")
        resolved = path.resolve()
        if resolved.is_relative_to(workspace.resolve()):
            return resolved
        root = _root(workspace, create=True)
        with get_sync_path_lock(root):
            total, count = _cleanup(root)
            if (
                count >= OUTBOUND_MEDIA_MAX_FILES
                or total + info.st_size > OUTBOUND_MEDIA_MAX_BYTES
            ):
                raise ValueError("Outbound media storage quota exceeded")
            directory = root / uuid.uuid4().hex
            directory.mkdir(mode=0o700)
            created.append(directory)
            destination = directory / "data" / name
            try:
                (directory / "data").mkdir(mode=0o700)
                size = 0
                with (directory / ".part").open("xb") as target:
                    while chunk := source.read(1024 * 1024):
                        size += len(chunk)
                        if total + size > OUTBOUND_MEDIA_MAX_BYTES:
                            raise ValueError(
                                "Outbound media storage quota exceeded",
                            )
                        target.write(chunk)
                (directory / ".part").replace(destination)
                write_json_atomic(
                    directory / ".state.json",
                    {
                        "schema": "qwenpaw.outbound-media.v1",
                        "name": name,
                        "expires_at": time.time() + OUTBOUND_MEDIA_TTL_SECONDS,
                        "pending": [],
                    },
                )
                return destination
            except BaseException:
                _remove(directory, name)
                raise


async def stage_outbound_file(path: Path | str) -> Path:
    """Snapshot an authorized local file before returning an attachment."""
    from ..config.context import get_current_workspace_dir
    from ..constant import WORKING_DIR

    workspace = Path(get_current_workspace_dir() or WORKING_DIR)
    created: list[Path] = []
    try:
        return await run_sync_io(_stage, Path(path), workspace, created)
    except asyncio.CancelledError:
        # run_sync_io waits until handles are closed before cancellation.
        if created and created[0].exists():

            def discard() -> None:
                with get_sync_path_lock(created[0].parent):
                    if created[0].exists():
                        _remove(created[0], Path(path).name)

            await run_sync_io(discard)
        raise


def _update(
    workspace: Path,
    parts: list[dict],
    delivery_id: str,
    pending: bool,
) -> None:
    root = _root(workspace)
    with get_sync_path_lock(root):
        for part in parts:
            kind = part.get("type")
            locator = part.get("data" if kind == "audio" else f"{kind}_url")
            if not isinstance(locator, str) or not (
                local := local_media_path(locator)
            ):
                continue
            path = Path(local).absolute()
            # Merely seeing a local URL grants nothing. Only exact snapshot
            # locations with our metadata can acquire a lifecycle pin.
            directory = path.parent.parent
            if (
                directory.parent != root
                or path.parent.name != "data"
                or path.is_symlink()
            ):
                continue
            if path.parent.is_symlink():
                raise ValueError("Invalid outbound media directory")
            try:
                state = _read_state(directory)
            except FileNotFoundError:
                continue
            if path.name != state["name"]:
                continue
            pins = set(state["pending"])
            if pending:
                pins.add(delivery_id)
            else:
                pins.discard(delivery_id)
                state["expires_at"] = time.time() + OUTBOUND_MEDIA_TTL_SECONDS
            state["pending"] = sorted(pins)
            write_json_atomic(directory / ".state.json", state)


async def update_outbound_media(
    workspace_dir: Path | str | None,
    content_parts: list[dict],
    delivery_id: str,
    *,
    pending: bool,
) -> None:
    """Pin before IPC, or release after a definitive platform outcome."""
    if workspace_dir is not None:
        root = Path(workspace_dir).absolute() / "media" / "outbound"
        candidates = []
        for part in content_parts:
            kind = part.get("type")
            locator = part.get("data" if kind == "audio" else f"{kind}_url")
            if not isinstance(locator, str) or not (
                local := local_media_path(locator)
            ):
                continue
            path = Path(local).absolute()
            if (
                path.parent.name == "data"
                and path.parent.parent.parent == root
                and re.fullmatch(r"[0-9a-f]{32}", path.parent.parent.name)
            ):
                candidates.append(part)
        if not candidates:
            return
        try:
            await run_sync_io(
                _update,
                Path(workspace_dir),
                candidates,
                delivery_id,
                pending,
            )
        except (OSError, ValueError, KeyError, TypeError):
            if pending:
                raise
            # Settlement bookkeeping cannot turn an acknowledged upload into
            # a failure (and an unsafe duplicate retry). Keep its durable pin.
            logger.warning(
                "Could not release outbound media delivery pin",
                exc_info=True,
            )


async def cleanup_outbound_media(workspace_dir: Path | str) -> None:
    """Expire only unpinned snapshots in this workspace's controlled store."""

    def clean() -> None:
        root = _root(Path(workspace_dir))
        with get_sync_path_lock(root):
            _cleanup(root)

    await run_sync_io(clean)
