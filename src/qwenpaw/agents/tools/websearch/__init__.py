# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""Pluggable web search providers for the ``web_search`` tool.

``SearchProvider`` is the abstraction that lets QwenPaw swap the search
backend without touching the tool surface.  The active provider and any
provider API key are selected per-agent via Console tool configuration
(``BuiltinToolConfig.config`` for ``web_search``), not environment
variables.
"""

from __future__ import annotations

import asyncio
import logging
import re

from abc import ABC, abstractmethod

import httpx

from ....app.agent_context import get_current_agent_id
from ....config.config import load_agent_config
from ....config.context import get_current_workspace_dir
from ....drivers.credentials.store import AsyncCredentialStore
from ....drivers.credentials.types import CredentialRecord
from ....drivers.errors import CredentialNotFoundError

logger = logging.getLogger(__name__)

_TIMEOUT = 30


async def _post(
    url: str,
    headers: dict,
    payload: dict,
) -> dict:
    """Async HTTP POST with certificate validation always on."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()


def format_search_results(results: list[dict]) -> str:
    """Format search results into readable text."""
    if not results:
        return "No results found."
    lines: list[str] = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("url", "")
        content = r.get("content", "")
        lines.append(f"[{i}] {title}")
        lines.append(f"    URL: {url}")
        if content:
            lines.append(f"    {content}")
        lines.append("")
    return "\n".join(lines).rstrip()


class SearchProvider(ABC):
    """Abstract web search backend."""

    name = ""

    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        """Return a list of ``{title, url, snippet, content}`` dicts."""
        raise NotImplementedError


class TavilyProvider(SearchProvider):
    """Legacy Tavily keyless search backend."""

    name = "tavily"

    _SEARCH_URL = "https://api.tavily.com/search"

    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        payload = {
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
        }
        data = await _post(
            self._SEARCH_URL,
            headers={
                "Content-Type": "application/json",
                "X-Tavily-Access-Mode": "keyless",
            },
            payload=payload,
        )
        return list(data.get("results") or [])


async def _current_agent_anysearch_key() -> str:
    """Read the AnySearch API key from the current agent's credential store.

    Uses the same workspace resolution as other tools
    (``get_current_workspace_dir``), pointing at the same
    ``credentials.yaml`` that ``DriverConfigService``'s fallback path uses.
    """
    workspace_dir = get_current_workspace_dir()
    if not workspace_dir:
        return ""
    store = AsyncCredentialStore(workspace_dir / "credentials.yaml")
    try:
        record = await store.get("tool/web_search/anysearch")
    except CredentialNotFoundError:
        return ""
    return str(record.secrets.get("api_key") or "")


_CRED_LINE_RE = re.compile(
    r"^(username|password|api_key)=(.+?)\.?$",
    re.MULTILINE,
)


def _parse_auto_registered_credentials(message: str) -> dict[str, str]:
    """Parse an AnySearch 402 auto-registration message body.

    Example message body (``\\n``-separated, ``api_key`` line ends with a
    trailing sentence period that must be stripped)::

        "...\\nusername=as_auto_Zpq983GDZvsW\\npassword=UYt0NW6PtaKy\\n"
        "api_key=as_sk_00d83dc1b2f507950d7e5412952b5fdf."
    """
    return {m.group(1): m.group(2) for m in _CRED_LINE_RE.finditer(message)}


class AnySearchProvider(SearchProvider):
    """AnySearch REST search backend (https://api.anysearch.com)."""

    name = "anysearch"

    _SEARCH_URL = "https://api.anysearch.com/v1/search"
    _CREDENTIAL_REF = "tool/web_search/anysearch"

    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        headers = {"Content-Type": "application/json"}
        api_key = await _current_agent_anysearch_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "query": query,
            "max_results": max_results,
        }
        try:
            data = await _post(
                self._SEARCH_URL,
                headers=headers,
                payload=payload,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 402:
                data = await self._handle_quota_exceeded(
                    exc.response,
                    headers,
                    payload,
                )
            else:
                raise
        return list((data.get("data") or {}).get("results") or [])

    async def _handle_quota_exceeded(
        self,
        response: httpx.Response,
        headers: dict,
        payload: dict,
    ) -> dict:
        body = response.json()
        message = str(body.get("message") or "")

        if "automatically generated" in message:
            creds = _parse_auto_registered_credentials(message)
            new_key = creds.get("api_key", "")
            if not new_key:
                raise ValueError(
                    f"AnySearch quota response missing api_key: {message!r}",
                )

            workspace_dir = get_current_workspace_dir()
            if workspace_dir:
                store = AsyncCredentialStore(
                    workspace_dir / "credentials.yaml",
                )
                try:
                    await store.put(
                        CredentialRecord(
                            ref=self._CREDENTIAL_REF,
                            kind="static",
                            secrets={"api_key": new_key},
                        ),
                    )
                except Exception:
                    logger.warning(
                        "Failed to persist AnySearch credential; "
                        "using in-memory key for this call",
                    )

            retry_headers = dict(headers)
            retry_headers["Authorization"] = f"Bearer {new_key}"
            return await _post(
                self._SEARCH_URL,
                headers=retry_headers,
                payload=payload,
            )

        if "anonymous free quota" in message:
            await asyncio.sleep(1)
            try:
                return await _post(
                    self._SEARCH_URL,
                    headers=headers,
                    payload=payload,
                )
            except httpx.HTTPStatusError as retry_exc:
                retry_message = str(
                    retry_exc.response.json().get("message") or "",
                )
                raise ValueError(
                    f"AnySearch quota error "
                    f"({retry_exc.response.status_code}): {retry_message}",
                ) from retry_exc

        raise ValueError(
            f"AnySearch quota error ({response.status_code}): {message}",
        )


def get_search_provider() -> SearchProvider:
    """Return the active search provider from the current agent's Console
    tool configuration.

    Defaults to ``tavily`` (the keyless backend) when unset. Unknown
    values raise ``ValueError`` instead of silently routing.
    """
    agent_id = get_current_agent_id()
    try:
        config = load_agent_config(agent_id)
        tool_cfg = (
            config.tools.builtin_tools.get("web_search")
            if config.tools
            else None
        )
        choice = (
            str(tool_cfg.config.get("provider") or "").strip().lower()
            if tool_cfg
            else ""
        )
    except Exception:
        choice = ""
    if choice in {"", "tavily"}:
        return TavilyProvider()
    if choice == "anysearch":
        return AnySearchProvider()
    raise ValueError(
        f"Unknown web_search provider: {choice!r} "
        "(expected 'tavily' or 'anysearch')",
    )


__all__ = [
    "SearchProvider",
    "TavilyProvider",
    "AnySearchProvider",
    "get_search_provider",
    "format_search_results",
]
