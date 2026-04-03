# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Browser automation tool using Playwright.

Single tool with action-based API matching browser MCP: start, stop, open,
navigate, navigate_back, screenshot, snapshot, click, type, eval, evaluate,
resize, console_messages, handle_dialog, file_upload, fill_form, install,
press_key, network_requests, run_code, drag, hover, select_option, tabs,
wait_for, pdf, close. Uses refs from snapshot for ref-based actions.
"""

import asyncio
import atexit
from concurrent import futures
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config import (
    get_playwright_chromium_executable_path,
    get_system_default_browser,
    is_running_in_container,
)
from ...config.context import get_current_workspace_dir
from ...constant import WORKING_DIR

from .browser_snapshot import build_role_snapshot_from_aria

logger = logging.getLogger(__name__)


def _resolve_output_path(path: str) -> str:
    """Resolve relative output paths under workspace_dir/browser/."""
    if Path(path).is_absolute():
        return path
    base_dir = (get_current_workspace_dir() or WORKING_DIR) / "browser"
    base_dir.mkdir(parents=True, exist_ok=True)
    return str(base_dir / path)


# Hybrid mode detection: Windows + Uvicorn reload mode requires sync Playwright
# to avoid NotImplementedError with asyncio.create_subprocess_exec.
# On other platforms or without reload, use async Playwright for better performance.
_USE_SYNC_PLAYWRIGHT = (
    sys.platform == "win32" and os.environ.get("COPAW_RELOAD_MODE") == "1"
)

if _USE_SYNC_PLAYWRIGHT:
    _executor: Optional[futures.ThreadPoolExecutor] = None

    def _get_executor() -> futures.ThreadPoolExecutor:
        global _executor
        if _executor is None:
            _executor = futures.ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="playwright",
            )
        return _executor

    async def _run_sync(func, *args, **kwargs):
        """Run a sync function in the thread pool and await the result."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _get_executor(),
            lambda: func(*args, **kwargs),
        )

else:

    async def _run_sync(func, *args, **kwargs):
        """Fallback: directly call async function (should not be used in async mode)."""
        return await func(*args, **kwargs)


# Per-workspace browser states: workspace_id -> state dict
_workspace_states: dict[str, dict[str, Any]] = {}


def _make_fresh_state(workspace_id: str, workspace_dir: str) -> dict[str, Any]:
    """Create a fresh browser state dict for a workspace."""
    user_data_dir = (
        str(Path(workspace_dir) / "browser" / "user_data")
        if workspace_dir
        else ""
    )
    return {
        "playwright": None,
        "browser": None,
        "context": None,
        "_sync_playwright": None,
        "_sync_browser": None,
        "_sync_context": None,
        "pages": {},
        "refs": {},  # page_id -> ref -> {role, name?, nth?}
        "refs_frame": {},  # page_id -> frame for last snapshot
        "console_logs": {},  # page_id -> list of {level, text}
        "network_requests": {},  # page_id -> list of request dicts
        "pending_dialogs": {},  # page_id -> dialog handlers
        "pending_file_choosers": {},  # page_id -> FileChooser list
        "headless": True,
        "current_page_id": None,
        "page_counter": 0,  # monotonic counter for page_N ids, avoids reuse after close
        "last_activity_time": 0.0,  # monotonic timestamp of last browser activity
        "_idle_task": None,  # background asyncio.Task for idle watchdog
        "_last_browser_error": None,  # message when launch failed (for user-facing error)
        "workspace_id": workspace_id,
        "user_data_dir": user_data_dir,
        "connected_via_cdp": False,
        "cdp_url": None,
    }


def _get_workspace_state(
    workspace_id: str,
    workspace_dir: str = "",
) -> dict[str, Any]:
    """Get or create the browser state for a workspace."""
    if workspace_id not in _workspace_states:
        _workspace_states[workspace_id] = _make_fresh_state(
            workspace_id,
            workspace_dir,
        )
    return _workspace_states[workspace_id]


# Stop the browser after this many seconds of inactivity (default 30 minutes).
_BROWSER_IDLE_TIMEOUT = 1800.0


def _touch_activity(state: dict) -> None:
    """Record the current time as the last browser activity timestamp."""
    state["last_activity_time"] = time.monotonic()


def _is_browser_running(state: dict) -> bool:
    """Check if browser is currently running (sync or async mode)."""
    if _USE_SYNC_PLAYWRIGHT:
        return state.get("_sync_browser") is not None
    return state.get("browser") is not None or state.get("context") is not None


def _reset_browser_state(state: dict) -> None:
    """Reset all browser-related state variables."""
    # Clear sync/async specific state
    state["playwright"] = None
    state["browser"] = None
    state["context"] = None
    state["_sync_playwright"] = None
    state["_sync_browser"] = None
    state["_sync_context"] = None
    # Clear shared state
    state["pages"].clear()
    state["refs"].clear()
    state["refs_frame"].clear()
    state["console_logs"].clear()
    state["network_requests"].clear()
    state["pending_dialogs"].clear()
    state["pending_file_choosers"].clear()
    state["current_page_id"] = None
    state["page_counter"] = 0
    state["last_activity_time"] = 0.0
    state["headless"] = True
    state["connected_via_cdp"] = False
    state["cdp_url"] = None


async def _idle_watchdog(
    state: dict,
    idle_seconds: float = _BROWSER_IDLE_TIMEOUT,
) -> None:
    """Background task: stop the browser after it has been idle for *idle_seconds*.

    This reclaims Chrome renderer processes that accumulate when pages are
    opened during agent tasks but never explicitly closed.
    """
    try:
        while True:
            await asyncio.sleep(60)  # check every minute
            if not _is_browser_running(state):
                return
            idle = time.monotonic() - state.get("last_activity_time", 0.0)
            if idle >= idle_seconds:
                logger.info(
                    "Browser idle for %.0fs (limit %.0fs), stopping to release resources",
                    idle,
                    idle_seconds,
                )
                await _action_stop(state)
                return
    except asyncio.CancelledError:
        pass


def _atexit_cleanup() -> None:
    """Best-effort browser cleanup registered with :func:`atexit`.

    Playwright child processes are cleaned up by the OS when the parent
    exits, but this gives Playwright a chance to flush any pending I/O and
    close Chrome gracefully before the process disappears.
    """
    if not _workspace_states:
        return

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running() or loop.is_closed():
            return
        for ws_state in list(_workspace_states.values()):
            if _is_browser_running(ws_state):
                try:
                    loop.run_until_complete(_action_stop(ws_state))
                except Exception:
                    pass
    except Exception:
        pass


atexit.register(_atexit_cleanup)


def _tool_response(text: str) -> ToolResponse:
    """Wrap text for agentscope Toolkit (return ToolResponse)."""
    return ToolResponse(
        content=[TextBlock(type="text", text=text)],
    )


def _chromium_launch_args() -> list[str]:
    """Extra args for Chromium when running in container."""
    if is_running_in_container():
        return ["--no-sandbox", "--disable-dev-shm-usage"]
    return []


def _chromium_executable_path() -> str | None:
    """Chromium executable path when set (e.g. container); else None."""
    return get_playwright_chromium_executable_path()


def _use_webkit_fallback() -> bool:
    """True only on macOS when no system Chrome/Edge/Chromium found.
    Use WebKit (Safari) to avoid downloading Chromium. Windows has no system
    WebKit, so we never use webkit there.
    """
    return sys.platform == "darwin" and _chromium_executable_path() is None


def _ensure_playwright_async():
    """Import async_playwright; raise ImportError with hint if missing."""
    try:
        from playwright.async_api import async_playwright

        return async_playwright
    except ImportError as exc:
        raise ImportError(
            "Playwright not installed. Use the same Python that runs CoPaw (e.g. "
            "activate your venv or use 'uv run'): "
            f"'{sys.executable}' -m pip install playwright && "
            f"'{sys.executable}' -m playwright install",
        ) from exc


def _ensure_playwright_sync():
    """Import sync_playwright; raise ImportError with hint if missing."""
    try:
        from playwright.sync_api import sync_playwright

        return sync_playwright
    except ImportError as exc:
        raise ImportError(
            "Playwright not installed. Use the same Python that runs CoPaw (e.g. "
            "activate your venv or use 'uv run'): "
            f"'{sys.executable}' -m pip install playwright && "
            f"'{sys.executable}' -m playwright install",
        ) from exc


def _sync_browser_launch(state: dict, cdp_port: int = 0):
    """Launch browser using sync Playwright (for hybrid mode)."""
    sync_playwright = _ensure_playwright_sync()
    pw = sync_playwright().start()  # Start without context manager
    use_default = not is_running_in_container() and os.environ.get(
        "COPAW_BROWSER_USE_DEFAULT",
        "1",
    ).strip().lower() in ("1", "true", "yes")
    default_kind, default_path = (
        get_system_default_browser() if use_default else (None, None)
    )
    exe: Optional[str] = None
    if default_kind == "chromium" and default_path:
        exe = default_path
    elif default_kind != "webkit":
        exe = _chromium_executable_path()

    extra_args = list(_chromium_launch_args())
    if cdp_port:
        extra_args.append(f"--remote-debugging-port={cdp_port}")

    if exe:
        user_data_dir = state["user_data_dir"]
        if user_data_dir:
            Path(user_data_dir).mkdir(parents=True, exist_ok=True)
            context = pw.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=state["headless"],
                executable_path=exe,
                args=extra_args if extra_args else [],
            )
            _attach_context_listeners(state, context)
            return pw, None, context
        launch_kwargs = {"headless": state["headless"]}
        if extra_args:
            launch_kwargs["args"] = extra_args
        launch_kwargs["executable_path"] = exe
        browser = pw.chromium.launch(**launch_kwargs)
    elif default_kind == "webkit" or sys.platform == "darwin":
        browser = pw.webkit.launch(headless=state["headless"])
    else:
        launch_kwargs = {"headless": state["headless"]}
        if extra_args:
            launch_kwargs["args"] = extra_args
        browser = pw.chromium.launch(**launch_kwargs)

    context = browser.new_context()
    _attach_context_listeners(state, context)
    return pw, browser, context


