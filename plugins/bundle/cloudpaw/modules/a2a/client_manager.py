# -*- coding: utf-8 -*-
"""A2A Client Manager: manage A2A 1.0 connections without SDK dependency.

Implements the A2A 1.0 JSON-RPC + SSE protocol directly using httpx
and httpx-sse, providing a unified interface for both generic A2A
and intelligent gateway scenarios.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from uuid import uuid4

import httpx
import httpx_sse

from .auth_interceptor import get_auth_headers
from .gateway_adapter import (
    normalize_gateway_card,
    patch_card_url,
)
from .gateway_token import GatewayTokenProvider

logger = logging.getLogger(__name__)

_CARD_CACHE_TTL = 3600  # 1 hour
_DEFAULT_TIMEOUT = 60.0
_A2A_VERSION = "1.0.0"


@dataclass
class _AgentEntry:
    """Internal state for a connected agent."""

    url: str
    auth_type: str
    auth_token: str = ""
    card: dict | None = None
    card_fetched_at: float = 0
    rpc_url: str = ""
    token_provider: GatewayTokenProvider | None = None
    gateway_config: dict = field(default_factory=dict)


class A2AClientManager:
    """Manage A2A connections for multiple remote agents.

    Usage::

        manager = A2AClientManager()
        info = await manager.connect("https://agent.example.com")
        async for event in manager.send_message(
            "https://agent.example.com",
            "hello",
        ):
            print(event)
        await manager.close()
    """

    def __init__(self) -> None:
        self._agents: dict[str, _AgentEntry] = {}
        self._http: httpx.AsyncClient | None = None

    async def connect(
        self,
        agent_url: str,
        auth_type: str = "",
        auth_token: str = "",
        gateway_config: dict | None = None,
    ) -> dict:
        """Discover Agent Card and establish authenticated connection.

        Args:
            agent_url: Remote A2A Agent base URL.
            auth_type: "bearer", "api_key", "gateway", or "" (none).
            auth_token: Token/key value (not needed for gateway).
            gateway_config: Optional gateway-specific config overrides.

        Returns:
            dict with agent card summary and connection status.
        """
        entry = self._agents.get(agent_url)
        if entry and entry.card and not self._card_expired(entry):
            logger.info("Reusing cached connection for %s", agent_url)
            return self._card_summary(entry)

        entry = _AgentEntry(
            url=agent_url,
            auth_type=auth_type,
            auth_token=auth_token,
            gateway_config=gateway_config or {},
        )

        card = await self._fetch_agent_card(agent_url, auth_type)
        entry.card = card
        entry.card_fetched_at = time.time()

        if auth_type == "gateway":
            card = patch_card_url(card)
            entry.card = card
            gw_cfg = gateway_config or {}
            entry.token_provider = GatewayTokenProvider(
                client_id=gw_cfg.get("client_id", "4081417976505782102"),
                scope=gw_cfg.get("scope", "/internal/agenthub"),
                endpoint=gw_cfg.get("endpoint", "ramoauth.aliyuncs.com"),
            )
            logger.info("Applied gateway URL patch for %s", agent_url)

        entry.rpc_url = card.get("url", agent_url)

        self._agents[agent_url] = entry
        logger.info("Connected to agent: %s (auth=%s)", agent_url, auth_type)
        return self._card_summary(entry)

    async def send_message(
        self,
        agent_url: str,
        message: str,
        context_id: str = "",
        streaming: bool = True,
    ) -> AsyncIterator[dict]:
        """Send a message to a remote agent and yield response events.

        Args:
            agent_url: Agent URL (must have been connected first).
            message: Text message to send.
            context_id: Optional conversation context ID.
            streaming: Whether to use streaming (SSE) mode.

        Yields:
            dict with event data (type, task, statusUpdate, etc.)
        """
        entry = await self._ensure_connected(agent_url)

        msg_id = str(uuid4())
        parts = [{"text": message}]
        msg_obj: dict = {
            "messageId": msg_id,
            "role": "ROLE_USER",
            "parts": parts,
        }
        if context_id:
            msg_obj["contextId"] = context_id

        method = "SendStreamingMessage" if streaming else "SendMessage"
        payload = self._build_jsonrpc(method, {"message": msg_obj})

        auth_headers = await get_auth_headers(
            entry.auth_type,
            entry.auth_token,
            entry.token_provider,
        )
        headers = {
            "Content-Type": "application/json",
            "A2A-Version": _A2A_VERSION,
            **auth_headers,
        }

        http = self._get_http(entry)

        if streaming:
            async for event_data in self._stream_sse(
                http,
                entry.rpc_url,
                payload,
                headers,
            ):
                yield self._classify_event(event_data)
        else:
            resp = await http.post(
                entry.rpc_url,
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            body = resp.json()
            if "error" in body:
                raise RuntimeError(
                    f"A2A error {body['error'].get('code')}: "
                    f"{body['error'].get('message')}",
                )
            result = body.get("result", {})
            yield self._classify_event(result)

    async def get_card_info(self, agent_url: str) -> dict | None:
        """Get cached card info for a connected agent."""
        entry = self._agents.get(agent_url)
        if entry and entry.card:
            return self._card_summary(entry)
        return None

    async def close(self) -> None:
        """Close all connections."""
        if self._http:
            await self._http.aclose()
            self._http = None
        self._agents.clear()
        logger.info("A2AClientManager closed all connections")

    async def disconnect(self, agent_url: str) -> None:
        """Disconnect and remove a specific agent."""
        self._agents.pop(agent_url, None)

    def list_connected(self) -> list[dict]:
        """List all connected agents with their card summaries."""
        return [
            self._card_summary(entry)
            for entry in self._agents.values()
            if entry.card
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_connected(self, agent_url: str) -> _AgentEntry:
        entry = self._agents.get(agent_url)
        if entry and entry.card and not self._card_expired(entry):
            return entry
        await self.connect(agent_url)
        entry = self._agents.get(agent_url)
        if not entry or not entry.card:
            raise RuntimeError(f"Failed to connect to {agent_url}")
        return entry

    async def _fetch_agent_card(
        self,
        agent_url: str,
        auth_type: str,
    ) -> dict:
        """Fetch and parse Agent Card JSON from remote endpoint."""
        is_gateway = auth_type == "gateway"
        verify_ssl = not is_gateway

        card_url = f"{agent_url.rstrip('/')}/.well-known/agent-card.json"
        async with httpx.AsyncClient(
            verify=verify_ssl,
            timeout=30.0,
        ) as http:
            resp = await http.get(
                card_url,
                headers={"A2A-Version": _A2A_VERSION},
            )
            resp.raise_for_status()
            card = resp.json()

        if is_gateway:
            card = normalize_gateway_card(card)

        if not card.get("url"):
            card["url"] = agent_url

        logger.info(
            "Agent Card fetched for %s: %s",
            agent_url,
            card.get("name"),
        )
        return card

    def _get_http(self, entry: _AgentEntry) -> httpx.AsyncClient:
        """Get or create a shared httpx client."""
        if self._http is None or self._http.is_closed:
            verify = entry.auth_type != "gateway"
            self._http = httpx.AsyncClient(
                verify=verify,
                timeout=_DEFAULT_TIMEOUT,
            )
        return self._http

    async def _stream_sse(
        self,
        http: httpx.AsyncClient,
        url: str,
        payload: dict,
        headers: dict,
    ) -> AsyncIterator[dict]:
        """Send JSON-RPC request and yield parsed SSE event data.

        Some A2A servers (e.g. the Alibaba Cloud gateway) may respond
        with Content-Type: application/json even for streaming requests.
        We handle both SSE and plain JSON responses gracefully.
        """
        resp = await http.send(
            http.build_request("POST", url, json=payload, headers=headers),
            stream=True,
        )
        try:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")

            if "text/event-stream" in content_type:
                event_source = httpx_sse.EventSource(resp)
                async for sse_event in event_source.aiter_sse():
                    if sse_event.data:
                        try:
                            data = json.loads(sse_event.data)
                            if "error" in data:
                                err = data["error"]
                                logger.warning(
                                    "SSE error: %s - %s",
                                    err.get("code"),
                                    err.get("message"),
                                )
                            result = data.get("result", data)
                            yield result
                        except json.JSONDecodeError:
                            logger.warning(
                                "Non-JSON SSE event: %s",
                                sse_event.data[:200],
                            )
            else:
                body = await resp.aread()
                data = json.loads(body)
                if "error" in data:
                    err = data["error"]
                    raise RuntimeError(
                        f"A2A error {err.get('code')}: {err.get('message')}",
                    )
                result = data.get("result", data)
                yield result
        finally:
            await resp.aclose()

    @staticmethod
    def _build_jsonrpc(method: str, params: dict) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }

    @staticmethod
    def _classify_event(data: dict) -> dict:
        """Add a 'type' field to an event dict for downstream processing."""
        if "task" in data:
            return {"type": "task", **data}
        if "statusUpdate" in data:
            return {"type": "status_update", **data}
        if "artifactUpdate" in data:
            return {"type": "artifact_update", **data}
        if "message" in data:
            return {"type": "message", **data}
        return {"type": "unknown", **data}

    @staticmethod
    def _card_expired(entry: _AgentEntry) -> bool:
        return (time.time() - entry.card_fetched_at) > _CARD_CACHE_TTL

    @staticmethod
    def _card_summary(entry: _AgentEntry) -> dict:
        card = entry.card
        if not card:
            return {"url": entry.url, "status": "not_connected"}

        skills = []
        for s in card.get("skills", []):
            skill_info = {"name": s.get("name", "")}
            desc = s.get("description")
            if desc:
                skill_info["description"] = desc
            skills.append(skill_info)

        interfaces = []
        for iface in card.get("additionalInterfaces", []):
            interfaces.append(
                {
                    "url": iface.get("url", ""),
                    "protocol_binding": iface.get("preferredTransport", ""),
                    "protocol_version": iface.get("protocolVersion", ""),
                },
            )

        caps = card.get("capabilities", {})
        return {
            "url": entry.url,
            "status": "connected",
            "auth_type": entry.auth_type,
            "name": card.get("name", ""),
            "description": card.get("description", ""),
            "version": card.get("version", ""),
            "skills": skills,
            "interfaces": interfaces,
            "capabilities": {
                "streaming": caps.get("streaming", False),
                "push_notifications": bool(
                    caps.get("pushNotifications")
                    or caps.get("pushNotificationConfig"),
                ),
            },
        }


_manager_instance: A2AClientManager | None = None


def get_a2a_manager() -> A2AClientManager:
    """Get or create the singleton A2AClientManager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = A2AClientManager()
    return _manager_instance


async def shutdown_a2a_manager() -> None:
    """Shutdown the singleton manager if it exists."""
    global _manager_instance
    if _manager_instance is not None:
        await _manager_instance.close()
        _manager_instance = None
