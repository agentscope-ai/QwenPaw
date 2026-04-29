# -*- coding: utf-8 -*-
"""GitHub Copilot OAuth device-code flow + token exchange service.

This module provides :class:`CopilotOAuthService`, an asyncio-driven
manager that owns the lifecycle of a single GitHub Copilot OAuth
session:

1. Initiate the GitHub device-code flow (``start_device_flow``).
2. Poll GitHub in the background until the user authorizes the
   application or the device code expires.
3. Exchange the long-lived OAuth access token for a short-lived
   Copilot API token via ``copilot_internal/v2/token``.
4. Cache and auto-refresh the Copilot API token before it expires.
5. Persist only the *long-lived* OAuth access token to disk via
   :class:`CopilotTokenStore` so the session survives restarts.

A process-global registry (:func:`get_oauth_service`) returns a single
service instance per ``provider_id`` so the FastAPI routes and the
provider implementation share state.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx

from qwenpaw.__version__ import __version__ as _QWENPAW_VERSION

from .copilot_token_store import CopilotTokenStore
from .models import CopilotApiToken, DeviceCodeStart, OAuthStatus

logger = logging.getLogger(__name__)


# Public, well-known client_id used by all official editor integrations
# (VS Code, JetBrains, Neovim, ...).  Not a secret.
DEFAULT_CLIENT_ID = "Iv1.b507a08c87ecfe98"

GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"  # noqa: S105
GITHUB_USER_URL = "https://api.github.com/user"
COPILOT_TOKEN_URL = (
    "https://api.github.com/copilot_internal/v2/token"  # noqa: S105, E501
)

# Headers the GitHub Copilot API expects from "editor-like" callers.
# Mismatched values can cause 401/403 responses.  The values are
# deliberately VS Code-style for compatibility, and are configurable
# via :class:`CopilotOAuthService` constructor / provider ``meta`` dict.
DEFAULT_EDITOR_VERSION = "vscode/1.95.0"
DEFAULT_PLUGIN_VERSION = f"qwenpaw/{_QWENPAW_VERSION}"
DEFAULT_USER_AGENT = f"QwenPaw/{_QWENPAW_VERSION}"

GRANT_TYPE_DEVICE_CODE = "urn:ietf:params:oauth:grant-type:device_code"


class CopilotOAuthError(Exception):
    """Raised when the OAuth flow fails irrecoverably."""


_StatusCallback = Callable[[OAuthStatus], Awaitable[None] | None]


class CopilotOAuthService:
    """Manage the GitHub Copilot OAuth lifecycle for one provider."""

    def __init__(
        self,
        provider_id: str = "github-copilot",
        *,
        client_id: str = DEFAULT_CLIENT_ID,
        editor_version: str = DEFAULT_EDITOR_VERSION,
        plugin_version: str = DEFAULT_PLUGIN_VERSION,
        user_agent: str = DEFAULT_USER_AGENT,
        token_store: Optional[CopilotTokenStore] = None,
        http_client_factory: Optional[Callable[[], httpx.AsyncClient]] = None,
        token_refresh_buffer: int = 300,
    ) -> None:
        self.provider_id = provider_id
        self.client_id = client_id
        self.editor_version = editor_version
        self.plugin_version = plugin_version
        self.user_agent = user_agent
        self.token_store = token_store or CopilotTokenStore(provider_id)
        self._http_client_factory = http_client_factory or (
            lambda: httpx.AsyncClient(timeout=30.0)
        )
        self._token_refresh_buffer = token_refresh_buffer

        # State (protected by a single lock to avoid races between
        # concurrent OAuth and request flows)
        self._lock = asyncio.Lock()
        self._oauth_access_token: Optional[str] = None
        self._github_login: str = ""
        self._copilot_token: Optional[CopilotApiToken] = None

        # Lazily-created shared httpx.AsyncClient reused by the
        # provider for chat / discovery requests.  Owning a single
        # long-lived client avoids leaking connections / file
        # descriptors across repeated check_connection / fetch_models
        # / chat invocations (which would otherwise each construct
        # and forget their own AsyncClient).
        self._shared_http_client: Optional[httpx.AsyncClient] = None
        self._shared_http_client_lock = threading.Lock()

        # Pending device-code session
        self._pending_device_code: Optional[str] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._refresh_task: Optional[asyncio.Task] = None
        self._last_status: OAuthStatus = OAuthStatus(
            status="not_started",
            message="Not authenticated",
        )

        # Optional notify hook (used by FastAPI routes to push final
        # state back to the provider for persistence)
        self._on_token_persisted: Optional[
            Callable[[str, str], Awaitable[None] | None]
        ] = None
        self._on_logout: Optional[Callable[[], Awaitable[None] | None]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_authenticated(self) -> bool:
        """True when an OAuth access token is held in memory."""
        return bool(self._oauth_access_token)

    @property
    def github_login(self) -> str:
        return self._github_login

    @property
    def oauth_access_token(self) -> Optional[str]:
        return self._oauth_access_token

    def set_on_token_persisted(
        self,
        callback: Optional[Callable[[str, str], Awaitable[None] | None]],
    ) -> None:
        """Register a hook invoked after a successful authorization.

        Called with ``(oauth_access_token, github_login)``.  Used by the
        ProviderManager glue to persist the token alongside provider
        config.
        """
        self._on_token_persisted = callback

    def set_on_logout(
        self,
        callback: Optional[Callable[[], Awaitable[None] | None]],
    ) -> None:
        self._on_logout = callback

    async def get_status(self) -> OAuthStatus:
        """Return the current OAuth status."""
        async with self._lock:
            base = self._last_status
            return OAuthStatus(
                status=base.status,
                message=base.message,
                is_authenticated=self.is_authenticated,
                login=self._github_login,
            )

    async def get_copilot_token(
        self,
        *,
        force_refresh: bool = False,
    ) -> str:
        """Return a fresh short-lived Copilot API token.

        Performs a synchronous refresh when the cached token is missing
        or about to expire.  Raises :class:`CopilotOAuthError` when the
        provider is not authenticated.
        """
        if not self._oauth_access_token:
            raise CopilotOAuthError(
                "GitHub Copilot is not authenticated; "
                "complete the device-code flow first.",
            )
        token = self._copilot_token
        if (
            not force_refresh
            and token is not None
            and not token.is_expired(self._token_refresh_buffer)
        ):
            return token.token
        await self._refresh_copilot_token()
        if self._copilot_token is None:
            raise CopilotOAuthError(
                "Failed to obtain Copilot API token after refresh.",
            )
        return self._copilot_token.token

    async def get_copilot_endpoint(self) -> str:
        """Return the Copilot REST endpoint base URL."""
        if self._copilot_token is None:
            await self.get_copilot_token()
        token = self._copilot_token
        return (
            token.api_endpoint
            if token is not None
            else "https://api.githubcopilot.com"
        )

    async def restore_from_disk(self) -> bool:
        """Load a persisted OAuth token, if any, and schedule a refresh.

        Returns True when a token was restored.
        """
        payload = self.token_store.load()
        if not payload:
            return False
        async with self._lock:
            self._oauth_access_token = payload["oauth_access_token"]
            self._github_login = payload.get("github_login", "")
            self._last_status = OAuthStatus(
                status="authorized",
                message="Restored from persisted token",
                is_authenticated=True,
                login=self._github_login,
            )
        # Kick off a background Copilot-token fetch; do not block.
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._refresh_copilot_token_safe())
        except RuntimeError:
            # No running loop (e.g. during sync ProviderManager init).
            # The token will be obtained lazily on first request via
            # get_copilot_token().
            pass
        logger.info(
            "Restored GitHub Copilot OAuth session (login=%s)",
            self._github_login or "<unknown>",
        )
        return True

    async def start_device_flow(self) -> DeviceCodeStart:
        """Initiate GitHub's device-code flow and start background polling.

        Cancels any previously pending device-code session.
        """
        await self._cancel_polling()
        async with self._lock:
            self._last_status = OAuthStatus(
                status="pending",
                message="Requesting device code from GitHub",
            )

        async with self._http_client_factory() as client:
            # GitHub's OAuth device-code endpoints expect
            # ``application/x-www-form-urlencoded`` per RFC 8628.
            # Sending JSON works today but is not spec-compliant and
            # has been observed to break under stricter API gateways.
            resp = await client.post(
                GITHUB_DEVICE_CODE_URL,
                headers={
                    "Accept": "application/json",
                    "User-Agent": self.user_agent,
                    "Editor-Version": self.editor_version,
                    "Editor-Plugin-Version": self.plugin_version,
                },
                data={"client_id": self.client_id, "scope": "read:user"},
            )
            resp.raise_for_status()
            data = resp.json()

        device_code = str(data.get("device_code") or "")
        user_code = str(data.get("user_code") or "")
        verification_uri = str(
            data.get("verification_uri") or "https://github.com/login/device",
        )
        expires_in = int(data.get("expires_in") or 900)
        interval = int(data.get("interval") or 5)

        if not device_code or not user_code:
            raise CopilotOAuthError(
                "GitHub device-code response was missing required fields.",
            )

        async with self._lock:
            self._pending_device_code = device_code
            self._last_status = OAuthStatus(
                status="pending",
                message="Waiting for user authorization",
            )

        # Background polling task
        self._poll_task = asyncio.create_task(
            self._poll_loop(device_code, interval, expires_in),
            name=f"copilot-oauth-poll[{self.provider_id}]",
        )

        logger.info(
            "GitHub Copilot device-code flow started "
            "(user_code=%s, verification_uri=%s, expires_in=%ss)",
            user_code,
            verification_uri,
            expires_in,
        )

        return DeviceCodeStart(
            user_code=user_code,
            verification_uri=verification_uri,
            expires_in=expires_in,
            interval=interval,
        )

    async def logout(self) -> None:
        """Clear all tokens, cancel background tasks, and delete persisted
        credentials."""
        await self._cancel_polling()
        await self._cancel_refresh()
        async with self._lock:
            self._oauth_access_token = None
            self._github_login = ""
            self._copilot_token = None
            self._pending_device_code = None
            self._last_status = OAuthStatus(
                status="not_started",
                message="Logged out",
            )
        # Drop the shared http client so the next sign-in gets a fresh
        # one bound to the new credentials, and to release sockets.
        await self.aclose_http_client()
        self.token_store.delete()
        if self._on_logout is not None:
            try:
                result = self._on_logout()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "on_logout callback failed for provider %s",
                    self.provider_id,
                    exc_info=True,
                )
        logger.info("GitHub Copilot OAuth session cleared")

    # ------------------------------------------------------------------
    # Pre-publish session seeding (used by the provider factory to
    # rehydrate a freshly-created service from on-disk state without
    # taking the asyncio lock — safe because callers invoke this
    # before the service is published in the global registry).
    # ------------------------------------------------------------------

    def seed_session(
        self,
        oauth_access_token: str,
        github_login: str = "",
    ) -> None:
        """Synchronously seed a new (unpublished) service with a token.

        Intended for use by ``get_oauth_service``'s factory closure
        before the service object is exposed to other coroutines.
        Does not acquire :attr:`_lock`; callers must guarantee no other
        coroutine has a reference to this instance yet.
        """
        if not oauth_access_token:
            return
        self._oauth_access_token = oauth_access_token
        self._github_login = github_login or ""
        self._last_status = OAuthStatus(
            status="authorized",
            message="Restored from persisted token",
            is_authenticated=True,
            login=self._github_login,
        )

    # ------------------------------------------------------------------
    # Shared httpx.AsyncClient lifecycle
    # ------------------------------------------------------------------

    def get_or_create_http_client(self) -> httpx.AsyncClient:
        """Return a shared :class:`httpx.AsyncClient` for chat / discovery.

        The client carries :class:`CopilotAuth` and the chat headers so
        every request uses a fresh OAuth bearer.  It is created lazily
        and reused for the lifetime of this service to avoid leaking
        sockets/file-descriptors across repeated calls.  Closed via
        :meth:`aclose_http_client` (e.g. on logout).
        """
        # Lazy import to avoid a circular dependency between
        # ``oauth.copilot_oauth_service`` and ``oauth.copilot_auth``.
        from .copilot_auth import CopilotAuth

        with self._shared_http_client_lock:
            client = self._shared_http_client
            if client is not None and not client.is_closed:
                return client
            client = httpx.AsyncClient(
                auth=CopilotAuth(self),
                headers=self.chat_headers(),
                timeout=httpx.Timeout(60.0, read=300.0),
            )
            self._shared_http_client = client
            return client

    async def aclose_http_client(self) -> None:
        """Close and clear the shared :class:`httpx.AsyncClient`."""
        with self._shared_http_client_lock:
            client = self._shared_http_client
            self._shared_http_client = None
        if client is not None and not client.is_closed:
            try:
                await client.aclose()
            except Exception:  # pylint: disable=broad-except
                logger.debug(
                    "Error while closing shared Copilot http client",
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Headers used by chat / api calls
    # ------------------------------------------------------------------

    def chat_headers(
        self,
        *,
        integration_id: str = "vscode-chat",
        intent: str = "conversation-panel",
    ) -> Dict[str, str]:
        """Return the headers the Copilot chat API expects.

        These are merged into the AsyncOpenAI client's ``default_headers``
        by :class:`GitHubCopilotProvider`.  The actual Bearer token is
        injected per-request by :class:`CopilotAuth`.
        """
        return {
            "Editor-Version": self.editor_version,
            "Editor-Plugin-Version": self.plugin_version,
            "Copilot-Integration-Id": integration_id,
            "Openai-Intent": intent,
            "X-Github-Api-Version": "2025-04-01",
            "User-Agent": self.user_agent,
        }

    # ------------------------------------------------------------------
    # Internal: device-code polling
    # ------------------------------------------------------------------

    async def _poll_loop(
        self,
        device_code: str,
        interval: int,
        expires_in: int,
    ) -> None:
        """Poll GitHub until the user authorizes or the code expires."""
        deadline = time.time() + max(60, expires_in)
        current_interval = max(1, interval)

        try:
            while time.time() < deadline:
                await asyncio.sleep(current_interval)
                try:
                    poll_result = await self._poll_once(device_code)
                except httpx.HTTPError as exc:
                    logger.warning(
                        "Transient error while polling GitHub OAuth: %s",
                        exc,
                    )
                    continue

                if poll_result == "pending":
                    continue
                if poll_result == "slow_down":
                    current_interval += 5
                    logger.info(
                        "GitHub requested slower polling; new interval=%ss",
                        current_interval,
                    )
                    continue
                if poll_result == "authorized":
                    return
                # Any other return is a terminal failure (already logged).
                return
            # Loop exited because device code expired.
            async with self._lock:
                self._pending_device_code = None
                self._last_status = OAuthStatus(
                    status="error",
                    message="Device code expired before user authorized",
                )
            logger.warning(
                "GitHub device-code expired before user authorization",
            )
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "Unexpected error in GitHub Copilot OAuth polling loop",
            )
            async with self._lock:
                self._pending_device_code = None
                self._last_status = OAuthStatus(
                    status="error",
                    message="Polling failed unexpectedly",
                )

    async def _poll_once(self, device_code: str) -> str:
        """Single poll attempt.  Returns one of:
        ``'pending'``, ``'slow_down'``, ``'authorized'``, ``'error'``.
        """
        async with self._http_client_factory() as client:
            # Form-encoded per RFC 8628; see comment in start_device_flow.
            resp = await client.post(
                GITHUB_TOKEN_URL,
                headers={
                    "Accept": "application/json",
                    "User-Agent": self.user_agent,
                    "Editor-Version": self.editor_version,
                    "Editor-Plugin-Version": self.plugin_version,
                },
                data={
                    "client_id": self.client_id,
                    "device_code": device_code,
                    "grant_type": GRANT_TYPE_DEVICE_CODE,
                },
            )
            data: Dict[str, Any] = resp.json() if resp.content else {}

        if "error" in data:
            err = str(data.get("error") or "")
            if err == "authorization_pending":
                return "pending"
            if err == "slow_down":
                return "slow_down"
            # expired_token, access_denied, ...
            async with self._lock:
                self._pending_device_code = None
                self._last_status = OAuthStatus(
                    status="error",
                    message=f"GitHub OAuth error: {err}",
                )
            logger.warning("GitHub device-code flow aborted: %s", err)
            return "error"

        access_token = str(data.get("access_token") or "")
        if not access_token:
            return "pending"

        # Success — fetch the user's login + exchange for a Copilot token.
        async with self._lock:
            self._oauth_access_token = access_token
            self._pending_device_code = None
            self._last_status = OAuthStatus(
                status="authorized",
                message="Authorization succeeded",
                is_authenticated=True,
            )

        try:
            self._github_login = await self._fetch_github_login(access_token)
        except Exception:  # pylint: disable=broad-except
            logger.debug(
                "Failed to fetch GitHub user login; continuing without it.",
                exc_info=True,
            )

        # Persist before refreshing the Copilot token so a refresh failure
        # doesn't lose the OAuth credential.
        self.token_store.save(access_token, self._github_login)
        if self._on_token_persisted is not None:
            try:
                result = self._on_token_persisted(
                    access_token,
                    self._github_login,
                )
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "on_token_persisted callback failed for %s",
                    self.provider_id,
                    exc_info=True,
                )

        await self._refresh_copilot_token_safe()
        return "authorized"

    async def _fetch_github_login(self, access_token: str) -> str:
        async with self._http_client_factory() as client:
            resp = await client.get(
                GITHUB_USER_URL,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"token {access_token}",
                    "User-Agent": self.user_agent,
                },
            )
            if resp.status_code != 200:
                return ""
            data = resp.json()
            return str(data.get("login") or "")

    # ------------------------------------------------------------------
    # Internal: Copilot API token exchange and refresh scheduling
    # ------------------------------------------------------------------

    async def _refresh_copilot_token_safe(self) -> None:
        """Best-effort refresh that swallows network errors."""
        try:
            await self._refresh_copilot_token()
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "Failed to refresh Copilot API token; "
                "will retry on next request",
                exc_info=True,
            )

    async def _refresh_copilot_token(self) -> None:
        """Exchange the OAuth access token for a fresh Copilot API token."""
        access_token = self._oauth_access_token
        if not access_token:
            raise CopilotOAuthError(
                "Cannot refresh Copilot token without an OAuth access token.",
            )
        async with self._http_client_factory() as client:
            resp = await client.get(
                COPILOT_TOKEN_URL,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"token {access_token}",
                    "User-Agent": self.user_agent,
                    "Editor-Version": self.editor_version,
                    "Editor-Plugin-Version": self.plugin_version,
                },
            )
            if resp.status_code == 401:
                # The OAuth token has been revoked — clear everything.
                logger.warning(
                    "GitHub Copilot rejected the OAuth token (401); "
                    "logging out so the user can re-authenticate.",
                )
                await self.logout()
                raise CopilotOAuthError(
                    "GitHub revoked the OAuth token. Please sign in again.",
                )
            resp.raise_for_status()
            data = resp.json() or {}

        token = str(data.get("token") or "")
        expires_at = int(data.get("expires_at") or 0)
        refresh_in = int(data.get("refresh_in") or 0)
        endpoints = data.get("endpoints") or {}
        api_endpoint = str(
            endpoints.get("api") or "https://api.githubcopilot.com",
        )
        chat_enabled = data.get("chat_enabled")
        if chat_enabled is not None:
            chat_enabled = bool(chat_enabled)
        sku = str(data.get("sku") or "")

        if not token:
            raise CopilotOAuthError(
                "Copilot token response did not contain a token field.",
            )

        new_token = CopilotApiToken(
            token=token,
            expires_at=expires_at,
            refresh_in=refresh_in,
            api_endpoint=api_endpoint,
            chat_enabled=chat_enabled,
            sku=sku,
        )
        async with self._lock:
            self._copilot_token = new_token
        self._schedule_refresh(new_token)
        logger.info(
            "Refreshed Copilot API token (sku=%s, endpoint=%s, "
            "expires_at=%s, refresh_in=%ss)",
            sku or "<unknown>",
            api_endpoint,
            expires_at,
            refresh_in,
        )

    def _schedule_refresh(self, token: CopilotApiToken) -> None:
        """(Re)schedule the background refresh task."""
        if self._refresh_task is not None and not self._refresh_task.done():
            self._refresh_task.cancel()
        delay = self._compute_refresh_delay(token)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._refresh_task = loop.create_task(
            self._delayed_refresh(delay),
            name=f"copilot-oauth-refresh[{self.provider_id}]",
        )

    def _compute_refresh_delay(self, token: CopilotApiToken) -> float:
        if token.refresh_in > 0:
            return float(max(30, token.refresh_in))
        if token.expires_at > 0:
            now = int(time.time())
            return float(
                max(
                    30,
                    token.expires_at - now - self._token_refresh_buffer,
                ),
            )
        return 600.0

    async def _delayed_refresh(self, delay: float) -> None:
        await asyncio.sleep(delay)
        await self._refresh_copilot_token_safe()

    async def _cancel_polling(self) -> None:
        task = self._poll_task
        self._poll_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _cancel_refresh(self) -> None:
        task = self._refresh_task
        self._refresh_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Process-global registry (one service per provider_id)
# ---------------------------------------------------------------------------

_services: Dict[str, CopilotOAuthService] = {}
_services_lock = threading.Lock()


def get_oauth_service(
    provider_id: str = "github-copilot",
    *,
    factory: Optional[Callable[[], CopilotOAuthService]] = None,
) -> CopilotOAuthService:
    """Return the (singleton) :class:`CopilotOAuthService` for *provider_id*.

    Thread-safe: a :class:`threading.Lock` guards the check-then-set so
    two concurrent callers cannot create competing service instances
    for the same ``provider_id``.  When *factory* is provided it is
    used to construct (and seed) the service on first access.
    """
    service = _services.get(provider_id)
    if service is not None:
        return service
    with _services_lock:
        # Re-check under the lock — another caller may have raced us.
        service = _services.get(provider_id)
        if service is not None:
            return service
        service = factory() if factory else CopilotOAuthService(provider_id)
        _services[provider_id] = service
        return service


def reset_oauth_services_for_test() -> None:
    """Test helper: clear the service registry."""
    _services.clear()
