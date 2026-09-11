# -*- coding: utf-8 -*-
"""Endpoint discovery and request authentication for Hub local runtimes."""

from __future__ import annotations

import ipaddress
from functools import partial

import httpx

from ..constant import EnvVarLoader
from .http import trust_env_for_url

_TOKEN_ENV = "QWENPAW_RUNTIME_INTERNAL_TOKEN"
_TOKEN_HEADER = "X-QwenPaw-Runtime-Token"


def _runtime_url() -> httpx.URL | None:
    """Read the endpoint supplied by Hub, never a user API override."""
    runtime_id = EnvVarLoader.get_str("QWENPAW_RUNTIME_ID")
    if not runtime_id or not EnvVarLoader.get_str(_TOKEN_ENV):
        return None
    value = EnvVarLoader.get_str("QWENPAW_RUNTIME_API_URL")
    if not value:
        return None
    try:
        url = httpx.URL(value)
        address = ipaddress.ip_address(url.host)
    except (httpx.InvalidURL, ValueError):
        return None
    if url.scheme != "http" or not address.is_loopback:
        return None
    if url.userinfo or url.path != "/" or url.query or url.fragment:
        return None
    return url


def read_runtime_api() -> tuple[str, int] | None:
    """Return the managed runtime address, or preserve standalone defaults."""
    url = _runtime_url()
    if url is None:
        return None
    host = f"[{url.host}]" if ":" in url.host else url.host
    return host, url.port or 80


def _same_origin(target: httpx.URL, runtime: httpx.URL) -> bool:
    """Compare the transport endpoint without accepting URL credentials."""
    return (
        target.scheme == runtime.scheme
        and target.host == runtime.host
        and target.port == runtime.port
        and not target.userinfo
    )


def _add_runtime_token(
    request: httpx.Request,
    *,
    base_url: httpx.URL,
) -> None:
    """Authenticate only requests from a trusted, direct runtime client."""
    runtime = _runtime_url()
    if runtime is None:
        return
    target = request.url
    request.headers.pop(_TOKEN_HEADER, None)
    if _same_origin(base_url, runtime) and _same_origin(target, runtime):
        request.headers[_TOKEN_HEADER] = EnvVarLoader.get_str(_TOKEN_ENV)


async def _add_runtime_token_async(
    request: httpx.Request,
    *,
    base_url: httpx.URL,
) -> None:
    """Apply the same boundary policy to asynchronous HTTP clients."""
    _add_runtime_token(request, base_url=base_url)


def api_client(
    base_url: str,
    *,
    timeout: float = 30.0,
    trust_env: bool = True,
) -> httpx.Client:
    """Bind auth to the endpoint; loopback always bypasses env proxies."""
    return httpx.Client(
        base_url=base_url,
        timeout=timeout,
        trust_env=trust_env and trust_env_for_url(base_url),
        event_hooks={
            "request": [
                partial(_add_runtime_token, base_url=httpx.URL(base_url)),
            ],
        },
    )


def async_api_client(
    base_url: str,
    *,
    timeout: float | httpx.Timeout = 30.0,
) -> httpx.AsyncClient:
    """Create an async client with the same direct-runtime policy."""
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=timeout,
        trust_env=trust_env_for_url(base_url),
        event_hooks={
            "request": [
                partial(
                    _add_runtime_token_async,
                    base_url=httpx.URL(base_url),
                ),
            ],
        },
    )
