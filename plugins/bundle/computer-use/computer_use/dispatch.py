# -*- coding: utf-8 -*-
"""Thin tool adapter for the host-managed Computer Use runtime."""

# NOTE: no `from __future__ import annotations` here, deliberately. The tool
# entry point below is handed to the runtime's JSON-schema builder, which
# resolves annotations in a namespace without our typing imports; stringized
# annotations would abort the toolkit build. Under Python 3.11 every
# annotation in this module evaluates fine at definition time.

import asyncio
import json
import logging
import threading
import time
from typing import Any, Literal, Mapping

from agentscope.message import DataBlock, TextBlock, ToolResultState, URLSource
from agentscope.tool import ToolChunk

from qwenpaw.runtime.tool_registry import tool_descriptor

from .client import get_computer_use_client
from .feature_state import get_computer_use_feature_state
from .protocol import ComputerUseProtocolError

_LOGGER = logging.getLogger(__name__)
_MAX_ACTIONS_PER_MINUTE = 60
_action_times: list[float] = []
_rate_limit_lock = threading.Lock()
_SCREENSHOT_URL_PLACEHOLDER = "<image delivered as a separate attachment>"

ComputerUseAction = Literal[
    "list_apps",
    "list_windows",
    "observe_window",
    "launch_app",
    "close_window",
    "click",
    "double_click",
    "right_click",
    "scroll",
    "drag",
    "type",
    "press_key",
    "invoke",
    "set_value",
    "wait",
    "stop",
]


def _check_rate_limit() -> None:
    # The tool can be entered from more than one event loop -- the host runs
    # per-workspace loops on their own threads -- so the guard is a threading
    # lock rather than an asyncio one, which serialises only within a single
    # loop. Under the GIL the unguarded check-then-append is narrow enough that
    # overshooting the cap could not be provoked, but that is a property of the
    # interpreter rather than of this code, and a free-threaded build removes
    # it. The body has no await, so the lock is held briefly.
    with _rate_limit_lock:
        now = time.monotonic()
        _action_times[:] = [
            value for value in _action_times if now - value < 60
        ]
        if len(_action_times) >= _MAX_ACTIONS_PER_MINUTE:
            raise ComputerUseProtocolError(
                "rate_limited",
                "Computer Use rate limit exceeded; wait before continuing.",
            )
        _action_times.append(now)


