# -*- coding: utf-8 -*-
"""Provision the driver-matched Playwright browser for Windows Desktop.

The packaged Windows application intentionally does not contain Chromium:
placing the full browser cache in the NSIS payload crosses NSIS's practical
single-file mapping limit. Instead, the frozen backend keeps an app-private
cache and asks its already-bundled Playwright driver to install the matching
revision in the background.

Readiness depends on Playwright's internal INSTALLATION_COMPLETE marker
files (verified against 1.59.0). Revisit this when upgrading Playwright.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from pathlib import Path

from ...constant import WORKING_DIR
from ...tauri.env import DESKTOP_MANAGED_PLAYWRIGHT_ENV

logger = logging.getLogger(__name__)

_PLAYWRIGHT_BROWSERS_PATH_ENV = "PLAYWRIGHT_BROWSERS_PATH"
_FAILURE_COOLDOWN_SECONDS = 60.0
_IN_FLIGHT_RETRY_SECONDS = 15.0
_INSTALL_TIMEOUT_SECONDS = 600.0
_PROCESS_STOP_TIMEOUT_SECONDS = 5.0
_INSTALL_MARKER = "INSTALLATION_COMPLETE"
_download_task: asyncio.Task[None] | None = None
_install_process: asyncio.subprocess.Process | None = None
_last_download_error = ""
_last_failure_at = 0.0


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
            (cache_dir / directory / _INSTALL_MARKER).is_file()
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


async def _stop_install_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        process.terminate()
    try:
        await asyncio.wait_for(
            process.wait(),
            timeout=_PROCESS_STOP_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        pass
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        process.kill()
    try:
        await asyncio.wait_for(
            process.wait(),
            timeout=_PROCESS_STOP_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        pass
    if process.returncode is None:
        logger.warning(
            "Managed Playwright installer pid=%s did not exit "
            "after terminate/kill",
            getattr(process, "pid", None),
        )


def _install_process_alive() -> bool:
    global _install_process
    process = _install_process
    if process is None:
        return False
    if process.returncode is not None:
        _install_process = None
        return False
    return True


async def _download_chromium() -> None:
    """Install Chromium through Playwright's bundled Node driver."""
    from playwright._impl._driver import (
        compute_driver_executable,
        get_driver_env,
    )

    global _install_process

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
    _install_process = process
    try:
        output, _ = await asyncio.wait_for(
            process.communicate(),
            timeout=_INSTALL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        await _stop_install_process(process)
        raise RuntimeError("Playwright Chromium download timed out") from None
    except asyncio.CancelledError:
        await _stop_install_process(process)
        raise
    finally:
        if process.returncode is not None:
            _install_process = None
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
    logger.info("Managed Playwright Chromium is ready")


async def _download_and_record() -> None:
    """Run one download and retain a concise diagnostic for the next retry."""
    global _last_download_error, _last_failure_at
    try:
        await _download_chromium()
    except Exception as exc:  # noqa: BLE001 - report installer diagnostics
        _last_download_error = str(exc) or "install failed"
        _last_failure_at = time.monotonic()
        logger.warning("Managed Playwright Chromium install failed: %s", exc)
    else:
        _last_download_error = ""
        _last_failure_at = 0.0


def _cooldown_remaining() -> float:
    if _last_failure_at <= 0:
        return 0.0
    return max(
        0.0,
        _FAILURE_COOLDOWN_SECONDS - (time.monotonic() - _last_failure_at),
    )


def start_managed_chromium_download() -> tuple[bool, str]:
    """Ensure one background Chromium download is running.

    Returns ``(ready, detail)``. A false ``ready`` value means Chromium is
    not yet available; ``ensure_managed_chromium`` reports how long to wait
    before retrying.
    """
    global _download_task, _last_download_error

    if not desktop_managed_playwright_enabled():
        return True, ""
    if managed_chromium_ready():
        return True, ""
    if _download_task is not None and not _download_task.done():
        return False, ""
    if _install_process_alive():
        leftover = (
            _last_download_error or "previous install process still running"
        )
        return False, leftover
    if _cooldown_remaining() > 0:
        return False, _last_download_error or "install failed"
    _download_task = asyncio.create_task(_download_and_record())
    _last_download_error = ""
    return False, ""


def ensure_managed_chromium() -> tuple[bool, str, float]:
    """Start a managed download if needed and return immediately.

    Returns ``(ready, detail, retry_after)``. When not ready, *retry_after*
    is seconds the caller should wait: an in-flight install uses a short
    poll interval, a failed install uses remaining cooldown.
    """
    ready, detail = start_managed_chromium_download()
    if ready:
        return True, "", 0.0
    if _download_task is not None and not _download_task.done():
        return False, "", _IN_FLIGHT_RETRY_SECONDS
    if _install_process_alive() or _last_failure_at > 0:
        retry_after = max(_cooldown_remaining(), 1.0)
        if _install_process_alive():
            retry_after = max(retry_after, _IN_FLIGHT_RETRY_SECONDS)
        return (
            False,
            detail or _last_download_error or "install failed",
            retry_after,
        )
    return False, "", 1.0


async def stop_managed_chromium_download() -> None:
    """Stop an in-flight installer while the desktop backend shuts down."""
    global _download_task, _install_process

    task = _download_task
    _download_task = None
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        # CancelledError is BaseException; catch everything during shutdown.
        except BaseException:  # noqa: BLE001
            pass
    # Cancelled tasks already stop their own installer; this second pass is
    # idempotent and covers only leftovers whose task is done.
    process = _install_process
    if process is None:
        return
    await _stop_install_process(process)
    if process.returncode is not None:
        _install_process = None
