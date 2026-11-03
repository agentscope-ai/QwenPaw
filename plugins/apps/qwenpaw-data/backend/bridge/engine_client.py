# -*- coding: utf-8 -*-
"""Async client for the engine's HTTP/SSE API (the single delivery surface).

Talks to the engine base URL directly — the EngineGateway exists for
browser traffic; server-side bridge calls skip the extra hop.
"""

from __future__ import annotations

import json
import logging
from http import HTTPStatus
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

_MAX_ERROR_DETAIL_LENGTH = 160


class EngineClientError(RuntimeError):
    """Base class for normalized engine client failures."""


class EngineUnavailableError(EngineClientError):
    """The engine sidecar is not reachable or not ready."""


class EngineResponseError(EngineClientError):
    """The engine returned an unsuccessful HTTP response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail[:_MAX_ERROR_DETAIL_LENGTH]
        super().__init__(
            f"engine request failed with HTTP {status_code}: {self.detail}",
        )


def _parse_sse_data(data_lines: List[str]) -> Optional[Dict[str, Any]]:
    """Consume one buffered SSE data payload, if it is valid JSON."""
    if not data_lines:
        return None
    raw = "\n".join(data_lines)
    data_lines.clear()
    try:
        frame = json.loads(raw)
    except ValueError:
        logger.warning("bridge: dropping unparseable SSE frame")
        return None
    return frame if isinstance(frame, dict) else None


class EngineClient:
    """Thin async wrapper over the engine's /api/v1 surface.

    ``endpoint`` returns ``(base_url, token)`` and is resolved lazily per
    call so managed-service restarts (new port) are picked up.
    """

    def __init__(
        self,
        endpoint: Callable[[], tuple[str, str]],
        *,
        timeout: float = 30.0,
    ) -> None:
        self._endpoint = endpoint
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    def _base_and_headers(self) -> tuple[str, Dict[str, str]]:
        try:
            base_url, token = self._endpoint()
        except RuntimeError as exc:
            raise EngineUnavailableError(str(exc)) from exc
        if not base_url:
            raise EngineUnavailableError("engine base URL is not available")
        headers: Dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return base_url.rstrip("/"), headers

    @staticmethod
    def _check_response(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            detail = HTTPStatus(response.status_code).phrase
        except ValueError:
            detail = "Unexpected HTTP response"
        raise EngineResponseError(response.status_code, detail)

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Any:
        base, headers = self._base_and_headers()
        try:
            response = await self._http().request(
                method,
                f"{base}{path}",
                headers=headers,
                **kwargs,
            )
        except httpx.TransportError as exc:
            raise EngineUnavailableError(str(exc)) from exc
        self._check_response(response)
        if "application/json" in response.headers.get("content-type", ""):
            return response.json()
        return response.content

    async def health(self) -> bool:
        try:
            await self._request("GET", "/health")
            return True
        except EngineClientError:
            return False

    async def create_session(
        self,
        *,
        title: str = "",
        datasource_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if title:
            body["title"] = title
        if datasource_id:
            body["datasource_id"] = datasource_id
        payload = await self._request("POST", "/api/v1/sessions", json=body)
        return payload.get("session") or payload

    async def create_chat(
        self,
        session_id: str,
        text: str,
        *,
        datasource_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"text": text}
        if datasource_id:
            body["datasource_id"] = datasource_id
        payload = await self._request(
            "POST",
            f"/api/v1/sessions/{session_id}/chats",
            json=body,
        )
        return payload.get("chat") or payload

    async def stop(self, session_id: str, chat_id: str) -> None:
        # The engine awaits the full runtime unwind before responding,
        # which can take minutes mid-sandbox-step.
        await self._request(
            "POST",
            f"/api/v1/sessions/{session_id}/chats/{chat_id}/stop",
            timeout=httpx.Timeout(180.0, connect=5.0),
        )

    async def answer_clarification(
        self,
        session_id: str,
        chat_id: str,
        *,
        clarification_id: str,
        answers: List[Dict[str, Any]],
    ) -> None:
        await self._request(
            "POST",
            f"/api/v1/sessions/{session_id}/chats/{chat_id}"
            "/clarification/answer",
            json={
                "clarification_id": clarification_id,
                "result": {"status": "answered", "answers": answers},
            },
        )

    async def list_datasources(self) -> List[Dict[str, Any]]:
        payload = await self._request("GET", "/api/v1/datasources")
        items = payload.get("items") or payload.get("datasources") or []
        return items if isinstance(items, list) else []

    async def download_artifact(self, session_id: str, path: str) -> bytes:
        base, headers = self._base_and_headers()
        try:
            response = await self._http().get(
                f"{base}/api/v1/sessions/{session_id}/artifacts/file",
                params={"path": path},
                headers=headers,
            )
        except httpx.TransportError as exc:
            raise EngineUnavailableError(str(exc)) from exc
        self._check_response(response)
        return response.content

    async def stream_events(
        self,
        session_id: str,
        chat_id: str,
        *,
        after_sequence_number: int = -1,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Yield parsed stream-object frames from the chat's SSE feed."""
        base, headers = self._base_and_headers()
        url = f"{base}/api/v1/sessions/{session_id}/chats/{chat_id}/events"
        try:
            async with self._http().stream(
                "GET",
                url,
                params={"after_sequence_number": after_sequence_number},
                headers=headers,
                timeout=httpx.Timeout(30.0, read=None),
            ) as response:
                self._check_response(response)
                data_lines: List[str] = []
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                        continue
                    if line == "":
                        frame = _parse_sse_data(data_lines)
                        if frame is not None:
                            yield frame
                frame = _parse_sse_data(data_lines)
                if frame is not None:
                    yield frame
        except httpx.TransportError as exc:
            raise EngineUnavailableError(str(exc)) from exc
