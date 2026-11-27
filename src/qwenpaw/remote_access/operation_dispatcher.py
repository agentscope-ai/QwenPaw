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
        self._owns_client = client is None
        self._headers = headers or dict

    async def close(self) -> None:
        """Close the binding's shared pool after transport shutdown."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

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
        run_id = body.get("run_id")
        if run_id is not None:
            if not isinstance(run_id, str) or not re.fullmatch(
                r"[a-f0-9-]{36}\.[a-f0-9]{64}\.[a-f0-9]{32}",
                run_id,
            ):
                raise ValueError("Invalid Relay run identity")
            headers["X-QwenPaw-Relay-Run"] = run_id
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

    def _http_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0),
                follow_redirects=False,
                trust_env=False,
                limits=httpx.Limits(
                    max_connections=32,
                    max_keepalive_connections=32,
                ),
            )
        return self._client

    def _url(self) -> httpx.URL:
        base = self._base_url() if callable(self._base_url) else self._base_url
        return httpx.URL(base)

    async def sync_runs(
        self,
        node_id: str,
        finished: list[str],
    ) -> dict[str, list[str]]:
        """Read task state from the personal Runtime that executes the run."""
        url = self._url().copy_with(
            path=f"/api/remote-access/relay-runs/{node_id}",
        )
        response = await self._http_client().post(
            url,
            headers=self._headers(),
            json=finished,
            timeout=5.0,
        )
        response.raise_for_status()
        return response.json()

    @asynccontextmanager
    async def _request(
        self,
        method: str,
        path: str,
        query: str,
        headers: dict[str, str],
        content: bytes,
    ) -> AsyncIterator[RelayResponse]:
        url = self._url().copy_with(
            path=f"/api{path}",
            query=query.encode("utf-8"),
        )
        async with self._http_client().stream(
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
    if (
        method == "POST"
        and path.rstrip("/") == "/providers/openrouter/oauth/start"
    ):
        raise ValueError("Connect OpenRouter from the local Console")
    return method, path
