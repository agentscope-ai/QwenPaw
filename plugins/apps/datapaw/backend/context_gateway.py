# -*- coding: utf-8 -*-
"""Authenticated, allowlisted gateway to the QwenPaw-Data context service."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import unquote

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import Response

from qwenpaw.pawapp import ManagedService

_ALLOWED_ROUTES = (
    ("/api/health", False),
    ("/api/v1", True),
    # Subtree: the console's Model Configuration page manages the Context
    # service's internal LLM/embedding stack (/llm, /embedding, /embedding/jobs
    # and their /test probes).
    ("/api/system/model-config", True),
    ("/api/semantic-config", True),
    # Read-only auth probe used by the embedded Context console; the managed
    # service runs without DATAPAW_AUTH_SECRET so it reports auth disabled.
    ("/api/auth/status", False),
)
_FORWARDED_REQUEST_HEADERS = {
    "accept",
    "content-type",
    "idempotency-key",
    "last-event-id",
    "x-neo4j-database",
    "x-request-id",
}
_FORWARDED_RESPONSE_HEADERS = {
    "content-disposition",
    "content-length",
    "content-type",
    "retry-after",
    "x-request-id",
}


class ContextGateway:
    def __init__(self, service: ManagedService, managed_token: str):
        self._service = service
        self._managed_token = managed_token
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=5.0),
            follow_redirects=False,
        )

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def json(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = await self._send(
            method,
            path,
            json=body,
            params=params,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=response.status_code,
                detail=self._error_detail(response),
            ) from exc
        return response.json()

    async def proxy(self, path: str, request: Request) -> Response:
        upstream_path = self._proxy_upstream_path(path)
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() in _FORWARDED_REQUEST_HEADERS
        }
        body = await request.body()
        response = await self._send(
            request.method,
            upstream_path,
            content=body or None,
            params=list(request.query_params.multi_items()),
            headers=headers,
        )
        response_headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() in _FORWARDED_RESPONSE_HEADERS
        }
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=response_headers,
            media_type=response.headers.get("content-type"),
        )

    @classmethod
    def _proxy_upstream_path(cls, path: str) -> str:
        """Resolve browser and CLI-style paths onto the Context API.

        The embedded UI uses paths such as ``semantic-config/metric-lib``.
        QwenPaw-Data CLI clients append canonical paths beginning with
        ``/api`` to ``DATAPAW_CM_BASE_URL``.  Accept both shapes so callers can
        point the CLI at ``.../api/datapaw/context`` and reach the same managed
        Context service that backs the portal.
        """

        normalized = path.lstrip("/")
        upstream_path = (
            f"/{normalized}"
            if normalized == "api" or normalized.startswith("api/")
            else f"/api/{normalized}"
        )
        cls._validate_path(upstream_path)
        return upstream_path

    async def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        self._validate_path(path)
        if self._client is None:
            raise HTTPException(
                status_code=503,
                detail="Context gateway is not ready",
            )
        token = (
            os.getenv("DATAPAW_CONTEXT_TOKEN", "").strip()
            if self._service.is_external
            else self._managed_token
        )
        headers = dict(kwargs.pop("headers", {}) or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            return await self._client.request(
                method,
                f"{self._service.base_url}{path}",
                headers=headers,
                **kwargs,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise HTTPException(
                status_code=503,
                detail="Context service is unavailable",
            ) from exc

    @staticmethod
    def _validate_path(path: str) -> None:
        if (
            not path.startswith("/")
            or "\\" in path
            or "?" in path
            or "#" in path
        ):
            raise HTTPException(
                status_code=404,
                detail="Context route is not exposed",
            )

        decoded = path
        # Match the frontend scope guard (scope.ts): eight decode passes, and
        # a path that still is not at a fixed point is treated as hostile
        # rather than validated against a partially decoded value.
        for _ in range(8):
            next_value = unquote(decoded)
            if next_value == decoded:
                break
            decoded = next_value
        else:
            raise HTTPException(
                status_code=404,
                detail="Context route is not exposed",
            )
        if "\\" in decoded or "?" in decoded or "#" in decoded:
            raise HTTPException(
                status_code=404,
                detail="Context route is not exposed",
            )
        segments = decoded.split("/")
        if any(segment in {".", ".."} for segment in segments):
            raise HTTPException(
                status_code=404,
                detail="Context route is not exposed",
            )

        allowed = any(
            decoded == route or (subtree and decoded.startswith(f"{route}/"))
            for route, subtree in _ALLOWED_ROUTES
        )
        if not allowed:
            raise HTTPException(
                status_code=404,
                detail="Context route is not exposed",
            )

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                return str(
                    payload.get("detail") or payload.get("message") or payload,
                )
        except ValueError:
            pass
        return (
            response.text[:500]
            or f"Context request failed ({response.status_code})"
        )
