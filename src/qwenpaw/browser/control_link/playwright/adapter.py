# -*- coding: utf-8 -*-
"""Playwright ControlLink multiplexer for raw browser mechanism facts."""

# pylint: disable=protected-access,unused-argument,unused-import

from __future__ import annotations

import atexit
import asyncio
import contextlib
import logging
import math
import pathlib
import time
from typing import Any, Callable, Mapping, cast

from playwright.async_api import Page, async_playwright

from ....config.context import get_current_workspace_dir
from ....constant import WORKING_DIR
from ....utils.io_utils import make_dirs_async
from ...errors import BrowserError, ErrorCategory, ErrorCause, fatal as _fatal
from ...runtime.managed_playwright import ensure_managed_chromium
from ...sdk.contracts import LocatorStep
from ...runtime.links import register_local
from ...runtime.ports import EventSink
from ..identity import OwnerKey, require_owner
from ..cdp_tree import ax_states as _ax_states
from ..cdp_tree import (
    dom_attrs_by_backend as _dom_attrs_by_backend,
)  # noqa: F401
from ..cdp_tree import merge_ax_dom as _merge_ax_dom
from ..cdp_verbs import persist_screenshot_async

_LIVE: list["PlaywrightControlLink"] = []
logger = logging.getLogger(__name__)


def _rebuild_spec(raw: Any) -> tuple[LocatorStep, ...]:
    return tuple(
        LocatorStep(
            str(item["method"]),
            tuple(item.get("args", ())),
            tuple(tuple(pair) for pair in item.get("kwargs", ())),
        )
        for item in raw
    )


_PROPERTY_STEPS = frozenset({"first", "last"})


def _locator_from_spec(root: Any, spec: tuple[LocatorStep, ...]) -> Any:
    """Lazily replay a wire locator specification against its current page."""
    locator = root
    for step in spec:
        attr = getattr(locator, step.method)
        if step.method in _PROPERTY_STEPS:
            locator = attr
        else:
            locator = attr(*step.args, **dict(step.kwargs))
    return locator


def _resolved_launch_binary(params: Mapping[str, Any]) -> tuple[str, str]:
    channel = str(params.get("channel") or "").strip()
    executable_path = str(params.get("executable_path") or "").strip()
    return channel, executable_path


