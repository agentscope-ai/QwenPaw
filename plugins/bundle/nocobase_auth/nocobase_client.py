# -*- coding: utf-8 -*-
"""NocoBase REST API client for the auth plugin."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0


class NocoBaseClientError(Exception):
    """Base exception for NocoBase client errors."""


class NocoBaseAuthError(NocoBaseClientError):
    """Raised when authentication against NocoBase fails."""


class NocoBaseRequestError(NocoBaseClientError):
    """Raised for HTTP or network errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class NocoBaseClient:
    """Minimal NocoBase REST client for users and roles."""

    def __init__(
        self,
        base_url: str,
        api_token: str,
        timeout: float = DEFAULT_TIMEOUT,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.timeout = timeout
        self.transport = transport
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {}
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
                follow_redirects=True,
                # The NocoBase URL is configured explicitly by the admin and
                # is typically loopback/LAN. Contact it directly: do NOT route
                # through ambient HTTP(S)_PROXY / system proxies, which can
                # silently hijack localhost (e.g. corporate security agents)
                # and break the integration with confusing 5xx responses.
                trust_env=False,
                transport=self.transport,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def health_check(self) -> bool:
        """Return True if NocoBase appears reachable and auth succeeds."""
        try:
            response = await self._get_client().get(
                "/api/users:list",
                params={"pageSize": 1},
            )
            return response.status_code == 200
        except Exception as exc:
            logger.debug("NocoBase health check failed: %s", exc)
            return False

    async def list_users(
        self,
        user_id_field: str = "email",
    ) -> List[Dict[str, Any]]:
        """Fetch all NocoBase users with their roles.

        Args:
            user_id_field: Field to extract as the channel sender_id.

        Returns:
            List of user dicts with keys: id, sender_id, email, roles.
        """
        response = await self._get_client().get(
            "/api/users:list",
            params={
                "paginate": "false",
                "appends": "roles",
            },
        )
        self._raise_for_status(response)

        payload = response.json()
        rows = (
            payload.get("data", []) if isinstance(payload, dict) else payload
        )
        if not isinstance(rows, list):
            raise NocoBaseRequestError("Unexpected users response format")

        users = []
        for row in rows:
            sender_id = self.extract_sender_id(row, user_id_field)
            roles = self._extract_roles(row)
            users.append(
                {
                    "id": str(row.get("id", "")),
                    "sender_id": sender_id,
                    "email": row.get("email", ""),
                    "nickname": row.get("nickname", ""),
                    "roles": roles,
                    "raw": row,
                },
            )
        return users

    async def list_roles(self) -> List[Dict[str, Any]]:
        """Fetch all NocoBase roles.

        Returns:
            List of role dicts with keys: id, name, title.
        """
        response = await self._get_client().get(
            "/api/roles:list",
            params={"paginate": "false"},
        )
        self._raise_for_status(response)

        payload = response.json()
        rows = (
            payload.get("data", []) if isinstance(payload, dict) else payload
        )
        if not isinstance(rows, list):
            raise NocoBaseRequestError("Unexpected roles response format")

        return [
            {
                "id": str(row.get("id", "")),
                "name": str(row.get("name", "")),
                "title": str(row.get("title", "")),
            }
            for row in rows
        ]

    async def verify_user_token(
        self,
        user_token: str,
    ) -> Optional[Dict[str, Any]]:
        """Verify a NocoBase *user* token via ``auth:check``.

        Uses the caller's own token (not the plugin's admin api_token), so a
        one-off client is created rather than reusing ``_get_client()``.
        Requests the user's roles via ``appends=roles`` so identity
        resolution can read roles straight off this response, on the hot
        path, using only the caller's own token.

        Returns:
            The user dict on success; ``None`` when the token is invalid
            (HTTP 401). Raises :class:`NocoBaseRequestError` on network or
            server errors so the caller can treat "could not verify" as a
            non-cacheable outcome.
        """
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {user_token}"},
                timeout=self.timeout,
                follow_redirects=True,
                trust_env=False,
                transport=self.transport,
            ) as client:
                response = await client.get(
                    "/api/auth:check",
                    params={"appends": "roles"},
                )
        except httpx.HTTPError as exc:
            raise NocoBaseRequestError(
                f"auth:check request failed: {exc}",
            ) from exc

        if response.status_code == 401:
            return None
        if response.status_code >= 400:
            raise NocoBaseRequestError(
                f"auth:check failed: {response.status_code}",
                status_code=response.status_code,
            )
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, dict) else None

    async def sign_in(
        self,
        username: str,
        password: str,
        *,
        authenticator: str = "basic",
    ) -> Optional[Dict[str, Any]]:
        """Authenticate username/password against NocoBase.

        Returns the NocoBase ``data`` payload on success, ``None`` for
        invalid credentials, and raises on network/server errors.
        """
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers={"X-Authenticator": authenticator},
                timeout=self.timeout,
                follow_redirects=True,
                trust_env=False,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    "/api/auth:signIn",
                    json={"account": username, "password": password},
                )
        except httpx.HTTPError as exc:
            raise NocoBaseRequestError(
                f"auth:signIn request failed: {exc}",
            ) from exc

        if response.status_code == 401:
            return None
        if response.status_code >= 400:
            raise NocoBaseRequestError(
                f"auth:signIn failed: {response.status_code}",
                status_code=response.status_code,
            )

        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, dict) else None

    @staticmethod
    def extract_sender_id(row: Dict[str, Any], user_id_field: str) -> str:
        """Extract the channel sender_id from a user row."""
        value = row.get(user_id_field)
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _extract_roles(row: Dict[str, Any]) -> List[str]:
        """Extract role names from a user row.

        NocoBase may return roles as a list of dicts or a list of strings.
        """
        roles = row.get("roles", [])
        if not isinstance(roles, list):
            return []
        result = []
        for role in roles:
            if isinstance(role, dict):
                name = role.get("name") or role.get("title", "")
                if name:
                    result.append(str(name))
            elif isinstance(role, str):
                result.append(role)
        return result

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 401:
            raise NocoBaseAuthError("Invalid or expired NocoBase API token")
        if response.status_code >= 400:
            detail = response.text[:200]
            raise NocoBaseRequestError(
                f"NocoBase request failed: {response.status_code} {detail}",
                status_code=response.status_code,
            )
