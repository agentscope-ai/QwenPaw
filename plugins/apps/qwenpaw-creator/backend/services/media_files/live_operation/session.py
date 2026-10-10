# -*- coding: utf-8 -*-
"""One Creator-owned browser session plus its recording channel.

The agent still drives QwenPaw's Browser SDK, but Creator constructs the
``Browser`` facade with an explicit recording link.  It never registers that
link with QwenPaw's process-wide browser runtime, so a recording cannot change
which provider an ordinary QwenPaw task resolves or intercept its operations.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_IDENTITIES = frozenset({"auto", "user", "avatar", "guest"})


class LiveSessionError(RuntimeError):
    """A live browser session could not be established or used."""


class LiveBrowserSession:
    """A connected browser plus the CDP attachment used for recording."""

    def __init__(self, browser: Any) -> None:
        self._browser = browser
        self._cdp_sessions: dict[str, Any] = {}

    @classmethod
    async def connect(
        cls,
        *,
        links: tuple[Any, ...],
        identity: str = "guest",
    ) -> "LiveBrowserSession":
        """Build an SDK browser from explicit Creator-owned links.

        Identity adjudication intentionally mirrors ``Engine.connect``.  The
        important difference is assembly: the selected link is passed straight
        to ``Engine`` rather than being inserted into, and rediscovered from,
        QwenPaw's shared runtime registry.
        """
        if identity not in _IDENTITIES:
            raise LiveSessionError(
                f"unsupported browser identity {identity!r}; expected one of "
                "auto, user, avatar, or guest",
            )

        from qwenpaw.config.utils import load_config
        from qwenpaw.browser import Browser
        from qwenpaw.browser.runtime.engine import Engine
        from qwenpaw.browser.runtime.identity import resolve_identity
        from qwenpaw.browser.runtime.launch_resolve import resolve_launch_env
        from qwenpaw.browser.runtime.ownership_adapter import build_session
        from qwenpaw.browser.sdk.contracts import Owner

        available: dict[str, bool] = {}
        by_variant: dict[str, Any] = {}
        for link in links:
            variant = str(getattr(link, "variant", ""))
            if not variant or variant in by_variant:
                continue
            by_variant[variant] = link
            try:
                available[variant] = bool(link.is_available())
            except Exception:  # noqa: BLE001 - provider probe boundary
                logger.debug(
                    "live-operation provider availability probe failed",
                    exc_info=True,
                )
                available[variant] = False

        config = load_config().browser
        resolution = resolve_identity(
            model_identity=identity,
            config_identity=config.identity,
            chrome_available=available.get("chrome", False),
            engine_backend=config.backend,
        )
        link = by_variant.get(resolution.variant)
        if link is None or not available.get(resolution.variant, False):
            if resolution.identity == "user":
                raise LiveSessionError(
                    "requested user browser is unavailable; connect the "
                    "Chrome extension, or record with avatar/guest identity",
                )
            raise LiveSessionError(
                "no available browser provider for Creator live operation "
                f"({resolution.variant})",
            )

        supported = frozenset(
            getattr(link, "supported_contexts", {"incognito", "profile"}),
        )
        if resolution.context not in supported:
            raise LiveSessionError(
                f"browser provider {resolution.variant} does not support "
                f"the {resolution.context!r} context required by "
                f"{resolution.identity!r} identity",
            )

        owner = Owner(
            workspace_id=uuid.uuid4().hex,
            session_id=uuid.uuid4().hex,
        )
        runtime_session = await build_session(
            link,
            context=resolution.context,
            owner=owner,
            variant=resolution.variant,
            identity=resolution.identity,
            launch=resolve_launch_env(config),
        )

        return cls(Browser(Engine(link=link, session=runtime_session)))

    @property
    def browser(self) -> Any:
        """The SDK facade handed to agent code verbatim."""
        return self._browser

    @property
    def control_link(self) -> Any:
        """The exact link selected when this browser engine connected."""
        # pylint: disable-next=protected-access
        return self._browser._engine.link  # noqa: SLF001

    async def close(self) -> None:
        for session in self._cdp_sessions.values():
            try:
                await session.detach()
            except Exception:  # noqa: BLE001 - teardown must not mask results
                logger.debug("cdp detach failed", exc_info=True)
        self._cdp_sessions.clear()
        try:
            # Call the owned Engine directly. ``Browser.close`` also clears
            # the current SDK execution context, which may belong to an
            # unrelated QwenPaw task when Creator is embedded in the host.
            # pylint: disable-next=protected-access
            await self._browser._engine.close()  # noqa: SLF001
        except Exception:  # noqa: BLE001 - the run's result already stands
            logger.debug("browser close failed", exc_info=True)

    async def cdp_session_for(self, page: Any) -> Any:
        """Return a filming channel for ``page``, creating it on first use.

        The channel is deliberately one-way: recording subscribes to frames
        and never issues an operation command, so what gets filmed is exactly
        what the agent did through the SDK.
        """
        page_id = str(getattr(page, "id", "") or "")
        if not page_id:
            raise LiveSessionError("cannot record a page without an id")
        existing = self._cdp_sessions.get(page_id)
        if existing is not None:
            return existing
        native = self._native_page(page_id)
        try:
            session = await native.context.new_cdp_session(native)
        except Exception as exc:  # noqa: BLE001 - surface an actionable cause
            raise LiveSessionError(
                "this browser backend cannot be filmed: "
                f"{type(exc).__name__}: {exc}",
            ) from exc
        self._cdp_sessions[page_id] = session
        return session

    def _native_page(self, page_id: str) -> Any:
        """Resolve the driver page behind one SDK page id.

        Filming needs the same page object the SDK is operating, which the
        control link owns. Reaching it here keeps the recording channel bound
        to the real session instead of opening a second browser that would
        show a different screen than the one being driven.
        """
        link = self.control_link
        provider = getattr(link, "inner", link)
        # pylint: disable-next=protected-access
        owner = self._browser._engine.session.owner  # noqa: SLF001
        resolver = getattr(provider, "_page", None)
        if resolver is None:
            raise LiveSessionError(
                "the active browser backend cannot produce video takes; "
                "use guest/avatar identity for Playwright recording, or "
                "capture screenshots with the current backend",
            )
        try:
            return resolver((owner.workspace_id, owner.session_id), page_id)
        except Exception as exc:  # noqa: BLE001 - stale page or closed session
            raise LiveSessionError(
                f"the page to record is unavailable: {exc}",
            ) from exc


def workspace_dir(root: Path, run_id: str) -> Path:
    """Return the scratch directory takes are assembled in for one run."""
    target = root / "live_operation" / run_id
    target.mkdir(parents=True, exist_ok=True)
    return target


__all__ = [
    "LiveBrowserSession",
    "LiveSessionError",
    "workspace_dir",
]
