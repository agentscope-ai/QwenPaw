# -*- coding: utf-8 -*-
"""Authentication module: external identity resolution + FastAPI middleware.

Login is disabled by default and only enabled when the environment
variable ``QWENPAW_AUTH_ENABLED`` is set to a truthy value (``true``,
``1``, ``yes``).

QwenPaw does not own a user system of its own.  When auth is enabled an
external identity provider (e.g. the NocoBase SSO plugin) is the sole
authority: it authenticates login credentials and verifies the tokens it
issues.  Plugins register resolvers/authenticators through the registries
below; the core stays ignorant of any specific provider.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ..constant import EnvVarLoader

logger = logging.getLogger(__name__)

# Paths that do NOT require authentication
_PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/api/auth/login",
        "/api/auth/status",
        "/api/version",
        "/api/settings/language",
        "/api/settings/upload-limit",
        "/api/frontend_plugin",
    },
)

# Prefixes that do NOT require authentication (static assets)
# /api/frontend_plugin/ is safe: only read-only GET handlers are registered
# under that prefix (list + static file serving).  All write operations
# remain under /api/plugins/ which requires authentication.
_PUBLIC_PREFIXES: tuple[str, ...] = (
    "/assets/",
    "/logo.png",
    "/qwenpaw-symbol.svg",
    "/api/frontend_plugin/",
)


# ---------------------------------------------------------------------------
# External identity resolvers (e.g. NocoBase SSO plugin)
# ---------------------------------------------------------------------------
@dataclass
class ResolvedIdentity:
    """Result of one external identity resolution.

    ``sender_id`` is the stable identity string (per ``user_id_field``) used
    by channel ACL and token-usage attribution. ``roles`` are the caller's
    NocoBase role names, resolved live so the console gate can evaluate the
    role→channel map without any local user mirror.
    """

    sender_id: str
    roles: list[str] = field(default_factory=list)


# A resolver maps an incoming request to a ResolvedIdentity (the sender_id
# used by channel ACL) or None when it has no opinion. Mirrors the
# BaseChannel._external_acl_checkers pattern: the core stays ignorant of any
# specific identity provider; plugins fill this in.
IdentityResolver = Callable[
    ["Request"],
    Awaitable[Optional["ResolvedIdentity"]],
]
_external_identity_resolvers: list[IdentityResolver] = []

# A login authenticator maps a username/password pair to an identity string
# or None when the credentials are invalid / the provider has no opinion.
# It may raise ExternalLoginDenied when the credentials are valid but the
# account is not allowed in (e.g. rejected by the console ACL) so the login
# route can answer 403 instead of the generic 401.
LoginAuthenticator = Callable[
    [str, str],
    Awaitable[Optional["ExternalLogin | str"]],
]
_external_login_authenticators: list[LoginAuthenticator] = []


class ExternalLoginDenied(Exception):
    """Valid credentials, but the account is denied access by an ACL."""

    def __init__(
        self,
        detail: str = "This account is not allowed to access the console",
    ):
        super().__init__(detail)
        self.detail = detail


@dataclass
class ExternalLogin:
    """Result of a successful external (e.g. NocoBase) login.

    ``token`` is the provider-issued access token.  When present, the login
    route returns it verbatim so the provider owns token issuing *and*
    verification end-to-end; when absent, the route falls back to minting a
    local QwenPaw token (legacy plugin behavior).
    """

    identity: str
    token: Optional[str] = None


def register_external_identity_resolver(resolver: IdentityResolver) -> None:
    """Register a resolver consulted when no valid QwenPaw token is present."""
    if resolver not in _external_identity_resolvers:
        _external_identity_resolvers.append(resolver)


def unregister_external_identity_resolver(
    resolver: IdentityResolver,
) -> None:
    """Remove a previously registered resolver (no-op if absent)."""
    try:
        _external_identity_resolvers.remove(resolver)
    except ValueError:
        pass


def has_external_identity_resolvers() -> bool:
    """Return True if at least one external identity resolver is registered."""
    return bool(_external_identity_resolvers)


def register_external_login_authenticator(
    authenticator: LoginAuthenticator,
) -> None:
    """Register a username/password authenticator provided by a plugin."""
    if authenticator not in _external_login_authenticators:
        _external_login_authenticators.append(authenticator)


def unregister_external_login_authenticator(
    authenticator: LoginAuthenticator,
) -> None:
    """Remove a previously registered login authenticator."""
    try:
        _external_login_authenticators.remove(authenticator)
    except ValueError:
        pass


def has_external_login_authenticators() -> bool:
    """Return True if a plugin can authenticate login credentials."""
    return bool(_external_login_authenticators)


async def authenticate_external_login(
    username: str,
    password: str,
) -> Optional[ExternalLogin]:
    """Return the first login accepted by an external provider.

    Legacy authenticators return a bare identity string; it is normalized
    to :class:`ExternalLogin` without a provider token.

    Raises:
        ExternalLoginDenied: an authenticator verified the credentials but
            the account is denied access; the login route maps this to 403.
    """
    for authenticator in _external_login_authenticators:
        try:
            result = await authenticator(username, password)
        except ExternalLoginDenied:
            raise
        except Exception:
            logger.exception(
                "external login authenticator %s failed",
                getattr(authenticator, "__qualname__", repr(authenticator)),
            )
            continue
        if isinstance(result, str):
            if result:
                return ExternalLogin(identity=result)
        elif result is not None and result.identity:
            return result
    return None


async def _resolve_external_identity(
    request: Request,
) -> Optional[ResolvedIdentity]:
    """Return the first identity from registered resolvers.

    A resolver that raises is logged and skipped so one bad plugin never
    fails the request pipeline.
    """
    for resolver in _external_identity_resolvers:
        try:
            identity = await resolver(request)
        except Exception:
            logger.exception(
                "external identity resolver %s failed",
                getattr(resolver, "__qualname__", repr(resolver)),
            )
            continue
        if identity and identity.sender_id:
            return identity
    return None


def is_auth_enabled() -> bool:
    """Check whether authentication is enabled via environment variable.

    Returns ``True`` when ``QWENPAW_AUTH_ENABLED`` is set to a truthy
    value (``true``, ``1``, ``yes``).  When enabled, an external identity
    provider (e.g. NocoBase) authenticates users and verifies tokens.
    """
    env_flag = EnvVarLoader.get_str("QWENPAW_AUTH_ENABLED", "").strip().lower()
    return env_flag in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# FastAPI middleware
# ---------------------------------------------------------------------------


def _resolve_client_ip(request: Request) -> str:
    """Return the real client IP, respecting reverse-proxy headers."""
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip", "")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else ""


# Make this function available at module level so it can be
# imported from routers
resolve_client_ip = _resolve_client_ip

# Public alias so routers can resolve an identity via registered external
# resolvers (e.g. verifying a NocoBase-issued Bearer token).
resolve_external_identity = _resolve_external_identity


# Cached config for hot-path auth checks (avoids disk read per request)
_auth_config_cache: tuple = (0, None)  # (mtime_ns, config)


def _get_config_cached():
    """Return config with mtime-based cache (stat is ~1us vs read ~1ms)."""
    global _auth_config_cache  # noqa: PLW0603
    from ..config import load_config
    from ..config.utils import get_config_path

    config_path = get_config_path()
    try:
        mtime_ns = config_path.stat().st_mtime_ns
    except OSError:
        mtime_ns = 0
    if mtime_ns != _auth_config_cache[0] or _auth_config_cache[1] is None:
        _auth_config_cache = (mtime_ns, load_config())
    return _auth_config_cache[1]


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that checks Bearer token on protected routes."""

    async def dispatch(
        self,
        request: Request,
        call_next,
    ) -> Response:
        """Resolve identity via external providers on protected API routes."""
        if self._should_skip_auth(request):
            return await call_next(request)

        identity = await _resolve_external_identity(request)
        if identity is None:
            token = self._extract_token(request)
            detail = (
                "Invalid or expired token" if token else "Not authenticated"
            )
            return Response(
                content=json.dumps({"detail": detail}),
                status_code=401,
                media_type="application/json",
            )

        request.state.user = identity.sender_id
        request.state.user_roles = identity.roles
        return await call_next(request)

    @staticmethod
    def _should_skip_auth(request: Request) -> bool:
        """Return ``True`` when the request does not require auth."""
        if not is_auth_enabled():
            return True

        path = request.url.path

        if request.method == "OPTIONS":
            return True

        if path in _PUBLIC_PATHS or any(
            path.startswith(p) for p in _PUBLIC_PREFIXES
        ):
            return True

        # Only protect /api/ routes.
        if not path.startswith("/api/"):
            return True

        # Explicit escape hatch (default empty): loopback/LAN hosts.
        client_host = resolve_client_ip(request)
        config = _get_config_cached()
        allowed_hosts = config.security.allow_no_auth_hosts
        if client_host in allowed_hosts:
            return True

        # Fail closed: auth is on and no external provider is registered
        # (plugin missing / failed to load). Deny rather than fall open;
        # dispatch() then returns 401 because _resolve_external_identity
        # yields None.
        if not has_external_identity_resolvers():
            logger.warning(
                "Auth enabled but no external identity resolver registered; "
                "denying %s (fail-closed)",
                path,
            )
        return False

    @staticmethod
    def _extract_token(request: Request) -> Optional[str]:
        """Extract Bearer token from header or WebSocket query param."""
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        if "upgrade" in request.headers.get("connection", "").lower():
            return request.query_params.get("token")

        token = request.query_params.get("token")
        if token:
            return token
        return None