def _sync_browser_close(state: dict):
    """Close browser using sync Playwright (for hybrid mode)."""
    if state["_sync_browser"] is not None:
        try:
            state["_sync_browser"].close()
        except Exception:
            pass
    elif state["_sync_context"] is not None:
        # persistent context mode: no separate browser object, close context directly
        try:
            state["_sync_context"].close()
        except Exception:
            pass
    if state["_sync_playwright"] is not None:
        try:
            state["_sync_playwright"].stop()
        except Exception:
            pass


def _parse_json_param(value: str, default: Any = None):
    """Parse optional JSON string param (e.g. fields, paths, values)."""
    if not value or not isinstance(value, str):
        return default
    value = value.strip()
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        if "," in value:
            return [x.strip() for x in value.split(",")]
        return default


def _get_page(state: dict, page_id: str):
    """Return page for page_id or None if not found."""
    return state["pages"].get(page_id)


def _get_context(state: dict):
    """Return the active browser context regardless of sync/async mode."""
    return state["context"] or state.get("_sync_context")


def _get_refs(state: dict, page_id: str) -> dict[str, dict]:
    """Return refs map for page_id (ref -> {role, name?, nth?})."""
    return state["refs"].setdefault(page_id, {})


def _get_root(page, frame_selector: str = ""):
    """Return page or frame for frame_selector (ref/selector)."""
    if not (frame_selector and frame_selector.strip()):
        return page
    return page.frame_locator(frame_selector.strip())


def _get_locator_by_ref(
    state: dict,
    page,
    page_id: str,
    ref: str,
    frame_selector: str = "",
):
    """Resolve snapshot ref to locator; frame_selector for iframe."""
    refs = _get_refs(state, page_id)
    info = refs.get(ref)
    if not info:
        return None
    role = info.get("role", "generic")
    name = info.get("name")
    nth = info.get("nth", 0)
    root = _get_root(page, frame_selector)
    locator = root.get_by_role(role, name=name or None)
    if nth is not None and nth > 0:
        locator = locator.nth(nth)
    return locator


def _attach_page_listeners(state: dict, page, page_id: str) -> None:
    """Attach console and request listeners for a page."""
    logs = state["console_logs"].setdefault(page_id, [])

    def on_console(msg):
        logs.append({"level": msg.type, "text": msg.text})

    page.on("console", on_console)
    requests_list = state["network_requests"].setdefault(page_id, [])

    def on_request(req):
        requests_list.append(
            {
                "url": req.url,
                "method": req.method,
                "resourceType": getattr(req, "resource_type", None),
            },
        )

    def on_response(res):
        for r in requests_list:
            if r.get("url") == res.url and "status" not in r:
                r["status"] = res.status
                break

    page.on("request", on_request)
    page.on("response", on_response)
    dialogs = state["pending_dialogs"].setdefault(page_id, [])

    def on_dialog(dialog):
        dialogs.append(dialog)

    page.on("dialog", on_dialog)
    choosers = state["pending_file_choosers"].setdefault(page_id, [])

    def on_filechooser(chooser):
        choosers.append(chooser)

    page.on("filechooser", on_filechooser)


def _next_page_id(state: dict) -> str:
    """Return a unique page_id (page_N).
    Uses monotonic counter so IDs are not reused after close."""
    state["page_counter"] = state.get("page_counter", 0) + 1
    return f"page_{state['page_counter']}"


def _attach_context_listeners(state: dict, context) -> None:
    """When the page opens a new tab (e.g. target=_blank, window.open),
    register it and set as current."""

    def on_page(page):
        new_id = _next_page_id(state)
        state["refs"][new_id] = {}
        state["console_logs"][new_id] = []
        state["network_requests"][new_id] = []
        state["pending_dialogs"][new_id] = []
        state["pending_file_choosers"][new_id] = []
        _attach_page_listeners(state, page, new_id)
        state["pages"][new_id] = page
        state["current_page_id"] = new_id
        logger.debug(
            "New tab opened by page, registered as page_id=%s",
            new_id,
        )

    context.on("page", on_page)


# pylint: disable=too-many-branches,too-many-statements
async def _ensure_browser(
    state: dict,
) -> bool:
    """Start browser if not running. Return True if ready, False on failure."""
    # CDP-connected mode: verify the connection is still alive; never auto-restart.
    if state.get("connected_via_cdp"):
        browser = state.get("browser")
        if browser is not None and browser.is_connected():
            _touch_activity(state)
            return True
        cdp_url = state.get("cdp_url") or "unknown"
        state["_last_browser_error"] = (
            f"CDP connection lost (was: {cdp_url}). "
            "Reconnect with action='connect_cdp'."
        )
        return False

    # Check browser state based on mode
    if _USE_SYNC_PLAYWRIGHT:
        if state["_sync_context"] is not None and (
            state["_sync_browser"] is not None or state["user_data_dir"]
        ):
            _touch_activity(state)
            return True
    else:
        # Accept both regular context (browser+context) and persistent context
        # (context only, no separate browser object)
        if state["context"] is not None:
            _touch_activity(state)
            return True

    try:
        if _USE_SYNC_PLAYWRIGHT:
            # Hybrid mode: use sync Playwright in thread pool
            loop = asyncio.get_event_loop()
            pw, browser, context = await loop.run_in_executor(
                _get_executor(),
                lambda: _sync_browser_launch(state),
            )
            state["_sync_playwright"] = pw
            state["_sync_browser"] = browser
            state["_sync_context"] = context
        else:
            # Standard mode: use async Playwright
            async_playwright = _ensure_playwright_async()
            pw = await async_playwright().start()
            # Prefer OS default browser when available (e.g. user's default Chrome/Safari).
            use_default = not is_running_in_container() and os.environ.get(
                "COPAW_BROWSER_USE_DEFAULT",
                "1",
            ).strip().lower() in ("1", "true", "yes")
            default_kind, default_path = (
                get_system_default_browser() if use_default else (None, None)
            )
            exe: Optional[str] = None
            if default_kind == "chromium" and default_path:
                exe = default_path
            elif default_kind != "webkit":
                exe = _chromium_executable_path()
            if exe:
                # System Chrome/Edge/Chromium: use persistent context when workspace
                # dir is available, otherwise fall back to a plain new_context.
                user_data_dir = state["user_data_dir"]
                if user_data_dir:
                    Path(user_data_dir).mkdir(parents=True, exist_ok=True)
                    extra_args = _chromium_launch_args()
                    context = await pw.chromium.launch_persistent_context(
                        user_data_dir=user_data_dir,
                        headless=state["headless"],
                        executable_path=exe,
                        args=extra_args if extra_args else [],
                    )
                    _attach_context_listeners(state, context)
                    state["playwright"] = pw
                    state[
                        "browser"
                    ] = None  # not needed for persistent context
                    state["context"] = context
                else:
                    launch_kwargs: dict[str, Any] = {
                        "headless": state["headless"],
                    }
                    extra_args = _chromium_launch_args()
                    if extra_args:
                        launch_kwargs["args"] = extra_args
                    launch_kwargs["executable_path"] = exe
                    pw_browser = await pw.chromium.launch(**launch_kwargs)
                    context = await pw_browser.new_context()
                    _attach_context_listeners(state, context)
                    state["playwright"] = pw
                    state["browser"] = pw_browser
                    state["context"] = context
            elif default_kind == "webkit" or sys.platform == "darwin":
                # macOS: default Safari or no Chromium → use WebKit (no persistent ctx)
                pw_browser = await pw.webkit.launch(
                    headless=state["headless"],
                )
                context = await pw_browser.new_context()
                _attach_context_listeners(state, context)
                state["playwright"] = pw
                state["browser"] = pw_browser
                state["context"] = context
            else:
                # Windows/Linux without system Chromium → Playwright's bundled Chromium
                launch_kwargs = {"headless": state["headless"]}
                extra_args = _chromium_launch_args()
                if extra_args:
                    launch_kwargs["args"] = extra_args
                pw_browser = await pw.chromium.launch(**launch_kwargs)
                context = await pw_browser.new_context()
                _attach_context_listeners(state, context)
                state["playwright"] = pw
                state["browser"] = pw_browser
                state["context"] = context
        state["_last_browser_error"] = None
        _touch_activity(state)
        _start_idle_watchdog(state)
        return True
    except Exception as e:
        state["_last_browser_error"] = str(e)
        return False