def _without_screenshot_urls(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Replace inline screenshot data with a placeholder for text output.

    Screenshots are attached as image blocks; repeating the base64 data
    URL inside the JSON text block would double a multi-megabyte payload
    and pollute the model's text context.
    """
    screenshots = payload.get("screenshots")
    if not isinstance(screenshots, list):
        return payload
    sanitized: list[Any] = []
    for screenshot in screenshots:
        if isinstance(screenshot, Mapping) and "url" in screenshot:
            sanitized.append(
                {**screenshot, "url": _SCREENSHOT_URL_PLACEHOLDER},
            )
        else:
            sanitized.append(screenshot)
    return {**payload, "screenshots": sanitized}


def _element_line(element: Mapping[str, Any]) -> str:
    """Render one accessibility element as a single compact line.

    Only the model reads these elements, so the JSON scaffolding around
    them is pure overhead. Windows reports pixel ``bounds`` and macOS
    reports a control ``value`` instead, so the locator part is chosen from
    whichever the platform actually provided rather than assumed.
    """
    parts = [
        str(element.get("id") or "?"),
        str(element.get("control_type_name") or element.get("role") or "?"),
        f'"{element.get("name") or ""}"',
    ]
    bounds = element.get("bounds")
    value = element.get("value")
    if isinstance(bounds, (list, tuple)) and len(bounds) == 4:
        try:
            left, top, right, bottom = (int(edge) for edge in bounds)
        except (TypeError, ValueError):
            pass
        else:
            parts.append(f"screen@{(left + right) // 2},{(top + bottom) // 2}")
    elif isinstance(value, str) and value:
        parts.append(f"={value}")
    # Both states stay visible: an offscreen entry may become reachable
    # after scrolling, and a disabled control tells the model not to try.
    if element.get("enabled") is False:
        parts.append("[disabled]")
    if element.get("offscreen") is True:
        parts.append("[offscreen]")
    if element.get("selected") is True:
        parts.append("[selected]")
    if element.get("settable") is True:
        parts.append("[settable]")
    if element.get("resource_backed") is True:
        parts.append("[resource-backed]")
    actions = element.get("actions")
    if isinstance(actions, list):
        names = [str(action) for action in actions if str(action)]
        if names:
            parts.append(f"[actions={','.join(names)}]")
    return " ".join(parts)


def _with_compact_elements(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Replace the accessibility element objects with one line each."""
    accessibility = payload.get("accessibility")
    if not isinstance(accessibility, Mapping):
        return payload
    elements = accessibility.get("elements")
    if not isinstance(elements, list):
        return payload
    lines = [
        _element_line(element)
        for element in elements
        if isinstance(element, Mapping)
    ]
    compact = {
        key: value for key, value in accessibility.items() if key != "elements"
    }
    compact["elements"] = "\n".join(lines)
    return {**payload, "accessibility": compact}


def _response(
    payload: Mapping[str, Any],
    *,
    include_images: bool = False,
    state: ToolResultState = ToolResultState.SUCCESS,
) -> ToolChunk:
    content: list[Any] = []
    if include_images:
        for screenshot in payload.get("screenshots", []):
            if isinstance(screenshot, Mapping) and isinstance(
                screenshot.get("url"),
                str,
            ):
                content.append(
                    DataBlock(
                        source=URLSource(
                            url=screenshot["url"],
                            media_type="image/*",
                        ),
                    ),
                )
    content.append(
        TextBlock(
            type="text",
            text=json.dumps(
                _with_compact_elements(_without_screenshot_urls(payload)),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        ),
    )
    return ToolChunk(content=content, state=state, is_last=True)


def _error(code: str, message: str) -> ToolChunk:
    return _response(
        {
            "ok": False,
            "error": {"code": code, "message": message},
        },
        state=ToolResultState.ERROR,
    )


@tool_descriptor(
    name="computer_use",
    enabled_by_default=True,
    async_execution=True,
    description=(
        "Control approved desktop applications through the native "
        "Computer Use runtime. Observe a window before acting; the runtime "
        "keeps the current observation synchronized between actions."
    ),
    requires_skills=("computer_use",),
)
async def computer_use(
    action: ComputerUseAction,
    app: str = "",
    window_id: str = "",
    element_id: str = "",
    x: int = 0,
    y: int = 0,
    start_x: int = 0,
    start_y: int = 0,
    end_x: int = 0,
    end_y: int = 0,
    source_element_id: str = "",
    target_element_id: str = "",
    button: str = "left",
    count: int = 1,
    delta_y: int = 0,
    text: str = "",
    value: str = "",
    key: str = "",
    wait_ms: int = 500,
    timeout_ms: int = 10000,
) -> ToolChunk:
    """Control one observed window at a time.

    Use ``list_apps`` or ``list_windows`` first. Observe a target with
    ``observe_window`` before acting. The client advances the native
    observation after every successful action; native rejects stale state.
    ``launch_app`` accepts an App ID returned by ``list_apps`` or an absolute
    platform-native application path.
    """
    # Each early return maps to one refusal reason the model must be able to
    # tell apart, so they are reported individually rather than merged.
    # pylint: disable=too-many-return-statements
    try:
        _check_rate_limit()
        action = str(action or "").strip().lower()
        if not action:
            raise ValueError("action is required.")
        if not get_computer_use_feature_state().is_enabled():
            return _error(
                "feature_disabled",
                "Computer Use is turned off. Enable it in the Computer Use "
                "panel to allow desktop automation.",
            )
        if action == "wait":
            await asyncio.sleep(max(0, min(wait_ms, 30_000)) / 1000)
            return _response(
                {"ok": True, "action": action, "waited_ms": wait_ms},
            )

        client = get_computer_use_client()
        if action == "stop":
            await client.stop_turn()
            return _response({"ok": True, "action": action})

        method, params, include_images = _native_request(
            action,
            app=app,
            window_id=window_id,
            element_id=element_id,
            x=x,
            y=y,
            start_x=start_x,
            start_y=start_y,
            end_x=end_x,
            end_y=end_y,
            source_element_id=source_element_id,
            target_element_id=target_element_id,
            button=button,
            count=count,
            delta_y=delta_y,
            text=text,
            value=value,
            key=key,
        )
        result = await client.execute(
            method,
            params,
            deadline_ms=max(100, min(timeout_ms, 30_000)),
        )
        payload = {"ok": True, "action": action, **result}
        return _response(
            payload,
            include_images=include_images or bool(result.get("screenshots")),
        )
    except ComputerUseProtocolError as error:
        return _error(error.code, str(error))
    except ValueError as error:
        return _error("invalid_request", str(error))
    except (
        Exception
    ) as error:  # noqa: BLE001 - tool calls must not escape errors
        # A tool entry point must not raise, but the errors that reach here are
        # the unexpected ones -- an attribute error, a bad type, a broken
        # import -- not the protocol failures handled above. Collapsing them to
        # one message keeps the turn alive; logging the traceback first keeps
        # them diagnosable rather than lost behind "Computer Use failed".
        _LOGGER.exception("Computer Use tool call failed unexpectedly")
        return _error("tool_failed", f"Computer Use failed: {error}")


def _native_request(
    action: str,
    **values: Any,
) -> tuple[str, dict[str, Any], bool]:
    # One branch per action keeps the whole request contract readable in a
    # single place; splitting it per action would scatter the protocol.
    # pylint: disable=too-many-return-statements
    # pylint: disable=too-many-branches, too-many-statements
    if action == "list_apps":
        return action, {}, False
    if action == "list_windows":
        app = str(values["app"] or "").strip()
        return action, ({"app": app} if app else {}), False
    if action == "launch_app":
        app = str(values["app"] or "").strip()
        if not app:
            raise ValueError(
                "launch_app requires an App ID or an absolute .exe path.",
            )
        return action, {"app": app}, False

    if action == "observe_window":
        window_id = str(values["window_id"] or "").strip()
        if not window_id:
            raise ValueError(
                "observe_window requires window_id from list_windows.",
            )
        return action, {"window_id": window_id}, True
    if action == "close_window":
        return action, {}, False
    if action in {"click", "double_click", "right_click"}:
        params = {}
        element_id = str(values.get("element_id") or "").strip()
        if element_id:
            params["element_id"] = element_id
        else:
            params["x"] = values["x"]
            params["y"] = values["y"]
        params["button"] = (
            "right" if action == "right_click" else values["button"]
        )
        params["count"] = 2 if action == "double_click" else values["count"]
        return "click", params, False
    if action == "scroll":
        params = {"x": values["x"], "y": values["y"]}
        params["delta_y"] = values["delta_y"]
        return action, params, False
    if action == "drag":
        source_element_id = str(
            values.get("source_element_id") or "",
        ).strip()
        target_element_id = str(
            values.get("target_element_id") or "",
        ).strip()
        if bool(source_element_id) != bool(target_element_id):
            raise ValueError(
                "drag requires both source_element_id and "
                "target_element_id, or neither.",
            )
        params = {}
        if source_element_id:
            params.update(
                source_element_id=source_element_id,
                target_element_id=target_element_id,
            )
        else:
            params.update(
                start_x=values["start_x"],
                start_y=values["start_y"],
                end_x=values["end_x"],
                end_y=values["end_y"],
            )
        return action, params, False
    if action == "type":
        text = str(values["text"] or "")
        if not text:
            raise ValueError("type requires non-empty text.")
        return (
            "type_text",
            {"text": text},
            False,
        )
    if action in {"invoke", "set_value"}:
        element_id = str(values["element_id"] or "").strip()
        if not element_id:
            raise ValueError(
                f"{action} requires element_id from observe_window.",
            )
        params = {"element_id": element_id}
        if action == "set_value":
            params["value"] = str(values["value"] or "")
        return (
            f"{action}_element" if action == "invoke" else action,
            params,
            False,
        )
    if action == "press_key":
        key = str(values["key"] or "").strip()
        if not key:
            raise ValueError("press_key requires key.")
        return action, {"key": key}, False
    raise ValueError(
        "Unknown action. Valid actions: list_apps, list_windows, "
        "observe_window, launch_app, close_window, click, "
        "double_click, right_click, scroll, drag, type, press_key, invoke, "
        "set_value, wait, stop.",
    )
