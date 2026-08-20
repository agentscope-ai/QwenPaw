# -*- coding: utf-8 -*-
"""Small async client for PowerContext's public memory HTTP contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

MAX_MEMORY_TEXT_BYTES = 8000
MAX_SCOPE_ID_LENGTH = 256
MAX_MEMORY_KIND_LENGTH = 128
MAX_SEARCH_QUERY_LENGTH = 8192
MIN_SEARCH_RESULTS = 1
MAX_SEARCH_RESULTS = 50


def truncate_utf8_text(
    text: str,
    *,
    max_bytes: int = MAX_MEMORY_TEXT_BYTES,
) -> str:
    """Bound text without splitting a UTF-8 code point.

    PowerContext accepts at most 8192 normalized UTF-8 bytes.  Keep a small
    margin so the client remains valid when the server normalizes whitespace.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def bound_search_limit(limit: int) -> int:
    """Clamp a caller-provided result count to the PowerContext contract."""
    return min(MAX_SEARCH_RESULTS, max(MIN_SEARCH_RESULTS, limit))


class PowerContextRequestValidationError(ValueError):
    """Safe local validation error for a PowerContext request field."""


def _validate_scope_id(scope_id: str) -> str:
    normalized = scope_id.strip()
    if not normalized:
        raise PowerContextRequestValidationError(
            "PowerContext scope_id must not be blank.",
        )
    if len(normalized) > MAX_SCOPE_ID_LENGTH:
        raise PowerContextRequestValidationError(
            "PowerContext scope_id must not exceed 256 characters.",
        )
    return normalized


def _validate_kind(kind: str) -> str:
    normalized = kind.strip()
    if not normalized:
        raise PowerContextRequestValidationError(
            "PowerContext kind must not be blank.",
        )
    if len(normalized) > MAX_MEMORY_KIND_LENGTH:
        raise PowerContextRequestValidationError(
            "PowerContext kind must not exceed 128 characters.",
        )
    return normalized


def _validate_query(query: str) -> str:
    if not query:
        raise PowerContextRequestValidationError(
            "PowerContext query must not be empty.",
        )
    if len(query) > MAX_SEARCH_QUERY_LENGTH:
        raise PowerContextRequestValidationError(
            "PowerContext query must not exceed 8192 characters.",
        )
    return query


@dataclass(frozen=True)
class PowerContextConfig:
    base_url: str
    token: str = ""
    scope_id: str = ""
    timeout: float = 10.0


class PowerContextHTTPError(RuntimeError):
    """A safe, operation-scoped error returned by the PowerContext API.

    The response body is reduced to a short server-provided summary.  Headers
    (including the bearer token) and arbitrary response payloads are never
    included in the exception string.
    """

    def __init__(
        self,
        *,
        operation: str,
        response: httpx.Response,
        token: str = "",
    ) -> None:
        self.operation = operation
        self.status_code = response.status_code
        self.summary = _safe_error_summary(response, token=token)
        super().__init__(
            f"PowerContext {operation} failed with HTTP {self.status_code}: "
            f"{self.summary}",
        )


class PowerContextProtocolError(RuntimeError):
    """Safe error for a successful response that violates the API contract."""

    def __init__(self, *, operation: str, summary: str) -> None:
        self.operation = operation
        self.summary = summary
        super().__init__(
            f"PowerContext {operation} returned invalid response: {summary}",
        )


def _safe_error_summary(response: httpx.Response, *, token: str = "") -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    if isinstance(payload, dict):
        code = payload.get("code")
        message = (
            payload.get("message")
            or payload.get("error")
            or payload.get("detail")
        )
        if (
            isinstance(code, str)
            and code.strip()
            and isinstance(message, str)
            and message.strip()
        ):
            summary = f"{code.strip()}: {message.strip()}"
            return (
                summary.replace(token, "<redacted>")[:300]
                if token
                else summary[:300]
            )
        for value in (message, code):
            if isinstance(value, str) and value.strip():
                summary = value.strip()
                return (
                    summary.replace(token, "<redacted>")[:300]
                    if token
                    else summary[:300]
                )
    if isinstance(payload, str) and payload.strip():
        summary = payload.strip()
        return (
            summary.replace(token, "<redacted>")[:300]
            if token
            else summary[:300]
        )
    return response.reason_phrase or "request failed"


class PowerContextMemoryClient:
    def __init__(self, config: PowerContextConfig) -> None:
        self.config = config
        headers = (
            {"Authorization": f"Bearer {config.token}"} if config.token else {}
        )
        self._http = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            headers=headers,
            timeout=config.timeout,
        )

    async def remember(
        self,
        *,
        kind: str,
        text: str,
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        resolved_scope_id = _validate_scope_id(
            scope_id or self.config.scope_id,
        )
        response = await self._http.post(
            "/v1/memory/remember",
            json={
                "scope_id": resolved_scope_id,
                "kind": _validate_kind(kind),
                "text": truncate_utf8_text(text),
            },
        )
        self._raise_for_status("memory remember", response)
        return response.json()

    async def search(
        self,
        *,
        query: str,
        limit: int = 5,
        scope_id: str | None = None,
    ) -> list[dict[str, Any]]:
        resolved_scope_id = _validate_scope_id(
            scope_id or self.config.scope_id,
        )
        response = await self._http.post(
            "/v1/memory/search",
            json={
                "scope_id": resolved_scope_id,
                "query": _validate_query(query),
                "limit": bound_search_limit(limit),
            },
        )
        self._raise_for_status("memory search", response)
        payload = response.json()
        if not isinstance(payload, dict):
            raise PowerContextProtocolError(
                operation="memory search",
                summary="response body must be an object",
            )
        hits = payload.get("hits")
        if not isinstance(hits, list):
            raise PowerContextProtocolError(
                operation="memory search",
                summary="response does not contain a hits list",
            )
        return hits

    async def close(self) -> None:
        await self._http.aclose()

    def _raise_for_status(
        self,
        operation: str,
        response: httpx.Response,
    ) -> None:
        if response.is_error:
            raise PowerContextHTTPError(
                operation=operation,
                response=response,
                token=self.config.token,
            )
