# -*- coding: utf-8 -*-
"""Desktop live operation: drive a native app and record the screen.

This mirrors the browser bridge so the agent organizes the flow itself: it
writes async Python with ``desktop`` (observe/act on the native app, reusing
the host's Computer Use client) and ``recorder`` (system screen capture) in
scope, and only start/stop bounds are filmed.

Desktop control requires the Tauri host's native runtime, which is absent on
headless servers. The tool therefore always probes capability first and
degrades with a clear, actionable result instead of failing opaquely — a
static UI can be shown with a screenshot plus motion instead of a recording.
The native client lives in the computer-use bundle, importable only once the
host has loaded it, so it is bound lazily.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import hashlib
import io
import logging
import math
import uuid
from pathlib import Path
from typing import Any

from .bridge import (
    LiveOperationError,
    LiveOperationRun,
    _clip,
    _compile,
    _execute,
)
from .manifest import ActionFact, BoundingBox
from .screen_recorder import (
    ScreenRecorder,
    ffmpeg_available,
    screen_capture_supported,
)
from .session import workspace_dir

logger = logging.getLogger(__name__)

_READ_ONLY_METHODS = frozenset(
    {"list_apps", "list_windows", "observe_window"},
)


def computer_use_status() -> dict[str, Any]:
    """Report every precondition for desktop operation, separately.

    Reported apart so a caller can tell a machine that will never support the
    feature from a host that simply has not offered a capability yet.
    """
    supported = screen_capture_supported()
    host_reachable = False
    platform_helper = False
    host_feature_enabled = False
    host_feature_state_available = False
    try:
        from qwenpaw.app.computer_use import HostRuntimeProvider

        runtime = HostRuntimeProvider.status()
        platform_helper = bool(runtime.supported_platform)
        host_reachable = bool(runtime.host_reachable)
    except Exception:  # noqa: BLE001 - runtime absent means simply unavailable
        logger.debug("computer-use runtime probe failed", exc_info=True)
    try:
        from computer_use.feature_state import (
            get_computer_use_feature_state,
        )

        host_feature_state_available = True
        host_feature_enabled = bool(
            get_computer_use_feature_state().is_enabled(),
        )
    except Exception:  # noqa: BLE001 - bundle absence means unavailable
        logger.debug("computer-use feature-state probe failed", exc_info=True)
    available = (
        platform_helper
        and host_reachable
        and host_feature_state_available
        and host_feature_enabled
    )
    return {
        "available": available,
        "recording_available": (
            available and supported and ffmpeg_available()
        ),
        "screen_capture_supported": supported,
        "native_helper_platform": platform_helper,
        "host_reachable": host_reachable,
        "host_feature_state_available": host_feature_state_available,
        "host_feature_enabled": host_feature_enabled,
        "ffmpeg": ffmpeg_available(),
    }


def _unavailable_reason(status: dict[str, Any]) -> str:
    if not status.get("host_feature_state_available"):
        return (
            "the host Computer Use plugin is unavailable; load the "
            "computer-use plugin before enabling Creator desktop operation"
        )
    if not status.get("host_feature_enabled"):
        return (
            "Computer Use is turned off in the host; enable it in the "
            "Computer Use panel before allowing any agent to control the "
            "desktop"
        )
    if (
        not status["native_helper_platform"]
        or not status["screen_capture_supported"]
    ):
        return (
            "desktop operation needs the native Computer Use helper, which "
            "exists only on Windows and macOS"
        )
    if not status["host_reachable"]:
        return (
            "the desktop host runtime is not reachable; desktop operation "
            "needs QwenPaw running on the desktop (Tauri host), not a "
            "headless server"
        )
    return "desktop operation is unavailable in this environment"


def _load_native_client(session_id: str) -> Any:
    """Bind the host's Computer Use client if the bundle is loaded."""
    try:
        from computer_use.client import (  # type: ignore[import-not-found]
            ComputerUseClient,
        )
    except Exception as exc:  # noqa: BLE001 - bundle absent outside a host
        raise LiveOperationError(
            "the Computer Use client is unavailable; desktop operation needs "
            "the computer-use plugin loaded by the desktop host",
        ) from exc
    return ComputerUseClient(session_id)


