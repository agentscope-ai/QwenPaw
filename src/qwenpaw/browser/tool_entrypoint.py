# -*- coding: utf-8 -*-
"""Wire-only control-plane entrypoint for the Browser SDK tool."""

from __future__ import annotations

import atexit
import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from ..config.context import (
    get_current_session_id,
    get_current_workspace_dir,
)
from ..constant import WORKING_DIR
from ..utils.io_utils import (
    make_dirs_async,
    read_bytes_async,
    unlink_async,
    write_bytes_async,
)
from .control_link.chrome.observe import (
    collect_self_test_async,
    render_repair_text,
)
from .handoff_signal import set_pending
from .execution.kernel import get_default_kernel_manager
from .execution.wire import ExecRequest

logger = logging.getLogger(__name__)


async def relocate_overflow_output_async(error: dict) -> dict:
    """Move worker-staged stdout into the active workspace for the model."""
    resolved = dict(error)
    staged_value = resolved.pop("overflow_stdout_path", None)
    if not staged_value:
        return resolved
    staged = Path(str(staged_value))
    try:
        contents = await read_bytes_async(staged)
    except OSError:
        teaching = str(resolved.get("teaching") or "").strip()
        resolved["teaching"] = (
            f"{teaching} The full output was lost; re-run this step."
        ).strip()
        return resolved
    directory = get_current_workspace_dir() or (
        WORKING_DIR / "workspaces" / "default"
    )
    directory = Path(directory).expanduser()
    await make_dirs_async(directory)
    digest = hashlib.sha256(contents).hexdigest()
    target = directory / f"browser_output_{digest[:8]}.txt"
    await write_bytes_async(target, contents)
    await unlink_async(staged)
    teaching = str(resolved.get("teaching") or "").strip()
    resolved["teaching"] = (
        f"{teaching} Full output saved to {target.resolve()}; read it with "
        "Read or Grep."
    ).strip()
    return resolved


def render_error_text(error: dict, stdout: str) -> str:
    """Render all error facts without allowing teaching to hide detail."""
    if error.get("cause") == "internal":
        logger.error(
            "browser.sdk.internal_error reason=%s detail=%s",
            error.get("reason"),
            error.get("detail"),
        )
    parts = [f"[{error.get('category')}] {error.get('reason')}"]
    detail = str(error.get("detail") or "").strip()
    teaching = str(error.get("teaching") or "").strip()
    if detail and detail not in teaching:
        parts.append(detail)
    if teaching:
        parts.append(teaching)
    text = "\n".join(parts)
    if stdout:
        text = f"{text}\n\n[stdout]\n{stdout}"
    return text


def _is_chrome_unavailable(error: dict) -> bool:
    """Return whether an error reflects a disconnected Chrome bridge."""
    return str(error.get("browser_error_code", "")) == "bridge_disconnected"


def derive_workspace_id(workspace_dir: Path | None) -> str:
    """Return a stable execution key for one controlled workspace path."""
    if workspace_dir is None:
        return "default"
    resolved = str(workspace_dir.expanduser().resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


_BROWSER_TOOL_DESCRIPTION = (
    "Drive a live browser by writing async Python against QwenPaw's "
    "built-in\nBrowser SDK. Your code runs in a Python runtime and the "
    "SDK is already\nin scope as Browser. Begin every session with:\n"
    "    browser = await Browser.connect()\n"
    '    page = await browser.open("https://example.com")\n\n'
    "The complete, authoritative reference ships with the browser skill. "
    "The API surface is closed: anything not listed does not exist. Re-load "
    "the browser skill (Skill tool) after context compaction.\n\n"
    "Work in a loop: read page state with await page.snapshot(), act "
    "through\nsemantic locators, and re-snapshot to confirm. For login, "
    "captcha, or 2FA,\ncall await browser.handoff(...) and stop.\n\n"
    "Arg: code — module-level async Python (await; return a value or "
    "print())."
)


async def run_browser_tool(code: str = "", **legacy: Any) -> ToolChunk:
    """Send one browser program to its workspace subprocess worker."""
    if "action" in legacy or (not code and legacy):
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "These parameters belong to the stable-track browser "
                        "tool. This is the unified browser: pass `code=` with "
                        "module-level async Python."
                    ),
                ),
            ],
        )
    session_id = get_current_session_id() or "default"
    request = ExecRequest(
        request_id=uuid.uuid4().hex,
        code=code,
        owner_workspace_id=derive_workspace_id(get_current_workspace_dir()),
        owner_session_id=session_id,
    )
    outcome = await get_default_kernel_manager().execute(request)
    if outcome.error is not None:
        error = await relocate_overflow_output_async(outcome.error)
        text = render_error_text(error, outcome.stdout or "")
        if _is_chrome_unavailable(error):
            self_test = await collect_self_test_async()
            text = f"{text}\n{render_repair_text(self_test)}"
        chunk = ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[TextBlock(type="text", text=text)],
        )
    else:
        if outcome.handoff:
            reason = str(outcome.handoff.get("reason", ""))
            instructions = str(outcome.handoff.get("instructions", ""))
            set_pending(
                session_id,
                {"reason": reason, "instructions": instructions},
            )
            get_default_kernel_manager().mark_handoff_pending(
                derive_workspace_id(get_current_workspace_dir()),
                session_id,
            )
            text = (
                f"Handoff requested: {reason}\n{instructions}\n"
                "Stopping so a human can take over."
            )
        else:
            text = (
                outcome.value
                if isinstance(outcome.value, str)
                else str(outcome.value or "")
            )
        chunk = ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[TextBlock(type="text", text=text)],
        )
        if outcome.stdout:
            chunk.content.append(
                TextBlock(type="text", text=f"[stdout]\n{outcome.stdout}"),
            )
    return chunk


def _atexit_cleanup() -> None:
    try:
        from .execution import kernel

        manager = kernel._MANAGER  # pylint: disable=protected-access
        if manager is not None:
            manager.discard_all_workers_sync()
    # intentional boundary: process-exit cleanup must not block shutdown.
    except Exception:
        pass


atexit.register(_atexit_cleanup)
