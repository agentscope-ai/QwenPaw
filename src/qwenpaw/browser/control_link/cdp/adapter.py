# -*- coding: utf-8 -*-
"""Direct-CDP ControlLink for attached and managed Chromium endpoints."""

# pylint: disable=arguments-renamed,unused-argument
from __future__ import annotations

import asyncio
import atexit
import contextlib
import logging
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from ....config.context import get_current_workspace_dir
from ....constant import WORKING_DIR
from ....utils.io_utils import run_sync_io
from ..._proc import kill_process_sync
from ...errors import BrowserError, ErrorCause, ErrorCategory
from ...runtime.links import register_local
from ..cdp_verbs import CdpVerbsMixin
from ..identity import require_owner
from .launch import spawn_managed_chromium, wait_for_devtools_active_port
from .transport import CdpTransport

logger = logging.getLogger(__name__)


class CdpControlLink(CdpVerbsMixin):
    """Serve browser verbs through an existing or owned CDP endpoint."""

    variant = "cdp"
    reclaim_on_idle = True
    supported_contexts = frozenset({"incognito", "profile"})

    def __init__(
        self,
        transport: Any | None = None,
        *,
        cdp_url: str | None = None,
        launcher: Any | None = None,
        transport_factory: Any | None = None,
    ) -> None:
        self._init_injected_state()
        self._transport_factory = transport_factory or CdpTransport
        self._injected_transport = transport
        self._transports: dict[str, Any] = {}
        self._endpoints: dict[str, str] = {}
        self._sinks: list[Any] = []
        self._owner_sinks: dict[tuple[str, str], list[Any]] = {}
        self._transport_unsubscribers: dict[str, Callable[[], None]] = {}
        self._url = cdp_url
        self._launcher = launcher or self._default_launcher
        self._sessions: dict[tuple[str, str], dict[str, str | None]] = {}
        self._pages: dict[tuple[tuple[str, str], str], tuple[str, str]] = {}
        self._active: dict[tuple[str, str], str | None] = {}
        self._closed: set[tuple[str, str]] = set()
        self._owned: dict[str, Any] = {}
        self._launch_locks: dict[str, asyncio.Lock] = {}
        atexit.register(self._terminate_owned_processes)

    def _launch_lock(self, workspace_id: str) -> asyncio.Lock:
        """Return the workspace-scoped lock for endpoint lifecycle changes."""
        lock = self._launch_locks.get(workspace_id)
        if lock is None:
            lock = asyncio.Lock()
            self._launch_locks[workspace_id] = lock
        return lock

    async def _default_launcher(
        self,
        spec: Mapping[str, Any],
    ) -> tuple[Any, str]:
        workspace_dir = get_current_workspace_dir() or (
            WORKING_DIR / "workspaces" / "default"
        )
        user_data_dir = Path(
            spec.get("user_data_dir") or workspace_dir / ".browser-cdp",
        )
        port = int(
            spec.get("cdp_port") or spec.get("remote_debugging_port") or 0,
        )
        args = list(spec.get("args", []))
        if spec.get("proxy"):
            args.append(f"--proxy-server={spec['proxy']}")
        created: list[tuple[Any, str | None]] = []
        try:
            await run_sync_io(
                spawn_managed_chromium,
                executable=spec["executable_path"],
                user_data_dir=user_data_dir,
                headless=bool(spec.get("headless")),
                port=port,
                args=args,
                sink=created,
            )
            process, stale_content = created[0]
            return process, await wait_for_devtools_active_port(
                user_data_dir,
                process,
                stale_content=stale_content,
            )
        except BaseException:
            if created:
                reap = asyncio.ensure_future(self._reap_process(created[0][0]))
                with contextlib.suppress(BaseException):
                    await asyncio.shield(reap)
            raise

    async def _reap_process(self, process: Any) -> None:
        """Reap one owned Chromium process outside the event loop."""
        await run_sync_io(kill_process_sync, process)

    def _terminate_owned_processes(self) -> None:
        for process in list(self._owned.values()):
            kill_process_sync(process, grace=0.2)
        self._owned.clear()

    def is_available(self) -> bool:
        return True

    async def request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        require_owner(params)
        return await getattr(self, f"_m_{method}")(
            dict(params),
            timeout=timeout,
        )

    def on_event(self, sink: Any) -> Any:
        self._sinks.append(sink)

        def _unsubscribe() -> None:
            if sink in self._sinks:
                self._sinks.remove(sink)

        return _unsubscribe

    def on_event_for_owner(
        self,
        workspace_id: str,
        session_id: str,
        sink: Any,
    ) -> Callable[[], None]:
        """Subscribe a worker transport only to one composite owner."""
        owner = (workspace_id, session_id)
        sinks = self._owner_sinks.setdefault(owner, [])
        sinks.append(sink)

        def _unsubscribe() -> None:
            sinks.remove(sink)
            if not sinks:
                self._owner_sinks.pop(owner, None)

        return _unsubscribe

    def _emit(self, owner: tuple[str, str], event: dict[str, Any]) -> None:
        for sink in list(self._owner_sinks.get(owner, [])):
            sink(event)
        for sink in list(self._sinks):
            sink(event)

    def _page_for_cdp_session(
        self,
        workspace_id: str,
        cdp_session_id: str,
    ) -> tuple[tuple[str, str], str] | None:
        matches = [
            (owner, page_id)
            for (owner, page_id), (
                _,
                candidate_session_id,
            ) in self._pages.items()
            if owner[0] == workspace_id
            and candidate_session_id == cdp_session_id
        ]
        return matches[0] if len(matches) == 1 else None

    def _on_transport_event(
        self,
        workspace_id: str,
        event: Mapping[str, Any],
    ) -> None:
        """Route only CDP events whose attached session has one owner/page."""
        cdp_session_id = event.get("sessionId")
        if not isinstance(cdp_session_id, str):
            return
        resolved = self._page_for_cdp_session(workspace_id, cdp_session_id)
        if resolved is None:
            return
        owner, page_id = resolved
        if event.get("method") != "Page.javascriptDialogOpening":
            return
        params = event.get("params")
        if not isinstance(params, Mapping):
            return
        self._emit(
            owner,
            {
                "type": "dialog",
                "workspace_id": owner[0],
                "session_id": owner[1],
                "page_id": page_id,
                "kind": params.get("type"),
                "message": params.get("message"),
            },
        )
        asyncio.create_task(
            self._dismiss_dialog(workspace_id, cdp_session_id),
        )

    async def _dismiss_dialog(
        self,
        workspace_id: str,
        cdp_session_id: str,
    ) -> None:
        try:
            await self._transport_for(workspace_id).send(
                "Page.handleJavaScriptDialog",
                {"accept": False},
                session_id=cdp_session_id,
            )
        except Exception:  # pragma: no cover - provider-dependent failure
            logger.warning("browser CDP dialog auto-dismiss failed")

    def _subscribe_transport_events(
        self,
        workspace_id: str,
        transport: Any,
    ) -> None:
        if workspace_id not in self._transport_unsubscribers:
            self._transport_unsubscribers[workspace_id] = transport.subscribe(
                lambda event: self._on_transport_event(workspace_id, event),
            )

    def _page_id(
        self,
        owner: tuple[str, str],
        page_id: str | None = None,
    ) -> str:
        resolved = page_id or self._active.get(owner)
        if resolved is None or (owner, resolved) not in self._pages:
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

    def _cache_page_id(
        self,
        owner: tuple[str, str],
        page_id: str | None,
    ) -> str:
        """Use the concrete active page for injected-engine cache entries."""
        return self._page_id(owner, page_id)

    async def _connect(self, workspace_id: str, url: str) -> None:
        existing = self._endpoints.get(workspace_id)
        if existing is not None:
            if existing != url:
                raise BrowserError(
                    category=ErrorCategory.FATAL,
                    suggested_action=(
                        "This workspace already has a CDP endpoint. Close "
                        "all sessions before switching endpoints."
                    ),
                    reason="workspace endpoint conflict",
                    detail=url,
                )
            return
        transport = self._injected_transport or self._transport_factory()
        try:
            await transport.connect(url)
            self._transports[workspace_id] = transport
            self._endpoints[workspace_id] = url
            self._subscribe_transport_events(workspace_id, transport)
        except BaseException:
            self._transports.pop(workspace_id, None)
            self._endpoints.pop(workspace_id, None)
            unsubscribe = self._transport_unsubscribers.pop(workspace_id, None)
            if unsubscribe is not None:
                unsubscribe()
            await transport.close()
            raise

    def _transport_for(self, workspace_id: str) -> Any:
        transport = self._transports.get(workspace_id)
        if transport is None:
            raise BrowserError(
                category=ErrorCategory.FATAL,
                suggested_action=(
                    "Open a session first so the endpoint is established."
                ),
                reason="no endpoint for workspace",
                detail=workspace_id,
            )
        return transport

    async def _cdp(
        self,
        owner: tuple[str, str],
        page_id: str | None,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        page = self._page_id(owner, page_id)
        _, cdp_session_id = self._pages[(owner, page)]
        return await self._transport_for(owner[0]).send(
            method,
            params or {},
            session_id=cdp_session_id,
            timeout=timeout,
        )

    # pylint: disable-next=too-many-branches
    async def _m_open_session(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        context = str(params.get("context", "incognito"))
        headless = bool(params.get("headless", False))
        if owner in self._sessions:
            if self._sessions[owner]["context"] == context:
                return {
                    "session_id": owner[1],
                    "context": self._sessions[owner]["context"],
                }
            await self._m_close_session(params, timeout=timeout)
        backend = params.get("backend")
        if backend == "managed_cdp":
            async with self._launch_lock(owner[0]):
                if owner[0] not in self._endpoints:
                    process, url = await self._launcher(params)
                    old_process = self._owned.pop(owner[0], None)
                    if old_process is not None:
                        logger.warning(
                            "Replacing stale owned Chromium for workspace %s",
                            owner[0],
                        )
                        await self._reap_process(old_process)
                    self._owned[owner[0]] = process
                    try:
                        await self._connect(owner[0], url)
                    except BaseException:
                        self._owned.pop(owner[0], None)
                        reap = asyncio.ensure_future(
                            self._reap_process(process),
                        )
                        with contextlib.suppress(BaseException):
                            await asyncio.shield(reap)
                        raise
        elif backend == "connect_cdp":
            if params.get("proxy"):
                logger.warning(
                    "browser.proxy is ignored for connect_cdp sessions",
                )
            await self._connect(owner[0], str(params["cdp_url"]))
            version = await self._transport_for(owner[0]).send(
                "Browser.getVersion",
                {},
                timeout=timeout,
            )
            headless = str(version.get("product", "")).startswith(
                "HeadlessChrome",
            )
        elif self._url:
            await self._connect(owner[0], self._url)
        elif self._injected_transport is not None:
            transport = self._transports.setdefault(
                owner[0],
                self._injected_transport,
            )
            self._endpoints.setdefault(owner[0], "injected")
            self._subscribe_transport_events(owner[0], transport)

        if context == "profile":
            holder = next(
                (
                    existing
                    for existing, info in self._sessions.items()
                    if existing[0] == owner[0] and info["context"] == "profile"
                ),
                None,
            )
            if holder is not None:
                raise BrowserError(
                    category=ErrorCategory.FATAL,
                    suggested_action=(
                        "This workspace's persistent profile is already held "
                        "by an open session. Reuse it or close it first; for "
                        "parallel work open an incognito session, which is "
                        "fully isolated."
                    ),
                    reason="profile session already open",
                    detail=holder[1],
                )

        browser_context_id = None
        if context == "incognito":
            browser_context = await self._transport_for(owner[0]).send(
                "Target.createBrowserContext",
                {},
                timeout=timeout,
            )
            browser_context_id = str(browser_context["browserContextId"])
        self._sessions[owner] = {
            "context": context,
            "browser_context_id": browser_context_id,
        }
        self._closed.discard(owner)
        return {
            "session_id": owner[1],
            "context": context,
            "headless": headless,
        }

    async def _m_new_page(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
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
        target_params: dict[str, Any] = {
            "url": str(params.get("url", "about:blank")),
        }
        browser_context_id = self._sessions[owner]["browser_context_id"]
        if browser_context_id is not None:
            target_params["browserContextId"] = browser_context_id
        target = await self._transport_for(owner[0]).send(
            "Target.createTarget",
            target_params,
            timeout=timeout,
        )
        attached = await self._transport_for(owner[0]).send(
            "Target.attachToTarget",
            {"targetId": target["targetId"], "flatten": True},
            timeout=timeout,
        )
        page_id = uuid.uuid4().hex[:8]
        self._pages[(owner, page_id)] = (
            str(target["targetId"]),
            str(attached["sessionId"]),
        )
        self._active[owner] = page_id
        return {
            "page_id": page_id,
            "url": str(params.get("url", "about:blank")),
        }

    async def _target_surface(
        self,
        owner: tuple[str, str],
        page_id: str,
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        target_id, _ = self._pages[(owner, page_id)]
        result = await self._transport_for(owner[0]).send(
            "Target.getTargetInfo",
            {"targetId": target_id},
            timeout=timeout,
        )
        return result.get("targetInfo", {})

    async def _m_list_pages(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        if owner in self._closed:
            return {"pages": []}
        pages = []
        for candidate_owner, page_id in self._pages:
            if candidate_owner != owner:
                continue
            surface = await self._target_surface(
                owner,
                page_id,
                timeout=timeout,
            )
            pages.append(
                {
                    "page_id": page_id,
                    "url": str(surface.get("url", "")),
                    "active": page_id == self._active.get(owner),
                },
            )
        return {"pages": pages}

    async def _m_current_surface(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        page_id = self._page_id(owner, params.get("page_id"))
        surface = await self._target_surface(
            owner,
            page_id,
            timeout=timeout,
        )
        return {
            "url": str(surface.get("url", "")),
            "title": str(surface.get("title", "")),
        }

    async def _m_activate_page(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        page_id = self._page_id(owner, str(params["page_id"]))
        target_id, _ = self._pages[(owner, page_id)]
        await self._transport_for(owner[0]).send(
            "Target.activateTarget",
            {"targetId": target_id},
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
        target_id, _ = self._pages.pop((owner, page_id))
        self._invalidate_injected(page_id)
        await self._transport_for(owner[0]).send(
            "Target.closeTarget",
            {"targetId": target_id},
            timeout=timeout,
        )
        if self._active.get(owner) == page_id:
            self._active[owner] = next(
                (
                    candidate
                    for candidate_owner, candidate in self._pages
                    if candidate_owner == owner
                ),
                None,
            )
        return {"closed": page_id}

    async def _m_close_session(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        owner = require_owner(params)
        for key in [key for key in self._pages if key[0] == owner]:
            target_id, _ = self._pages.pop(key)
            self._invalidate_injected(key[1])
            await self._transport_for(owner[0]).send(
                "Target.closeTarget",
                {"targetId": target_id},
                timeout=timeout,
            )
        session = self._sessions.pop(owner, None)
        browser_context_id = (
            None if session is None else session["browser_context_id"]
        )
        if browser_context_id is not None:
            await self._transport_for(owner[0]).send(
                "Target.disposeBrowserContext",
                {"browserContextId": browser_context_id},
                timeout=timeout,
            )
        self._active.pop(owner, None)
        self._closed.add(owner)
        if not any(remaining[0] == owner[0] for remaining in self._sessions):
            async with self._launch_lock(owner[0]):
                if not any(
                    remaining[0] == owner[0] for remaining in self._sessions
                ):
                    process = self._owned.pop(owner[0], None)
                    if process is not None:
                        await self._reap_process(process)
                    transport = self._transports.pop(owner[0], None)
                    self._endpoints.pop(owner[0], None)
                    unsubscribe = self._transport_unsubscribers.pop(
                        owner[0],
                        None,
                    )
                    if unsubscribe is not None:
                        unsubscribe()
                    if transport is not None:
                        await transport.close()
        return {"closed_session": owner[1]}

    async def _m_close(
        self,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        await self.close_all()
        return {"closed": True}

    async def close_all(self) -> None:
        for owner in list(self._sessions):
            await self._m_close_session(
                {"workspace_id": owner[0], "session_id": owner[1]},
            )
        self._transports.clear()
        self._endpoints.clear()
        for unsubscribe in self._transport_unsubscribers.values():
            unsubscribe()
        self._transport_unsubscribers.clear()
        await self._reap_orphan_owned()

    async def close_all_sessions(self) -> None:
        """Explicitly destroy every session during application shutdown."""
        for owner in list(self._sessions):
            await self._m_close_session(
                {"workspace_id": owner[0], "session_id": owner[1]},
            )
        await self._reap_orphan_owned()

    async def _reap_orphan_owned(self) -> None:
        """Reclaim owned Chromium processes without a remaining session."""
        for workspace_id in list(self._owned):
            if any(owner[0] == workspace_id for owner in self._sessions):
                continue
            async with self._launch_lock(workspace_id):
                if any(owner[0] == workspace_id for owner in self._sessions):
                    continue
                orphan = self._owned.pop(workspace_id, None)
                if orphan is not None:
                    await self._reap_process(orphan)


def register() -> None:
    register_local(CdpControlLink())
