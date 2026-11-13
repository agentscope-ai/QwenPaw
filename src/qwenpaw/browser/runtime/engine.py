# -*- coding: utf-8 -*-
"""Assembly root for unified-browser semantic runtime domains."""

from __future__ import annotations

from typing import Any

from ..errors import BrowserError, ErrorCategory, ErrorCause
from ..sdk.contracts import Context, Owner, PageRef, SessionStatus, Variant
from .links import availability, link_for
from .locator import LocatorDomain
from .observation import ObservationDomain
from .ownership import Session
from .ownership_adapter import build_session


def _resolve_context(link: Any, context: str) -> str:
    """Reject a context the selected variant does not support."""
    supported: frozenset[str] = getattr(
        link,
        "supported_contexts",
        frozenset({"incognito", "profile"}),
    )
    if context not in supported:
        raise BrowserError(
            category=ErrorCategory.ASK_HUMAN,
            cause=ErrorCause.CAPABILITY_UNSUPPORTED,
            suggested_action=(
                "Use context='profile', or switch the browser backend to "
                "playwright/cdp for incognito."
            ),
            reason=(
                f"variant {link.variant} does not support context '{context}'"
            ),
            detail=context,
        )
    return context


class Engine:
    """Session-scoped coordinator that owns all semantic domain instances."""

    def __init__(self, *, link: Any, session: Session) -> None:
        self.link = link
        self.session = session

    def locator_for(self, page_id: str) -> LocatorDomain:
        """Return lazy locator operations bound to one concrete page."""
        return LocatorDomain(self.link, self.session.owner, page_id)

    def observation_for(self, page_id: str) -> ObservationDomain:
        """Return observation operations bound to one concrete page."""
        return ObservationDomain(
            self.link,
            self.session.owner,
            page_id,
            self,
        )

    @classmethod
    async def connect(
        cls,
        *,
        identity: str = "auto",
        owner: Owner,
        user_data_dir: str | None = None,
    ) -> "Engine":
        """Adjudicate identity and open its concrete provider context."""
        from ...config.utils import load_config
        from .identity import resolve_identity
        from .launch_resolve import resolve_launch_env

        config = load_config().browser
        facts = await availability()
        resolution = resolve_identity(
            model_identity=identity,
            config_identity=config.identity,
            chrome_available=facts.get("chrome", False),
            engine_backend=config.backend,
        )
        from ..sdk.execution_context import get_execution_context

        execution = get_execution_context()
        if execution is not None:
            execution.automatic_identity_fallback = (
                resolution.source == "auto" and not facts.get("chrome", False)
            )
            execution.resolved_backend = resolution.variant
        if (
            resolution.identity == "user"
            and resolution.source in {"model", "config"}
            and not facts.get("chrome", False)
        ):
            raise BrowserError(
                category=ErrorCategory.ASK_HUMAN,
                suggested_action=(
                    "Connect the Chrome extension, then retry as user; or "
                    "choose avatar or guest explicitly."
                ),
                reason="requested user browser is unavailable",
            )
        link = link_for(resolution.variant)
        if link is None or not facts.get(resolution.variant, False):
            raise BrowserError(
                category=ErrorCategory.REROUTE,
                suggested_action="reroute",
                reason="no available control link",
            )
        launch = resolve_launch_env(config)
        resolved_context = _resolve_context(link, resolution.context)
        session = await build_session(
            link,
            context=resolved_context,
            owner=owner,
            variant=resolution.variant,
            identity=resolution.identity,
            launch=launch,
            user_data_dir=user_data_dir,
        )
        return cls(link=link, session=session)

    def is_headless(self) -> bool:
        """Return whether this session has no visible browser window."""
        return bool(self.session.headless)

    async def close(self) -> None:
        """Close the owned provider session-context."""
        await self.link.request(
            "close_session",
            {
                "workspace_id": self.session.workspace_id,
                "session_id": self.session.session_id,
            },
        )
        self.session.connected = False

    async def _request(self, method: str, params: dict[str, Any]) -> Any:
        """Dispatch a live session verb, rejecting stale engines locally."""
        if not self.session.connected:
            raise BrowserError(
                category=ErrorCategory.RETRYABLE,
                cause=ErrorCause.STATE_STALE,
                suggested_action=(
                    "Reconnect first: browser = await Browser.connect()"
                ),
                reason="browser session is closed",
                detail="this session was closed earlier in the chat",
            )
        return await self.link.request(method, params)

    def session_status(self) -> SessionStatus:
        """Return this engine's typed identity and connection status."""
        session = self.session
        return SessionStatus(
            owner=session.owner,
            variant=Variant(session.variant),
            context=Context(session.context),
            identity=session.identity,
            connected=session.connected,
        )

    async def pages(self) -> list[PageRef]:
        """Return safe page facts for this session context only."""
        raw = await self._request(
            "list_pages",
            {
                "workspace_id": self.session.workspace_id,
                "session_id": self.session.session_id,
            },
        )
        return [
            PageRef(
                id=str(page["page_id"]),
                url=str(page.get("url", "")),
                title=str(page.get("title", "")),
                active=bool(page.get("active")),
            )
            for page in raw.get("pages", [])
        ]

    async def open(
        self,
        url: str | None = None,
        *,
        new_tab: bool = False,
    ) -> PageRef:
        """Ensure a usable page, reusing the active page when possible."""
        if not new_tab and self.session.page_id:
            try:
                if url:
                    await self._navigate(
                        self.session.page_id,
                        "navigate",
                        url,
                    )
                raw = await self._request(
                    "current_surface",
                    {
                        "workspace_id": self.session.workspace_id,
                        "session_id": self.session.session_id,
                        "page_id": self.session.page_id,
                    },
                )
                return PageRef(
                    id=self.session.page_id,
                    url=str(raw.get("url", "")),
                    title="",
                    active=True,
                )
            except BrowserError as exc:
                if exc.cause is not ErrorCause.STATE_STALE:
                    raise
                self.session.page_id = None
        params: dict[str, str] = {
            "workspace_id": self.session.workspace_id,
            "session_id": self.session.session_id,
        }
        if url:
            params["url"] = url
        raw = await self._request("new_page", params)
        self.session.page_id = str(raw["page_id"])
        return PageRef(
            id=self.session.page_id,
            url=str(raw.get("url", "")),
            title="",
            active=True,
        )

    async def present(self, url: str | None = None) -> PageRef:
        """Open a page which remains available for the chat lifetime."""
        params: dict[str, str] = {
            "workspace_id": self.session.workspace_id,
            "session_id": self.session.session_id,
        }
        if url:
            params["url"] = url
        raw = await self._request("present_page", params)
        self.session.page_id = str(raw["page_id"])
        return PageRef(
            id=self.session.page_id,
            url=str(raw.get("url", "")),
            title="",
            active=True,
        )

    async def switch_page(self, page: PageRef) -> None:
        """Make one safe page reference active in this session."""
        await self._request(
            "activate_page",
            {
                "workspace_id": self.session.workspace_id,
                "session_id": self.session.session_id,
                "page_id": page.id,
            },
        )

    async def close_page(self, page: PageRef) -> None:
        """Close one safe page reference in this session."""
        await self._request(
            "close_page",
            {
                "workspace_id": self.session.workspace_id,
                "session_id": self.session.session_id,
                "page_id": page.id,
            },
        )

    async def _navigate(
        self,
        page_id: str,
        method: str,
        url: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "workspace_id": self.session.workspace_id,
            "session_id": self.session.session_id,
            "page_id": page_id,
        }
        if url is not None:
            params["url"] = url
        return dict(await self._request(method, params))

    async def _keep_page(self, page_id: str) -> None:
        """Upgrade one page to the chat lifetime."""
        await self._request(
            "keep_page",
            {
                "workspace_id": self.session.workspace_id,
                "session_id": self.session.session_id,
                "page_id": page_id,
            },
        )

    async def _carry_over(self, page_id: str, *, cycles: int) -> None:
        """Protect a cycle page from a bounded number of cleanups."""
        await self._request(
            "carry_over_page",
            {
                "workspace_id": self.session.workspace_id,
                "session_id": self.session.session_id,
                "page_id": page_id,
                "cycles": cycles,
            },
        )

    async def _wait_for_load_state(
        self,
        page_id: str,
        state: str,
        timeout: float | None,
    ) -> dict[str, Any]:
        """Request a backend-native wait for a page lifecycle state."""
        params: dict[str, Any] = {
            "workspace_id": self.session.workspace_id,
            "session_id": self.session.session_id,
            "page_id": page_id,
            "state": state,
        }
        if timeout is not None:
            params["timeout"] = timeout
        return dict(await self._request("wait_for_load_state", params))

    async def _screenshot(self, page_id: str) -> dict[str, str]:
        """Capture one page through its selected provider."""
        raw = await self._request(
            "screenshot",
            {
                "workspace_id": self.session.workspace_id,
                "session_id": self.session.session_id,
                "page_id": page_id,
            },
        )
        return {"path": str(raw["path"])}

    async def _input(
        self,
        page_id: str,
        kind: str,
        action: str,
        **params: Any,
    ) -> dict[str, Any]:
        return dict(
            await self._request(
                "input",
                {
                    "workspace_id": self.session.workspace_id,
                    "session_id": self.session.session_id,
                    "page_id": page_id,
                    "kind": kind,
                    "action": action,
                    **params,
                },
            ),
        )
