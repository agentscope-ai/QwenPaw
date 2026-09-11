# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""AnySearch REST search backend (https://api.anysearch.com)."""

from __future__ import annotations

import asyncio
import logging
import re
import threading

import httpx

from ....config.context import get_current_workspace_dir
from ....drivers.credentials.store import AsyncCredentialStore
from ....drivers.credentials.types import CredentialRecord
from ....drivers.errors import CredentialNotFoundError
from .base import SearchProvider, _post

logger = logging.getLogger(__name__)

_CREDENTIAL_REF = "tool/web_search/anysearch"

# mtime-keyed cache for the per-agent AnySearch key: the credential YAML is
# re-read (and re-decrypted) only when the file changes, mirroring the agent
# config cache in config.utils.
_key_cache: dict[str, tuple[float, str]] = {}
_key_cache_lock = threading.RLock()


async def _current_agent_anysearch_key() -> str:
    """Read the AnySearch API key from the current agent's credential store.

    Uses the same workspace resolution as other tools
    (``get_current_workspace_dir``), pointing at the same
    ``credentials.yaml`` that ``DriverConfigService``'s fallback path uses.
    """
    workspace_dir = get_current_workspace_dir()
    if not workspace_dir:
        return ""
    path = workspace_dir / "credentials.yaml"
    try:
        current_mtime = path.stat().st_mtime
    except OSError:
        current_mtime = 0.0
    cache_key = str(path)
    with _key_cache_lock:
        cached = _key_cache.get(cache_key)
        if cached is not None and cached[0] == current_mtime:
            return cached[1]
    store = AsyncCredentialStore(path)
    try:
        record = await store.get(_CREDENTIAL_REF)
        key = str(record.secrets.get("api_key") or "")
    except CredentialNotFoundError:
        key = ""
    with _key_cache_lock:
        _key_cache[cache_key] = (current_mtime, key)
    return key


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
                            ref=_CREDENTIAL_REF,
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


__all__ = [
    "AnySearchProvider",
    "_current_agent_anysearch_key",
    "_parse_auto_registered_credentials",
]
