# -*- coding: utf-8 -*-
"""Chrome ControlLink composed from Native Messaging ``tab.*`` commands."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import inspect
import logging
import uuid
from typing import Any, Awaitable, Callable, Mapping

from ...errors import BrowserError, ErrorCause, ErrorCategory
from ...runtime.links import register_local
from ...runtime.ports import EventSink
from ..cdp_verbs import CdpVerbsMixin, persist_screenshot_async
from ..identity import require_owner
from .bridge import NMBridgeWireError, get_nm_bridge
from .protocol import PROTOCOL_VERSION

OwnerKey = tuple[str, str]
_STALE_TAB_ERROR_TEXT = (
    "no tab with id",
    "no such tab",
    "tab not found",
    "tab gone",
)
logger = logging.getLogger(__name__)


class ChromeControlLink(CdpVerbsMixin):
    """First-party ControlLink with local session and page lifecycle state."""

    variant = "chrome"
    reclaim_on_idle = False
    supported_contexts = frozenset({"profile"})
    default_context = "profile"

    def __init__(self, bridge: Any | None = None) -> None:
        self._init_injected_state()
        self._bridge = bridge if bridge is not None else get_nm_bridge()
        self._sessions: dict[OwnerKey, dict[str, str]] = {}
        self._pages: dict[tuple[str, str, str], int] = {}
        self._active: dict[OwnerKey, str | None] = {}
        self._live_session_resolvers: dict[
            str,
            Callable[[], Awaitable[set[str]] | set[str]],
        ] = {}
        self._closed: set[OwnerKey] = set()
        self._reset_after_disconnect: set[OwnerKey] = set()
        self._tab_owners: dict[int, OwnerKey] = {}
        self._sinks: list[EventSink] = []
        self._owner_sinks: dict[OwnerKey, list[EventSink]] = {}
        self._bridge.add_event_listener("cdp.event", self._on_cdp_event)
        self._bridge.add_event_listener("tabs.removed", self._on_tab_removed)
        self._bridge.subscribe_ready(self._on_handshake_complete)

    def is_available(self) -> bool:
        return bool(self._bridge.is_connected())

    async def request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Handle lifecycle verbs locally; leave Phase 2b verbs to bridge."""
        require_owner(params)
        handler = getattr(self, f"_m_{method}", None)
        if handler is not None:
            return await handler(dict(params), timeout=timeout)
        return await self._bridge.request(
            method,
            dict(params),
            timeout=timeout,
        )

    def on_event(self, sink: EventSink) -> Callable[[], None]:
        self._sinks.append(sink)
        return lambda: self._sinks.remove(sink)

    def on_event_for_owner(
        self,
        workspace_id: str,
        session_id: str,
        sink: EventSink,
    ) -> Callable[[], None]:
        """Subscribe a worker transport only to one composite owner."""
        owner = (workspace_id, session_id)
        sinks = self._owner_sinks.setdefault(owner, [])
        sinks.append(sink)

        def unsubscribe() -> None:
            sinks.remove(sink)
            if not sinks:
                self._owner_sinks.pop(owner, None)

        return unsubscribe

    def register_live_session_resolver(
        self,
        workspace_id: str,
        resolver: Callable[[], Awaitable[set[str]] | set[str]],
    ) -> Callable[[], None]:
        """Register one workspace's read-only live-chat session lookup."""
        self._live_session_resolvers[workspace_id] = resolver

        def unregister() -> None:
            if self._live_session_resolvers.get(workspace_id) is resolver:
                self._live_session_resolvers.pop(workspace_id, None)

        return unregister

    def _emit(self, owner: OwnerKey, event: dict[str, Any]) -> None:
        for sink in list(self._owner_sinks.get(owner, [])):
            sink(event)
        for sink in list(self._sinks):
            sink(event)

    @staticmethod
    def _page_key(owner: OwnerKey, page_id: str) -> tuple[str, str, str]:
        return owner[0], owner[1], page_id

    def _page_for_tab(self, tab_id: int) -> tuple[OwnerKey, str, str] | None:
        """Return the owned session/page that currently maps to ``tab_id``."""
        owner = self._tab_owners.get(tab_id)
        if owner is None:
            return None
        for (_, session_id, page_id), candidate in self._pages.items():
            if candidate == tab_id:
                return owner, session_id, page_id
        return None

    def _on_cdp_event(self, event: Mapping[str, Any]) -> None:
        """Normalize raw extension CDP events into the public event schema."""
        tab_id = event.get("tabId")
        method = event.get("method")
        params = event.get("params")
        if not isinstance(tab_id, int) or not isinstance(params, Mapping):
            return
        page = self._page_for_tab(tab_id)
        if page is None:
            return
        owner, session_id, page_id = page

        if method == "Page.frameNavigated":
            frame = params.get("frame")
            if isinstance(frame, Mapping):
                self._invalidate_frame_contexts(page_id)
                if "parentId" not in frame:
                    self._invalidate_injected(page_id)
                    self._emit(
                        owner,
                        {
                            "type": "load",
                            "session_id": session_id,
                            "page_id": page_id,
                            "url": frame.get("url", ""),
                        },
                    )
        elif method == "Page.javascriptDialogOpening":
            self._emit(
                owner,
                {
                    "type": "dialog",
                    "session_id": session_id,
                    "page_id": page_id,
                    "kind": params.get("type"),
                    "message": params.get("message"),
                },
            )
            asyncio.create_task(self._dismiss_dialog(owner, page_id))

    async def _dismiss_dialog(self, owner: OwnerKey, page_id: str) -> None:
        try:
            await self._cdp(
                owner,
                page_id,
                "Page.handleJavaScriptDialog",
                {"accept": False},
            )
        except Exception:  # pragma: no cover - provider-dependent failure
            logger.warning("browser Chrome dialog auto-dismiss failed")

    def _on_tab_removed(self, event: Mapping[str, Any]) -> None:
        """Clear local page state after Chrome removes an owned tab."""
        tab_id = event.get("tabId")
        if not isinstance(tab_id, int):
            return
        owner = self._tab_owners.pop(tab_id, None)
        if owner is None:
            return
        stale_page_ids = [
            page_id
            for (
                workspace_id,
                session_id,
                page_id,
            ), candidate in self._pages.items()
            if candidate == tab_id and (workspace_id, session_id) == owner
        ]
        for page_id in stale_page_ids:
            self._pages.pop(self._page_key(owner, page_id), None)
            self._invalidate_injected(page_id)
        if self._active.get(owner) in stale_page_ids:
            remaining = [
                page_id
                for workspace_id, session_id, page_id in self._pages
                if (workspace_id, session_id) == owner
            ]
            self._active[owner] = remaining[0] if remaining else None
        for page_id in stale_page_ids:
            self._emit(
                owner,
                {
                    "type": "page_closed",
                    "session_id": owner[1],
                    "page_id": page_id,
                    "reason": str(event.get("reason") or "external_close"),
                },
            )

    async def _on_handshake_complete(
        self,
        _event: Mapping[str, Any] | None = None,
    ) -> None:
        """Reconcile local state after an extension handshake."""
        result = await self._bridge.request("tabs.list", {})
        tabs = result if isinstance(result, list) else result.get("tabs", [])
        await self._reconcile_on_handshake(
            [tab for tab in tabs if isinstance(tab, Mapping)],
        )

    async def _live_session_ids(
        self,
        workspace_id: str,
    ) -> set[str] | None:
        resolver = self._live_session_resolvers.get(workspace_id)
        if resolver is None:
            return None
        sessions = resolver()
        if inspect.isawaitable(sessions):
            sessions = await sessions
        return {str(session_id) for session_id in sessions}

    def _reclaim_tab(self, tab: Mapping[str, Any]) -> OwnerKey | None:
        """Adopt a live extension tab as chat-scoped local state."""
        tab_id = tab.get("tabId")
        workspace_id = str(tab.get("workspaceId") or "")
        session_id = str(tab.get("ownerId") or "")
        if not isinstance(tab_id, int) or not workspace_id or not session_id:
            return None
        owner = (workspace_id, session_id)
        page_id = uuid.uuid4().hex[:8]
        self._pages[self._page_key(owner, page_id)] = tab_id
        self._tab_owners[tab_id] = owner
        self._active.setdefault(owner, page_id)
        self._sessions.setdefault(
            owner,
            {"context": "profile", "workspace_id": workspace_id},
        )
        self._closed.discard(owner)
        return owner

    async def _reconcile_on_handshake(
        self,
        tabs: list[Mapping[str, Any]],
    ) -> None:
        """Reconcile local pages with extension-owned tabs after reconnect."""
        extension_tabs = [
            tab
            for tab in tabs
            if tab.get("createdByQwenPaw")
            and isinstance(tab.get("tabId"), int)
        ]
        extension_tab_ids = {int(tab["tabId"]) for tab in extension_tabs}
        for (workspace_id, session_id, page_id), tab_id in list(
            self._pages.items(),
        ):
            if tab_id not in extension_tab_ids:
                self._forget_page((workspace_id, session_id), page_id, tab_id)

        known_tab_ids = set(self._pages.values())
        for tab in extension_tabs:
            tab_id = int(tab["tabId"])
            if tab_id in known_tab_ids:
                continue
            workspace_id = str(tab.get("workspaceId") or "")
            owner_id = str(tab.get("ownerId") or "")
            live_sessions = await self._live_session_ids(workspace_id)
            if live_sessions is None:
                logger.warning(
                    "browser.chrome.reconcile skipped: no live-session "
                    "resolver for workspace %s",
                    workspace_id,
                )
                continue
            if owner_id in live_sessions:
                self._reclaim_tab(tab)
                known_tab_ids.add(tab_id)
                continue
            await self._close_tab_idempotent(tab_id)

    def _page_id(self, owner: OwnerKey, page_id: str | None = None) -> str:
        resolved = page_id or self._active.get(owner)
        if (
            resolved is None
            or self._page_key(owner, resolved) not in self._pages
        ):
            if owner in self._closed:
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
        return resolved

    def _cache_page_id(self, owner: OwnerKey, page_id: str | None) -> str:
        """Use the concrete active page for injected-engine cache entries."""
        return self._page_id(owner, page_id)

    async def _cdp(
        self,
        owner: OwnerKey,
        page_id: str | None,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        if owner in self._reset_after_disconnect:
            self._reset_after_disconnect.discard(owner)
            raise BrowserError(
                category=ErrorCategory.REROUTE,
                suggested_action="reroute",
                reason="browser session was reset after a disconnect",
                detail="Previous pages were lost; re-open the page you need.",
            )
        resolved = self._page_id(owner, page_id)
        tab_id = self._pages[self._page_key(owner, resolved)]
        try:
            await self._bridge.request(
                "tab.attach",
                {"tabId": tab_id},
                timeout=timeout,
            )
            return await self._bridge.request(
                "cdp.send",
                {
                    "tabId": tab_id,
                    "method": method,
                    "params": dict(params or {}),
                },
                timeout=timeout,
            )
        except NMBridgeWireError as exc:
            if not self._is_stale_tab_error(exc):
                raise
            self._forget_page(owner, resolved, tab_id)
            raise BrowserError(
                category=ErrorCategory.RETRYABLE,
                cause=ErrorCause.STATE_STALE,
                suggested_action="Open a new page if you need to continue",
                reason="page has been closed",
                detail=str(exc),
            ) from exc

    async def _tabs(
        self,
        *,
        timeout: float | None = None,
    ) -> dict[int, Mapping[str, Any]]:
        result = await self._bridge.request("tabs.list", {}, timeout=timeout)
        tabs = result if isinstance(result, list) else result.get("tabs", [])
        return {
            int(tab["tabId"]): tab
            for tab in tabs
            if isinstance(tab, Mapping) and "tabId" in tab
        }

    async def _close_tab_idempotent(
        self,
        tab_id: int,
        *,
        timeout: float | None = None,
    ) -> None:
        """Close a control tab, accepting an already-observed disappearance."""
        try:
            await self._bridge.request(
                "tab.close",
                {"tabId": tab_id},
                timeout=timeout,
            )
        except NMBridgeWireError as exc:
            if self._is_stale_tab_error(exc):
                return
            raise

    @staticmethod
    def _is_stale_tab_error(exc: NMBridgeWireError) -> bool:
        """Return whether a wire error proves the target tab disappeared."""
        code = str(exc.browser_error_code).lower()
        message = str(exc).lower()
        return code in {"tab_not_found", "tab_gone"} or any(
            text in message for text in _STALE_TAB_ERROR_TEXT
        )

    async def _reap_owner_orphans(
        self,
        owner: OwnerKey,
        *,
        timeout: float | None = None,
    ) -> None:
        """Close extension-owned tabs absent from local registry."""
        registered = set(self._pages.values())
        for tab in (await self._tabs(timeout=timeout)).values():
            if (
                tab.get("createdByQwenPaw")
                and str(tab.get("ownerId", "")) == owner[1]
                and str(tab.get("workspaceId", "")) == owner[0]
                and int(tab["tabId"]) not in registered
            ):
                await self._close_tab_idempotent(
                    int(tab["tabId"]),
                    timeout=timeout,
                )

    def _forget_page(
        self,
        owner: OwnerKey,
        page_id: str,
        tab_id: int,
    ) -> None:
        self._pages.pop(self._page_key(owner, page_id), None)
        self._tab_owners.pop(tab_id, None)
        if self._active.get(owner) == page_id:
            remaining = [
                candidate_id
                for workspace_id, session_id, candidate_id in self._pages
                if (workspace_id, session_id) == owner
            ]
            self._active[owner] = remaining[0] if remaining else None

    def _forget_owner(self, owner: OwnerKey) -> None:
        """Drop all local state for one owner after a disconnect rebuild."""
        for key in [key for key in self._pages if key[:2] == owner]:
            self._tab_owners.pop(self._pages[key], None)
            self._pages.pop(key, None)
        self._sessions.pop(owner, None)
        self._active.pop(owner, None)

    async def _m_open_session(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        if params.get("proxy"):
            logger.warning("browser.proxy is ignored for extension sessions")
        session_id = owner[1]
        context = str(params.get("context", "profile"))
        rebuilt_after_disconnect = False
        if owner in self._sessions:
            if not self._bridge.is_connected():
                self._forget_owner(owner)
                rebuilt_after_disconnect = True
            elif self._sessions[owner]["context"] != context:
                await self._m_close_session(params, timeout=timeout)
            else:
                return {
                    "session_id": session_id,
                    "context": self._sessions[owner]["context"],
                    "headless": False,
                }
        await self._reap_owner_orphans(owner, timeout=timeout)
        self._sessions[owner] = {
            "context": context,
            "workspace_id": owner[0],
        }
        if rebuilt_after_disconnect:
            self._reset_after_disconnect.add(owner)
        self._closed.discard(owner)
        return {
            "session_id": session_id,
            "context": context,
            "headless": False,
        }

    async def _m_new_page(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        session_id = owner[1]
        if owner not in self._sessions:
            raise BrowserError(
                category=ErrorCategory.RETRYABLE,
                cause=ErrorCause.STATE_STALE,
                suggested_action=(
                    "Reconnect first: browser = await Browser.connect()"
                ),
                reason="browser session is closed",
                detail="this session was closed earlier in the chat",
            )
        workspace_id = self._sessions[owner]["workspace_id"]
        created = await self._bridge.request(
            "tab.create",
            {
                "url": str(params.get("url", "about:blank")),
                "ownerId": session_id,
                "workspaceId": workspace_id,
                "protocolVersion": PROTOCOL_VERSION,
            },
            timeout=timeout,
        )
        page_id = uuid.uuid4().hex[:8]
        tab_id = int(created["tabId"])
        try:
            self._pages[self._page_key(owner, page_id)] = tab_id
            self._tab_owners[tab_id] = owner
            self._active[owner] = page_id
            await self._cdp(owner, page_id, "Page.enable", {}, timeout=timeout)
        except Exception:
            await self._close_tab_idempotent(tab_id, timeout=timeout)
            self._forget_page(owner, page_id, tab_id)
            raise
        return {"page_id": page_id, "url": str(created.get("url", ""))}

    async def _m_list_pages(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        if owner in self._closed:
            return {"pages": []}
        tabs = await self._tabs(timeout=timeout)
        return {
            "pages": [
                {
                    "page_id": page_id,
                    "url": str(tabs.get(tab_id, {}).get("url", "")),
                    "active": page_id == self._active.get(owner),
                }
                for (
                    workspace_id,
                    session_id,
                    page_id,
                ), tab_id in self._pages.items()
                if (workspace_id, session_id) == owner
            ],
        }

    async def _m_current_surface(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        page_id = self._page_id(owner, params.get("page_id"))
        tab_id = self._pages[self._page_key(owner, page_id)]
        tab = (await self._tabs(timeout=timeout)).get(tab_id, {})
        return {
            "url": str(tab.get("url", "")),
            "title": str(tab.get("title", "")),
        }

    async def _m_activate_page(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        page_id = self._page_id(owner, str(params["page_id"]))
        await self._bridge.request(
            "tab.activate",
            {"tabId": self._pages[self._page_key(owner, page_id)]},
            timeout=timeout,
        )
        self._active[owner] = page_id
        return {"active": page_id}

    async def _m_close_page(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        page_id = self._page_id(owner, str(params["page_id"]))
        tab_id = self._pages.pop(self._page_key(owner, page_id))
        self._tab_owners.pop(tab_id, None)
        await self._close_tab_idempotent(tab_id, timeout=timeout)
        if self._active.get(owner) == page_id:
            remaining = [
                candidate_id
                for workspace_id, session_id, candidate_id in self._pages
                if (workspace_id, session_id) == owner
            ]
            self._active[owner] = remaining[0] if remaining else None
        return {"closed": page_id}

    async def _m_close_session(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        session_id = owner[1]
        for key in [key for key in self._pages if key[:2] == owner]:
            tab_id = self._pages.pop(key)
            self._tab_owners.pop(tab_id, None)
            await self._close_tab_idempotent(tab_id, timeout=timeout)
        await self._reap_owner_orphans(owner, timeout=timeout)
        self._sessions.pop(owner, None)
        self._active.pop(owner, None)
        self._closed.add(owner)
        return {"closed_session": session_id}

    async def _m_close(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        del params, timeout
        await self.close_all()
        return {"closed": True}

    async def _m_screenshot(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        out = await self._cdp(
            require_owner(params),
            params.get("page_id"),
            "Page.captureScreenshot",
            {"format": "png"},
            timeout=timeout,
        )
        return await persist_screenshot_async(
            base64.b64decode(str(out["data"])),
        )

    async def close_all(self) -> None:
        """Close every locally-owned Chrome tab and forget its sessions."""
        for workspace_id, session_id in list(self._sessions):
            await self._m_close_session(
                {"workspace_id": workspace_id, "session_id": session_id},
            )

    async def close_all_sessions(self) -> None:
        """Close registered QwenPaw tabs and forget every owner."""
        for key in list(self._pages):
            tab_id = self._pages.pop(key)
            self._tab_owners.pop(tab_id, None)
            with contextlib.suppress(Exception):
                await self._close_tab_idempotent(tab_id)
        self._sessions.clear()
        self._active.clear()


def register() -> None:
    """Register the first-party Chrome control link."""
    register_local(ChromeControlLink())
