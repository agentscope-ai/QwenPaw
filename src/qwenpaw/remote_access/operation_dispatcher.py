# -*- coding: utf-8 -*-
"""Whitelisted Relay operations backed by the local QwenPaw API."""
from __future__ import annotations

import json
from typing import Any, Mapping

import httpx

from .node_transport import RelayOperationDispatcher
from .protocol import RelayOperation


class RelayLocalApi:
    """Translate fixed Relay operations into loopback-only API calls."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8088",
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client

    def dispatcher(self) -> RelayOperationDispatcher:
        """Return a dispatcher containing only the V1 operation registry."""
        return RelayOperationDispatcher(
            {
                RelayOperation.AGENT_LIST: self._agent_list,
                RelayOperation.AGENT_GET: self._agent_get,
                RelayOperation.SESSION_LIST: self._session_list,
                RelayOperation.SESSION_GET: self._session_get,
                RelayOperation.SESSION_CREATE: self._session_create,
                RelayOperation.SESSION_UPDATE: self._session_update,
                RelayOperation.SESSION_ARCHIVE: self._session_archive,
                RelayOperation.SESSION_DELETE: self._session_delete,
                RelayOperation.MESSAGE_SEND: self._message_send,
                RelayOperation.RUN_CANCEL: self._run_cancel,
                RelayOperation.APPROVAL_RESOLVE: self._approval_resolve,
            },
        )

    async def _agent_list(self, payload: bytes) -> bytes:
        body = _payload(payload)
        return await self._request("GET", "/api/agents", body=body)

    async def _agent_get(self, payload: bytes) -> bytes:
        body = _payload(payload)
        agent_id = _identifier(body, "agent_id")
        return await self._request("GET", f"/api/agents/{agent_id}")

    async def _session_list(self, payload: bytes) -> bytes:
        body = _payload(payload)
        resource = body.get("resource", "chats")
        if resource == "groups":
            return await self._request("GET", "/api/chats/groups", body=body)
        if resource != "chats":
            raise ValueError("Unsupported session list resource")
        archived = "true" if body.get("archived") is True else "false"
        return await self._request(
            "GET",
            f"/api/chats?archived={archived}",
            body=body,
        )

    async def _session_get(self, payload: bytes) -> bytes:
        body = _payload(payload)
        chat_id = _identifier(body, "chat_id")
        return await self._request("GET", f"/api/chats/{chat_id}", body=body)

    async def _session_create(self, payload: bytes) -> bytes:
        body = _payload(payload)
        if body.get("resource", "chats") == "groups":
            return await self._request("POST", "/api/chats/groups", body=body)
        return await self._request("POST", "/api/chats", body=body)

    async def _session_archive(self, payload: bytes) -> bytes:
        body = _payload(payload)
        chat_id = _identifier(body, "chat_id")
        action = body.get("action", "archive")
        if action not in {"archive", "unarchive"}:
            raise ValueError("Unsupported session archive action")
        return await self._request(
            "POST",
            f"/api/chats/{chat_id}/{action}",
            body=body,
        )

    async def _session_update(self, payload: bytes) -> bytes:
        body = _payload(payload)
        resource = body.get("resource", "chats")
        if resource == "groups":
            group_id = _identifier(body, "target_group_id")
            return await self._request(
                "PUT",
                f"/api/chats/groups/{group_id}",
                body=body,
            )
        if resource != "chats":
            raise ValueError("Unsupported session update resource")
        chat_id = _identifier(body, "chat_id")
        return await self._request(
            "PUT",
            f"/api/chats/{chat_id}",
            body=body,
        )

    async def _session_delete(self, payload: bytes) -> bytes:
        body = _payload(payload)
        resource = body.get("resource", "chats")
        if resource == "groups":
            group_id = _identifier(body, "target_group_id")
            return await self._request(
                "DELETE",
                f"/api/chats/groups/{group_id}",
                body=body,
            )
        chat_id = _identifier(body, "chat_id")
        return await self._request(
            "DELETE",
            f"/api/chats/{chat_id}",
            body=body,
        )

    async def _message_send(self, payload: bytes) -> bytes:
        return await self._request(
            "POST",
            "/api/console/chat",
            body=_payload(payload),
        )

    async def _run_cancel(self, payload: bytes) -> bytes:
        body = _payload(payload)
        chat_id = _identifier(body, "chat_id")
        return await self._request(
            "POST",
            f"/api/console/chat/stop?chat_id={chat_id}",
            body=body,
        )

    async def _approval_resolve(self, payload: bytes) -> bytes:
        body = _payload(payload)
        decision = body.get("decision")
        if decision not in {"approve", "deny"}:
            raise ValueError("Unsupported approval decision")
        return await self._request(
            "POST",
            f"/api/approval/{decision}",
            body=body,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
    ) -> bytes:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(120.0),
            follow_redirects=False,
        )
        headers = {
            "Accept": "application/json, text/event-stream",
            "X-Agent-Id": str((body or {}).get("agent_id", "default")),
        }
        request_body = _business_body(body)
        try:
            response = await client.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                json=request_body if method != "GET" else None,
            )
        finally:
            if owns_client:
                await client.aclose()
        if not response.is_success:
            raise RuntimeError(
                f"Local QwenPaw operation failed: {response.status_code}",
            )
        return response.content


def _payload(value: bytes) -> Mapping[str, Any]:
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Relay operation payload must be JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("Relay operation payload must be an object")
    return decoded


def _identifier(body: Mapping[str, Any], name: str) -> str:
    value = body.get(name)
    if (
        not isinstance(value, str)
        or not value
        or any(character in value for character in "/?#\\\x00")
    ):
        raise ValueError(f"Relay operation {name} is invalid")
    return value


def _business_body(body: Mapping[str, Any] | None) -> dict[str, Any]:
    if body is None:
        return {}
    internal = {
        "action",
        "agent_id",
        "archived",
        "chat_id",
        "decision",
        "resource",
        "target_group_id",
    }
    return {key: value for key, value in body.items() if key not in internal}
