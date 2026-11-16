# -*- coding: utf-8 -*-
"""Carry Console API requests to the owned loopback Runtime."""

from __future__ import annotations

import base64
import json
import re
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import unquote

import httpx

from .node_transport import RelayOperationDispatcher, RelayResponse
from .protocol import RelayOperation

# Runtime API groups used by the shared Console. Hub and binding control
# routes remain outside this surface, including for Hub administrators.
CONSOLE_API_ROOTS = frozenset(
    {
        "access-control",
        "advisor-mode",
        "agent",
        "agent-stats",
        "agent-status",
        "agents",
        "approval",
        "avatars",
        "backups",
        "browser",
        "channels",
        "chats",
        "coding-mode",
        "commands",
        "community",
        "config",
        "console",
        "cron",
        "envs",
        "files",
        "fork",
        "frontend_plugin",
        "harness",
        "harnesses",
        "health",
        "healthz",
        "language",
        "local-models",
        "loops",
        "mail-access-control",
        "market",
        "mcp",
        "messages",
        "models",
        "pawapps",
        "plugins",
        "portability",
        "providers",
        "profile",
        "runtime",
        "settings",
        "skills",
        "token-usage",
        "terminals",
        "tool-calls",
        "tools",
        "version",
        "workspace",
    },
)
METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"})
RESPONSE_HEADERS = ("content-disposition", "content-range", "accept-ranges")


class RelayLocalApi:
    """Forward requests to the owned Runtime without caller credentials."""

    def __init__(
        self,
        base_url: str | Callable[[], str],
        *,
        client: httpx.AsyncClient | None = None,
        headers: Callable[[], Mapping[str, str]] | None = None,
    ) -> None:
        self._base_url = base_url
        self._client = client
        self._headers = headers or dict

    def dispatcher(self) -> RelayOperationDispatcher:
        """Expose one transport contract for the existing Console API."""
        return RelayOperationDispatcher(
            {
                RelayOperation.CONSOLE_REQUEST: self._console_request,
            },
        )

    async def _console_request(self, payload: bytes):
        body = json.loads(payload)
        if not isinstance(body, dict):
            raise ValueError("Console request must be an object")
        method, path = _route(body)
        agent_id = body.get("agent_id", "default")
        if (
            not isinstance(agent_id, str)
            or agent_id in {".", ".."}
            or not re.fullmatch(
                r"[A-Za-z0-9_.:-]{1,200}",
                agent_id,
            )
        ):
            raise ValueError("Invalid Console agent")
        content = base64.b64decode(body.get("body", ""), validate=True)
        if len(content) > 8 * 1024 * 1024:
            raise ValueError("Console request exceeds 8 MiB")
        headers = {**self._headers(), "X-Agent-Id": agent_id}
        for name in (
            "content-type",
            "range",
            "accept",
            "x-chat-id",
            "x-session-project-dir",
        ):
            value = body.get("headers", {}).get(name)
            if value:
                headers[name] = value
        return self._request(
            method,
            path,
            body.get("query", ""),
            headers,
            content,
        )

    @asynccontextmanager
    async def _request(
        self,
        method: str,
        path: str,
        query: str,
        headers: dict[str, str],
        content: bytes,
    ) -> AsyncIterator[RelayResponse]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(120.0),
            follow_redirects=False,
            trust_env=False,
        )
        base = self._base_url() if callable(self._base_url) else self._base_url
        url = httpx.URL(base).copy_with(
            path=f"/api{path}",
            query=query.encode("utf-8"),
        )
        try:
            async with client.stream(
                method,
                url,
                headers=headers,
                content=content,
            ) as response:
                yield RelayResponse(
                    status=response.status_code,
                    content_type=response.headers.get(
                        "content-type",
                        "application/octet-stream",
                    ),
                    headers={
                        key: response.headers[key]
                        for key in RESPONSE_HEADERS
                        if key in response.headers
                    },
                    body=response.aiter_bytes(),
                )
        finally:
            if owns_client:
                await client.aclose()


def _route(body: Mapping[str, Any]) -> tuple[str, str]:
    method = body.get("method")
    path = body.get("path")
    if method not in METHODS or not isinstance(path, str):
        raise ValueError("Invalid Console request")
    path = unquote(path)
    if not path.startswith("/") or any(c in path for c in ("?", "#", "\\")):
        raise ValueError("Invalid Console path")
    parts = path[1:].split("/")
    if any(part in {".", ".."} for part in parts) or re.search(
        r"%(?:2e|2f|5c)",
        path,
        re.IGNORECASE,
    ):
        raise ValueError("Invalid Console path")
    if parts[0] not in CONSOLE_API_ROOTS and not (
        path == "/auth/status" and method == "GET"
    ):
        raise ValueError("Console route is not available remotely")
    return method, path
