# -*- coding: utf-8 -*-
"""AgentScope sandbox provider for CoPaw.

This provider implements SandboxProvider by calling sandbox-manager's
AgentScope HTTP API directly (no SDK required):

    POST /create_from_pool  — create sandbox
    POST /call_tool         — execute tool in sandbox
    POST /release           — release sandbox
    POST /check_health      — health check

Environment variables::

    SANDBOX_MANAGER_URL=http://sandbox-manager:8000
    SANDBOX_MANAGER_TOKEN=<bearer_token>

Usage::

    provider = AgentscopeSandboxProvider(
        sandbox_manager_url="http://...:8000",
        sandbox_manager_token="token",
        sandbox_type="agentscope-sandbox",
    )
    sandbox = await provider.get_or_create(session_id, user_id)
    # sandbox is an AgentscopeSandboxHandle with .call_tool() method
    await provider.release(session_id, user_id)
"""

import asyncio
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

_ANONYMOUS_USER = "anonymous"


def _sandbox_key(user_id: str, session_id: str) -> str:
    uid = user_id or _ANONYMOUS_USER
    return f"{uid}:{session_id}"


class AgentscopeSandboxHandle:
    """Lightweight handle representing a live AgentScope sandbox.

    Provides ``call_tool()`` and ``list_tools()`` methods that proxy
    through sandbox-manager's HTTP API.
    """

    def __init__(
        self,
        sandbox_id: str,
        sandbox_manager_url: str,
        sandbox_manager_token: str,
    ) -> None:
        self.sandbox_id = sandbox_id
        self._url = sandbox_manager_url.rstrip("/")
        self._token = sandbox_manager_token

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: float = 300,
    ) -> Dict[str, Any]:
        """Call a tool in the sandbox via sandbox-manager /call_tool."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._url}/call_tool",
                json={
                    "identity": self.sandbox_id,
                    "tool_name": tool_name,
                    "arguments": arguments,
                },
                headers=self._headers(),
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()

    async def list_tools(self, timeout: float = 30) -> Dict[str, Any]:
        """List available tools in the sandbox."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._url}/list_tools",
                json={"identity": self.sandbox_id},
                headers=self._headers(),
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()

    async def check_health(self, timeout: float = 10) -> bool:
        """Check sandbox health."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._url}/check_health",
                    json={"identity": self.sandbox_id},
                    headers=self._headers(),
                    timeout=timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("data", False) is True
        except Exception:
            return False


class AgentscopeSandboxProvider:
    """SandboxProvider implementation backed by sandbox-manager AgentScope API.

    Each (user_id, session_id) pair maps to one sandbox. The provider
    calls sandbox-manager's HTTP endpoints directly — no SDK needed.
    """

    def __init__(
        self,
        sandbox_manager_url: str,
        sandbox_manager_token: str = "",
        sandbox_type: str = "base",
    ) -> None:
        self._url = sandbox_manager_url.rstrip("/")
        self._token = sandbox_manager_token
        self._sandbox_type = sandbox_type
        self._sandboxes: Dict[str, AgentscopeSandboxHandle] = {}
        self._lock = asyncio.Lock()
        logger.info(
            "AgentscopeSandboxProvider initialized (url=%s, type=%s)",
            self._url,
            self._sandbox_type,
        )

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    async def get_or_create(
        self,
        session_id: str,
        user_id: str = "",
    ) -> Optional[AgentscopeSandboxHandle]:
        """Return existing sandbox handle or create a new one."""
        key = _sandbox_key(user_id, session_id)

        async with self._lock:
            if key in self._sandboxes:
                return self._sandboxes[key]

        effective_user = user_id or _ANONYMOUS_USER
        logger.info(
            "AgentscopeSandboxProvider: creating sandbox "
            "user=%s session=%s (type=%s)",
            effective_user,
            session_id,
            self._sandbox_type,
        )

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._url}/create_from_pool",
                json={
                    "sandbox_type": self._sandbox_type,
                    "meta": {
                        "session_ctx_id": f"{effective_user}:{session_id}",
                        "user_id": effective_user,
                        "session_id": session_id,
                    },
                },
                headers=self._headers(),
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            sandbox_id = data.get("data", "")

        if not sandbox_id:
            raise RuntimeError(
                f"sandbox-manager returned empty sandbox_id: {data}"
            )

        handle = AgentscopeSandboxHandle(
            sandbox_id=sandbox_id,
            sandbox_manager_url=self._url,
            sandbox_manager_token=self._token,
        )

        logger.info(
            "AgentscopeSandboxProvider: sandbox created "
            "user=%s session=%s -> id=%s",
            effective_user,
            session_id,
            sandbox_id,
        )

        async with self._lock:
            if key not in self._sandboxes:
                self._sandboxes[key] = handle
            else:
                # Another coroutine created one; release the duplicate
                logger.warning(
                    "AgentscopeSandboxProvider: "
                    "duplicate creation key=%s, releasing",
                    key,
                )
                await self._release_handle(handle)
                handle = self._sandboxes[key]

        return handle

    async def release(
        self,
        session_id: str,
        user_id: str = "",
    ) -> None:
        """Release the sandbox for (user_id, session_id)."""
        key = _sandbox_key(user_id, session_id)
        async with self._lock:
            handle = self._sandboxes.pop(key, None)
        if handle is not None:
            await self._release_handle(handle)

    async def release_all(self) -> None:
        """Release all tracked sandboxes."""
        async with self._lock:
            items = list(self._sandboxes.items())
            self._sandboxes.clear()
        for key, handle in items:
            logger.info(
                "AgentscopeSandboxProvider: "
                "releasing sandbox on shutdown key=%s",
                key,
            )
            await self._release_handle(handle)

    async def _release_handle(self, handle: AgentscopeSandboxHandle) -> None:
        """Release a single sandbox via sandbox-manager /release."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._url}/release",
                    json={"identity": handle.sandbox_id},
                    headers=self._headers(),
                    timeout=15,
                )
                if resp.status_code in (200, 204):
                    logger.info(
                        "AgentscopeSandboxProvider: released sandbox %s",
                        handle.sandbox_id,
                    )
                else:
                    logger.warning(
                        "AgentscopeSandboxProvider: "
                        "release sandbox %s returned %s",
                        handle.sandbox_id,
                        resp.status_code,
                    )
        except Exception as exc:
            logger.warning(
                "AgentscopeSandboxProvider: "
                "failed to release sandbox %s: %s",
                handle.sandbox_id,
                exc,
            )
