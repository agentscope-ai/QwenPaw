# -*- coding: utf-8 -*-
"""Provision the driver-matched Playwright browser for Windows Desktop.

The packaged Windows application intentionally does not contain Chromium:
placing the full browser cache in the NSIS payload crosses NSIS's practical
single-file mapping limit. Instead, the frozen backend keeps an app-private
cache and asks its already-bundled Playwright driver to install the matching
revision in the background.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path

from ...constant import WORKING_DIR
from ...tauri.env import DESKTOP_MANAGED_PLAYWRIGHT_ENV

logger = logging.getLogger(__name__)

_PLAYWRIGHT_BROWSERS_PATH_ENV = "PLAYWRIGHT_BROWSERS_PATH"
_download_task: asyncio.Task[None] | None = None
_last_download_error = ""


def desktop_managed_playwright_enabled() -> bool:
    """Return whether this process must use QwenPaw's managed browser cache."""
    return os.environ.get(DESKTOP_MANAGED_PLAYWRIGHT_ENV) == "1"


def configure_desktop_playwright_cache() -> None:
    """Set an app-private cache before browser workers inherit it."""
    if not desktop_managed_playwright_enabled():
        return
    os.environ.setdefault(
        _PLAYWRIGHT_BROWSERS_PATH_ENV,
        str(WORKING_DIR / "browser" / "playwright"),
    )


def _cache_dir() -> Path:
    return Path(
        os.environ.get(
            _PLAYWRIGHT_BROWSERS_PATH_ENV,
            str(WORKING_DIR / "browser" / "playwright"),
        ),
    ).expanduser()


def _required_browser_directories() -> tuple[str, ...]:
    """Return cache directory names needed for headed and headless Chromium."""
    from playwright._impl._driver import compute_driver_executable

    _node, cli = compute_driver_executable()
    manifest = Path(cli).parent / "browsers.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    required: list[str] = []
    for browser in data.get("browsers", []):
        if browser.get("name") in {"chromium", "chromium-headless-shell"}:
            revision = browser.get("revision")
            if isinstance(revision, str) and revision:
                name = str(browser["name"]).replace("-", "_")
                required.append(f"{name}-{revision}")
    if len(required) != 2:
        raise RuntimeError(
            "Playwright driver has incomplete Chromium metadata",
        )
    return tuple(required)


def managed_chromium_ready() -> bool:
    """Return whether this driver's exact Chromium revision is available."""
    if not desktop_managed_playwright_enabled():
        return True
    try:
        cache_dir = _cache_dir()
        return all(
            (cache_dir / directory).is_dir()
            for directory in _required_browser_directories()
        )
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError):
        logger.warning(
            "Could not inspect the managed Playwright cache",
            exc_info=True,
        )
        return False


def _trim_output(output: bytes) -> str:
    text = output.decode("utf-8", errors="replace").strip()
    return text[-4000:] if len(text) > 4000 else text


async def _download_chromium() -> None:
    """Install Chromium through Playwright's bundled Node driver."""
    global _last_download_error

    from playwright._impl._driver import (
        compute_driver_executable,
        get_driver_env,
    )

    cache_dir = _cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    node, cli = compute_driver_executable()
    env = get_driver_env()
    env[_PLAYWRIGHT_BROWSERS_PATH_ENV] = str(cache_dir)
    logger.info("Installing managed Playwright Chromium into %s", cache_dir)
    process = await asyncio.create_subprocess_exec(
        node,
        cli,
        "install",
        "chromium",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await process.communicate()
    except asyncio.CancelledError:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            await process.wait()
        raise
    if process.returncode:
        detail = _trim_output(output)
        raise RuntimeError(
            "Playwright Chromium download failed"
            + (f": {detail}" if detail else ""),
        )
    if not managed_chromium_ready():
        raise RuntimeError(
            "Playwright Chromium download did not create its cache",
        )
    _last_download_error = ""
    logger.info("Managed Playwright Chromium is ready")


async def _download_and_record() -> None:
    """Run one download and retain a concise diagnostic for the next retry."""
    global _last_download_error
    try:
        await _download_chromium()
    except Exception as exc:  # noqa: BLE001 - report installer diagnostics
        _last_download_error = str(exc)
        logger.warning("Managed Playwright Chromium install failed: %s", exc)


def start_managed_chromium_download() -> tuple[bool, str]:
    """Ensure one background Chromium download is running.

    Returns ``(ready, detail)``. A false ``ready`` value means that the caller
    must report a retryable preparation state instead of waiting inside a
    browser execution request.
    """
    global _download_task, _last_download_error

    if not desktop_managed_playwright_enabled() or managed_chromium_ready():
        return True, ""
    if _download_task is not None and not _download_task.done():
        return False, _last_download_error
    previous_error = _last_download_error
    _last_download_error = ""
    _download_task = asyncio.create_task(_download_and_record())
    return False, previous_error


async def stop_managed_chromium_download() -> None:
    """Stop an in-flight installer while the desktop backend shuts down."""
    global _download_task

    task = _download_task
    _download_task = None
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
