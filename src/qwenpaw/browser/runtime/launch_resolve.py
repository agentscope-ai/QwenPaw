# -*- coding: utf-8 -*-
"""Resolve operator browser configuration into a concrete launch spec."""

from __future__ import annotations

import os
import sys
from typing import Any, Optional, Tuple


def resolve_launch(
    config: Any,
    *,
    in_container: bool,
    has_display: bool,
    system_default: Tuple[Optional[str], Optional[str]],
    bundled_path: Optional[str],
    prefer_desktop_bundle: bool = False,
) -> dict[str, Any]:
    """Resolve automatic launch fields without reading process state."""
    if config.headless == "true":
        headless = True
    elif config.headless == "false":
        headless = False
    else:
        headless = in_container or not has_display

    default_kind, default_path = system_default
    engine = config.engine
    executable_path = config.executable_path
    if executable_path:
        engine = "chromium" if engine == "auto" else engine
    elif config.channel:
        engine = "chromium" if engine == "auto" else engine
    elif prefer_desktop_bundle:
        # Windows Tauri uses a QwenPaw-managed Playwright cache. Leave the
        # executable unset so Playwright selects the exact driver-matched
        # Chromium revision instead of an arbitrary system browser.
        engine = "chromium" if engine == "auto" else engine
    elif engine == "auto":
        if (
            config.use_system_default
            and not in_container
            and default_kind == "chromium"
            and default_path
        ):
            engine, executable_path = "chromium", default_path
        else:
            engine, executable_path = "chromium", bundled_path

    return {
        "headless": headless,
        "engine": engine,
        "executable_path": executable_path,
        "channel": config.channel,
        "args": list(config.args),
        "viewport": config.viewport,
        "proxy": config.proxy,
        "user_data_dir": config.user_data_dir,
        "backend": config.backend,
        "cdp_url": config.cdp_url,
        "cdp_port": config.cdp_port,
        "remote_debugging_port": config.cdp_port,
    }


def _has_display(in_container: bool) -> bool:
    """Return whether a headed browser can be displayed in this environment."""
    if in_container:
        return False
    if sys.platform in ("darwin", "win32"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def resolve_launch_env(config: Any) -> dict[str, Any]:
    """Resolve a launch spec using the current machine's browser facts."""
    from ...config.utils import (
        get_playwright_chromium_executable_path,
        get_system_default_browser,
        is_running_in_container,
    )

    in_container = is_running_in_container()
    prefer_desktop_bundle = (
        os.environ.get("QWENPAW_DESKTOP_MANAGED_PLAYWRIGHT") == "1"
    )
    return resolve_launch(
        config,
        in_container=in_container,
        has_display=_has_display(in_container),
        system_default=get_system_default_browser(),
        bundled_path=get_playwright_chromium_executable_path(),
        prefer_desktop_bundle=prefer_desktop_bundle,
    )
