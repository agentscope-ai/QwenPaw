# -*- coding: utf-8 -*-
"""NocoBase auth plugin entry point."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("qwenpaw").getChild("plugin.nocobase-auth")

_PLUGIN_DIR = Path(__file__).parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))


class NocoBaseAuthPlugin:
    """Registers NocoBase auth capabilities via QwenPaw plugin hooks."""

    def __init__(self):
        self._checker: Optional[
            Callable[[str, str, dict], Optional[str]]
        ] = None
        self._identity_resolver: Optional[Callable[..., Any]] = None
        self._sync_engine: Optional[Any] = None

    def register(self, api: Any) -> None:
        """Called by PluginLoader when the plugin is loaded."""
        logger.info("NocoBaseAuthPlugin.register() called")

        from .routers import build_router

        api.register_http_router(build_router(), prefix="/nocobase-auth")

        api.register_startup_hook(
            hook_name="nocobase_auth_init",
            callback=self._on_startup,
            priority=60,
        )
        api.register_uninstall_hook(
            hook_name="nocobase_auth_cleanup",
            callback=self._on_uninstall,
        )
        logger.info("NocoBase auth plugin hooks registered")

    async def _on_startup(self) -> None:
        """Initialize the sync engine and register the channel gate checker."""
        from .channel_gate import build_checker
        from .sync_engine import SyncEngine

        logger.info("NocoBase auth plugin starting up...")

        self._sync_engine = SyncEngine()
        await self._sync_engine.start()

        engine = self._sync_engine
        self._checker = build_checker(
            engine.store,
            is_enabled=lambda: bool(engine.config and engine.config.enabled),
        )
        try:
            from qwenpaw.app.channels.base import BaseChannel

            BaseChannel.register_external_acl_checker(self._checker)
            logger.info("NocoBase auth channel gate checker registered")
        except Exception as exc:
            logger.error("Failed to register channel gate checker: %s", exc)

        try:
            from qwenpaw.app.auth import (
                register_external_identity_resolver,
            )

            from .identity_cache import TokenIdentityCache
            from .identity_resolver import build_identity_resolver

            cache = TokenIdentityCache()
            self._identity_resolver = build_identity_resolver(
                self._sync_engine,
                cache,
            )
            register_external_identity_resolver(self._identity_resolver)
            logger.info("NocoBase auth identity resolver registered")
        except Exception as exc:
            logger.error(
                "Failed to register identity resolver: %s",
                exc,
            )

    async def _on_uninstall(
        self,
        plugin_id: str,  # pylint: disable=unused-argument
        delete_files: bool = False,  # pylint: disable=unused-argument
    ) -> None:
        """Clean up when the plugin is uninstalled."""
        logger.info("NocoBase auth plugin uninstalling...")
        if self._checker is not None:
            try:
                from qwenpaw.app.channels.base import BaseChannel

                BaseChannel.unregister_external_acl_checker(self._checker)
                logger.info("NocoBase auth channel gate checker removed")
            except Exception as exc:
                logger.error(
                    "Failed to unregister channel gate checker: %s",
                    exc,
                )
            self._checker = None

        if self._identity_resolver is not None:
            try:
                from qwenpaw.app.auth import (
                    unregister_external_identity_resolver,
                )

                unregister_external_identity_resolver(
                    self._identity_resolver,
                )
                logger.info("NocoBase auth identity resolver removed")
            except Exception as exc:
                logger.error(
                    "Failed to unregister identity resolver: %s",
                    exc,
                )
            self._identity_resolver = None

        if self._sync_engine is not None:
            from .sync_engine import set_sync_engine

            await self._sync_engine.stop()
            self._sync_engine = None
            set_sync_engine(None)
            logger.info("NocoBase auth sync engine cleared")


plugin = NocoBaseAuthPlugin()
