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
import json
import logging
import subprocess
import sys
import time
from typing import Any

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from .browser_snapshot import build_role_snapshot_from_aria

logger = logging.getLogger(__name__)

# Process-global browser state (one browser, multiple pages by page_id)
_state: dict[str, Any] = {
    "playwright": None,
    "browser": None,
    "context": None,
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
}


def _tool_response(text: str) -> ToolResponse:
    """Wrap text for agentscope Toolkit (return ToolResponse)."""
    return ToolResponse(
        content=[TextBlock(type="text", text=text)],
    )


def _ensure_playwright_async():
    """Import async_playwright; raise ImportError with hint if missing."""
    try:
        from playwright.async_api import async_playwright

        return async_playwright
    except ImportError as exc:
        raise ImportError(
            "Playwright not installed. Install with: pip install playwright "
            "&& python -m playwright install",
        ) from exc


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
) -> ToolResponse:
    """Control browser (Playwright). Default is headless. Use headed=True with
    action=start to open a visible browser window. Flow: start, open(url),
    snapshot to get refs, then click/type etc. with ref or selector. Use
    page_id for multiple tabs.

    Args:
        action (str):
            Required. Action type. Values: start, stop, open, navigate,
            navigate_back, snapshot, screenshot, click, type, eval, evaluate,
            resize, console_messages, network_requests, handle_dialog,
            file_upload, fill_form, install, press_key, run_code, drag, hover,
            select_option, tabs, wait_for, pdf, close.
        url (str):
            URL to open. Required for action=open or navigate.
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
            action=fill_form.
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
        headed (bool):
            When True with action=start, launch a visible browser window
            (non-headless). User can see the real browser. Default False.
    """
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
    current = _state.get("current_page_id")
    pages = _state.get("pages") or {}
    if page_id == "default" and current and current in pages:
        page_id = current
    current = _state.get("current_page_id")
    pages = _state.get("pages") or {}
    if page_id == "default" and current and current in pages:
        page_id = current

    try:
        if action == "start":
            return await _action_start(headed=headed)
        if action == "stop":
            return await _action_stop()
        if action == "open":
            return await _action_open(url, page_id)
        if action == "navigate":
            return await _action_navigate(url, page_id)
        if action == "navigate_back":
            return await _action_navigate_back(page_id)
        if action in ("screenshot", "take_screenshot"):
            return await _action_screenshot(
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
                page_id,
                snapshot_filename or filename,
                frame_selector,
            )
        if action == "click":
            return await _action_click(
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
            return await _action_eval(page_id, code)
        if action == "evaluate":
            return await _action_evaluate(
                page_id,
                code,
                ref,
                element,
                frame_selector,
            )
        if action == "resize":
            return await _action_resize(page_id, width, height)
        if action == "console_messages":
            return await _action_console_messages(
                page_id,
                level,
                filename or path,
            )
        if action == "handle_dialog":
            return await _action_handle_dialog(page_id, accept, prompt_text)
        if action == "file_upload":
            return await _action_file_upload(page_id, paths_json)
        if action == "fill_form":
            return await _action_fill_form(page_id, fields_json)
        if action == "install":
            return await _action_install()
        if action == "press_key":
            return await _action_press_key(page_id, key)
        if action == "network_requests":
            return await _action_network_requests(
                page_id,
                include_static,
                filename or path,
            )
        if action == "run_code":
            return await _action_run_code(page_id, code)
        if action == "drag":
            return await _action_drag(
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
                page_id,
                ref,
                element,
                selector,
                frame_selector,
            )
        if action == "select_option":
            return await _action_select_option(
                page_id,
                ref,
                element,
                values_json,
                frame_selector,
            )
        if action == "tabs":
            return await _action_tabs(page_id, tab_action, index)
        if action == "wait_for":
            return await _action_wait_for(page_id, wait_time, text, text_gone)
        if action == "pdf":
            return await _action_pdf(page_id, path)
        if action == "close":
            return await _action_close(page_id)
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


def _get_page(page_id: str):
    """Return page for page_id or None if not found."""
    return _state["pages"].get(page_id)


def _get_refs(page_id: str) -> dict[str, dict]:
    """Return refs map for page_id (ref -> {role, name?, nth?})."""
    return _state["refs"].setdefault(page_id, {})


def _get_root(page, _page_id: str, frame_selector: str = ""):
    """Return page or frame for frame_selector (ref/selector)."""
    if not (frame_selector and frame_selector.strip()):
        return page
    return page.frame_locator(frame_selector.strip())


def _get_locator_by_ref(
    page,
    page_id: str,
    ref: str,
    frame_selector: str = "",
):
    """Resolve snapshot ref to locator; frame_selector for iframe."""
    refs = _get_refs(page_id)
    info = refs.get(ref)
    if not info:
        return None
    role = info.get("role", "generic")
    name = info.get("name")
    nth = info.get("nth", 0)
    root = _get_root(page, page_id, frame_selector)
    locator = root.get_by_role(role, name=name or None)
    if nth is not None and nth > 0:
        locator = locator.nth(nth)
    return locator


def _attach_page_listeners(page, page_id: str) -> None:
    """Attach console and request listeners for a page."""
    logs = _state["console_logs"].setdefault(page_id, [])

    def on_console(msg):
        logs.append({"level": msg.type, "text": msg.text})

    page.on("console", on_console)
    requests_list = _state["network_requests"].setdefault(page_id, [])

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
    dialogs = _state["pending_dialogs"].setdefault(page_id, [])

    def on_dialog(dialog):
        dialogs.append(dialog)

    page.on("dialog", on_dialog)
    choosers = _state["pending_file_choosers"].setdefault(page_id, [])

    def on_filechooser(chooser):
        choosers.append(chooser)

    page.on("filechooser", on_filechooser)


def _next_page_id() -> str:
    """Return a unique page_id (page_N).
    Uses monotonic counter so IDs are not reused after close."""
    _state["page_counter"] = _state.get("page_counter", 0) + 1
    return f"page_{_state['page_counter']}"


def _attach_context_listeners(context) -> None:
    """When the page opens a new tab (e.g. target=_blank, window.open),
    register it and set as current."""

    def on_page(page):
        new_id = _next_page_id()
        _state["refs"][new_id] = {}
        _state["console_logs"][new_id] = []
        _state["network_requests"][new_id] = []
        _state["pending_dialogs"][new_id] = []
        _state["pending_file_choosers"][new_id] = []
        _attach_page_listeners(page, new_id)
        _state["pages"][new_id] = page
        _state["current_page_id"] = new_id
        logger.debug(
            "New tab opened by page, registered as page_id=%s",
            new_id,
        )

    context.on("page", on_page)


async def _ensure_browser() -> bool:
    """Start browser if not running. Return True if ready, False on failure."""
    if _state["browser"] is not None and _state["context"] is not None:
        return True
    try:
        async_playwright = _ensure_playwright_async()
        pw = await async_playwright().start()
        pw_browser = await pw.chromium.launch(headless=_state["headless"])
        context = await pw_browser.new_context()
        _attach_context_listeners(context)
        _state["playwright"] = pw
        _state["browser"] = pw_browser
        _state["context"] = context
        return True
    except Exception:
        return False


async def _action_start(headed: bool = False) -> ToolResponse:
    # If user asks for visible window (headed=True)
    # but browser is already running headless, restart with headed
    if _state["browser"] is not None:
        if headed and _state["headless"]:
            try:
                await _state["browser"].close()
                if _state["playwright"] is not None:
                    await _state["playwright"].stop()
            except Exception:
                pass
            finally:
                _state["playwright"] = None
                _state["browser"] = None
                _state["context"] = None
                _state["pages"].clear()
                _state["refs"].clear()
                _state["refs_frame"].clear()
                _state["console_logs"].clear()
                _state["network_requests"].clear()
                _state["pending_dialogs"].clear()
                _state["pending_file_choosers"].clear()
                _state["current_page_id"] = None
                _state["page_counter"] = 0
        else:
            return _tool_response(
                json.dumps(
                    {"ok": True, "message": "Browser already running"},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
    # Default: headless (background). Only headed=True (e.g. browser_visible skill) shows window.
    _state["headless"] = not headed
    try:
        async_playwright = _ensure_playwright_async()
    except ImportError as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": str(e)},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        pw = await async_playwright().start()
        pw_browser = await pw.chromium.launch(headless=_state["headless"])
        context = await pw_browser.new_context()
        _attach_context_listeners(context)
        _state["playwright"] = pw
        _state["browser"] = pw_browser
        _state["context"] = context
        msg = (
            "Browser started (visible window)"
            if _state["headless"] is False
            else "Browser started"
        )
        return _tool_response(
            json.dumps(
                {"ok": True, "message": msg},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Browser start failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_stop() -> ToolResponse:
    if _state["browser"] is None:
        return _tool_response(
            json.dumps(
                {"ok": True, "message": "Browser not running"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        await _state["browser"].close()
        if _state["playwright"] is not None:
            await _state["playwright"].stop()
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Browser stop failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    finally:
        _state["playwright"] = None
        _state["browser"] = None
        _state["context"] = None
        _state["pages"].clear()
        _state["refs"].clear()
        _state["refs_frame"].clear()
        _state["console_logs"].clear()
        _state["network_requests"].clear()
        _state["pending_dialogs"].clear()
        _state["pending_file_choosers"].clear()
        _state["current_page_id"] = None
        _state["page_counter"] = 0
        _state["headless"] = True  # next start defaults to background
    return _tool_response(
        json.dumps(
            {"ok": True, "message": "Browser stopped"},
            ensure_ascii=False,
            indent=2,
        ),
    )


async def _action_open(url: str, page_id: str) -> ToolResponse:
    url = (url or "").strip()
    if not url:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "url required for open"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    if not await _ensure_browser():
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "Browser not started"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        page = await _state["context"].new_page()
        _state["refs"][page_id] = {}
        _state["console_logs"][page_id] = []
        _state["network_requests"][page_id] = []
        _state["pending_dialogs"][page_id] = []
        _state["pending_file_choosers"][page_id] = []
        _attach_page_listeners(page, page_id)
        await page.goto(url)
        _state["pages"][page_id] = page
        _state["current_page_id"] = page_id
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


async def _action_navigate(url: str, page_id: str) -> ToolResponse:
    url = (url or "").strip()
    if not url:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "url required for navigate"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        await page.goto(url)
        _state["current_page_id"] = page_id
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
    page = _get_page(page_id)
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
            await locator.screenshot(
                path=path,
                type=screenshot_type if screenshot_type == "jpeg" else "png",
            )
        else:
            if frame_selector and frame_selector.strip():
                root = _get_root(page, page_id, frame_selector)
                locator = root.locator("body").first
                await locator.screenshot(
                    path=path,
                    type=screenshot_type
                    if screenshot_type == "jpeg"
                    else "png",
                )
            else:
                await page.screenshot(
                    path=path,
                    full_page=full_page,
                    type=screenshot_type
                    if screenshot_type == "jpeg"
                    else "png",
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
    page = _get_page(page_id)
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
            "button": button
            if button in ("left", "right", "middle")
            else "left",
        }
        if mods:
            kwargs["modifiers"] = [
                m
                for m in mods
                if m in ("Alt", "Control", "ControlOrMeta", "Meta", "Shift")
            ]
        if ref:
            locator = _get_locator_by_ref(page, page_id, ref, frame_selector)
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
            root = _get_root(page, page_id, frame_selector)
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
    page = _get_page(page_id)
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
            locator = _get_locator_by_ref(page, page_id, ref, frame_selector)
            if locator is None:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": f"Unknown ref: {ref}"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            if slowly:
                await locator.press_sequentially(text or "")
            else:
                await locator.fill(text or "")
            if submit:
                await locator.press("Enter")
        else:
            root = _get_root(page, page_id, frame_selector)
            loc = root.locator(selector).first
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


async def _action_eval(page_id: str, code: str) -> ToolResponse:
    code = (code or "").strip()
    if not code:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "code required for eval"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(page_id)
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
            result = await page.evaluate(code)
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


async def _action_pdf(page_id: str, path: str) -> ToolResponse:
    path = (path or "page.pdf").strip() or "page.pdf"
    page = _get_page(page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
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


async def _action_close(page_id: str) -> ToolResponse:
    page = _get_page(page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        await page.close()
        del _state["pages"][page_id]
        for key in (
            "refs",
            "refs_frame",
            "console_logs",
            "network_requests",
            "pending_dialogs",
            "pending_file_choosers",
        ):
            _state[key].pop(page_id, None)
        if _state.get("current_page_id") == page_id:
            remaining = list(_state["pages"].keys())
            _state["current_page_id"] = remaining[0] if remaining else None
        if _state.get("current_page_id") == page_id:
            remaining = list(_state["pages"].keys())
            _state["current_page_id"] = remaining[0] if remaining else None
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
    page_id: str,
    filename: str,
    frame_selector: str = "",
) -> ToolResponse:
    page = _get_page(page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        root = _get_root(page, page_id, frame_selector)
        locator = root.locator(":root")
        raw = await locator.aria_snapshot()
        raw_str = str(raw) if raw is not None else ""
        snapshot, refs = build_role_snapshot_from_aria(
            raw_str,
            interactive=False,
            compact=False,
        )
        _state["refs"][page_id] = refs
        _state["refs_frame"][page_id] = (
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
            with open(filename.strip(), "w", encoding="utf-8") as f:
                f.write(snapshot)
            out["filename"] = filename.strip()
        return _tool_response(json.dumps(out, ensure_ascii=False, indent=2))
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Snapshot failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_navigate_back(page_id: str) -> ToolResponse:
    page = _get_page(page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
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
    page = _get_page(page_id)
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
            result = await locator.evaluate(code)
        else:
            if code.strip().startswith("(") or code.strip().startswith(
                "function",
            ):
                result = await page.evaluate(code)
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
                {"ok": False, "error": f"Evaluate failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_resize(
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
    page = _get_page(page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
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
    page_id: str,
    level: str,
    filename: str,
) -> ToolResponse:
    level = (level or "info").strip().lower()
    order = ("error", "warning", "info", "debug")
    idx = order.index(level) if level in order else 2
    page = _get_page(page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    logs = _state["console_logs"].get(page_id, [])
    filtered = (
        [m for m in logs if order.index(m["level"]) <= idx]
        if level in order
        else logs
    )
    lines = [f"[{m['level']}] {m['text']}" for m in filtered]
    text = "\n".join(lines)
    if filename and filename.strip():
        with open(filename.strip(), "w", encoding="utf-8") as f:
            f.write(text)
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Console messages saved to {filename}",
                    "filename": filename.strip(),
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
    page_id: str,
    accept: bool,
    prompt_text: str,
) -> ToolResponse:
    page = _get_page(page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    dialogs = _state["pending_dialogs"].get(page_id, [])
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
                await dialog.accept(prompt_text)
            else:
                await dialog.accept()
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


async def _action_file_upload(page_id: str, paths_json: str) -> ToolResponse:
    page = _get_page(page_id)
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
        choosers = _state["pending_file_choosers"].get(page_id, [])
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
            await chooser.set_files(paths)
            return _tool_response(
                json.dumps(
                    {"ok": True, "message": f"Uploaded {len(paths)} file(s)"},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
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


async def _action_fill_form(page_id: str, fields_json: str) -> ToolResponse:
    page = _get_page(page_id)
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
    refs = _get_refs(page_id)
    # Use last snapshot's frame so fill_form works after iframe snapshot
    frame = _state["refs_frame"].get(page_id, "")
    try:
        for f in fields:
            ref = (f.get("ref") or "").strip()
            if not ref or ref not in refs:
                continue
            locator = _get_locator_by_ref(page, page_id, ref, frame)
            if locator is None:
                continue
            field_type = (f.get("type") or "textbox").lower()
            value = f.get("value")
            if field_type == "checkbox":
                if isinstance(value, str):
                    value = value.strip().lower() in ("true", "1", "yes")
                await locator.set_checked(bool(value))
            elif field_type == "radio":
                await locator.set_checked(True)
            elif field_type == "combobox":
                await locator.select_option(
                    label=value if isinstance(value, str) else None,
                    value=value,
                )
            elif field_type == "slider":
                await locator.fill(str(value))
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


async def _action_install() -> ToolResponse:
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install"],
            check=True,
            capture_output=True,
            text=True,
            timeout=120000,
        )
        return _tool_response(
            json.dumps(
                {"ok": True, "message": "Browser installed"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Install failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_press_key(page_id: str, key: str) -> ToolResponse:
    key = (key or "").strip()
    if not key:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "key required for press_key"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
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
    page_id: str,
    include_static: bool,
    filename: str,
) -> ToolResponse:
    page = _get_page(page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    requests = _state["network_requests"].get(page_id, [])
    if not include_static:
        static = ("image", "stylesheet", "font", "media")
        requests = [r for r in requests if r.get("resourceType") not in static]
    lines = [
        f"{r.get('method', '')} {r.get('url', '')} {r.get('status', '')}"
        for r in requests
    ]
    text = "\n".join(lines)
    if filename and filename.strip():
        with open(filename.strip(), "w", encoding="utf-8") as f:
            f.write(text)
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Network requests saved to {filename}",
                    "filename": filename.strip(),
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


async def _action_run_code(page_id: str, code: str) -> ToolResponse:
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
    page = _get_page(page_id)
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
            result = await page.evaluate(code)
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
    page = _get_page(page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        root = _get_root(page, page_id, frame_selector)
        if use_refs:
            start_locator = _get_locator_by_ref(
                page,
                page_id,
                start_ref,
                frame_selector,
            )
            end_locator = _get_locator_by_ref(
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
    page = _get_page(page_id)
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
            locator = _get_locator_by_ref(page, page_id, ref, frame_selector)
            if locator is None:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": f"Unknown ref: {ref}"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
        else:
            root = _get_root(page, page_id, frame_selector)
            locator = root.locator(selector).first
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
    page = _get_page(page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        locator = _get_locator_by_ref(page, page_id, ref, frame_selector)
        if locator is None:
            return _tool_response(
                json.dumps(
                    {"ok": False, "error": f"Unknown ref: {ref}"},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
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
    pages = _state["pages"]
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
        if not _state["context"]:
            ok = await _ensure_browser()
            if not ok:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": "Browser not started"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
        try:
            page = await _state["context"].new_page()
            new_id = _next_page_id()
            _state["refs"][new_id] = {}
            _state["console_logs"][new_id] = []
            _state["network_requests"][new_id] = []
            _state["pending_dialogs"][new_id] = []
            _attach_page_listeners(page, new_id)
            _state["pages"][new_id] = page
            _state["current_page_id"] = new_id
            return _tool_response(
                json.dumps(
                    {
                        "ok": True,
                        "page_id": new_id,
                        "tabs": list(_state["pages"].keys()),
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
        return await _action_close(target_id)
    if tab_action == "select":
        target_id = page_ids[index] if 0 <= index < len(page_ids) else page_id
        _state["current_page_id"] = target_id
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
    page_id: str,
    wait_time: float,
    text: str,
    text_gone: str,
) -> ToolResponse:
    page = _get_page(page_id)
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
            await page.get_by_text(text).wait_for(
                state="visible",
                timeout=30000,
            )
        if text_gone:
            await page.get_by_text(text_gone).wait_for(
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
