# -*- coding: utf-8 -*-
"""REST client for ADBPG memory storage."""

import json
import logging
from dataclasses import dataclass

import httpx

from ...memory_scope.models import MemoryScopeDenied

logger = logging.getLogger(__name__)


@dataclass
class ADBPGConfig:
    """ADBPG REST API configuration."""

    rest_base_url: str
    rest_api_key: str
    search_timeout: float = 10.0


class ADBPGMemoryClient:
    """Async ADBPG memory client using the REST API."""

    def __init__(self, config: ADBPGConfig):
        """Initialize the client.

        Args:
            config: ADBPG REST API configuration.
        """
        self._config = config
        self._rest_headers = {
            "Authorization": f"Token {config.rest_api_key}",
            "Content-Type": "application/json",
        }
        self._rest_timeout = config.search_timeout
        self._http_client = httpx.AsyncClient(follow_redirects=True)

    async def add_memory(
        self,
        messages: list[dict],
        user_id: str = "",
        run_id: str | None = None,
        agent_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Store memories via REST API."""
        identity = self._private_identity(
            agent_id=agent_id or "",
            user_id=user_id,
            run_id=run_id or "",
        )
        body: dict = {
            "messages": messages,
            "agent_id": identity["agent_id"],
            "user_id": identity["user_id"],
            "run_id": identity["run_id"],
        }
        if metadata:
            body["metadata"] = metadata

        url = self._url("/v3/memories/add/")
        self._log_rest_curl("POST", url, body)
        try:
            resp = await self._http_client.post(
                url,
                headers=self._rest_headers,
                json=body,
                timeout=max(self._rest_timeout, 30.0),
            )
            resp.raise_for_status()
            logger.debug("REST add_memory result: %s", resp.text[:500])
        except Exception as e:
            logger.error("REST add_memory failed: %s", e)

    async def search_memory(
        self,
        query: str,
        user_id: str = "",
        run_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 5,
        timeout: float | None = None,
    ) -> list[dict]:
        """Search memories via REST API.

        权限过滤使用 ``agent_id + user_id``；``run_id`` 作为顶层审计字段，
        不限制跨会话长期记忆检索。
        """
        identity = self._private_identity(
            agent_id=agent_id or "",
            user_id=user_id,
            run_id=run_id or "",
        )

        body: dict = {
            "query": query,
            "filters": {
                "agent_id": identity["agent_id"],
                "user_id": identity["user_id"],
            },
            "run_id": identity["run_id"],
            "top_k": limit,
        }

        url = self._url("/v3/memories/search/")
        req_timeout = timeout or self._rest_timeout
        self._log_rest_curl("POST", url, body)
        try:
            resp = await self._http_client.post(
                url,
                headers=self._rest_headers,
                json=body,
                timeout=req_timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                return data.get("results", [])
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            error_str = str(e).lower()
            if "timeout" in error_str:
                logger.warning(
                    "REST memory search timed out for query: %r",
                    query,
                )
            else:
                logger.error("REST search_memory failed: %s", e)
            return []

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http_client.aclose()

    def _url(self, path: str) -> str:
        return f"{self._config.rest_base_url.rstrip('/')}{path}"

    @staticmethod
    def _private_identity(
        *,
        agent_id: str,
        user_id: str,
        run_id: str,
    ) -> dict[str, str]:
        """校验私有记忆请求的完整可信身份，禁止 shared 回退。"""
        agent_id = str(agent_id or "").strip()
        user_id = str(user_id or "").strip()
        run_id = str(run_id or "").strip()
        if not user_id:
            raise MemoryScopeDenied("authenticated_user_required")
        if not agent_id:
            raise MemoryScopeDenied("agent_id_required")
        if not run_id:
            raise MemoryScopeDenied("run_id_required")
        if "shared" in {agent_id.lower(), user_id.lower(), run_id.lower()}:
            raise MemoryScopeDenied("shared_identity_denied")
        return {
            "agent_id": agent_id,
            "user_id": user_id,
            "run_id": run_id,
        }

    def _log_rest_curl(self, method: str, url: str, body: dict) -> None:
        """Log an equivalent curl command for debugging REST calls."""
        header_parts = []
        for key, value in self._rest_headers.items():
            if key.lower() == "content-type":
                continue
            if key.lower() == "authorization":
                header_parts.append(f"-H '{key}: {value[:12]}***'")
            else:
                header_parts.append(f"-H '{key}: {value}'")
        logger.debug(
            "curl -X %s '%s' -H 'Content-Type: application/json' %s -d '%s'",
            method,
            url,
            " ".join(header_parts),
            json.dumps(body, ensure_ascii=False)[:2000],
        )
