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


class PowerContextMemoryClient:
    def __init__(self, config: PowerContextConfig) -> None:
        self.config = config
        headers = {"Authorization": f"Bearer {config.token}"} if config.token else {}
        self._http = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            headers=headers,
            timeout=config.timeout,
        )

    async def remember(self, *, kind: str, text: str, scope_id: str | None = None) -> dict[str, Any]:
        response = await self._http.post(
            "/v1/memory/remember",
            json={"scope_id": scope_id or self.config.scope_id, "kind": kind, "text": text},
        )
        response.raise_for_status()
        return response.json()

    async def search(self, *, query: str, limit: int = 5, scope_id: str | None = None) -> list[dict[str, Any]]:
        response = await self._http.post(
            "/v1/memory/search",
            json={"scope_id": scope_id or self.config.scope_id, "query": query, "limit": limit},
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("hits", []) if isinstance(payload, dict) else []

    async def close(self) -> None:
        await self._http.aclose()
