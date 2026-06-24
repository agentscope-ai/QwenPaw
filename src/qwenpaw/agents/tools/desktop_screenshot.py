# -*- coding: utf-8 -*-
"""Desktop/screen screenshot tool."""

import json
import os
import platform
import time
import mimetypes
from agentscope.message import DataBlock, TextBlock, URLSource
from agentscope.tool import ToolChunk
from agentscope.message import ToolResultState

from ...config.context import get_current_workspace_dir
from ...constant import WORKING_DIR
from ...runtime.tool_registry import tool_descriptor
from .file_io import _path_to_file_url


def _tool_error(msg: str) -> ToolChunk:
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
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


def _tool_ok(path: str, message: str) -> ToolChunk:
    file_url = _path_to_file_url(path)
    mime_type, _ = mimetypes.guess_type(path)
    if mime_type is None:
        mime_type = "image/*"
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[
            DataBlock(
                source=URLSource(
                    url=file_url,
                    media_type=mime_type,
                ),
                name=os.path.basename(path),
            ),
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


def _capture_mss(path: str) -> ToolChunk:
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


async def _capture_macos_screencapture(
    path: str,
    capture_window: bool,
) -> ToolChunk:
    """macOS: screencapture (supports window selection with -w)."""
    import asyncio

    from ...tool_calls import cancellable_wait

    cmd = ["screencapture", "-x", path]
    if capture_window:
        cmd.insert(-1, "-w")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await cancellable_wait(
            proc.communicate(),
            fallback_secs=30,
        )
        if proc.returncode != 0:
            stderr_str = (stderr or b"").decode().strip() or "Unknown error"
            return _tool_error(f"screencapture failed: {stderr_str}")
        if not os.path.isfile(path):
            return _tool_error(
                "screencapture reported success but file was not created",
            )
        return _tool_ok(path, f"Desktop screenshot saved to {path}")
    except (asyncio.TimeoutError, asyncio.CancelledError):
        return _tool_error(
            "screencapture timed out (e.g. window selection cancelled)",
        )
    except Exception as e:
        return _tool_error(f"desktop_screenshot failed: {e!s}")


@tool_descriptor(requires_sandbox=("file_write",), async_execution=True)
async def desktop_screenshot(
    path: str = "",
    capture_window: bool = False,
) -> ToolChunk:
    """Capture a screenshot of the entire desktop (all monitors)
        or a single window.

    Supported platforms: Windows, Linux, macOS. Full-screen
    capture uses the mss library on all platforms.
    On macOS, capture_window=True uses the system screencapture
    tool to let the user click a window to capture.

    Args:
        path (`str`):
            Optional path to save the screenshot. If empty, saves under
            the current workspace directory. Should end in .png for PNG output.
        capture_window (`bool`):
            If True on macOS, the user can click a window to capture just
            that window. On Windows/Linux, only full-screen is supported
            (capture_window is ignored).

    Returns:
        `ToolChunk`:
            JSON with "ok", "path" (saved file path), and optional "message"
            or "error".
    """
    path = (path or "").strip()
    if not path:
        base_dir = get_current_workspace_dir() or WORKING_DIR
        path = str(base_dir / f"desktop_screenshot_{int(time.time())}.png")
    if not path.lower().endswith(".png"):
        path = path.rstrip("/\\") + ".png"

    system = platform.system()

    # macOS: optional window selection via screencapture -w
    if system == "Darwin" and capture_window:
        return await _capture_macos_screencapture(path, capture_window=True)

    # Full-screen on all platforms (macOS, Linux, Windows) via mss
    return _capture_mss(path)