def _build_launch_kwargs(
    params: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build Playwright launch and context kwargs from session parameters."""
    engine = str(params.get("engine") or "chromium")
    if engine != "chromium":
        raise _fatal(f"engine not wired yet: {engine}", engine)
    launch: dict[str, Any] = {"headless": bool(params.get("headless", True))}
    channel, executable_path = _resolved_launch_binary(params)
    if channel:
        launch["channel"] = channel
    elif executable_path:
        launch["executable_path"] = executable_path
    if params.get("args"):
        launch["args"] = list(params["args"])
    if params.get("proxy"):
        launch["proxy"] = {"server": str(params["proxy"])}
    context: dict[str, Any] = {}
    viewport = params.get("viewport")
    if viewport:
        context["viewport"] = {
            "width": int(viewport[0]),
            "height": int(viewport[1]),
        }
    return launch, context


def _launch_needs_managed_cache(params: Mapping[str, Any]) -> bool:
    """Whether this launch needs the QwenPaw-managed Playwright cache."""
    channel, executable_path = _resolved_launch_binary(params)
    return not (channel or executable_path)


def _managed_cache_not_ready(detail: str, retry_after: float) -> BrowserError:
    wait_for = max(1, math.ceil(retry_after))
    if detail:
        reason = "Managed Playwright Chromium install failed."
    else:
        reason = (
            "Managed Playwright Chromium is downloading in the background."
        )
    return BrowserError(
        category=ErrorCategory.RETRYABLE,
        cause=ErrorCause.TIMING,
        suggested_action=(
            f"Wait {wait_for} seconds, then retry Browser.connect()."
        ),
        reason=reason,
        detail=detail,
    )


def teaching_from_strict_violation(exc: Exception) -> BrowserError | None:
    text = str(exc).lower()
    if "strict mode violation" not in text and "resolved to" not in text:
        return None
    return BrowserError(
        category=ErrorCategory.RETRYABLE,
        cause=ErrorCause.LOCATE_FAILED,
        suggested_action=(
            "Scope to a stable container, then locate its child element."
        ),
        reason=str(exc),
        example=(
            'page.get_by_role("dialog").' 'get_by_role("button", name="OK")'
        ),
    )


class PlaywrightControlLink:
    """Per-variant multiplexer for workspace processes and session contexts."""

    variant = "playwright"
    reclaim_on_idle = True
    supported_contexts = frozenset({"incognito", "profile"})

    def __init__(self) -> None:
        self._pw: Any | None = None
        self._pw_lock = asyncio.Lock()
        self._launch_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._procs: dict[tuple[str, str], dict[str, Any]] = {}
        self._fixed_profile_workspaces: dict[str, str] = {}
        self._contexts: dict[OwnerKey, Any] = {}
        self._opening: dict[OwnerKey, str] = {}
        self._sessions: dict[OwnerKey, dict[str, str]] = {}
        self._pages: dict[tuple[OwnerKey, str], Page] = {}
        self._active: dict[OwnerKey, str | None] = {}
        self._last_used: dict[OwnerKey, float] = {}
        self._sinks: list[EventSink] = []
        self._closed_sessions: set[OwnerKey] = set()
        _LIVE.append(self)

    def _launch_lock(self, key: tuple[str, str]) -> asyncio.Lock:
        """Return the lock protecting one workspace/context browser cell."""
        lock = self._launch_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._launch_locks[key] = lock
        return lock

    def is_available(self) -> bool:
        """Return whether the Playwright Python dependency is importable."""
        try:
            import playwright
        except ImportError:
            return False
        return playwright is not None

    async def request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Dispatch one raw provider method without semantic interpretation."""
        require_owner(params)
        handler = getattr(self, f"_m_{method}", None)
        if handler is None:
            raise _fatal(f"unknown method: {method}", method)
        typed_handler = cast(Callable[..., Any], handler)
        return await typed_handler(dict(params), timeout=timeout)

    def on_event(self, sink: EventSink) -> Callable[[], None]:
        """Subscribe to raw provider events and return an unsubscribe callback.

        The callback unregisters exactly this sink.
        """
        self._sinks.append(sink)

        def _unsubscribe() -> None:
            if sink in self._sinks:
                self._sinks.remove(sink)

        return _unsubscribe

    def _emit(self, event: dict[str, Any]) -> None:
        for sink in list(self._sinks):
            sink(event)

    def _touch(self, owner: OwnerKey) -> None:
        self._last_used[owner] = time.monotonic()

    def _ctx(self, owner: OwnerKey) -> Any:
        if owner not in self._contexts:
            raise BrowserError(
                category=ErrorCategory.RETRYABLE,
                cause=ErrorCause.STATE_STALE,
                suggested_action=(
                    "Reconnect first: browser = await Browser.connect()"
                ),
                reason="browser session is closed",
                detail="this session was closed earlier in the chat",
            )
        return self._contexts[owner]

    def _page(self, owner: OwnerKey, page_id: str | None = None) -> Page:
        resolved_page_id = page_id or self._active.get(owner)
        if resolved_page_id is None:
            if owner in self._closed_sessions:
                raise BrowserError(
                    category=ErrorCategory.RETRYABLE,
                    cause=ErrorCause.STATE_STALE,
                    suggested_action=(
                        "Reconnect first: browser = await Browser.connect()"
                    ),
                    reason="browser session is closed",
                    detail="this session was closed earlier in the chat",
                )
            raise BrowserError(
                category=ErrorCategory.RETRYABLE,
                cause=ErrorCause.STATE_STALE,
                suggested_action=(
                    "Open a fresh page with await browser.open(url)"
                ),
                reason="no active page in this session",
                detail="pages are released when a response cycle ends",
            )
        try:
            return self._pages[(owner, resolved_page_id)]
        except KeyError as exc:
            raise BrowserError(
                category=ErrorCategory.RETRYABLE,
                cause=ErrorCause.STATE_STALE,
                suggested_action=(
                    "Open a fresh page with await browser.open(url)"
                ),
                reason="no active page in this session",
                detail="pages are released when a response cycle ends",
            ) from exc

    async def _default_profile_dir(self) -> str:
        """Use the controlled workspace directory for persistent profiles."""
        directory = get_current_workspace_dir() or (
            WORKING_DIR / "workspaces" / "default"
        )
        directory = directory / ".browser-profile"
        await make_dirs_async(directory)
        return str(directory)

    @staticmethod
    def _proc_is_alive(process: Mapping[str, Any], kind: str) -> bool:
        """Return whether a cached workspace process can host sessions."""
        if kind == "profile":
            return not process["context"].is_closed()
        return process["browser"].is_connected()

    async def _close_workspace_proc(
        self,
        workspace_id: str,
        kind: str,
    ) -> None:
        """Close one process cell; caller must hold its proc-key lock."""
        process = self._procs.pop((workspace_id, kind), None)
        if process is None:
            return
        if kind == "profile":
            try:
                await process["context"].close()
            # intentional boundary: best-effort context teardown.
            except Exception:
                pass
        else:
            try:
                await process["browser"].close()
            # intentional boundary: best-effort browser teardown.
            except Exception:
                pass
        fixed_profile = process.get("fixed_profile")
        if (
            fixed_profile is not None
            and self._fixed_profile_workspaces.get(fixed_profile)
            == workspace_id
        ):
            self._fixed_profile_workspaces.pop(fixed_profile, None)

    def _profile_holder(self, workspace_id: str) -> str | None:
        """Return the session currently holding this workspace's profile."""
        for owner, info in self._sessions.items():
            if owner[0] == workspace_id and info["context"] == "profile":
                return owner[1]
        return None

    def _has_session_or_opening(self, workspace_id: str, kind: str) -> bool:
        """Report whether a proc-key still has a live or opening session."""
        return any(
            owner[0] == workspace_id and info["context"] == kind
            for owner, info in self._sessions.items()
        ) or any(
            owner[0] == workspace_id and opening_kind == kind
            for owner, opening_kind in self._opening.items()
        )

    async def _create_session_context(
        self,
        owner: OwnerKey,
        context_kind: str,
        params: Mapping[str, Any],
        launch_kwargs: dict[str, Any],
        context_kwargs: dict[str, Any],
    ) -> Any:
        """Create a session context while holding its proc-key lock."""
        workspace_id = owner[0]
        proc_key = (workspace_id, context_kind)
        async with self._launch_lock(proc_key):
            process = self._procs.get(proc_key)
            if process is not None and not self._proc_is_alive(
                process,
                context_kind,
            ):
                await self._close_workspace_proc(workspace_id, context_kind)
            if context_kind == "profile":
                holder = self._profile_holder(workspace_id)
                if holder is not None:
                    raise BrowserError(
                        category=ErrorCategory.FATAL,
                        suggested_action="Reuse the existing profile session.",
                        reason="profile session already open",
                        detail=holder,
                    )
                if proc_key not in self._procs:
                    fixed_profile = params.get("user_data_dir")
                    if fixed_profile:
                        fixed_profile = str(
                            pathlib.Path(str(fixed_profile))
                            .expanduser()
                            .resolve(),
                        )
                        profile_workspace = self._fixed_profile_workspaces.get(
                            fixed_profile,
                        )
                        if (
                            profile_workspace is not None
                            and profile_workspace != workspace_id
                        ):
                            raise BrowserError(
                                category=ErrorCategory.FATAL,
                                suggested_action=(
                                    "Use a different user_data_dir for this "
                                    "workspace."
                                ),
                                reason="fixed user_data_dir is already in use",
                                detail=fixed_profile,
                            )
                    user_data_dir = (
                        fixed_profile
                        if fixed_profile is not None
                        else await self._default_profile_dir()
                    )
                    context = (
                        await self._pw.chromium.launch_persistent_context(
                            user_data_dir,
                            **launch_kwargs,
                            **context_kwargs,
                        )
                    )
                    self._procs[proc_key] = {
                        "context": context,
                        "fixed_profile": fixed_profile,
                    }
                    if fixed_profile is not None:
                        self._fixed_profile_workspaces[
                            fixed_profile
                        ] = workspace_id
                return self._procs[proc_key]["context"]
            if proc_key not in self._procs:
                browser = await self._pw.chromium.launch(**launch_kwargs)
                self._procs[proc_key] = {"browser": browser}
            return await self._procs[proc_key]["browser"].new_context(
                **context_kwargs,
            )

    async def _m_open_session(  # pylint: disable=too-many-branches
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        session_id = owner[1]
        context_kind = str(params.get("context", "incognito"))
        if context_kind not in self.supported_contexts:
            raise _fatal(f"unsupported context: {context_kind}", context_kind)
        if owner in self._sessions:
            if self._sessions[owner]["context"] == context_kind:
                return {
                    "session_id": session_id,
                    "context": context_kind,
                }
            await self._m_close_session(params, timeout=timeout)
        if _launch_needs_managed_cache(params):
            ready, detail, retry_after = ensure_managed_chromium()
            if not ready:
                raise _managed_cache_not_ready(detail, retry_after)
        if self._pw is None:
            async with self._pw_lock:
                if self._pw is None:
                    self._pw = await async_playwright().start()

        launch_kwargs, context_kwargs = _build_launch_kwargs(params)
        self._opening[owner] = context_kind
        try:
            self._contexts[owner] = await self._create_session_context(
                owner,
                context_kind,
                params,
                launch_kwargs,
                context_kwargs,
            )
        except BaseException:
            self._opening.pop(owner, None)
            raise

        self._sessions[owner] = {"context": context_kind}
        self._opening.pop(owner, None)
        self._closed_sessions.discard(owner)
        self._touch(owner)
        return {
            "session_id": session_id,
            "context": context_kind,
            "headless": bool(params.get("headless", False)),
        }

    def _wire_page_events(
        self,
        page: Page,
        owner: OwnerKey,
        page_id: str,
    ) -> None:
        page.on(
            "load",
            lambda _loaded_page: self._emit(
                {
                    "type": "load",
                    "workspace_id": owner[0],
                    "session_id": owner[1],
                    "page_id": page_id,
                    "url": page.url,
                },
            ),
        )

        def on_dialog(dialog: Any) -> None:
            self._emit(
                {
                    "type": "dialog",
                    "workspace_id": owner[0],
                    "session_id": owner[1],
                    "page_id": page_id,
                    "kind": dialog.type,
                    "message": dialog.message,
                },
            )
            asyncio.create_task(self._dismiss_dialog(dialog))

        page.on("dialog", on_dialog)

    @staticmethod
    async def _dismiss_dialog(dialog: Any) -> None:
        try:
            await dialog.dismiss()
        except Exception:  # pragma: no cover - provider-dependent failure
            logger.warning("browser Playwright dialog auto-dismiss failed")

    async def _m_new_page(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        import uuid

        owner = require_owner(params)
        page = await self._ctx(owner).new_page()
        page_id = uuid.uuid4().hex[:8]
        self._pages[(owner, page_id)] = page
        self._active[owner] = page_id
        self._wire_page_events(page, owner, page_id)
        self._touch(owner)
        if params.get("url"):
            await page.goto(str(params["url"]))
        return {"page_id": page_id, "url": page.url}

    async def _m_list_pages(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        if owner in self._closed_sessions:
            return {"pages": []}
        self._ctx(owner)
        self._touch(owner)
        return {
            "pages": [
                {
                    "page_id": page_id,
                    "url": page.url,
                    "active": page_id == self._active.get(owner),
                }
                for (candidate_owner, page_id), page in self._pages.items()
                if candidate_owner == owner
            ],
        }

    async def _m_current_surface(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Return the current page facts used by in-place navigation."""
        del timeout
        owner = require_owner(params)
        page = self._page(owner, params.get("page_id"))
        self._touch(owner)
        return {"url": page.url, "title": await page.title()}

    async def _m_activate_page(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        page_id = str(params["page_id"])
        page = self._page(owner, page_id)
        await page.bring_to_front()
        self._active[owner] = page_id
        self._touch(owner)
        return {"active": page_id}

    async def _m_close_page(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        page_id = str(params["page_id"])
        page = self._pages.pop((owner, page_id), None)
        if page is None:
            raise _fatal(f"no such page for session: {owner[1]}", page_id)
        await page.close()
        if self._active.get(owner) == page_id:
            remaining = [
                candidate_id
                for candidate_owner, candidate_id in self._pages
                if candidate_owner == owner
            ]
            self._active[owner] = remaining[0] if remaining else None
        self._touch(owner)
        return {"closed": page_id}

    async def _m_close_session(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        session_id = owner[1]
        info = self._sessions.pop(owner, None)
        if info is None:
            self._closed_sessions.add(owner)
            return {"closed_session": session_id}
        for key in [key for key in self._pages if key[0] == owner]:
            page = self._pages.pop(key)
            try:
                await page.close()
            # intentional boundary: best-effort page teardown.
            except Exception:
                pass
        self._active.pop(owner, None)
        self._last_used.pop(owner, None)
        context = self._contexts.pop(owner, None)
        if context is not None and info["context"] != "profile":
            await context.close()
        workspace_id = owner[0]
        kind = info["context"]
        if not self._has_session_or_opening(workspace_id, kind):
            async with self._launch_lock((workspace_id, kind)):
                if not self._has_session_or_opening(workspace_id, kind):
                    await self._close_workspace_proc(workspace_id, kind)
        self._closed_sessions.add(owner)
        return {"closed_session": session_id}

    async def _m_close(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        await self.close_all()
        return {"closed": True}

    async def close_all_sessions(self) -> None:
        """Explicitly destroy every session during application shutdown."""
        for owner in list(self._sessions):
            await self._m_close_session(
                {"workspace_id": owner[0], "session_id": owner[1]},
            )

    async def _m_capture_tree(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Capture an AX tree enriched with safe DOM locator attributes."""
        owner = require_owner(params)
        page = self._page(owner, params.get("page_id"))
        cdp = await page.context.new_cdp_session(page)
        try:
            ax = await cdp.send("Accessibility.getFullAXTree")
            snapshot = await cdp.send(
                "DOMSnapshot.captureSnapshot",
                {"computedStyles": []},
            )
        finally:
            await cdp.detach()
        self._touch(owner)
        return {
            "tree": _merge_ax_dom(
                ax.get("nodes", []),
                snapshot,
            ),
            "url": page.url,
            "title": await page.title(),
        }

    async def _m_locator_count(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        locator = _locator_from_spec(
            self._page(owner, params.get("page_id")),
            _rebuild_spec(params["spec"]),
        )
        self._touch(owner)
        return {"count": await locator.count()}

    async def _m_locator_read(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        locator = _locator_from_spec(
            self._page(owner, params.get("page_id")),
            _rebuild_spec(params["spec"]),
        )
        method = str(params["property"])
        args = tuple(params.get("args", ()))
        self._touch(owner)
        return {"value": await getattr(locator, method)(*args)}

    async def _m_locator_wait_for(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Delegate locator-state waiting to Playwright's native locator."""
        owner = require_owner(params)
        locator = _locator_from_spec(
            self._page(owner, params.get("page_id")),
            _rebuild_spec(params["spec"]),
        )
        wait_ms = float(params.get("timeout") or 30_000.0)
        await locator.wait_for(
            state=str(params.get("state", "visible")),
            timeout=wait_ms,
        )
        self._touch(owner)
        return {"state": str(params.get("state", "visible"))}

    async def _m_locator_bounding_box(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Return Playwright's viewport rectangle for the resolved locator."""
        owner = require_owner(params)
        locator = _locator_from_spec(
            self._page(owner, params.get("page_id")),
            _rebuild_spec(params["spec"]),
        )
        self._touch(owner)
        return {"value": await locator.bounding_box(timeout=timeout)}

    async def _m_locator_screenshot(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Capture and persist one Playwright locator image."""
        owner = require_owner(params)
        locator = _locator_from_spec(
            self._page(owner, params.get("page_id")),
            _rebuild_spec(params["spec"]),
        )
        image = await locator.screenshot(timeout=timeout)
        self._touch(owner)
        return await persist_screenshot_async(image)

    async def _m_locator_action(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        locator = _locator_from_spec(
            self._page(owner, params.get("page_id")),
            _rebuild_spec(params["spec"]),
        )
        action = str(params["action"])
        try:
            await self._apply_locator_action(
                locator,
                action,
                params,
                int((timeout or 5) * 1000),
            )
        # intentional boundary: normalize provider failures for teaching.
        except Exception as exc:
            taught = teaching_from_strict_violation(exc)
            if taught is not None:
                raise taught from exc
            raise _fatal(f"{action} failed", str(exc)) from exc
        self._touch(owner)
        return {
            "evidence": (
                f"{action} event dispatched; verify the intended effect "
                "with a fresh snapshot()"
            ),
        }

    async def _apply_locator_action(
        self,
        locator: Any,
        action: str,
        params: Mapping[str, Any],
        timeout: int,
    ) -> None:
        handlers = {
            "click": lambda: locator.click(timeout=timeout),
            "fill": lambda: locator.fill(
                str(params["value"]),
                timeout=timeout,
            ),
            "type_text": lambda: locator.type(
                str(params["text"]),
                timeout=timeout,
            ),
            "press_key": lambda: locator.press(
                str(params["key"]),
                timeout=timeout,
            ),
            "set_checked": lambda: locator.set_checked(
                bool(params["checked"]),
                timeout=timeout,
            ),
            "select_option": lambda: locator.select_option(
                params["values"],
                timeout=timeout,
            ),
            "hover": lambda: locator.hover(timeout=timeout),
            "double_click": lambda: locator.dblclick(timeout=timeout),
            "scroll": lambda: locator.scroll_into_view_if_needed(
                timeout=timeout,
            ),
            "focus": lambda: locator.focus(timeout=timeout),
            "blur": lambda: locator.blur(timeout=timeout),
            "clear": lambda: locator.clear(timeout=timeout),
        }
        handler = handlers.get(action)
        if handler is None:
            raise ValueError(f"unknown locator action: {action}")
        await handler()

    async def _m_navigate(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Navigate the active page and return raw response facts."""
        owner = require_owner(params)
        page = self._page(owner, params.get("page_id"))
        response = await page.goto(str(params["url"]))
        self._touch(owner)
        return {
            "url": page.url,
            "status": response.status if response is not None else None,
        }

    async def _m_reload(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        page = self._page(owner, params.get("page_id"))
        await page.reload()
        self._touch(owner)
        return {"url": page.url}

    async def _m_wait_for_load_state(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Wait for a Playwright page lifecycle state."""
        del timeout
        owner = require_owner(params)
        page = self._page(owner, params.get("page_id"))
        state = str(params.get("state", "load"))
        wait_ms = float(params.get("timeout") or 30_000.0)
        await page.wait_for_load_state(state, timeout=wait_ms)
        self._touch(owner)
        return {"state": state, "url": page.url}

    async def _m_input(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Dispatch a coordinate mouse or keyboard operation on one page."""
        del timeout
        owner = require_owner(params)
        page = self._page(owner, params.get("page_id"))
        kind = params.get("kind")
        action = params.get("action")
        if kind == "mouse" and action == "click":
            await page.mouse.click(params["x"], params["y"])
        elif kind == "keyboard" and action == "press":
            await page.keyboard.press(params["key"])
        else:
            raise _fatal(
                f"unsupported input: {kind}/{action}",
                f"{kind}:{action}",
            )
        return {"ok": True}

    async def _m_screenshot(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Capture and persist a page image in the active workspace."""
        owner = require_owner(params)
        image = await self._page(
            owner,
            str(params.get("page_id") or "") or None,
        ).screenshot()
        self._touch(owner)
        return await persist_screenshot_async(image)

    async def _m_go_back(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        page = self._page(owner, params.get("page_id"))
        await page.go_back()
        self._touch(owner)
        return {"url": page.url}

    async def _m_go_forward(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        page = self._page(owner, params.get("page_id"))
        await page.go_forward()
        self._touch(owner)
        return {"url": page.url}

    async def close_all(self) -> None:
        """Close all contexts/processes and reset multiplexer state."""
        for session_id, context in list(self._contexts.items()):
            info = self._sessions.get(session_id) or {}
            if info.get("context") != "profile":
                try:
                    await context.close()
                # intentional boundary: best-effort per-context shutdown.
                except Exception:
                    pass
        for process in self._procs.values():
            try:
                if process.get("context") is not None:
                    await process["context"].close()
                if process.get("browser") is not None:
                    await process["browser"].close()
            # intentional boundary: best-effort process shutdown.
            except Exception:
                pass
        if self._pw is not None:
            await self._pw.stop()
        self._procs.clear()
        self._contexts.clear()
        self._sessions.clear()
        self._pages.clear()
        self._active.clear()
        self._last_used.clear()
        self._closed_sessions.clear()
        self._fixed_profile_workspaces.clear()
        self._pw = None
        if self in _LIVE:
            _LIVE.remove(self)


def register() -> None:
    """Register the Playwright control link for later application wiring."""
    register_local(PlaywrightControlLink())


def _atexit_close_all() -> None:
    """Try to shut down when the host exits outside its normal lifecycle."""
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None
    if running_loop is not None and running_loop.is_running():
        return
    for link in list(_LIVE):
        if not link._procs and not link._contexts and link._pw is None:
            continue
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(link.close_all())
            loop.close()
        # intentional boundary: atexit cleanup must not raise at exit.
        except Exception:
            pass


atexit.register(_atexit_close_all)
