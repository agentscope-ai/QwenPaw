# -*- coding: utf-8 -*-
"""Owned Chromium launch helpers for the direct CDP backend."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Any

from ...errors import BrowserError, ErrorCategory
from ....utils.io_utils import run_sync_io

logger = logging.getLogger(__name__)


def _clear_stale_marker(marker: Path) -> str | None:
    """Remove an old endpoint marker or preserve its content if locked."""
    try:
        marker.unlink(missing_ok=True)
    except OSError as exc:
        try:
            stale_content = marker.read_text(encoding="utf-8")
        except OSError as read_exc:
            raise BrowserError(
                category=ErrorCategory.FATAL,
                suggested_action=(
                    "Close the other Chromium using this profile or use a "
                    "different user_data_dir."
                ),
                reason="DevToolsActivePort is locked and cannot be read",
                detail=str(read_exc),
            ) from read_exc
        logger.warning(
            "DevToolsActivePort could not be removed; waiting for it to "
            "change: %s",
            exc,
        )
        return stale_content
    return None


def spawn_managed_chromium(
    *,
    executable: str,
    user_data_dir: str | Path,
    headless: bool,
    port: int,
    args: list[str],
    runner: Any = subprocess.Popen,
    sink: list[tuple[Any, str | None]] | None = None,
) -> tuple[Any, str | None]:
    """Start Chromium after removing any endpoint marker from an old child."""
    directory = Path(user_data_dir)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    marker = directory / "DevToolsActivePort"
    stale_content = _clear_stale_marker(marker)
    argv = (
        [
            executable,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={directory}",
        ]
        + (["--headless=new"] if headless else [])
        + list(args)
    )
    created = (runner(argv), stale_content)
    if sink is not None:
        sink.append(created)
    return created


async def wait_for_devtools_active_port(
    user_data_dir: str | Path,
    process: Any,
    *,
    retries: int = 100,
    delay: float = 0.1,
    stale_content: str | None = None,
) -> str:
    """Return the endpoint from Chromium's DevToolsActivePort file."""
    marker = Path(user_data_dir) / "DevToolsActivePort"
    for _ in range(retries):
        if process.poll() is not None:
            raise BrowserError(
                category=ErrorCategory.FATAL,
                suggested_action="fatal",
                reason="chromium exited before CDP was ready",
            )
        content = await run_sync_io(_probe_marker, marker)
        if content is not None:
            if content == stale_content:
                await asyncio.sleep(delay)
                continue
            lines = content.splitlines()
            if len(lines) >= 2:
                port, guid_path = lines[:2]
                return f"ws://127.0.0.1:{int(port)}{guid_path}"
        await asyncio.sleep(delay)
    raise BrowserError(
        category=ErrorCategory.RETRYABLE,
        suggested_action="retry",
        reason="CDP endpoint did not become ready",
    )


def _probe_marker(marker: Path) -> str | None:
    """Read the active-port marker, treating an in-flight write as absent."""
    if not marker.is_file():
        return None
    try:
        return marker.read_text(encoding="utf-8")
    except OSError:
        return None