class DesktopController:  # pylint: disable=too-many-public-methods
    """The ``desktop`` name the model sees: observe and act on the app.

    Every method forwards to the host's native client, so the vocabulary and
    trust boundary are the host's, not a reimplementation. Observations expose
    the focused window's bounds, which recording crops to and which action
    coordinates are projected against.
    """

    def __init__(
        self,
        client: Any,
        recorder: ScreenRecorder,
        workspace: Path,
    ) -> None:
        self._client = client
        self._recorder = recorder
        self._workspace = workspace
        self._window_bounds: dict[str, Any] | None = None
        self._element_bounds: dict[str, dict[str, Any]] = {}
        self._screenshot_geometry: dict[str, dict[str, Any]] = {}
        self._screenshots: list[str] = []

    @property
    def window_bounds(self) -> dict[str, Any] | None:
        return self._window_bounds

    @property
    def screenshots(self) -> list[str]:
        return list(self._screenshots)

    async def _execute(self, method: str, **params: Any) -> dict[str, Any]:
        return await self._execute_recorded(method, method, params)

    async def _execute_recorded(
        self,
        method: str,
        fact_op: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute one native verb under its precise manifest operation."""
        bbox = self._action_bbox(method, params)
        manifest = self._recorder.manifest
        started_ms = self._recorder.elapsed_ms() if manifest else 0
        failed = False
        try:
            result = await self._client.execute(method, params)
        except BaseException:
            failed = True
            raise
        finally:
            if manifest is not None and method not in _READ_ONLY_METHODS:
                manifest.record(
                    ActionFact(
                        op=fact_op,
                        t_start_ms=started_ms,
                        t_end_ms=self._recorder.elapsed_ms(),
                        target=_desktop_target(params),
                        bbox=bbox,
                        screenshot_ref=str(params.get("screenshot_id") or ""),
                        failed=failed,
                    ),
                )
        if method == "observe_window":
            self._remember_observation(result)
        return result

    def _remember_observation(self, result: Any) -> None:
        if not isinstance(result, dict):
            return
        window = result.get("window")
        bounds = window.get("bounds") if isinstance(window, dict) else None
        if isinstance(bounds, dict):
            self._window_bounds = dict(bounds)
        self._element_bounds = {}
        accessibility = result.get("accessibility")
        elements = (
            accessibility.get("elements")
            if isinstance(accessibility, dict)
            else None
        )
        if isinstance(elements, list):
            for element in elements:
                if not isinstance(element, dict):
                    continue
                element_id = str(element.get("id") or "")
                element_bounds = element.get("bounds")
                if element_id and isinstance(element_bounds, dict):
                    self._element_bounds[element_id] = dict(element_bounds)
        screenshots = result.get("screenshots")
        if not isinstance(screenshots, list):
            return
        for screenshot in screenshots:
            if not isinstance(screenshot, dict):
                continue
            screenshot_id = str(screenshot.get("id") or "")
            if screenshot_id:
                self._screenshot_geometry[screenshot_id] = dict(screenshot)
            self._save_screenshot(screenshot)

    def _save_screenshot(self, screenshot: dict[str, Any]) -> None:
        """Persist a native observation image for ordinary asset ingestion."""
        url = screenshot.get("url")
        if not isinstance(url, str) or not url.startswith("data:image/"):
            return
        header, separator, encoded = url.partition(",")
        if not separator or ";base64" not in header:
            return
        media_type = header[5:].split(";", 1)[0].casefold()
        suffix = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }.get(media_type)
        if suffix is None:
            return
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return
        if not content:
            return
        digest = hashlib.sha256(content).hexdigest()[:16]
        path = self._workspace / f"desktop-shot-{digest}{suffix}"
        if not path.exists():
            path.write_bytes(content)
        value = str(path)
        if value not in self._screenshots:
            self._screenshots.append(value)

    # pylint: disable-next=too-many-return-statements
    def _action_bbox(
        self,
        method: str,
        params: dict[str, Any],
    ) -> BoundingBox | None:
        """Resolve an action target against the latest native observation."""
        direct = _bounds_to_bbox(params.get("bounds"), self._window_bounds)
        if direct is not None:
            return direct
        if method == "drag":
            source_id = str(params.get("source_element_id") or "")
            target_id = str(params.get("target_element_id") or "")
            source = _bounds_to_bbox(
                self._element_bounds.get(source_id),
                self._window_bounds,
            )
            target = _bounds_to_bbox(
                self._element_bounds.get(target_id),
                self._window_bounds,
            )
            if source is not None and target is not None:
                left = min(source.x, target.x)
                top = min(source.y, target.y)
                right = max(source.x + source.width, target.x + target.width)
                bottom = max(
                    source.y + source.height,
                    target.y + target.height,
                )
                return BoundingBox(left, top, right - left, bottom - top)
        element_id = str(params.get("element_id") or "")
        if element_id:
            return _bounds_to_bbox(
                self._element_bounds.get(element_id),
                self._window_bounds,
            )
        screenshot_id = str(params.get("screenshot_id") or "")
        geometry = self._screenshot_geometry.get(screenshot_id)
        if not isinstance(geometry, dict):
            return None
        origin = geometry.get("origin")
        origin_x = (
            origin.get("x", 0)
            if isinstance(origin, dict)
            else geometry.get("x", 0)
        )
        origin_y = (
            origin.get("y", 0)
            if isinstance(origin, dict)
            else geometry.get("y", 0)
        )
        if method == "drag":
            try:
                start_x = float(params["start_x"]) + float(origin_x)
                start_y = float(params["start_y"]) + float(origin_y)
                end_x = float(params["end_x"]) + float(origin_x)
                end_y = float(params["end_y"]) + float(origin_y)
            except (KeyError, TypeError, ValueError):
                return None
            return _bounds_to_bbox(
                {
                    "x": min(start_x, end_x),
                    "y": min(start_y, end_y),
                    "width": max(abs(end_x - start_x), 12.0),
                    "height": max(abs(end_y - start_y), 12.0),
                },
                self._window_bounds,
            )
        try:
            x = float(params["x"]) + float(origin_x)
            y = float(params["y"]) + float(origin_y)
        except (KeyError, TypeError, ValueError):
            return None
        return _bounds_to_bbox(
            {"x": x - 12, "y": y - 12, "width": 24, "height": 24},
            self._window_bounds,
        )

    async def list_apps(self) -> dict[str, Any]:
        return await self._execute("list_apps")

    async def list_windows(self, **params: Any) -> dict[str, Any]:
        return await self._execute("list_windows", **params)

    async def launch_app(self, app: str, **params: Any) -> dict[str, Any]:
        return await self._execute("launch_app", app=app, **params)

    async def observe_window(self, **params: Any) -> dict[str, Any]:
        return await self._execute("observe_window", **params)

    async def click(self, **params: Any) -> dict[str, Any]:
        return await self._execute("click", **params)

    async def double_click(self, **params: Any) -> dict[str, Any]:
        return await self._execute_recorded(
            "click",
            "double_click",
            {**params, "count": 2},
        )

    async def right_click(self, **params: Any) -> dict[str, Any]:
        return await self._execute_recorded(
            "click",
            "right_click",
            {**params, "button": "right"},
        )

    async def type_text(self, text: str, **params: Any) -> dict[str, Any]:
        return await self._execute("type_text", text=text, **params)

    async def type(self, text: str, **params: Any) -> dict[str, Any]:
        return await self.type_text(text, **params)

    async def press_key(self, key: str, **params: Any) -> dict[str, Any]:
        return await self._execute("press_key", key=key, **params)

    async def scroll(self, **params: Any) -> dict[str, Any]:
        return await self._execute("scroll", **params)

    async def drag(self, **params: Any) -> dict[str, Any]:
        return await self._execute("drag", **params)

    async def invoke_element(self, **params: Any) -> dict[str, Any]:
        return await self._execute("invoke_element", **params)

    async def invoke(self, **params: Any) -> dict[str, Any]:
        return await self.invoke_element(**params)

    async def begin_text_edit(self, **params: Any) -> dict[str, Any]:
        return await self._execute(
            "invoke_element",
            expects_text_input=True,
            **params,
        )

    async def set_value(self, **params: Any) -> dict[str, Any]:
        return await self._execute("set_value", **params)

    async def close_window(self, **params: Any) -> dict[str, Any]:
        return await self._execute("close_window", **params)

    async def sequence(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._execute("sequence", steps=steps)

    async def wait(self, wait_ms: int = 500) -> dict[str, Any]:
        bounded = max(0, min(int(wait_ms), 30_000))
        await asyncio.sleep(bounded / 1000)
        return {"ok": True, "waited_ms": bounded}


class DesktopRecorderHandle:
    """The ``recorder`` name inside desktop code: start/stop a screen take."""

    def __init__(
        self,
        recorder: ScreenRecorder,
        controller: DesktopController,
    ) -> None:
        self._recorder = recorder
        self._controller = controller

    async def start(self, *, label: str = "", screen: str = "0") -> str:
        return await asyncio.to_thread(
            self._recorder.start,
            label=label,
            window_bounds=self._controller.window_bounds,
            screen=screen,
        )

    async def stop(self) -> dict[str, Any]:
        _output, manifest = await asyncio.to_thread(self._recorder.stop)
        return {
            "take_id": manifest.take_id,
            "label": manifest.label,
            "summary": manifest.summary(),
        }

    def is_recording(self) -> bool:
        return self._recorder.recording


async def run_computer_use_code(
    code: str,
    *,
    run_root: Path,
    run_id: str,
    session_id: str,
    fps: int = 25,
    max_take_seconds: float = 300.0,
    timeout_seconds: float = 600.0,
) -> LiveOperationRun:
    """Run desktop code, or return a clear degraded run when unavailable."""
    source = code.strip()
    if not source:
        raise LiveOperationError("code is empty")
    status = computer_use_status()
    outcome = LiveOperationRun()
    if not status["available"]:
        outcome.output = "computer_use unavailable: " + _unavailable_reason(
            status,
        )
        outcome.result_repr = repr(status)
        return outcome
    compiled = _compile(source)
    workspace = workspace_dir(run_root, run_id)
    recorder = ScreenRecorder(
        workspace=workspace,
        fps=fps,
        max_duration_seconds=max_take_seconds,
    )
    client = _load_native_client(session_id)
    controller = DesktopController(client, recorder, workspace)
    from qwenpaw.app.computer_use import set_current_computer_use_turn_id
    from qwenpaw.app.agent_context import scoped_session_id

    # Bind one native turn for this dispatch; the host API is a setter, so its
    # result is not captured.
    stdout = io.StringIO()
    with scoped_session_id(session_id):
        set_current_computer_use_turn_id(f"creator-{uuid.uuid4().hex}")
        try:
            namespace: dict[str, Any] = {
                "__name__": "__computer_use__",
                "desktop": controller,
                "recorder": DesktopRecorderHandle(recorder, controller),
            }
            value = await asyncio.wait_for(
                _execute(
                    compiled,
                    namespace,
                    output=stdout,
                    deadline_seconds=timeout_seconds,
                ),
                timeout=timeout_seconds,
            )
            if value is not None:
                outcome.result_repr = _clip(repr(value), 2_000)
        except TimeoutError as exc:
            raise LiveOperationError(
                f"desktop code exceeded {timeout_seconds:g} seconds",
            ) from exc
        except Exception as exc:  # noqa: BLE001 - model-code boundary
            raise LiveOperationError(
                "desktop code failed: " f"{type(exc).__name__}: {exc}",
            ) from exc
        finally:
            await asyncio.to_thread(recorder.stop_if_recording)
            outcome.takes = recorder.takes
            outcome.screenshots = controller.screenshots
            outcome.output = _clip(stdout.getvalue(), 12_000)
            with contextlib.suppress(Exception):
                await client.close()
            _reset_turn()
    return outcome


def _reset_turn() -> None:
    from qwenpaw.app.computer_use import set_current_computer_use_turn_id

    # Clearing to None ends the turn binding for this dispatch.
    with contextlib.suppress(Exception):
        set_current_computer_use_turn_id(None)


def _desktop_target(params: dict[str, Any]) -> str:
    element_id = str(params.get("element_id") or "")
    if element_id:
        return element_id
    source = str(params.get("source_element_id") or "")
    target = str(params.get("target_element_id") or "")
    if source or target:
        return f"{source} -> {target}".strip()
    screenshot_id = str(params.get("screenshot_id") or "")
    if screenshot_id:
        return screenshot_id
    return ""


def _bounds_to_bbox(
    bounds: Any,
    window_bounds: dict[str, Any] | None = None,
) -> BoundingBox | None:
    if not isinstance(bounds, dict):
        return None
    try:
        x = float(bounds.get("x", bounds.get("left", 0)))
        y = float(bounds.get("y", bounds.get("top", 0)))
        width = float(bounds["width"])
        height = float(bounds["height"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in (x, y, width, height)):
        return None
    if width <= 0 or height <= 0:
        return None
    if isinstance(window_bounds, dict):
        try:
            x -= float(window_bounds.get("x", window_bounds.get("left", 0)))
            y -= float(window_bounds.get("y", window_bounds.get("top", 0)))
        except (TypeError, ValueError):
            pass
    return BoundingBox(x, y, width, height)


__all__ = [
    "DesktopController",
    "DesktopRecorderHandle",
    "computer_use_status",
    "run_computer_use_code",
]
