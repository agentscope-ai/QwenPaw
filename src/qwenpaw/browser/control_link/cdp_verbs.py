# -*- coding: utf-8 -*-
"""Shared implementations for links backed by Chrome DevTools Protocol."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping

from ...config.context import get_current_workspace_dir
from ...constant import WORKING_DIR
from ...utils.io_utils import make_dirs_async, write_bytes_async
from ..errors import BrowserError, ErrorCause, ErrorCategory
from .identity import require_owner
from .injected import get_engine_source
from .cdp_tree import (
    merge_ax_dom,
)

_READY_ACCEPT = {
    "domcontentloaded": {"interactive", "complete"},
    "load": {"complete"},
    "networkidle": {"complete"},
}

_NAMED_KEYS = {
    "Enter": ("Enter", 13, "\r"),
    "Tab": ("Tab", 9, None),
    "Escape": ("Escape", 27, None),
    "Backspace": ("Backspace", 8, None),
    "Delete": ("Delete", 46, None),
    "ArrowUp": ("ArrowUp", 38, None),
    "ArrowDown": ("ArrowDown", 40, None),
    "ArrowLeft": ("ArrowLeft", 37, None),
    "ArrowRight": ("ArrowRight", 39, None),
    "Home": ("Home", 36, None),
    "End": ("End", 35, None),
    "PageUp": ("PageUp", 33, None),
    "PageDown": ("PageDown", 34, None),
}

_MODIFIER_BITS = {"Alt": 1, "Control": 2, "Meta": 4, "Shift": 8}
_MODIFIER_VIRTUAL_KEY_CODES = {
    "Alt": 18,
    "Control": 17,
    "Meta": 91,
    "Shift": 16,
}


def _printable_frame(key: str, modifiers: int) -> dict[str, Any]:
    """Build the key-down frame for one printable character."""
    frame: dict[str, Any] = {
        "type": "keyDown",
        "key": key,
        "modifiers": modifiers,
    }
    if key.isascii() and key.isalpha():
        frame["code"] = f"Key{key.upper()}"
        frame["windowsVirtualKeyCode"] = ord(key.upper())
    elif key.isascii() and key.isdigit():
        frame["code"] = f"Digit{key}"
        frame["windowsVirtualKeyCode"] = ord(key)
    if modifiers in (0, _MODIFIER_BITS["Shift"]):
        frame["text"] = key
        frame["unmodifiedText"] = key.lower() if key.isupper() else key
    return frame


def _normalized_key_parts(key: str) -> tuple[list[str], str]:
    """Return normalized modifier names and the non-modifier key."""
    parts = key.split("+")
    if not key or any(not part for part in parts):
        return [], ""
    modifiers = parts[:-1]
    main_key = parts[-1]
    if main_key == "Mod":
        return [], ""
    normalized_modifiers: list[str] = []
    for modifier in modifiers:
        normalized = "Meta" if modifier == "Mod" else modifier
        if (
            normalized not in _MODIFIER_BITS
            or normalized in normalized_modifiers
        ):
            return [], ""
        normalized_modifiers.append(normalized)
    if len(main_key) == 1 and main_key.isupper():
        if "Shift" not in normalized_modifiers:
            normalized_modifiers.append("Shift")
    return normalized_modifiers, main_key


def _key_event_frames(key: str) -> list[dict[str, Any]]:
    """Build faithful CDP keyboard frames for the supported press subset."""
    normalized_modifiers, main_key = _normalized_key_parts(key)
    modifier_bits = sum(
        _MODIFIER_BITS[modifier] for modifier in normalized_modifiers
    )
    named = _NAMED_KEYS.get(main_key)
    if not main_key or (named is None and len(main_key) != 1):
        supported = ", ".join(_NAMED_KEYS)
        raise BrowserError(
            category=ErrorCategory.FATAL,
            cause=ErrorCause.CAPABILITY_UNSUPPORTED,
            suggested_action=(
                "Use a printable character or one of the supported keys: "
                f"{supported}; Control/Shift/Alt/Meta combos are supported."
            ),
            reason=f"unsupported key for chrome/cdp press: {key!r}",
        )

    frames: list[dict[str, Any]] = []
    active_bits = 0
    for modifier in normalized_modifiers:
        active_bits |= _MODIFIER_BITS[modifier]
        frames.append(
            {
                "type": "rawKeyDown",
                "key": modifier,
                "code": f"{modifier}Left",
                "modifiers": active_bits,
                "windowsVirtualKeyCode": _MODIFIER_VIRTUAL_KEY_CODES[modifier],
            },
        )
    if named is not None:
        code, virtual_key_code, text = named
        down: dict[str, Any] = {
            "type": "keyDown",
            "key": main_key,
            "code": code,
            "modifiers": modifier_bits,
            "windowsVirtualKeyCode": virtual_key_code,
        }
        if text is not None:
            down["text"] = text
            down["unmodifiedText"] = text
    else:
        down = _printable_frame(main_key, modifier_bits)
    frames.append(down)
    up = {
        name: value
        for name, value in down.items()
        if name not in {"text", "unmodifiedText"}
    }
    up["type"] = "keyUp"
    frames.append(up)
    for modifier in reversed(normalized_modifiers):
        active_bits &= ~_MODIFIER_BITS[modifier]
        frames.append(
            {
                "type": "keyUp",
                "key": modifier,
                "code": f"{modifier}Left",
                "modifiers": active_bits,
                "windowsVirtualKeyCode": _MODIFIER_VIRTUAL_KEY_CODES[modifier],
            },
        )
    return frames


async def persist_screenshot_async(image: bytes) -> dict[str, str]:
    """Write browser PNG bytes to the active workspace and return its path."""
    directory = get_current_workspace_dir() or (
        WORKING_DIR / "workspaces" / "default"
    )
    directory = Path(directory).expanduser()
    await make_dirs_async(directory)
    digest = hashlib.sha256(image).hexdigest()
    path = directory / f"browser_screenshot_{digest[:8]}.png"
    await write_bytes_async(path, image)
    return {"path": str(path.resolve())}


class CdpVerbsMixin:
    """Implement protocol-neutral browser verbs using the CDP primitive."""

    async def _dispatch_key_events(
        self,
        owner: Any,
        page_id: str | None,
        key: str,
        *,
        timeout: float | None = None,
    ) -> None:
        """Dispatch one key sequence and always release held modifiers."""
        frames = _key_event_frames(key)
        release_start = len(frames)
        while (
            release_start
            and frames[release_start - 1]["type"] == "keyUp"
            and frames[release_start - 1]["key"] in _MODIFIER_BITS
        ):
            release_start -= 1
        try:
            for frame in frames[:release_start]:
                await self._cdp(
                    owner,
                    page_id,
                    "Input.dispatchKeyEvent",
                    frame,
                    timeout=timeout,
                )
        finally:
            for frame in frames[release_start:]:
                await self._cdp(
                    owner,
                    page_id,
                    "Input.dispatchKeyEvent",
                    frame,
                    timeout=timeout,
                )

    def _init_injected_state(self) -> None:
        """Initialize lazy per-page injected-engine state for a link."""
        self._injected_contexts: set[str] = set()
        self._injection_locks: dict[str, asyncio.Lock] = {}
        self._frame_contexts: dict[tuple[str, str], int] = {}
        self._engine_source = get_engine_source()

    def _injected_key(self, page_id: str | None) -> str:
        """Return the cache key for a page and active-page fallback."""
        return str(page_id) if page_id is not None else "__active_page__"

    def _cache_page_id(self, owner: Any, page_id: str | None) -> str | None:
        """Resolve an omitted page ID before storing per-document state."""
        del owner
        return page_id

    def _invalidate_injected(self, page_id: str | None) -> None:
        """Forget an engine installed in a document that has gone away."""
        if not hasattr(self, "_injected_contexts"):
            self._init_injected_state()
        key = self._injected_key(page_id)
        self._injected_contexts.discard(key)
        self._invalidate_frame_contexts(page_id)

    def _invalidate_frame_contexts(self, page_id: str | None) -> None:
        """Forget isolated worlds belonging to a navigated top-level page."""
        if not hasattr(self, "_frame_contexts"):
            self._init_injected_state()
        key = self._injected_key(page_id)
        self._frame_contexts = {
            context_key: context_id
            for context_key, context_id in self._frame_contexts.items()
            if context_key[0] != key
        }

    @staticmethod
    def _engine_value(output: Mapping[str, Any]) -> Any:
        """Return a Runtime.evaluate value or preserve its useful exception."""
        exception = output.get("exceptionDetails")
        if exception:
            remote = exception.get("exception", {})
            message = (
                remote.get("description")
                or remote.get("value")
                or exception.get("text")
                or "engine call failed"
            )
            raise ValueError(str(message))
        return output.get("result", {}).get("value")

    async def _ensure_injected(
        self,
        owner: Any,
        page_id: str | None,
        *,
        timeout: float | None = None,
    ) -> None:
        """Install the browser-side locator engine once for this document."""
        if not hasattr(self, "_injected_contexts"):
            self._init_injected_state()
        cache_page_id = self._cache_page_id(owner, page_id)
        key = self._injected_key(cache_page_id)
        if key in self._injected_contexts:
            return
        lock = self._injection_locks.setdefault(key, asyncio.Lock())
        async with lock:
            if key in self._injected_contexts:
                return
            await self._cdp(
                owner,
                page_id,
                "Runtime.evaluate",
                {
                    "expression": self._engine_source,
                    "returnByValue": True,
                },
                timeout=timeout,
            )
            self._injected_contexts.add(key)

    async def _engine_call(
        self,
        owner: Any,
        page_id: str | None,
        method: str,
        *arguments: Any,
        timeout: float | None = None,
    ) -> Any:
        """Call one serializable injected-engine method through CDP."""
        await self._ensure_injected(owner, page_id, timeout=timeout)
        encoded = ",".join(
            json.dumps(argument, ensure_ascii=False, separators=(",", ":"))
            for argument in arguments
        )
        output = await self._cdp(
            owner,
            page_id,
            "Runtime.evaluate",
            {
                "expression": f"window.__qwenpaw.{method}({encoded})",
                "returnByValue": True,
                "awaitPromise": True,
            },
            timeout=timeout,
        )
        return self._engine_value(output)

    @staticmethod
    def _frame_selector(
        spec: list[Mapping[str, Any]],
    ) -> str | None:
        """Extract the sole supported frame-locator prefix from a spec."""
        frame_steps = [
            index
            for index, step in enumerate(spec)
            if step.get("method") == "frame_locator"
        ]
        if not frame_steps:
            return None
        if len(frame_steps) != 1 or frame_steps[0] != 0:
            raise BrowserError(
                category=ErrorCategory.FATAL,
                cause=ErrorCause.API_MISUSE,
                suggested_action=(
                    "Use one frame_locator(selector) at the start of a "
                    "locator chain; nested frames are not supported yet."
                ),
                reason="unsupported frame locator chain",
            )
        args = spec[0].get("args", [])
        if not args or not isinstance(args[0], str) or not args[0]:
            raise BrowserError(
                category=ErrorCategory.FATAL,
                cause=ErrorCause.API_MISUSE,
                suggested_action="pass a non-empty iframe CSS selector",
                reason="frame_locator requires a CSS selector",
            )
        return args[0]

    @staticmethod
    def _frame_tree_frames(tree: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        """Flatten ``Page.getFrameTree`` child frames in document order."""
        frames: list[Mapping[str, Any]] = []

        def visit(node: Mapping[str, Any]) -> None:
            frame = node.get("frame")
            if isinstance(frame, Mapping):
                frames.append(frame)
            for child in node.get("childFrames", []):
                if isinstance(child, Mapping):
                    visit(child)

        visit(tree)
        return frames

    async def _resolve_in_frame(
        self,
        owner: Any,
        page_id: str | None,
        frame_selector: str,
        spec: list[Mapping[str, Any]],
        method: str,
        *arguments: Any,
        timeout: float | None = None,
    ) -> Any:
        """Run a frame-prefixed locator operation in an isolated CDP world."""
        info = await self._engine_call(
            owner,
            page_id,
            "frameInfo",
            frame_selector,
            timeout=timeout,
        )
        if not isinstance(info, Mapping):
            raise BrowserError(
                category=ErrorCategory.RETRYABLE,
                cause=ErrorCause.STATE_STALE,
                suggested_action="retry",
                reason=(
                    "the cross-origin iframe disappeared before it could "
                    "be resolved"
                ),
            )
        await self._cdp(
            owner,
            page_id,
            "Page.enable",
            {},
            timeout=timeout,
        )
        name = str(info.get("name", ""))
        source = str(info.get("src", ""))
        deadline = time.monotonic() + min(float(timeout or 3.0), 3.0)
        candidates: list[Mapping[str, Any]] = []
        while True:
            tree_result = await self._cdp(
                owner,
                page_id,
                "Page.getFrameTree",
                {},
                timeout=timeout,
            )
            frames = self._frame_tree_frames(tree_result.get("frameTree", {}))
            child_frames = frames[1:]
            named = [
                frame
                for frame in child_frames
                if name and str(frame.get("name", "")) == name
            ]
            sourced = [
                frame
                for frame in child_frames
                if source and str(frame.get("url", "")) == source
            ]
            candidates = named or sourced
            if len(candidates) == 1 and candidates[0].get("id"):
                break
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.05)
        if len(candidates) != 1 or not candidates[0].get("id"):
            raise BrowserError(
                category=ErrorCategory.RETRYABLE,
                cause=ErrorCause.LOCATE_FAILED,
                suggested_action=(
                    "use an iframe selector that identifies one frame with "
                    "a stable name or src"
                ),
                reason=(
                    "could not uniquely match the cross-origin iframe in "
                    "Page.getFrameTree"
                ),
            )
        frame_id = str(candidates[0]["id"])
        cache_page_id = self._cache_page_id(owner, page_id)
        cache_key = (self._injected_key(cache_page_id), frame_id)
        context_id = self._frame_contexts.get(cache_key)
        if context_id is None:
            created = await self._cdp(
                owner,
                page_id,
                "Page.createIsolatedWorld",
                {
                    "frameId": frame_id,
                    "worldName": "__qwenpaw_frame",
                    "grantUniveralAccess": True,
                },
                timeout=timeout,
            )
            context_id = int(created["executionContextId"])
            injected = await self._cdp(
                owner,
                page_id,
                "Runtime.evaluate",
                {
                    "expression": self._engine_source,
                    "contextId": context_id,
                    "returnByValue": True,
                    "awaitPromise": True,
                },
                timeout=timeout,
            )
            self._engine_value(injected)
            self._frame_contexts[cache_key] = context_id

        encoded = ",".join(
            json.dumps(argument, ensure_ascii=False, separators=(",", ":"))
            for argument in (spec[1:], *arguments)
        )
        output = await self._cdp(
            owner,
            page_id,
            "Runtime.evaluate",
            {
                "expression": f"window.__qwenpaw.{method}({encoded})",
                "contextId": context_id,
                "returnByValue": True,
                "awaitPromise": True,
            },
            timeout=timeout,
        )
        value = self._engine_value(output)
        if method in {
            "resolveAndGetClickTarget",
            "resolveAndBoundingBox",
        } and isinstance(value, dict):
            value = {
                **value,
                "x": float(value["x"]) + float(info.get("x", 0)),
                "y": float(value["y"]) + float(info.get("y", 0)),
            }
        return value

    async def _engine_call_for_spec(
        self,
        owner: Any,
        page_id: str | None,
        method: str,
        spec: list[Mapping[str, Any]],
        *arguments: Any,
        timeout: float | None = None,
    ) -> Any:
        """Run a locator operation, with a cross-origin frame fallback."""
        frame_selector = self._frame_selector(spec)
        try:
            return await self._engine_call(
                owner,
                page_id,
                method,
                spec,
                *arguments,
                timeout=timeout,
            )
        except ValueError as exc:
            if (
                frame_selector is None
                or "QWENPAW_CROSS_ORIGIN_FRAME:" not in str(exc)
            ):
                raise
            return await self._resolve_in_frame(
                owner,
                page_id,
                frame_selector,
                spec,
                method,
                *arguments,
                timeout=timeout,
            )

    async def _cdp(
        self,
        owner: Any,
        page_id: str | None,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        raise NotImplementedError

    def _owner(self, params: Mapping[str, Any]) -> Any:
        """Return the complete owner required by every CDP-backed verb."""
        return require_owner(params)

    async def _m_wait_for_load_state(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Poll the document lifecycle state through CDP."""
        owner = self._owner(params)
        page_id = params.get("page_id")
        state = str(params.get("state", "load"))
        accepted = _READY_ACCEPT.get(state)
        if accepted is None:
            raise BrowserError(
                category=ErrorCategory.FATAL,
                cause=ErrorCause.API_MISUSE,
                suggested_action=(
                    "Use one of: load, domcontentloaded, networkidle."
                ),
                reason=f"unknown load state {state!r}",
            )
        deadline = time.monotonic() + (
            float(params.get("timeout") or 30_000.0) / 1000.0
        )
        while True:
            output = await self._cdp(
                owner,
                page_id,
                "Runtime.evaluate",
                {
                    "expression": "document.readyState",
                    "returnByValue": True,
                },
                timeout=timeout,
            )
            ready = str(output.get("result", {}).get("value", ""))
            if ready in accepted:
                break
            if time.monotonic() >= deadline:
                raise BrowserError(
                    category=ErrorCategory.RETRYABLE,
                    cause=ErrorCause.TIMING,
                    suggested_action="retry",
                    reason=f"timed out waiting for page {state!r} state",
                    detail=f"document.readyState remained {ready!r}",
                )
            await asyncio.sleep(0.1)
        if state == "networkidle":
            await asyncio.sleep(0.5)
        return {"state": state, "ready_state": ready}

    async def _resolve(
        self,
        owner: Any,
        page_id: str | None,
        spec: list[Mapping[str, Any]],
    ) -> list[int]:
        count = await self._engine_call_for_spec(
            owner,
            page_id,
            "resolveAndCount",
            spec,
        )
        # Locator resolution is now browser-side. Retain the private method's
        # list shape for legacy callers without manufacturing backend node IDs.
        return list(range(int(count or 0)))

    async def _object_id(
        self,
        owner: Any,
        page_id: str | None,
        backend_id: int,
    ) -> str:
        """Resolve a legacy backend node ID for snapshot-only callers.

        Locator verbs deliberately do not use backend node IDs any more; keep
        this primitive available to existing CDP mixin consumers.
        """
        resolved = await self._cdp(
            owner,
            page_id,
            "DOM.resolveNode",
            {"backendNodeId": backend_id},
        )
        return str(resolved["object"]["objectId"])

    async def _m_capture_tree(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner, page_id = self._owner(params), params.get("page_id")
        ax = await self._cdp(
            owner,
            page_id,
            "Accessibility.getFullAXTree",
            {},
            timeout=timeout,
        )
        snapshot = await self._cdp(
            owner,
            page_id,
            "DOMSnapshot.captureSnapshot",
            {"computedStyles": []},
            timeout=timeout,
        )
        surface = await self._m_current_surface(params, timeout=timeout)
        return {
            "tree": merge_ax_dom(
                ax.get("nodes", []),
                snapshot,
            ),
            "url": surface["url"],
            "title": surface["title"],
        }

    async def _m_locator_count(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = self._owner(params)
        return {
            "count": int(
                await self._engine_call_for_spec(
                    owner,
                    params.get("page_id"),
                    "resolveAndCount",
                    params["spec"],
                    timeout=timeout,
                )
                or 0,
            ),
        }

    async def _m_locator_read(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner, page_id = self._owner(params), params.get("page_id")
        property_name = str(params["property"])
        arguments = list(params.get("args", ()))
        method = (
            "resolveAndReadAll"
            if property_name == "all_text_contents"
            else "resolveAndRead"
        )
        read_property = (
            "text_content" if method == "resolveAndReadAll" else property_name
        )
        value = await self._engine_call_for_spec(
            owner,
            page_id,
            method,
            params["spec"],
            read_property,
            arguments,
            timeout=timeout,
        )
        return {"value": value}

    async def _m_locator_wait_for(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Wait inside the browser document for a locator state transition."""
        owner, page_id = self._owner(params), params.get("page_id")
        state = str(params.get("state", "visible"))
        if state not in {"attached", "visible", "hidden", "detached"}:
            raise BrowserError(
                category=ErrorCategory.FATAL,
                cause=ErrorCause.API_MISUSE,
                suggested_action=(
                    "Use one of: attached, visible, hidden, detached."
                ),
                reason=f"unknown locator wait state {state!r}",
            )
        timeout_ms = float(params.get("timeout", 30_000))
        if timeout_ms < 0:
            raise BrowserError(
                category=ErrorCategory.FATAL,
                cause=ErrorCause.API_MISUSE,
                suggested_action="use a non-negative timeout",
                reason=f"invalid locator timeout {timeout_ms!r}",
            )
        cdp_timeout = max(timeout_ms / 1000.0 + 5.0, timeout or 0.0)
        try:
            await self._engine_call_for_spec(
                owner,
                page_id,
                "waitFor",
                params["spec"],
                state,
                timeout_ms,
                timeout=cdp_timeout,
            )
        except ValueError as exc:
            raise BrowserError(
                category=ErrorCategory.RETRYABLE,
                cause=ErrorCause.TIMING,
                suggested_action="retry",
                reason=str(exc),
            ) from exc
        return {"state": state}

    async def _m_locator_bounding_box(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Return a visible locator's viewport bounding rectangle."""
        value = await self._engine_call_for_spec(
            self._owner(params),
            params.get("page_id"),
            "resolveAndBoundingBox",
            params["spec"],
            timeout=timeout,
        )
        return {"value": value}

    async def _m_screenshot(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Capture a full page screenshot and persist its PNG bytes."""
        output = await self._cdp(
            self._owner(params),
            params.get("page_id"),
            "Page.captureScreenshot",
            {"format": "png"},
            timeout=timeout,
        )
        return await persist_screenshot_async(
            base64.b64decode(str(output["data"])),
        )

    async def _m_locator_screenshot(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Capture a visible locator's viewport rectangle as a PNG."""
        owner, page_id = self._owner(params), params.get("page_id")
        box = await self._engine_call_for_spec(
            owner,
            page_id,
            "resolveAndClipRect",
            params["spec"],
            timeout=timeout,
        )
        if box is None:
            raise BrowserError(
                category=ErrorCategory.RETRYABLE,
                cause=ErrorCause.LOCATE_FAILED,
                suggested_action="choose a visible locator",
                reason="cannot screenshot a hidden locator",
            )
        clip = {
            "x": float(box["x"]),
            "y": float(box["y"]),
            "width": float(box["width"]),
            "height": float(box["height"]),
            "scale": 1,
        }
        output = await self._cdp(
            owner,
            page_id,
            "Page.captureScreenshot",
            {"format": "png", "clip": clip},
            timeout=timeout,
        )
        return await persist_screenshot_async(
            base64.b64decode(str(output["data"])),
        )

    async def _m_locator_action(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner, page_id, action = (
            self._owner(params),
            params.get("page_id"),
            str(params["action"]),
        )
        if action in {"click", "hover", "double_click"}:
            target = await self._engine_call_for_spec(
                owner,
                page_id,
                "resolveAndGetClickTarget",
                params["spec"],
                timeout=timeout,
            )
            await self._dispatch_pointer(
                owner,
                page_id,
                target,
                action,
                timeout=timeout,
            )
        elif action == "press_key":
            key = str(params.get("key", ""))
            await self._engine_call_for_spec(
                owner,
                page_id,
                "resolveAndAction",
                params["spec"],
                "focus",
                {},
                timeout=timeout,
            )
            await self._dispatch_key_events(
                owner,
                page_id,
                key,
                timeout=timeout,
            )
        elif action in {
            "fill",
            "type_text",
            "set_checked",
            "select_option",
            "scroll",
            "scroll_into_view",
            "focus",
            "blur",
            "clear",
        }:
            await self._engine_call_for_spec(
                owner,
                page_id,
                "resolveAndAction",
                params["spec"],
                action,
                params,
                timeout=timeout,
            )
        else:
            raise ValueError(f"unsupported locator action: {action}")
        return {
            "evidence": (
                f"{action} event dispatched; verify the intended effect "
                "with a fresh snapshot()"
            ),
        }

    async def _dispatch_pointer(
        self,
        owner: Any,
        page_id: str | None,
        target: Mapping[str, Any],
        action: str,
        *,
        timeout: float | None,
    ) -> None:
        x, y = float(target["x"]), float(target["y"])
        if action == "hover":
            await self._cdp(
                owner,
                page_id,
                "Input.dispatchMouseEvent",
                {"type": "mouseMoved", "x": x, "y": y},
                timeout=timeout,
            )
            return
        count = 2 if action == "double_click" else 1
        for event_type in ("mousePressed", "mouseReleased"):
            await self._cdp(
                owner,
                page_id,
                "Input.dispatchMouseEvent",
                {
                    "type": event_type,
                    "x": x,
                    "y": y,
                    "button": "left",
                    "clickCount": count,
                },
                timeout=timeout,
            )

    async def _m_navigate(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        out = await self._cdp(
            self._owner(params),
            params.get("page_id"),
            "Page.navigate",
            {"url": str(params["url"])},
            timeout=timeout,
        )
        error_text = str(out.get("errorText") or "")
        if error_text:
            raise BrowserError(
                category=ErrorCategory.RETRYABLE,
                suggested_action=(
                    "Navigation failed at the network layer. Check the URL "
                    "and retry, or open a different page."
                ),
                reason="navigation failed",
                detail=error_text,
            )
        self._invalidate_injected(params.get("page_id"))
        return {"url": str(params["url"]), "status": None}

    async def _m_reload(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        await self._cdp(
            self._owner(params),
            params.get("page_id"),
            "Page.reload",
            {},
            timeout=timeout,
        )
        self._invalidate_injected(params.get("page_id"))
        return {
            "url": (await self._m_current_surface(params, timeout=timeout))[
                "url"
            ],
        }

    async def _m_go_back(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        return await self._history_move(params, -1, timeout)

    async def _m_go_forward(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        return await self._history_move(params, 1, timeout)

    async def _history_move(
        self,
        params: dict[str, Any],
        delta: int,
        timeout: float | None,
    ) -> Mapping[str, Any]:
        owner, page_id = self._owner(params), params.get("page_id")
        history = await self._cdp(
            owner,
            page_id,
            "Page.getNavigationHistory",
            {},
            timeout=timeout,
        )
        target = int(history.get("currentIndex", 0)) + delta
        entries = history.get("entries", [])
        if 0 <= target < len(entries):
            await self._cdp(
                owner,
                page_id,
                "Page.navigateToHistoryEntry",
                {"entryId": entries[target]["id"]},
                timeout=timeout,
            )
            self._invalidate_injected(page_id)
            return {"url": str(entries[target].get("url", ""))}
        return {
            "url": (await self._m_current_surface(params, timeout=timeout))[
                "url"
            ],
        }

    async def _m_input(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner, page_id = self._owner(params), params.get("page_id")
        kind, action = params.get("kind"), params.get("action")
        if kind == "mouse" and action == "click":
            for event_type in ("mousePressed", "mouseReleased"):
                await self._cdp(
                    owner,
                    page_id,
                    "Input.dispatchMouseEvent",
                    {
                        "type": event_type,
                        "x": params["x"],
                        "y": params["y"],
                        "button": "left",
                        "clickCount": 1,
                    },
                    timeout=timeout,
                )
        elif kind == "keyboard" and action == "press":
            await self._dispatch_key_events(
                owner,
                page_id,
                str(params["key"]),
                timeout=timeout,
            )
        elif kind == "mouse" and action == "wheel":
            await self._cdp(
                owner,
                page_id,
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseWheel",
                    "x": 0,
                    "y": 0,
                    "deltaX": float(params.get("delta_x") or 0.0),
                    "deltaY": float(params.get("delta_y") or 0.0),
                },
                timeout=timeout,
            )
        else:
            raise ValueError(f"unsupported input: {kind}/{action}")
        return {"ok": True}
