# -*- coding: utf-8 -*-
"""Authenticated gateway to the QwenPaw-Data analysis engine service."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import unquote

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from qwenpaw.pawapp import ManagedService

_ALLOWED_ROUTES = (
    ("/health", False),
    ("/api/v1", True),
)
# Engine IM-channel management stays unreachable through the plugin:
# the QwenPaw host's channel infrastructure is the delivery layer.
_DENIED_ROUTES = (
    ("/api/v1/system/channel-config", True),
    ("/api/v1/channels/reload", False),
)
_FORWARDED_REQUEST_HEADERS = {
    "accept",
    "content-type",
    "last-event-id",
    "x-request-id",
}
_FORWARDED_RESPONSE_HEADERS = {
    "content-disposition",
    "content-length",
    "content-type",
    "retry-after",
    "x-request-id",
}
_SSE_PATH_RE = re.compile(r"/api/v1/sessions/[^/]+/chats/[^/]+/events/?\Z")


class EngineGateway:
    """Proxy for the engine's session/chat API, including SSE streams."""

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
        response = await self._request(method, path, json=body, params=params)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=response.status_code,
                detail=self._error_detail(response),
            ) from exc
        return response.json()

    async def proxy(self, path: str, request: Request) -> Response:
        upstream_path = self._upstream_path(path)
        if request.method == "GET" and _SSE_PATH_RE.search(upstream_path):
            return await self._stream(upstream_path, request)
        body = await request.body()
        response = await self._request(
            request.method,
            upstream_path,
            content=body or None,
            params=list(request.query_params.multi_items()),
            headers=self._request_headers(request),
        )
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=self._response_headers(response),
            media_type=response.headers.get("content-type"),
        )

    async def _stream(self, path: str, request: Request) -> StreamingResponse:
        upstream_request = self._build_request(
            "GET",
            path,
            params=list(request.query_params.multi_items()),
            headers=self._request_headers(request),
            timeout=httpx.Timeout(120.0, connect=5.0, read=None),
        )
        client = self._require_client()
        try:
            upstream = await client.send(upstream_request, stream=True)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise HTTPException(
                status_code=503,
                detail="Engine service is unavailable",
            ) from exc
        if upstream.status_code >= 400:
            content = await upstream.aread()
            await upstream.aclose()
            return Response(
                content=content,
                status_code=upstream.status_code,
                media_type=upstream.headers.get("content-type"),
            )

        async def forward():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()

        headers = self._response_headers(upstream)
        headers.pop("content-length", None)
        headers["cache-control"] = "no-cache"
        headers["x-accel-buffering"] = "no"
        return StreamingResponse(
            forward(),
            status_code=upstream.status_code,
            headers=headers,
            media_type=upstream.headers.get("content-type"),
        )

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> httpx.Response:
        upstream_request = self._build_request(method, path, **kwargs)
        client = self._require_client()
        try:
            return await client.send(upstream_request)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise HTTPException(
                status_code=503,
                detail="Engine service is unavailable",
            ) from exc

    def _build_request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> httpx.Request:
        validated_path = self._validate_path(path)
        client = self._require_client()
        token = (
            os.getenv("QWENPAW_DATA_ENGINE_TOKEN", "").strip()
            if self._service.is_external
            else self._managed_token
        )
        headers = dict(kwargs.pop("headers", {}) or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            base_url = self._service.base_url
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail="Engine service is unavailable",
            ) from exc
        return client.build_request(
            method,
            f"{base_url}{validated_path}",
            headers=headers,
            **kwargs,
        )

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise HTTPException(
                status_code=503,
                detail="Engine gateway is not ready",
            )
        return self._client

    @staticmethod
    def _request_headers(request: Request) -> dict[str, str]:
        return {
            key: value
            for key, value in request.headers.items()
            if key.lower() in _FORWARDED_REQUEST_HEADERS
        }

    @staticmethod
    def _response_headers(response: httpx.Response) -> dict[str, str]:
        return {
            key: value
            for key, value in response.headers.items()
            if key.lower() in _FORWARDED_RESPONSE_HEADERS
        }

    @classmethod
    def _upstream_path(cls, path: str) -> str:
        normalized = path.lstrip("/")
        upstream_path = f"/{normalized}"
        return cls._validate_path(upstream_path)

    @staticmethod
    def _validate_path(path: str) -> str:
        def has_forbidden_character(value: str) -> bool:
            return any(
                character.isspace()
                or ord(character) < 32
                or 127 <= ord(character) <= 159
                for character in value
            )

        if (
            not path.startswith("/")
            or "\\" in path
            or "?" in path
            or "#" in path
            or has_forbidden_character(path)
        ):
            raise HTTPException(
                status_code=404,
                detail="Engine route is not exposed",
            )
        decoded = path
        for _ in range(8):
            next_value = unquote(decoded)
            if next_value == decoded:
                break
            decoded = next_value
        else:
            raise HTTPException(
                status_code=404,
                detail="Engine route is not exposed",
            )
        if (
            "\\" in decoded
            or "?" in decoded
            or "#" in decoded
            or has_forbidden_character(decoded)
        ):
            raise HTTPException(
                status_code=404,
                detail="Engine route is not exposed",
            )
        segments = decoded.split("/")
        if (
            any(segment in {".", ".."} for segment in segments)
            or "" in segments[1:-1]
        ):
            raise HTTPException(
                status_code=404,
                detail="Engine route is not exposed",
            )
        allowed = any(
            decoded == route or (subtree and decoded.startswith(f"{route}/"))
            for route, subtree in _ALLOWED_ROUTES
        )
        if not allowed:
            raise HTTPException(
                status_code=404,
                detail="Engine route is not exposed",
            )
        denied = any(
            decoded.rstrip("/") == route
            or (subtree and decoded.startswith(f"{route}/"))
            for route, subtree in _DENIED_ROUTES
        )
        if denied:
            raise HTTPException(
                status_code=404,
                detail="Engine route is not exposed",
            )
        return decoded

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
            or f"Engine request failed ({response.status_code})"
        )