def _start_idle_watchdog(state: dict) -> None:
    """Cancel any existing idle watchdog and start a fresh one."""
    old_task = state.get("_idle_task")
    if old_task and not old_task.done():
        old_task.cancel()
    state["_idle_task"] = asyncio.ensure_future(_idle_watchdog(state))


def _cancel_idle_watchdog(state: dict) -> None:
    """Cancel the idle watchdog, if running.

    Note: If called from within the watchdog task itself (e.g., during _action_stop
    triggered by idle timeout), we don't cancel the current task - just clear the
    reference and let the watchdog exit naturally after _action_stop returns.
    """
    task = state.get("_idle_task")
    current = asyncio.current_task()
    if task and not task.done() and task is not current:
        task.cancel()
    state["_idle_task"] = None


# pylint: disable=R0912,R0915
async def _action_start(
    state: dict,
    headed: bool = False,
    cdp_port: int = 0,
) -> ToolResponse:
    # Check browser state based on mode
    if _USE_SYNC_PLAYWRIGHT:
        browser_exists = (
            state["_sync_browser"] is not None
            or state["_sync_context"] is not None
        )
        current_headless = not state.get("_sync_headless", True)
    else:
        browser_exists = (
            state["browser"] is not None or state["context"] is not None
        )
        current_headless = state["headless"]

    # If user asks for visible window (headed=True)
    # but browser is already running headless, restart with headed
    if browser_exists:
        if state.get("connected_via_cdp"):
            return _tool_response(
                json.dumps(
                    {
                        "ok": False,
                        "error": (
                            f"Already connected to an external browser via CDP "
                            f"({state.get('cdp_url') or 'unknown'}). "
                            "Disconnect first with action='stop'."
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        if headed and current_headless:
            _cancel_idle_watchdog(state)
            try:
                await _action_stop(state)
            except Exception:
                pass
        else:
            return _tool_response(
                json.dumps(
                    {"ok": True, "message": "Browser already running"},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
    # Default: headless (background). Only headed=True (e.g. browser_visible skill) shows window.
    state["headless"] = not headed

    if cdp_port:
        import socket as _socket

        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as _s:
            if _s.connect_ex(("127.0.0.1", cdp_port)) == 0:
                return _tool_response(
                    json.dumps(
                        {
                            "ok": False,
                            "error": (
                                f"Port {cdp_port} is already in use. "
                                "Another browser may be running on this port. "
                                "Choose a different cdp_port or stop the existing process first."
                            ),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )

    try:
        if _USE_SYNC_PLAYWRIGHT:
            loop = asyncio.get_event_loop()
            pw, browser, context = await loop.run_in_executor(
                _get_executor(),
                lambda: _sync_browser_launch(state, cdp_port),
            )
            state["_sync_playwright"] = pw
            state["_sync_browser"] = browser
            state["_sync_context"] = context
            state["_sync_headless"] = not headed
        else:
            async_playwright = _ensure_playwright_async()
            pw = await async_playwright().start()
            use_default = not is_running_in_container() and os.environ.get(
                "COPAW_BROWSER_USE_DEFAULT",
                "1",
            ).strip().lower() in ("1", "true", "yes")
            default_kind, default_path = (
                get_system_default_browser() if use_default else (None, None)
            )
            exe: Optional[str] = None
            if default_kind == "chromium" and default_path:
                exe = default_path
            elif default_kind != "webkit":
                exe = _chromium_executable_path()
            extra_args = list(_chromium_launch_args())
            if cdp_port:
                extra_args.append(f"--remote-debugging-port={cdp_port}")

            if exe:
                # Use persistent context so cookies/storage survive browser restarts
                user_data_dir = state["user_data_dir"]
                if user_data_dir:
                    Path(user_data_dir).mkdir(parents=True, exist_ok=True)
                    context = await pw.chromium.launch_persistent_context(
                        user_data_dir=user_data_dir,
                        headless=state["headless"],
                        executable_path=exe if exe else None,
                        args=extra_args if extra_args else [],
                    )
                    # launch_persistent_context returns context directly; no separate browser object
                    _attach_context_listeners(state, context)
                    state["playwright"] = pw
                    state[
                        "browser"
                    ] = None  # not needed for persistent context
                    state["context"] = context
                else:
                    launch_kwargs = {"headless": state["headless"]}
                    if extra_args:
                        launch_kwargs["args"] = extra_args
                    launch_kwargs["executable_path"] = exe
                    pw_browser = await pw.chromium.launch(**launch_kwargs)
                    context = await pw_browser.new_context()
                    _attach_context_listeners(state, context)
                    state["playwright"] = pw
                    state["browser"] = pw_browser
                    state["context"] = context
            elif default_kind == "webkit" or sys.platform == "darwin":
                pw_browser = await pw.webkit.launch(
                    headless=state["headless"],
                )
                context = await pw_browser.new_context()
                _attach_context_listeners(state, context)
                state["playwright"] = pw
                state["browser"] = pw_browser
                state["context"] = context
            else:
                launch_kwargs = {"headless": state["headless"]}
                if extra_args:
                    launch_kwargs["args"] = extra_args
                pw_browser = await pw.chromium.launch(**launch_kwargs)
                context = await pw_browser.new_context()
                _attach_context_listeners(state, context)
                state["playwright"] = pw
                state["browser"] = pw_browser
                state["context"] = context
        _touch_activity(state)
        _start_idle_watchdog(state)
        msg = (
            "Browser started (visible window)"
            if not state["headless"]
            else "Browser started"
        )
        result: dict[str, Any] = {
            "ok": True,
            "message": msg,
            "tip": "Enable browser-related skills in the agent config for a better experience.",
        }
        if cdp_port:
            result["cdp_url"] = f"http://localhost:{cdp_port}"
            result["message"] = msg + f" with CDP port {cdp_port}"
        return _tool_response(
            json.dumps(result, ensure_ascii=False, indent=2),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Browser start failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_stop(state: dict) -> ToolResponse:
    _cancel_idle_watchdog(state)

    # Check browser state based on mode
    if not _is_browser_running(state):
        return _tool_response(
            json.dumps(
                {"ok": True, "message": "Browser not running"},
                ensure_ascii=False,
                indent=2,
            ),
        )

    # CDP-connected mode: just disconnect Playwright; leave Chrome process running.
    if state.get("connected_via_cdp"):
        cdp_url = state.get("cdp_url") or ""
        try:
            if state["context"] is not None:
                try:
                    await state["context"].close()
                except Exception:
                    pass
            if state["browser"] is not None:
                try:
                    await state["browser"].close()
                except Exception:
                    pass
            if state["playwright"] is not None:
                try:
                    await state["playwright"].stop()
                except Exception:
                    pass
        finally:
            _reset_browser_state(state)
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Disconnected from Chrome (process still running: {cdp_url})",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    # Playwright-launched browser: terminate Chrome process.
    # Warn that other agents sharing this browser will lose their connection.
    warning = (
        "Chrome process will be terminated. "
        "Any other agents connected to this browser via CDP will be disconnected."
    )
    if _USE_SYNC_PLAYWRIGHT:
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                _get_executor(),
                lambda: _sync_browser_close(state),
            )
        except Exception as e:
            return _tool_response(
                json.dumps(
                    {"ok": False, "error": f"Browser stop failed: {e!s}"},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        finally:
            _reset_browser_state(state)
    else:
        try:
            # For persistent_context, close the context directly (no separate browser)
            if state["context"] is not None:
                try:
                    await state["context"].close()
                except Exception:
                    pass
            if state["browser"] is not None:
                try:
                    await state["browser"].close()
                except Exception:
                    pass
            if state["playwright"] is not None:
                try:
                    await state["playwright"].stop()
                except Exception:
                    pass
        except Exception as e:
            return _tool_response(
                json.dumps(
                    {"ok": False, "error": f"Browser stop failed: {e!s}"},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        finally:
            _reset_browser_state(state)

    return _tool_response(
        json.dumps(
            {"ok": True, "message": "Browser stopped", "warning": warning},
            ensure_ascii=False,
            indent=2,
        ),
    )


async def _action_open(state: dict, url: str, page_id: str) -> ToolResponse:
    url = (url or "").strip()
    if not url:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "url required for open"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    if not await _ensure_browser(state):
        err = state.get("_last_browser_error") or "Browser not started"
        return _tool_response(
            json.dumps(
                {"ok": False, "error": err},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if _USE_SYNC_PLAYWRIGHT:
            # Hybrid mode: create page in thread pool
            loop = asyncio.get_event_loop()
            # pylint: disable=unnecessary-lambda
            page = await loop.run_in_executor(
                _get_executor(),
                lambda: state["_sync_context"].new_page(),
            )
        else:
            # Standard async mode
            page = await state["context"].new_page()

        state["refs"][page_id] = {}
        state["console_logs"][page_id] = []
        state["network_requests"][page_id] = []
        state["pending_dialogs"][page_id] = []
        state["pending_file_choosers"][page_id] = []
        _attach_page_listeners(state, page, page_id)

        if _USE_SYNC_PLAYWRIGHT:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                _get_executor(),
                lambda: page.goto(url),
            )
        else:
            await page.goto(url)

        state["pages"][page_id] = page
        state["current_page_id"] = page_id
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Opened {url}",
                    "page_id": page_id,
                    "url": url,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Open failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_navigate(
    state: dict,
    url: str,
    page_id: str,
) -> ToolResponse:
    url = (url or "").strip()
    if not url:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "url required for navigate"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if _USE_SYNC_PLAYWRIGHT:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                _get_executor(),
                lambda: page.goto(url),
            )
        else:
            await page.goto(url)
        state["current_page_id"] = page_id
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Navigated to {url}",
                    "url": page.url,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Navigate failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_screenshot(
    state: dict,
    page_id: str,
    path: str,
    full_page: bool,
    screenshot_type: str = "png",
    ref: str = "",
    element: str = "",  # pylint: disable=unused-argument
    frame_selector: str = "",
) -> ToolResponse:
    path = (path or "").strip()
    if not path:
        ext = "jpeg" if screenshot_type == "jpeg" else "png"
        path = f"page-{int(time.time())}.{ext}"
    path = _resolve_output_path(path)
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if ref and ref.strip():
            locator = _get_locator_by_ref(
                state,
                page,
                page_id,
                ref.strip(),
                frame_selector,
            )
            if locator is None:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": f"Unknown ref: {ref}"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            if _USE_SYNC_PLAYWRIGHT:
                await _run_sync(
                    locator.screenshot,
                    path=path,
                    type=(
                        screenshot_type if screenshot_type == "jpeg" else "png"
                    ),
                )
            else:
                await locator.screenshot(
                    path=path,
                    type=(
                        screenshot_type if screenshot_type == "jpeg" else "png"
                    ),
                )
        else:
            if frame_selector and frame_selector.strip():
                root = _get_root(page, frame_selector)
                locator = root.locator("body").first
                if _USE_SYNC_PLAYWRIGHT:
                    await _run_sync(
                        locator.screenshot,
                        path=path,
                        type=(
                            screenshot_type
                            if screenshot_type == "jpeg"
                            else "png"
                        ),
                    )
                else:
                    await locator.screenshot(
                        path=path,
                        type=(
                            screenshot_type
                            if screenshot_type == "jpeg"
                            else "png"
                        ),
                    )
            else:
                if _USE_SYNC_PLAYWRIGHT:
                    await _run_sync(
                        page.screenshot,
                        path=path,
                        full_page=full_page,
                        type=(
                            screenshot_type
                            if screenshot_type == "jpeg"
                            else "png"
                        ),
                    )
                else:
                    await page.screenshot(
                        path=path,
                        full_page=full_page,
                        type=(
                            screenshot_type
                            if screenshot_type == "jpeg"
                            else "png"
                        ),
                    )
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Screenshot saved to {path}",
                    "path": path,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Screenshot failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_click(  # pylint: disable=too-many-branches
    state: dict,
    page_id: str,
    selector: str,
    ref: str = "",
    element: str = "",  # pylint: disable=unused-argument
    wait: int = 0,
    double_click: bool = False,
    button: str = "left",
    modifiers_json: str = "",
    frame_selector: str = "",
) -> ToolResponse:
    ref = (ref or "").strip()
    selector = (selector or "").strip()
    if not ref and not selector:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "selector or ref required for click"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if wait > 0:
            await asyncio.sleep(wait / 1000.0)
        mods = _parse_json_param(modifiers_json, [])
        if not isinstance(mods, list):
            mods = []
        kwargs = {
            "button": (
                button if button in ("left", "right", "middle") else "left"
            ),
        }
        if mods:
            kwargs["modifiers"] = [
                m
                for m in mods
                if m in ("Alt", "Control", "ControlOrMeta", "Meta", "Shift")
            ]

        if _USE_SYNC_PLAYWRIGHT:
            loop = asyncio.get_event_loop()
            if ref:
                locator = _get_locator_by_ref(
                    state,
                    page,
                    page_id,
                    ref,
                    frame_selector,
                )
                if locator is None:
                    return _tool_response(
                        json.dumps(
                            {"ok": False, "error": f"Unknown ref: {ref}"},
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                if double_click:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: locator.dblclick(**kwargs),
                    )
                else:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: locator.click(**kwargs),
                    )
            else:
                root = _get_root(page, frame_selector)
                locator = root.locator(selector).first
                if double_click:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: locator.dblclick(**kwargs),
                    )
                else:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: locator.click(**kwargs),
                    )
        else:
            # Standard async mode
            if ref:
                locator = _get_locator_by_ref(
                    state,
                    page,
                    page_id,
                    ref,
                    frame_selector,
                )
                if locator is None:
                    return _tool_response(
                        json.dumps(
                            {"ok": False, "error": f"Unknown ref: {ref}"},
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                if double_click:
                    await locator.dblclick(**kwargs)
                else:
                    await locator.click(**kwargs)
            else:
                root = _get_root(page, frame_selector)
                locator = root.locator(selector).first
                if double_click:
                    await locator.dblclick(**kwargs)
                else:
                    await locator.click(**kwargs)

        return _tool_response(
            json.dumps(
                {"ok": True, "message": f"Clicked {ref or selector}"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Click failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_type(
    state: dict,
    page_id: str,
    selector: str,
    ref: str = "",
    element: str = "",  # pylint: disable=unused-argument
    text: str = "",
    submit: bool = False,
    slowly: bool = False,
    frame_selector: str = "",
) -> ToolResponse:
    ref = (ref or "").strip()
    selector = (selector or "").strip()
    if not ref and not selector:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "selector or ref required for type"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if ref:
            locator = _get_locator_by_ref(
                state,
                page,
                page_id,
                ref,
                frame_selector,
            )
            if locator is None:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": f"Unknown ref: {ref}"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            if _USE_SYNC_PLAYWRIGHT:
                loop = asyncio.get_event_loop()
                if slowly:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: locator.press_sequentially(text or ""),
                    )
                else:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: locator.fill(text or ""),
                    )
                if submit:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: locator.press("Enter"),
                    )
            else:
                if slowly:
                    await locator.press_sequentially(text or "")
                else:
                    await locator.fill(text or "")
                if submit:
                    await locator.press("Enter")
        else:
            root = _get_root(page, frame_selector)
            loc = root.locator(selector).first
            if _USE_SYNC_PLAYWRIGHT:
                loop = asyncio.get_event_loop()
                if slowly:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: loc.press_sequentially(text or ""),
                    )
                else:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: loc.fill(text or ""),
                    )
                if submit:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: loc.press("Enter"),
                    )
            else:
                if slowly:
                    await loc.press_sequentially(text or "")
                else:
                    await loc.fill(text or "")
                if submit:
                    await loc.press("Enter")
        return _tool_response(
            json.dumps(
                {"ok": True, "message": f"Typed into {ref or selector}"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Type failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_eval(state: dict, page_id: str, code: str) -> ToolResponse:
    code = (code or "").strip()
    if not code:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "code required for eval"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if code.strip().startswith("(") or code.strip().startswith("function"):
            if _USE_SYNC_PLAYWRIGHT:
                result = await _run_sync(page.evaluate, code)
            else:
                result = await page.evaluate(code)
        else:
            if _USE_SYNC_PLAYWRIGHT:
                result = await _run_sync(
                    page.evaluate,
                    f"() => {{ return ({code}); }}",
                )
            else:
                result = await page.evaluate(f"() => {{ return ({code}); }}")
        try:
            out = json.dumps(
                {"ok": True, "result": result},
                ensure_ascii=False,
                indent=2,
            )
        except TypeError:
            out = json.dumps(
                {"ok": True, "result": str(result)},
                ensure_ascii=False,
                indent=2,
            )
        return _tool_response(out)
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Eval failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_pdf(state: dict, page_id: str, path: str) -> ToolResponse:
    path = (path or "page.pdf").strip() or "page.pdf"
    path = _resolve_output_path(path)
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if _USE_SYNC_PLAYWRIGHT:
            await _run_sync(page.pdf, path=path)
        else:
            await page.pdf(path=path)
        return _tool_response(
            json.dumps(
                {"ok": True, "message": f"PDF saved to {path}", "path": path},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"PDF failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_close(state: dict, page_id: str) -> ToolResponse:
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if _USE_SYNC_PLAYWRIGHT:
            await _run_sync(page.close)
        else:
            await page.close()
        del state["pages"][page_id]
        for key in (
            "refs",
            "refs_frame",
            "console_logs",
            "network_requests",
            "pending_dialogs",
            "pending_file_choosers",
        ):
            state[key].pop(page_id, None)
        if state.get("current_page_id") == page_id:
            remaining = list(state["pages"].keys())
            state["current_page_id"] = remaining[0] if remaining else None
        return _tool_response(
            json.dumps(
                {"ok": True, "message": f"Closed page '{page_id}'"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Close failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_snapshot(
    state: dict,
    page_id: str,
    filename: str,
    frame_selector: str = "",
) -> ToolResponse:
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if _USE_SYNC_PLAYWRIGHT:
            # Hybrid mode: execute in thread pool
            loop = asyncio.get_event_loop()
            root = _get_root(page, frame_selector)
            locator = root.locator(":root")
            raw = await loop.run_in_executor(
                _get_executor(),
                lambda: locator.aria_snapshot(),  # pylint: disable=unnecessary-lambda
            )
        else:
            root = _get_root(page, frame_selector)
            locator = root.locator(":root")
            raw = await locator.aria_snapshot()

        raw_str = str(raw) if raw is not None else ""
        snapshot, refs = build_role_snapshot_from_aria(
            raw_str,
            interactive=False,
            compact=False,
        )
        state["refs"][page_id] = refs
        state["refs_frame"][page_id] = (
            frame_selector.strip() if frame_selector else ""
        )
        out = {
            "ok": True,
            "snapshot": snapshot,
            "refs": list(refs.keys()),
            "url": page.url,
        }
        if frame_selector and frame_selector.strip():
            out["frame_selector"] = frame_selector.strip()
        if filename and filename.strip():
            resolved = _resolve_output_path(filename.strip())
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(snapshot)
            out["filename"] = resolved
        return _tool_response(json.dumps(out, ensure_ascii=False, indent=2))
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Snapshot failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_navigate_back(state: dict, page_id: str) -> ToolResponse:
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if _USE_SYNC_PLAYWRIGHT:
            await _run_sync(page.go_back)
        else:
            await page.go_back()
        return _tool_response(
            json.dumps(
                {"ok": True, "message": "Navigated back", "url": page.url},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Navigate back failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_evaluate(
    state: dict,
    page_id: str,
    code: str,
    ref: str = "",
    element: str = "",  # pylint: disable=unused-argument
    frame_selector: str = "",
) -> ToolResponse:
    code = (code or "").strip()
    if not code:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "code required for evaluate"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if ref and ref.strip():
            locator = _get_locator_by_ref(
                state,
                page,
                page_id,
                ref.strip(),
                frame_selector,
            )
            if locator is None:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": f"Unknown ref: {ref}"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            if _USE_SYNC_PLAYWRIGHT:
                result = await _run_sync(locator.evaluate, code)
            else:
                result = await locator.evaluate(code)
        else:
            if code.strip().startswith("(") or code.strip().startswith(
                "function",
            ):
                if _USE_SYNC_PLAYWRIGHT:
                    result = await _run_sync(page.evaluate, code)
                else:
                    result = await page.evaluate(code)
            else:
                if _USE_SYNC_PLAYWRIGHT:
                    result = await _run_sync(
                        page.evaluate,
                        f"() => {{ return ({code}); }}",
                    )
                else:
                    result = await page.evaluate(
                        f"() => {{ return ({code}); }}",
                    )
        try:
            out = json.dumps(
                {"ok": True, "result": result},
                ensure_ascii=False,
                indent=2,
            )
        except TypeError:
            out = json.dumps(
                {"ok": True, "result": str(result)},
                ensure_ascii=False,
                indent=2,
            )
        return _tool_response(out)
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Evaluate failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_resize(
    state: dict,
    page_id: str,
    width: int,
    height: int,
) -> ToolResponse:
    if width <= 0 or height <= 0:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "width and height must be positive"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if _USE_SYNC_PLAYWRIGHT:
            await _run_sync(
                page.set_viewport_size,
                {"width": width, "height": height},
            )
        else:
            await page.set_viewport_size({"width": width, "height": height})
        return _tool_response(
            json.dumps(
                {"ok": True, "message": f"Resized to {width}x{height}"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Resize failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_console_messages(
    state: dict,
    page_id: str,
    level: str,
    filename: str,
) -> ToolResponse:
    level = (level or "info").strip().lower()
    order = ("error", "warning", "info", "debug")
    idx = order.index(level) if level in order else 2
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    logs = state["console_logs"].get(page_id, [])
    filtered = (
        [m for m in logs if order.index(m["level"]) <= idx]
        if level in order
        else logs
    )
    lines = [f"[{m['level']}] {m['text']}" for m in filtered]
    text = "\n".join(lines)
    if filename and filename.strip():
        resolved = _resolve_output_path(filename.strip())
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(text)
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Console messages saved to {resolved}",
                    "filename": resolved,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return _tool_response(
        json.dumps(
            {"ok": True, "messages": filtered, "text": text},
            ensure_ascii=False,
            indent=2,
        ),
    )


async def _action_handle_dialog(
    state: dict,
    page_id: str,
    accept: bool,
    prompt_text: str,
) -> ToolResponse:
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    dialogs = state["pending_dialogs"].get(page_id, [])
    if not dialogs:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "No pending dialog"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        dialog = dialogs.pop(0)
        if accept:
            if prompt_text and hasattr(dialog, "accept"):
                if _USE_SYNC_PLAYWRIGHT:
                    await _run_sync(dialog.accept, prompt_text)
                else:
                    await dialog.accept(prompt_text)
            else:
                if _USE_SYNC_PLAYWRIGHT:
                    await _run_sync(dialog.accept)
                else:
                    await dialog.accept()
        else:
            if _USE_SYNC_PLAYWRIGHT:
                await _run_sync(dialog.dismiss)
            else:
                await dialog.dismiss()
        return _tool_response(
            json.dumps(
                {"ok": True, "message": "Dialog handled"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Handle dialog failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_file_upload(
    state: dict,
    page_id: str,
    paths_json: str,
) -> ToolResponse:
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    paths = _parse_json_param(paths_json, [])
    if not isinstance(paths, list):
        paths = []
    try:
        choosers = state["pending_file_choosers"].get(page_id, [])
        if not choosers:
            return _tool_response(
                json.dumps(
                    {
                        "ok": False,
                        "error": "No chooser. Click upload then file_upload.",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        chooser = choosers.pop(0)
        if paths:
            if _USE_SYNC_PLAYWRIGHT:
                await _run_sync(chooser.set_files, paths)
            else:
                await chooser.set_files(paths)
            return _tool_response(
                json.dumps(
                    {"ok": True, "message": f"Uploaded {len(paths)} file(s)"},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        if _USE_SYNC_PLAYWRIGHT:
            await _run_sync(chooser.set_files, [])
        else:
            await chooser.set_files([])
        return _tool_response(
            json.dumps(
                {"ok": True, "message": "File chooser cancelled"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"File upload failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_fill_form(
    state: dict,
    page_id: str,
    fields_json: str,
) -> ToolResponse:
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    fields = _parse_json_param(fields_json, [])
    if not isinstance(fields, list) or not fields:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "fields required (JSON array)"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    refs = _get_refs(state, page_id)
    # Use last snapshot's frame so fill_form works after iframe snapshot
    frame = state["refs_frame"].get(page_id, "")
    try:
        for f in fields:
            ref = (f.get("ref") or "").strip()
            if not ref or ref not in refs:
                continue
            locator = _get_locator_by_ref(state, page, page_id, ref, frame)
            if locator is None:
                continue
            field_type = (f.get("type") or "textbox").lower()
            value = f.get("value")
            if field_type == "checkbox":
                if isinstance(value, str):
                    value = value.strip().lower() in ("true", "1", "yes")
                if _USE_SYNC_PLAYWRIGHT:
                    await _run_sync(locator.set_checked, bool(value))
                else:
                    await locator.set_checked(bool(value))
            elif field_type == "radio":
                if _USE_SYNC_PLAYWRIGHT:
                    await _run_sync(locator.set_checked, True)
                else:
                    await locator.set_checked(True)
            elif field_type == "combobox":
                if _USE_SYNC_PLAYWRIGHT:
                    await _run_sync(
                        locator.select_option,
                        label=value if isinstance(value, str) else None,
                        value=value,
                    )
                else:
                    await locator.select_option(
                        label=value if isinstance(value, str) else None,
                        value=value,
                    )
            elif field_type == "slider":
                if _USE_SYNC_PLAYWRIGHT:
                    await _run_sync(locator.fill, str(value))
                else:
                    await locator.fill(str(value))
            else:
                if _USE_SYNC_PLAYWRIGHT:
                    await _run_sync(
                        locator.fill,
                        str(value) if value is not None else "",
                    )
                else:
                    await locator.fill(str(value) if value is not None else "")
        return _tool_response(
            json.dumps(
                {"ok": True, "message": f"Filled {len(fields)} field(s)"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Fill form failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


def _run_playwright_install() -> None:
    """Run playwright install in a blocking way (for use in thread)."""
    subprocess.run(
        [sys.executable, "-m", "playwright", "install"],
        check=True,
        capture_output=True,
        text=True,
        timeout=600,  # 10 minutes max
    )


async def _action_install() -> ToolResponse:
    """Install Playwright browsers. If a system Chrome/Chromium/Edge is found,
    use it and skip download. On macOS with no Chromium, use Safari (WebKit)
    so no download is needed. Only run playwright install when necessary.
    """
    exe = _chromium_executable_path()
    if exe:
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Using system browser (no download): {exe}",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    if _use_webkit_fallback():
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": "On macOS using Safari (WebKit); no browser download needed.",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        await asyncio.to_thread(_run_playwright_install)
        return _tool_response(
            json.dumps(
                {"ok": True, "message": "Browser installed"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except subprocess.TimeoutExpired:
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": "Browser install timed out (10 min). Run manually in terminal: "
                    f"{sys.executable!s} -m playwright install",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": f"Install failed: {e!s}. Install manually: "
                    f"{sys.executable!s} -m pip install playwright && "
                    f"{sys.executable!s} -m playwright install",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_press_key(
    state: dict,
    page_id: str,
    key: str,
) -> ToolResponse:
    key = (key or "").strip()
    if not key:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "key required for press_key"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if _USE_SYNC_PLAYWRIGHT:
            await _run_sync(page.keyboard.press, key)
        else:
            await page.keyboard.press(key)
        return _tool_response(
            json.dumps(
                {"ok": True, "message": f"Pressed key {key}"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Press key failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_network_requests(
    state: dict,
    page_id: str,
    include_static: bool,
    filename: str,
) -> ToolResponse:
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    requests = state["network_requests"].get(page_id, [])
    if not include_static:
        static = ("image", "stylesheet", "font", "media")
        requests = [r for r in requests if r.get("resourceType") not in static]
    lines = [
        f"{r.get('method', '')} {r.get('url', '')} {r.get('status', '')}"
        for r in requests
    ]
    text = "\n".join(lines)
    if filename and filename.strip():
        resolved = _resolve_output_path(filename.strip())
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(text)
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Network requests saved to {resolved}",
                    "filename": resolved,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return _tool_response(
        json.dumps(
            {"ok": True, "requests": requests, "text": text},
            ensure_ascii=False,
            indent=2,
        ),
    )


async def _action_run_code(
    state: dict,
    page_id: str,
    code: str,
) -> ToolResponse:
    """Run JS in page (like eval). Use evaluate for element (ref)."""
    code = (code or "").strip()
    if not code:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "code required for run_code"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if code.strip().startswith("(") or code.strip().startswith("function"):
            if _USE_SYNC_PLAYWRIGHT:
                result = await _run_sync(page.evaluate, code)
            else:
                result = await page.evaluate(code)
        else:
            if _USE_SYNC_PLAYWRIGHT:
                result = await _run_sync(
                    page.evaluate,
                    f"() => {{ return ({code}); }}",
                )
            else:
                result = await page.evaluate(f"() => {{ return ({code}); }}")
        try:
            out = json.dumps(
                {"ok": True, "result": result},
                ensure_ascii=False,
                indent=2,
            )
        except TypeError:
            out = json.dumps(
                {"ok": True, "result": str(result)},
                ensure_ascii=False,
                indent=2,
            )
        return _tool_response(out)
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Run code failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_drag(
    state: dict,
    page_id: str,
    start_ref: str,
    end_ref: str,
    start_selector: str = "",
    end_selector: str = "",
    start_element: str = "",  # pylint: disable=unused-argument
    end_element: str = "",  # pylint: disable=unused-argument
    frame_selector: str = "",
) -> ToolResponse:
    start_ref = (start_ref or "").strip()
    end_ref = (end_ref or "").strip()
    start_selector = (start_selector or "").strip()
    end_selector = (end_selector or "").strip()
    use_refs = bool(start_ref and end_ref)
    use_selectors = bool(start_selector and end_selector)
    if not use_refs and not use_selectors:
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": (
                        "drag needs (start_ref,end_ref) or (start_sel,end_sel)"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        root = _get_root(page, frame_selector)
        if use_refs:
            start_locator = _get_locator_by_ref(
                state,
                page,
                page_id,
                start_ref,
                frame_selector,
            )
            end_locator = _get_locator_by_ref(
                state,
                page,
                page_id,
                end_ref,
                frame_selector,
            )
            if start_locator is None or end_locator is None:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": "Unknown ref for drag"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
        else:
            start_locator = root.locator(start_selector).first
            end_locator = root.locator(end_selector).first
        if _USE_SYNC_PLAYWRIGHT:
            await _run_sync(start_locator.drag_to, end_locator)
        else:
            await start_locator.drag_to(end_locator)
        return _tool_response(
            json.dumps(
                {"ok": True, "message": "Drag completed"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Drag failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_hover(
    state: dict,
    page_id: str,
    ref: str = "",
    element: str = "",  # pylint: disable=unused-argument
    selector: str = "",
    frame_selector: str = "",
) -> ToolResponse:
    ref = (ref or "").strip()
    selector = (selector or "").strip()
    if not ref and not selector:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "hover requires ref or selector"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if ref:
            locator = _get_locator_by_ref(
                state,
                page,
                page_id,
                ref,
                frame_selector,
            )
            if locator is None:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": f"Unknown ref: {ref}"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
        else:
            root = _get_root(page, frame_selector)
            locator = root.locator(selector).first
        if _USE_SYNC_PLAYWRIGHT:
            await _run_sync(locator.hover)
        else:
            await locator.hover()
        return _tool_response(
            json.dumps(
                {"ok": True, "message": f"Hovered {ref or selector}"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Hover failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_select_option(
    state: dict,
    page_id: str,
    ref: str = "",
    element: str = "",  # pylint: disable=unused-argument
    values_json: str = "",
    frame_selector: str = "",
) -> ToolResponse:
    ref = (ref or "").strip()
    values = _parse_json_param(values_json, [])
    if not isinstance(values, list):
        values = [values] if values is not None else []
    if not ref:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "ref required for select_option"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    if not values:
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": "values required (JSON array or comma-separated)",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        locator = _get_locator_by_ref(
            state,
            page,
            page_id,
            ref,
            frame_selector,
        )
        if locator is None:
            return _tool_response(
                json.dumps(
                    {"ok": False, "error": f"Unknown ref: {ref}"},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        if _USE_SYNC_PLAYWRIGHT:
            await _run_sync(locator.select_option, value=values)
        else:
            await locator.select_option(value=values)
        return _tool_response(
            json.dumps(
                {"ok": True, "message": f"Selected {values}"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Select option failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_tabs(  # pylint: disable=too-many-return-statements
    state: dict,
    page_id: str,
    tab_action: str,
    index: int,
) -> ToolResponse:
    tab_action = (tab_action or "").strip().lower()
    if not tab_action:
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": "tab_action required (list, new, close, select)",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    pages = state["pages"]
    page_ids = list(pages.keys())
    if tab_action == "list":
        return _tool_response(
            json.dumps(
                {"ok": True, "tabs": page_ids, "count": len(page_ids)},
                ensure_ascii=False,
                indent=2,
            ),
        )
    if tab_action == "new":
        if _USE_SYNC_PLAYWRIGHT:
            if not state["_sync_context"]:
                ok = await _ensure_browser(state)
                if not ok:
                    err = (
                        state.get("_last_browser_error")
                        or "Browser not started"
                    )
                    return _tool_response(
                        json.dumps(
                            {"ok": False, "error": err},
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
        else:
            if not state["context"]:
                ok = await _ensure_browser(state)
                if not ok:
                    err = (
                        state.get("_last_browser_error")
                        or "Browser not started"
                    )
                    return _tool_response(
                        json.dumps(
                            {"ok": False, "error": err},
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
        try:
            if _USE_SYNC_PLAYWRIGHT:
                page = await _run_sync(state["_sync_context"].new_page)
            else:
                page = await state["context"].new_page()
            new_id = _next_page_id(state)
            state["refs"][new_id] = {}
            state["console_logs"][new_id] = []
            state["network_requests"][new_id] = []
            state["pending_dialogs"][new_id] = []
            _attach_page_listeners(state, page, new_id)
            state["pages"][new_id] = page
            state["current_page_id"] = new_id
            return _tool_response(
                json.dumps(
                    {
                        "ok": True,
                        "page_id": new_id,
                        "tabs": list(state["pages"].keys()),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        except Exception as e:
            return _tool_response(
                json.dumps(
                    {"ok": False, "error": f"New tab failed: {e!s}"},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
    if tab_action == "close":
        target_id = page_ids[index] if 0 <= index < len(page_ids) else page_id
        return await _action_close(state, target_id)
    if tab_action == "select":
        target_id = page_ids[index] if 0 <= index < len(page_ids) else page_id
        state["current_page_id"] = target_id
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Use page_id={target_id} for later actions",
                    "page_id": target_id,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return _tool_response(
        json.dumps(
            {"ok": False, "error": f"Unknown tab_action: {tab_action}"},
            ensure_ascii=False,
            indent=2,
        ),
    )


async def _action_wait_for(
    state: dict,
    page_id: str,
    wait_time: float,
    text: str,
    text_gone: str,
) -> ToolResponse:
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if wait_time and wait_time > 0:
            await asyncio.sleep(wait_time)
        text = (text or "").strip()
        text_gone = (text_gone or "").strip()
        if text:
            locator = page.get_by_text(text)
            if _USE_SYNC_PLAYWRIGHT:
                await _run_sync(
                    locator.wait_for,
                    state="visible",
                    timeout=30000,
                )
            else:
                await locator.wait_for(
                    state="visible",
                    timeout=30000,
                )
        if text_gone:
            locator = page.get_by_text(text_gone)
            if _USE_SYNC_PLAYWRIGHT:
                await _run_sync(
                    locator.wait_for,
                    state="hidden",
                    timeout=30000,
                )
            else:
                await locator.wait_for(
                    state="hidden",
                    timeout=30000,
                )
        return _tool_response(
            json.dumps(
                {"ok": True, "message": "Wait completed"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Wait failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


_BROWSER_DISK_CACHE_DIRS = [
    Path("Default") / "Cache",
    Path("Default") / "Code Cache",
    Path("Default") / "GPUCache",
    Path("Default") / "DawnWebGPUCache",
    Path("Default") / "DawnGraphiteCache",
    Path("GrShaderCache"),
    Path("ShaderCache"),
    Path("GraphiteDawnCache"),
]


async def _action_clear_browser_cache(state: dict) -> ToolResponse:
    """Clear browser cache.

    - Browser running: uses CDP Network.clearBrowserCache (no restart needed).
      Cookies and Local Storage are untouched.
    - Browser stopped: removes cache directories from user_data_dir on disk.
    """
    if _is_browser_running(state):
        context = _get_context(state)
        pages = list(state.get("pages", {}).values())
        if not context or not pages:
            return _tool_response(
                json.dumps(
                    {
                        "ok": False,
                        "error": "No open page to attach CDP session.",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        try:
            page = pages[0]
            if _USE_SYNC_PLAYWRIGHT:
                loop = asyncio.get_event_loop()
                cdp = await loop.run_in_executor(
                    _get_executor(),
                    lambda: context.new_cdp_session(page),
                )
                await loop.run_in_executor(
                    _get_executor(),
                    lambda: cdp.send("Network.clearBrowserCache"),
                )
            else:
                cdp = await context.new_cdp_session(page)
                await cdp.send("Network.clearBrowserCache")
            return _tool_response(
                json.dumps(
                    {"ok": True, "message": "HTTP cache cleared."},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        except Exception as exc:
            return _tool_response(
                json.dumps(
                    {"ok": False, "error": f"CDP cache clear failed: {exc}"},
                    ensure_ascii=False,
                    indent=2,
                ),
            )

    # Browser stopped: remove cache dirs from disk
    import shutil

    user_data_dir = state.get("user_data_dir") or ""
    if not user_data_dir:
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": "No user_data_dir configured for this workspace.",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    base = Path(user_data_dir)
    removed: list[str] = []
    errors: list[str] = []
    for rel in _BROWSER_DISK_CACHE_DIRS:
        p = base / rel
        if p.exists():
            try:
                shutil.rmtree(p)
                removed.append(str(rel))
            except Exception as exc:
                errors.append(f"{rel}: {exc}")
    if errors:
        return _tool_response(
            json.dumps(
                {"ok": False, "removed": removed, "errors": errors},
                ensure_ascii=False,
                indent=2,
            ),
        )
    msg = (
        f"Cleared {len(removed)} cache director{'y' if len(removed) == 1 else 'ies'}."
        if removed
        else "No cache directories found."
    )
    return _tool_response(
        json.dumps(
            {"ok": True, "message": msg, "removed": removed},
            ensure_ascii=False,
            indent=2,
        ),
    )


_CDP_SCAN_PORT_MIN = 9000
_CDP_SCAN_PORT_MAX = 10000


def _fetch_cdp_json(port: int) -> list:
    """Fetch CDP /json endpoint synchronously. Raises on failure."""
    import urllib.request

    url = f"http://localhost:{port}/json"
    with urllib.request.urlopen(url, timeout=1) as resp:  # noqa: S310
        return json.loads(resp.read())


async def _action_list_cdp_targets(
    port: int = 0,
    port_min: int = 0,
    port_max: int = 0,
) -> ToolResponse:
    """List CDP targets on local ports.

    Priority: port (single) > port_min/port_max (range) > default range.
    """
    if port:
        ports_to_scan: Any = [port]
    elif port_min or port_max:
        lo = port_min or _CDP_SCAN_PORT_MIN
        hi = port_max or _CDP_SCAN_PORT_MAX
        ports_to_scan = range(lo, hi + 1)
    else:
        ports_to_scan = range(_CDP_SCAN_PORT_MIN, _CDP_SCAN_PORT_MAX + 1)
    loop = asyncio.get_event_loop()

    async def probe(p: int):
        try:
            targets = await loop.run_in_executor(None, _fetch_cdp_json, p)
            return p, targets
        except Exception:
            return p, None

    results = await asyncio.gather(*[probe(p) for p in ports_to_scan])
    found = {str(p): t for p, t in results if t is not None}
    if found:
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "found": found,
                    "message": f"Found CDP endpoints on port(s): {', '.join(found.keys())}",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    if port:
        scan_desc = f"port {port}"
    else:
        # ports_to_scan is a range when port is not set
        scan_desc = f"range {ports_to_scan.start}-{ports_to_scan.stop - 1}"
    msg = (
        f"No CDP endpoints found in {scan_desc}. "
        "Try expanding the range with port_min/port_max, "
        "or make sure Chrome is started with --remote-debugging-port=N."
    )
    return _tool_response(
        json.dumps(
            {"ok": False, "found": {}, "message": msg},
            ensure_ascii=False,
            indent=2,
        ),
    )


async def _action_connect_cdp(state: dict, cdp_url: str) -> ToolResponse:
    """Connect Playwright to a running Chrome via CDP."""
    if not cdp_url:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "cdp_url is required"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    if _is_browser_running(state):
        if state.get("connected_via_cdp"):
            return _tool_response(
                json.dumps(
                    {
                        "ok": False,
                        "error": (
                            f"Already connected to an external browser via CDP "
                            f"({state.get('cdp_url') or 'unknown'}). "
                            "Disconnect first with action='stop'."
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": (
                        "A Playwright-managed browser is currently running. "
                        "Stop it first with action='stop' before connecting via CDP."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    try:
        async_playwright = _ensure_playwright_async()
        pw = await async_playwright().start()
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        contexts = browser.contexts
        if contexts:
            context = contexts[0]
        else:
            context = await browser.new_context()
        _attach_context_listeners(state, context)
        state["playwright"] = pw
        state["browser"] = browser
        state["context"] = context
        state["connected_via_cdp"] = True
        state["cdp_url"] = cdp_url
        # Register existing pages
        for page in context.pages:
            page_id = f"page_{state['page_counter']}"
            state["page_counter"] += 1
            state["pages"][page_id] = page
            if state["current_page_id"] is None:
                state["current_page_id"] = page_id
        if not state["pages"]:
            page = await context.new_page()
            page_id = f"page_{state['page_counter']}"
            state["page_counter"] += 1
            state["pages"][page_id] = page
            state["current_page_id"] = page_id
        _touch_activity(state)
        _start_idle_watchdog(state)
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Connected to Chrome via CDP at {cdp_url}",
                    "pages": list(state["pages"].keys()),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"CDP connect failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def browser_use(  # pylint: disable=R0911,R0912
    action: str,
    url: str = "",
    page_id: str = "default",
    selector: str = "",
    text: str = "",
    code: str = "",
    path: str = "",
    wait: int = 0,
    full_page: bool = False,
    width: int = 0,
    height: int = 0,
    level: str = "info",
    filename: str = "",
    accept: bool = True,
    prompt_text: str = "",
    ref: str = "",
    element: str = "",
    paths_json: str = "",
    fields_json: str = "",
    key: str = "",
    submit: bool = False,
    slowly: bool = False,
    include_static: bool = False,
    screenshot_type: str = "png",
    snapshot_filename: str = "",
    double_click: bool = False,
    button: str = "left",
    modifiers_json: str = "",
    start_ref: str = "",
    end_ref: str = "",
    start_selector: str = "",
    end_selector: str = "",
    start_element: str = "",
    end_element: str = "",
    values_json: str = "",
    tab_action: str = "",
    index: int = -1,
    wait_time: float = 0,
    text_gone: str = "",
    frame_selector: str = "",
    headed: bool = False,
    cdp_port: int = 0,
    cdp_url: str = "",
    port: int = 0,
    port_min: int = 0,
    port_max: int = 0,
) -> ToolResponse:
    """Control browser (Playwright). Default is headless. Use headed=True with
    action=start to open a visible browser window. Flow: start, open(url),
    snapshot to get refs, then click/type etc. with ref or selector. Use
    page_id for multiple tabs. Note: To enhance the experience, consider
    reminding the user to enable browser-related skills in the agent config.
    Once enabled, you will be able to proactively determine when to invoke the
    browser tool and pass the appropriate arguments.

    Args:
        action (str):
            Required. Action type. Values: start, stop, open, navigate,
            navigate_back, snapshot, screenshot, click, type, eval, evaluate,
            resize, console_messages, network_requests, handle_dialog,
            file_upload, fill_form, install, press_key, run_code, drag, hover,
            select_option, tabs, wait_for, pdf, close, cookies_get, cookies_set,
            cookies_clear, connect_cdp, list_cdp_targets, clear_browser_cache.
        url (str):
            URL to open. Required for action=open or navigate. For
            cookies_get, optional URL or JSON array of URLs to filter
            cookies by domain.
        page_id (str):
            Page/tab identifier, default "default". Use different page_id for
            multiple tabs.
        selector (str):
            CSS selector to locate element for click/type/hover etc. Prefer
            ref when available.
        text (str):
            Text to type. Required for action=type.
        code (str):
            JavaScript code. Required for action=eval, evaluate, or run_code.
        path (str):
            File path for screenshot save or PDF export.
        wait (int):
            Milliseconds to wait after click. Used with action=click.
        full_page (bool):
            Whether to capture full page. Used with action=screenshot.
        width (int):
            Viewport width in pixels. Used with action=resize.
        height (int):
            Viewport height in pixels. Used with action=resize.
        level (str):
            Console log level filter, e.g. "info" or "error". Used with
            action=console_messages.
        filename (str):
            Filename for saving logs or screenshot. Used with
            console_messages, network_requests, screenshot.
        accept (bool):
            Whether to accept dialog (true) or dismiss (false). Used with
            action=handle_dialog.
        prompt_text (str):
            Input for prompt dialog. Used with action=handle_dialog when
            dialog is prompt.
        ref (str):
            Element ref from snapshot output; use for stable targeting. Prefer
            ref for click/type/hover/screenshot/evaluate/select_option.
        element (str):
            Element description for evaluate etc. Prefer ref when available.
        paths_json (str):
            JSON array string of file paths. Used with action=file_upload.
        fields_json (str):
            JSON object string of form field name to value. Used with
            action=fill_form. For cookies_set, JSON array of cookie objects
            with keys: name, value, url (or domain+path), expires, httpOnly,
            secure, sameSite.
        key (str):
            Key name, e.g. "Enter", "Control+a". Required for
            action=press_key.
        submit (bool):
            Whether to submit (press Enter) after typing. Used with
            action=type.
        slowly (bool):
            Whether to type character by character. Used with action=type.
        include_static (bool):
            Whether to include static resource requests. Used with
            action=network_requests.
        screenshot_type (str):
            Screenshot format, "png" or "jpeg". Used with action=screenshot.
        snapshot_filename (str):
            File path to save snapshot output. Used with action=snapshot.
        double_click (bool):
            Whether to double-click. Used with action=click.
        button (str):
            Mouse button: "left", "right", or "middle". Used with
            action=click.
        modifiers_json (str):
            JSON array of modifier keys, e.g. ["Shift","Control"]. Used with
            action=click.
        start_ref (str):
            Drag start element ref. Used with action=drag.
        end_ref (str):
            Drag end element ref. Used with action=drag.
        start_selector (str):
            Drag start CSS selector. Used with action=drag.
        end_selector (str):
            Drag end CSS selector. Used with action=drag.
        start_element (str):
            Drag start element description. Used with action=drag.
        end_element (str):
            Drag end element description. Used with action=drag.
        values_json (str):
            JSON of option value(s) for select. Used with
            action=select_option.
        tab_action (str):
            Tab action: list, new, close, or select. Required for
            action=tabs.
        index (int):
            Tab index for tabs select, zero-based. Used with action=tabs.
        wait_time (float):
            Seconds to wait. Used with action=wait_for.
        text_gone (str):
            Wait until this text disappears from page. Used with
            action=wait_for.
        frame_selector (str):
            iframe selector, e.g. "iframe#main". Set when operating inside
            that iframe in snapshot/click/type etc.
        headed (bool):
            When True with action=start, launch a visible browser window
            (non-headless). User can see the real browser. Default False.
        cdp_port (int):
            When > 0 with action=start, Chrome is launched with
            --remote-debugging-port=N so external tools (or connect_cdp) can
            attach. Default 0 (internal Playwright-managed port, not exposed).
        cdp_url (str):
            CDP base URL, e.g. "http://localhost:9222". Required for
            action=connect_cdp.
        port (int):
            Scan a single specific port for action=list_cdp_targets.
        port_min (int):
            Lower bound of port range for action=list_cdp_targets.
            Defaults to 9000 when not specified.
        port_max (int):
            Upper bound of port range for action=list_cdp_targets.
            Defaults to 10000 when not specified.
    """
    # Resolve per-workspace state using context var set by react_agent.py
    from ...config.context import get_current_workspace_dir as _get_cwd

    _cwd = _get_cwd()
    _ws_id = _cwd.name if _cwd else "default"
    _ws_dir = str(_cwd) if _cwd else ""
    state = _get_workspace_state(_ws_id, _ws_dir)

    action = (action or "").strip().lower()
    if not action:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "action required"},
                ensure_ascii=False,
                indent=2,
            ),
        )

    page_id = (page_id or "default").strip() or "default"
    current = state.get("current_page_id")
    pages = state.get("pages") or {}
    if page_id == "default" and current and current in pages:
        page_id = current

    try:
        if action == "start":
            return await _action_start(state, headed=headed, cdp_port=cdp_port)
        if action == "stop":
            return await _action_stop(state)
        if action == "connect_cdp":
            return await _action_connect_cdp(state, cdp_url)
        if action == "list_cdp_targets":
            return await _action_list_cdp_targets(port, port_min, port_max)
        if action == "open":
            return await _action_open(state, url, page_id)
        if action == "navigate":
            return await _action_navigate(state, url, page_id)
        if action == "navigate_back":
            return await _action_navigate_back(state, page_id)
        if action in ("screenshot", "take_screenshot"):
            return await _action_screenshot(
                state,
                page_id,
                path or filename,
                full_page,
                screenshot_type,
                ref,
                element,
                frame_selector,
            )
        if action == "snapshot":
            return await _action_snapshot(
                state,
                page_id,
                snapshot_filename or filename,
                frame_selector,
            )
        if action == "click":
            return await _action_click(
                state,
                page_id,
                selector,
                ref,
                element,
                wait,
                double_click,
                button,
                modifiers_json,
                frame_selector,
            )
        if action == "type":
            return await _action_type(
                state,
                page_id,
                selector,
                ref,
                element,
                text,
                submit,
                slowly,
                frame_selector,
            )
        if action == "eval":
            return await _action_eval(state, page_id, code)
        if action == "evaluate":
            return await _action_evaluate(
                state,
                page_id,
                code,
                ref,
                element,
                frame_selector,
            )
        if action == "resize":
            return await _action_resize(state, page_id, width, height)
        if action == "console_messages":
            return await _action_console_messages(
                state,
                page_id,
                level,
                filename or path,
            )
        if action == "handle_dialog":
            return await _action_handle_dialog(
                state,
                page_id,
                accept,
                prompt_text,
            )
        if action == "file_upload":
            return await _action_file_upload(state, page_id, paths_json)
        if action == "fill_form":
            return await _action_fill_form(state, page_id, fields_json)
        if action == "install":
            return await _action_install()
        if action == "press_key":
            return await _action_press_key(state, page_id, key)
        if action == "network_requests":
            return await _action_network_requests(
                state,
                page_id,
                include_static,
                filename or path,
            )
        if action == "run_code":
            return await _action_run_code(state, page_id, code)
        if action == "drag":
            return await _action_drag(
                state,
                page_id,
                start_ref,
                end_ref,
                start_selector,
                end_selector,
                start_element,
                end_element,
                frame_selector,
            )
        if action == "hover":
            return await _action_hover(
                state,
                page_id,
                ref,
                element,
                selector,
                frame_selector,
            )
        if action == "select_option":
            return await _action_select_option(
                state,
                page_id,
                ref,
                element,
                values_json,
                frame_selector,
            )
        if action == "tabs":
            return await _action_tabs(state, page_id, tab_action, index)
        if action == "wait_for":
            return await _action_wait_for(
                state,
                page_id,
                wait_time,
                text,
                text_gone,
            )
        if action == "pdf":
            return await _action_pdf(state, page_id, path)
        if action == "close":
            return await _action_close(state, page_id)
        if action == "cookies_get":
            ctx = _get_context(state)
            if not ctx:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": "Browser not started"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            urls_list = _parse_json_param(url, None) if url else None
            if urls_list is None and url:
                urls_list = [url]
            urls_list = urls_list or []
            try:
                if _USE_SYNC_PLAYWRIGHT:
                    loop = asyncio.get_event_loop()
                    cookies = await loop.run_in_executor(
                        _get_executor(),
                        lambda: ctx.cookies(
                            urls=urls_list if urls_list else [],
                        ),
                    )
                else:
                    cookies = await ctx.cookies(
                        urls=urls_list if urls_list else [],
                    )
                return _tool_response(
                    json.dumps(
                        {"ok": True, "cookies": cookies},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            except Exception as e:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": str(e)},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
        if action == "cookies_set":
            ctx = _get_context(state)
            if not ctx:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": "Browser not started"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            try:
                cookies = json.loads(fields_json) if fields_json else []
                if not isinstance(cookies, list) or not all(
                    isinstance(c, dict) and "name" in c and "value" in c
                    for c in cookies
                ):
                    return _tool_response(
                        json.dumps(
                            {
                                "ok": False,
                                "error": (
                                    "fields_json must be a JSON array of"
                                    " cookie objects with 'name' and 'value'"
                                ),
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                if _USE_SYNC_PLAYWRIGHT:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: ctx.add_cookies(cookies),
                    )
                else:
                    await ctx.add_cookies(cookies)
                return _tool_response(
                    json.dumps(
                        {
                            "ok": True,
                            "message": f"Injected {len(cookies)} cookie(s)",
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            except Exception as e:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": str(e)},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
        if action == "cookies_clear":
            ctx = _get_context(state)
            if not ctx:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": "Browser not started"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            try:
                if _USE_SYNC_PLAYWRIGHT:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        _get_executor(),
                        ctx.clear_cookies,
                    )
                else:
                    await ctx.clear_cookies()
                return _tool_response(
                    json.dumps(
                        {"ok": True, "message": "All cookies cleared"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            except Exception as e:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": str(e)},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
        if action == "clear_browser_cache":
            return await _action_clear_browser_cache(state)
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Unknown action: {action}"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        logger.error("Browser tool error: %s", e, exc_info=True)
        return _tool_response(
            json.dumps(
                {"ok": False, "error": str(e)},
                ensure_ascii=False,
                indent=2,
            ),
        )
