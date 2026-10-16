# -*- coding: utf-8 -*-
"""Small, secret-safe asynchronous REST client for OpenViking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class OpenVikingError(RuntimeError):
    """Base error raised by the OpenViking REST client."""


class OpenVikingConfigurationError(OpenVikingError):
    """Authentication or permanent request configuration is invalid."""


class OpenVikingServiceError(OpenVikingError):
    """The remote service is temporarily unavailable or returned an error."""


def safe_openviking_exception_summary(
    error: BaseException | str,
    *,
    api_key: str = "",
) -> str:
    """Return a bounded diagnostic without the configured tenant key.

    Never surface a server response body. A remote endpoint can echo received
    headers, so even a short body is not a safe operational diagnostic.
    """
    summary = str(error).strip() or type(error).__name__
    if api_key:
        summary = summary.replace(api_key, "<redacted>")
    return summary[:300]


@dataclass(frozen=True)
class OpenVikingClientConfig:
    """Connection settings for an OpenViking HTTP server."""

    base_url: str
    api_key: str
    request_timeout: float = 10.0


@dataclass(frozen=True)
class OpenVikingIdentity:
    """Tenant namespace resolved from the configured OpenViking API key."""

    account_id: str
    user_id: str

    @property
    def namespace(self) -> str:
        """Return a stable label used in QwenPaw session derivation."""
        return f"{self.account_id}/{self.user_id}"


class OpenVikingClient:
    """Async REST client covering the initial OpenViking plugin surface."""

    def __init__(
        self,
        config: OpenVikingClientConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self._http = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            headers={
                "X-API-Key": config.api_key,
                "Content-Type": "application/json",
            },
            follow_redirects=False,
            timeout=config.request_timeout,
            transport=transport,
        )

    async def close(self) -> None:
        """Release the persistent HTTP connection pool."""
        await self._http.aclose()

    async def resolve_identity(self) -> OpenVikingIdentity:
        """Validate credentials and resolve their OpenViking namespace."""
        data = await self._request("GET", "/health", unwrap=False)
        if not isinstance(data, dict):
            raise OpenVikingServiceError(
                "OpenViking health response is invalid.",
            )
        auth_mode = str(data.get("auth_mode") or "")
        account_id = str(data.get("account_id") or "")
        user_id = str(data.get("user_id") or "")
        if auth_mode == "api_key" and (not account_id or not user_id):
            raise OpenVikingConfigurationError(
                "OpenViking rejected the configured API key.",
            )
        return OpenVikingIdentity(
            account_id=account_id or "default",
            user_id=user_id or "default",
        )

    async def ensure_session(
        self,
        session_id: str,
        *,
        auto_commit_policy: dict[str, int] | None,
    ) -> None:
        body: dict[str, Any] = {
            "session_id": session_id,
            "auto_commit_policy": auto_commit_policy,
        }
        await self._request(
            "POST",
            "/api/v1/sessions",
            json=body,
            allowed_statuses={409},
        )
        await self._request(
            "PATCH",
            f"/api/v1/sessions/{session_id}/config",
            json={"auto_commit_policy": auto_commit_policy},
        )

    async def add_messages(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> None:
        """Append a completed QwenPaw turn to an OpenViking session."""
        await self._request(
            "POST",
            f"/api/v1/sessions/{session_id}/messages/batch",
            json={"messages": messages},
        )

    async def commit(self, session_id: str) -> dict[str, Any]:
        """Archive the live session and enqueue memory extraction."""
        result = await self._request(
            "POST",
            f"/api/v1/sessions/{session_id}/commit",
            json={"keep_recent_count": 0},
        )
        return result if isinstance(result, dict) else {}

    async def search_context(
        self,
        *,
        query: str,
        session_id: str,
        max_results: int,
        token_budget: int,
    ) -> dict[str, Any]:
        """Return OpenViking's injection-ready, budgeted memory context."""
        result = await self._request(
            "POST",
            "/api/v1/search/search",
            json={
                "query": query,
                "context_type": "memory",
                "session_id": session_id,
                "limit": max_results,
                "mode": "context",
                "query_expansion": "off",
                "max_tokens": token_budget,
            },
        )
        return result if isinstance(result, dict) else {}

    async def search_memories(
        self,
        *,
        query: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """Search the authenticated user's long-term-memory namespace."""
        result = await self._request(
            "POST",
            "/api/v1/search/search",
            json={
                "query": query,
                "target_uri": "viking://~/memories",
                "context_type": "memory",
                "limit": max_results,
                "mode": "list",
            },
        )
        if not isinstance(result, dict):
            return []
        memories = result.get("memories")
        return memories if isinstance(memories, list) else []

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        unwrap: bool = True,
        allowed_statuses: set[int] | None = None,
    ) -> Any:
        allowed_statuses = allowed_statuses or set()
        try:
            response = await self._http.request(method, path, json=json)
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise OpenVikingServiceError(
                "OpenViking request failed: "
                + safe_openviking_exception_summary(
                    exc,
                    api_key=self.config.api_key,
                ),
            ) from exc

        if response.status_code in allowed_statuses:
            return {}
        if response.status_code in {401, 403}:
            raise OpenVikingConfigurationError(
                "OpenViking authentication or authorization failed.",
            )
        if not response.is_success:
            error_type = (
                OpenVikingServiceError
                if response.status_code >= 500
                or response.status_code in {408, 425, 429}
                else OpenVikingConfigurationError
            )
            raise error_type(
                f"OpenViking returned HTTP {response.status_code}.",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenVikingServiceError(
                "OpenViking returned a non-JSON response.",
            ) from exc
        if not unwrap:
            return payload
        if not isinstance(payload, dict):
            raise OpenVikingServiceError(
                "OpenViking returned an invalid response envelope.",
            )
        if payload.get("status") == "error":
            error = payload.get("error") or {}
            code = (
                str(error.get("code") or "") if isinstance(error, dict) else ""
            )
            error_type = (
                OpenVikingConfigurationError
                if code
                in {"UNAUTHENTICATED", "PERMISSION_DENIED", "INVALID_ARGUMENT"}
                else OpenVikingServiceError
            )
            raise error_type("OpenViking returned an API error.")
        if payload.get("status") != "ok" or not isinstance(
            payload.get("result"),
            dict,
        ):
            raise OpenVikingServiceError(
                "OpenViking returned an invalid success envelope.",
            )
        return payload["result"]
