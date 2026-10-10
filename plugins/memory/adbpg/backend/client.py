# -*- coding: utf-8 -*-
"""REST client owned by the memory-adbpg plugin."""

import logging
from dataclasses import dataclass

import httpx

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
        """Submit memories and propagate failures to the task worker.

        A successful response acknowledges the submission; server-side
        extraction may continue asynchronously after this method returns.
        """
        body: dict = {
            "messages": messages,
            **self._identity(agent_id or "", user_id),
        }
        if run_id:
            body["run_id"] = run_id
        if metadata:
            body["metadata"] = metadata

        url = self._url("/v3/memories/add/")
        self._log_rest_request("POST", "add_memory")
        try:
            resp = await self._http_client.post(
                url,
                headers=self._rest_headers,
                json=body,
                timeout=max(self._rest_timeout, 30.0),
            )
            resp.raise_for_status()
            logger.debug(
                "ADBPG REST request succeeded: operation=add_memory status=%s",
                resp.status_code,
            )
        except Exception as e:
            logger.error(
                "ADBPG REST request failed: operation=add_memory "
                "error_type=%s",
                type(e).__name__,
            )
            # The manager records message IDs only after this call succeeds.
            # Swallowing a rejection would mark unsaved messages as persisted
            # and prevent a later submission from retrying them.
            raise

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

        The current REST search endpoint filters by identity fields
        (``agent_id`` and ``user_id``). ``run_id`` is accepted for API
        compatibility with add operations, but is not sent as a search
        filter.
        """
        _ = run_id

        body: dict = {
            "query": query,
            "filters": self._identity(agent_id or "", user_id),
            "top_k": limit,
        }

        url = self._url("/v3/memories/search/")
        req_timeout = timeout or self._rest_timeout
        self._log_rest_request("POST", "search_memory")
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
                logger.warning("ADBPG REST memory search timed out")
            else:
                logger.error(
                    "ADBPG REST request failed: operation=search_memory "
                    "error_type=%s",
                    type(e).__name__,
                )
            return []

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http_client.aclose()

    def _url(self, path: str) -> str:
        return f"{self._config.rest_base_url.rstrip('/')}{path}"

    @staticmethod
    def _identity(agent_id: str, user_id: str) -> dict:
        """Common identity fields for REST requests."""
        identity: dict = {}
        if agent_id:
            identity["agent_id"] = agent_id
        if user_id:
            identity["user_id"] = user_id
        return identity

    @staticmethod
    def _log_rest_request(method: str, operation: str) -> None:
        """Log non-sensitive metadata for an outgoing REST request."""
        logger.debug(
            "ADBPG REST request: method=%s operation=%s",
            method,
            operation,
        )
