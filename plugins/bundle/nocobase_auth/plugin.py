# -*- coding: utf-8 -*-
"""NocoBase auth plugin entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional

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
        self._login_authenticator: Optional[Callable[..., Any]] = None
        self._engine: Optional[Any] = None

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
        """Initialize the engine and register identity/login/gate hooks."""
        from .channel_gate import build_checker
        from .config import NocoBaseAuthConfig
        from .engine import NocoBaseEngine

        logger.info("NocoBase auth plugin starting up...")

        try:
            NocoBaseAuthConfig.seed_from_env()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "NocoBase auth: seeding config from env failed: %s", exc
            )

        self._engine = NocoBaseEngine()
        await self._engine.start()

        engine = self._engine
        self._checker = build_checker(
            get_config=lambda: engine.config,
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
                ExternalLogin,
                ExternalLoginDenied,
                register_external_identity_resolver,
                register_external_login_authenticator,
            )

            from .identity_cache import TokenIdentityCache
            from .identity_resolver import build_identity_resolver
            from .nocobase_client import NocoBaseClient

            cache = TokenIdentityCache()
            self._identity_resolver = build_identity_resolver(
                self._engine,
                cache,
            )
            register_external_identity_resolver(self._identity_resolver)
            logger.info("NocoBase auth identity resolver registered")

            checker = self._checker

            async def _login_with_console_acl(
                username: str,
                password: str,
            ) -> Optional[ExternalLogin]:
                # pylint: disable=protected-access
                # Same checker as the per-message channel gate, so login and
                # chat can never disagree. Resolve the user's roles live so
                # the role→channel policy applies at login too.
                result = await engine.authenticate_credentials(
                    username,
                    password,
                )
                if not result:
                    return None
                sender_id, nb_token = result
                roles: List[str] = []
                if nb_token:
                    try:
                        user = await engine.verify_user_token(nb_token)
                        if user:
                            roles = NocoBaseClient._extract_roles(user)
                    except Exception:  # noqa: BLE001
                        roles = []
                if (
                    checker is not None
                    and checker("console", sender_id, {"acl_roles": roles})
                    == "deny"
                ):
                    raise ExternalLoginDenied(
                        "This account is not allowed to access the console",
                    )
                # Pass the NocoBase-issued token through so NocoBase owns the
                # token system (issuing + verification) end-to-end.
                return ExternalLogin(identity=sender_id, token=nb_token)

            self._login_authenticator = _login_with_console_acl
            register_external_login_authenticator(
                self._login_authenticator,
            )
            logger.info("NocoBase auth login authenticator registered")
        except Exception as exc:
            logger.error(
                "Failed to register identity/login resolver: %s",
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

        if self._login_authenticator is not None:
            try:
                from qwenpaw.app.auth import (
                    unregister_external_login_authenticator,
                )

                unregister_external_login_authenticator(
                    self._login_authenticator,
                )
                logger.info("NocoBase auth login authenticator removed")
            except Exception as exc:
                logger.error(
                    "Failed to unregister login authenticator: %s",
                    exc,
                )
            self._login_authenticator = None

        if self._engine is not None:
            from .engine import set_engine

            await self._engine.stop()
            self._engine = None
            set_engine(None)
            logger.info("NocoBase auth engine cleared")


plugin = NocoBaseAuthPlugin()
