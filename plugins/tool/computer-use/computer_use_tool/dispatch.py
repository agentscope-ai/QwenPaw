"""Thin tool adapter for the host-managed Computer Use runtime."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Mapping

from agentscope.message import DataBlock, TextBlock, URLSource
from agentscope.tool import ToolResponse

from qwenpaw.runtime.tool_registry import tool_descriptor

from .client import get_computer_use_client
from .feature_state import get_computer_use_feature_state
from .protocol import ComputerUseProtocolError

_MAX_ACTIONS_PER_MINUTE = 60
_action_times: list[float] = []
_SCREENSHOT_URL_PLACEHOLDER = "<image delivered as a separate attachment>"

# Control actions that can open a dialog, prompt, or error window. After one
# of these we probe the window list and flag anything that just appeared, so
# the model observes it instead of blindly sending more input to the old
# window.
_DIALOG_HINT_ACTIONS = frozenset(
    {
        "press_key",
        "type",
        "click",
        "double_click",
        "right_click",
        "drag",
        "invoke",
        "set_value",
        "close_window",
    }
)
_WINDOW_PROBE_DEADLINE_MS = 3000


def _check_rate_limit() -> None:
    now = time.monotonic()
    _action_times[:] = [value for value in _action_times if now - value < 60]
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
                {**screenshot, "url": _SCREENSHOT_URL_PLACEHOLDER}
            )
        else:
            sanitized.append(screenshot)
    return {**payload, "screenshots": sanitized}


def _response(payload: Mapping[str, Any], *, include_images: bool = False) -> ToolResponse:
    content: list[Any] = []
    if include_images:
        for screenshot in payload.get("screenshots", []):
            if isinstance(screenshot, Mapping) and isinstance(screenshot.get("url"), str):
                content.append(
                    DataBlock(
                        source=URLSource(url=screenshot["url"], media_type="image/*"),
                    ),
                )
    content.append(
        TextBlock(
            type="text",
            text=json.dumps(
                _without_screenshot_urls(payload), ensure_ascii=False, indent=2
            ),
        ),
    )
    return ToolResponse(content=content)


def _error(code: str, message: str) -> ToolResponse:
    return _response({"ok": False, "error": {"code": code, "message": message}})


def _dialog_hint(new_windows: list[Mapping[str, Any]]) -> str:
    listed = "; ".join(
        f'id={window.get("id")} "{window.get("title", "")}"'
        for window in new_windows[:5]
    )
    return (
        f"A new window appeared after this action ({listed}). It may be a "
        "dialog, prompt, or error that needs handling. Select it and call "
        "observe_window before continuing; act through its accessibility "
        "elements rather than sending more input to the previous window."
    )


async def _note_new_windows(client: Any, payload: dict[str, Any]) -> None:
    """Flag any window a control action just opened (best-effort).

    Probing must never fail the action it follows, so transport errors are
    swallowed and the original acknowledgement is returned unchanged.
    """
    try:
        probe = await client.execute(
            "list_windows", {}, deadline_ms=_WINDOW_PROBE_DEADLINE_MS
        )
    except Exception:  # noqa: BLE001 - a probe must not break the action
        return
    new_windows = client.observe_windows(probe.get("windows"))
    if new_windows:
        payload["hint"] = _dialog_hint(new_windows)


def _window_id(value: str, action: str) -> str:
    window_id = str(value or "").strip()
    if not window_id:
        raise ValueError(f"{action} requires window_id from list_windows.")
    return window_id


def _snapshot_params(
    *,
    window_id: str,
    snapshot_id: str,
    screenshot_id: str,
) -> dict[str, str]:
    if not snapshot_id:
        raise ValueError("Coordinate input requires snapshot_id from observe_window.")
    if not screenshot_id:
        raise ValueError("Coordinate input requires screenshot_id from observe_window.")
    return {
        "window_id": window_id,
        "snapshot_id": snapshot_id,
        "screenshot_id": screenshot_id,
    }


def _point_params(
    *,
    window_id: str,
    snapshot_id: str,
    screenshot_id: str,
    x: int,
    y: int,
) -> dict[str, Any]:
    return {
        **_snapshot_params(
            window_id=window_id,
            snapshot_id=snapshot_id,
            screenshot_id=screenshot_id,
        ),
        "x": x,
        "y": y,
    }


@tool_descriptor(
    name="computer_use",
    enabled_by_default=True,
    async_execution=True,
    description="Control approved desktop applications through the native Computer Use runtime.",
    requires_skills=("computer_use",),
)
async def computer_use(
    action: str,
    app: str = "",
    window_id: str = "",
    snapshot_id: str = "",
    screenshot_id: str = "",
    accessibility_revision: str = "",
    element_id: str = "",
    x: int = 0,
    y: int = 0,
    start_x: int = 0,
    start_y: int = 0,
    end_x: int = 0,
    end_y: int = 0,
    button: str = "left",
    count: int = 1,
    delta_y: int = 0,
    text: str = "",
    value: str = "",
    key: str = "",
    wait_ms: int = 500,
    timeout_ms: int = 10000,
    **_ignored: Any,
) -> ToolResponse:
    """Control one observed window at a time.

    Use ``list_apps`` or ``list_windows`` first. Observe a target with
    ``observe_window`` before any coordinate action. Visual input always
    requires the exact ``window_id``, ``snapshot_id``, and ``screenshot_id``
    returned by that observation; stale geometry is rejected by Native.
    ``launch_app`` accepts an App ID returned by ``list_apps`` or an absolute
    ``.exe`` path.
    """
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
            return _response({"ok": True, "action": action, "waited_ms": wait_ms})

        client = get_computer_use_client()
        if action == "stop":
            await client.stop_turn()
            return _response({"ok": True, "action": action})

        method, params, include_images = _native_request(
            action,
            app=app,
            window_id=window_id,
            snapshot_id=snapshot_id,
            screenshot_id=screenshot_id,
            accessibility_revision=accessibility_revision,
            element_id=element_id,
            x=x,
            y=y,
            start_x=start_x,
            start_y=start_y,
            end_x=end_x,
            end_y=end_y,
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
        if action == "list_windows":
            client.observe_windows(result.get("windows"))
        elif action in _DIALOG_HINT_ACTIONS:
            await _note_new_windows(client, payload)
        return _response(payload, include_images=include_images)
    except ComputerUseProtocolError as error:
        return _error(error.code, str(error))
    except ValueError as error:
        return _error("invalid_request", str(error))
    except Exception as error:  # noqa: BLE001 - tool calls must not escape errors
        return _error("tool_failed", f"Computer Use failed: {error}")


def _native_request(action: str, **values: Any) -> tuple[str, dict[str, Any], bool]:
    if action in {"list_apps", "list_windows"}:
        return action, {}, False
    if action == "launch_app":
        app = str(values["app"] or "").strip()
        if not app:
            raise ValueError("launch_app requires an App ID or an absolute .exe path.")
        return action, {"app": app}, False

    window_id = _window_id(values["window_id"], action)
    if action == "find_window":
        return action, {"window_id": window_id}, False
    if action == "observe_window":
        return action, {"window_id": window_id}, True
    if action == "set_focus":
        return action, {"window_id": window_id}, False
    if action == "close_window":
        return action, {"window_id": window_id}, False
    if action in {"click", "double_click", "right_click"}:
        params = _point_params(
            window_id=window_id,
            snapshot_id=values["snapshot_id"],
            screenshot_id=values["screenshot_id"],
            x=values["x"],
            y=values["y"],
        )
        params["button"] = "right" if action == "right_click" else values["button"]
        params["count"] = 2 if action == "double_click" else values["count"]
        return "click", params, False
    if action == "scroll":
        params = _point_params(
            window_id=window_id,
            snapshot_id=values["snapshot_id"],
            screenshot_id=values["screenshot_id"],
            x=values["x"],
            y=values["y"],
        )
        params["delta_y"] = values["delta_y"]
        return action, params, False
    if action == "drag":
        params = _snapshot_params(
            window_id=window_id,
            snapshot_id=values["snapshot_id"],
            screenshot_id=values["screenshot_id"],
        )
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
        return "type_text", {"window_id": window_id, "text": text}, False
    if action in {"invoke", "set_value"}:
        revision = str(values["accessibility_revision"] or "").strip()
        element_id = str(values["element_id"] or "").strip()
        if not revision or not element_id:
            raise ValueError(
                f"{action} requires accessibility_revision and element_id from observe_window.",
            )
        params = {
            "window_id": window_id,
            "accessibility_revision": revision,
            "element_id": element_id,
        }
        if action == "set_value":
            params["value"] = str(values["value"] or "")
        return f"{action}_element" if action == "invoke" else action, params, False
    if action == "press_key":
        key = str(values["key"] or "").strip()
        if not key:
            raise ValueError("press_key requires key.")
        return action, {"window_id": window_id, "key": key}, False
    raise ValueError(
        "Unknown action. Valid actions: list_apps, list_windows, find_window, "
        "observe_window, launch_app, set_focus, close_window, click, "
        "double_click, right_click, scroll, drag, type, press_key, invoke, "
        "set_value, wait, stop.",
    )
