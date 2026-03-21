# -*- coding: utf-8 -*-
"""Desktop/screen screenshot tool."""

import json
import os
import platform
import subprocess
import tempfile
import time

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse


def _tool_error(msg: str) -> ToolResponse:
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(
                    {"ok": False, "error": msg},
                    ensure_ascii=False,
                    indent=2,
                ),
            ),
        ],
    )


def _tool_ok(path: str, message: str) -> ToolResponse:
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(
                    {
                        "ok": True,
                        "path": os.path.abspath(path),
                        "message": message,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            ),
        ],
    )


def _capture_mss(path: str) -> ToolResponse:
    """Full-screen capture using mss (Windows, Linux, macOS)."""
    try:
        import mss
    except ImportError:
        return _tool_error(
            "desktop_screenshot requires the 'mss' package. "
            "Install with: pip install mss",
        )
    try:
        with mss.mss() as sct:
            # mon=0: all monitors combined
            sct.shot(mon=0, output=path)
        if not os.path.isfile(path):
            return _tool_error("mss reported success but file was not created")
        return _tool_ok(path, f"Desktop screenshot saved to {path}")
    except Exception as e:
        return _tool_error(f"desktop_screenshot (mss) failed: {e!s}")


def _capture_macos_screencapture(
    path: str,
    capture_window: bool,
) -> ToolResponse:
    """macOS: screencapture (supports window selection with -w)."""
    cmd = ["screencapture", "-x", path]
    if capture_window:
        cmd.insert(-1, "-w")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip() or "Unknown error"
            return _tool_error(f"screencapture failed: {stderr}")
        if not os.path.isfile(path):
            return _tool_error(
                "screencapture reported success but file was not created",
            )
        return _tool_ok(path, f"Desktop screenshot saved to {path}")
    except subprocess.TimeoutExpired:
        return _tool_error(
            "screencapture timed out (e.g. window selection cancelled)",
        )
    except Exception as e:
        return _tool_error(f"desktop_screenshot failed: {e!s}")


async def desktop_screenshot(
    path: str = "",
    capture_window: bool = False,
) -> ToolResponse:
    """Capture a screenshot of the entire desktop (all monitors)
        or a single window.

    Supported platforms: Windows, Linux, macOS. Full-screen
    capture uses the mss library on all platforms.
    On macOS, capture_window=True uses the system screencapture
    tool to let the user click a window to capture.

    Args:
        path (`str`):
            Optional path to save the screenshot. If empty, saves to a temp
            file and returns that path. Should end in .png for PNG output.
        capture_window (`bool`):
            If True on macOS, the user can click a window to capture just
            that window. On Windows/Linux, only full-screen is supported
            (capture_window is ignored).

    Returns:
        `ToolResponse`:
            JSON with "ok", "path" (saved file path), and optional "message"
            or "error".
    """
    path = (path or "").strip()
    if not path:
        path = os.path.join(
            tempfile.gettempdir(),
            f"desktop_screenshot_{int(time.time())}.png",
        )
    if not path.lower().endswith(".png"):
        path = path.rstrip("/\\") + ".png"

    system = platform.system()

    # macOS: optional window selection via screencapture -w
    if system == "Darwin" and capture_window:
        return _capture_macos_screencapture(path, capture_window=True)

    # Full-screen on all platforms (macOS, Linux, Windows) via mss
    return _capture_mss(path)
