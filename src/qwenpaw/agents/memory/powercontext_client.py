"""Small async client for PowerContext's public memory HTTP contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class PowerContextConfig:
    base_url: str
    token: str = ""
    scope_id: str = "workspace:qwenpaw"
    timeout: float = 10.0


class PowerContextHTTPError(RuntimeError):
    """A safe, operation-scoped error returned by the PowerContext API.

    The response body is reduced to a short server-provided summary.  Headers
    (including the bearer token) and arbitrary response payloads are never
    included in the exception string.
    """

    def __init__(
        self, *, operation: str, response: httpx.Response, token: str = ""
    ) -> None:
        self.operation = operation
        self.status_code = response.status_code
        self.summary = _safe_error_summary(response, token=token)
        super().__init__(
            f"PowerContext {operation} failed with HTTP {self.status_code}: "
            f"{self.summary}"
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
        return summary.replace(token, "<redacted>")[:300] if token else summary[:300]
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
        self, *, kind: str, text: str, scope_id: str | None = None
    ) -> dict[str, Any]:
        response = await self._http.post(
            "/v1/memory/remember",
            json={
                "scope_id": scope_id or self.config.scope_id,
                "kind": kind,
                "text": text,
            },
        )
        self._raise_for_status("memory remember", response)
        return response.json()

    async def search(
        self, *, query: str, limit: int = 5, scope_id: str | None = None
    ) -> list[dict[str, Any]]:
        response = await self._http.post(
            "/v1/memory/search",
            json={
                "scope_id": scope_id or self.config.scope_id,
                "query": query,
                "limit": limit,
            },
        )
        self._raise_for_status("memory search", response)
        payload = response.json()
        return payload.get("hits", []) if isinstance(payload, dict) else []

    async def close(self) -> None:
        await self._http.aclose()

    def _raise_for_status(self, operation: str, response: httpx.Response) -> None:
        if response.is_error:
            raise PowerContextHTTPError(
                operation=operation, response=response, token=self.config.token
            )
