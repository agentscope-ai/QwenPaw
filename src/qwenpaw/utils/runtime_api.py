# -*- coding: utf-8 -*-
"""Endpoint discovery and request authentication for Hub local runtimes."""

from __future__ import annotations

import os

import httpx

from .http import is_loopback_host

_TOKEN_ENV = "QWENPAW_RUNTIME_INTERNAL_TOKEN"
_TOKEN_HEADER = "X-QwenPaw-Runtime-Token"


def _runtime_url() -> httpx.URL | None:
    """Read the endpoint supplied by Hub, never a user API override."""
    if not os.environ.get("QWENPAW_RUNTIME_ID") or not os.environ.get(
        _TOKEN_ENV,
    ):
        return None
    value = os.environ.get("QWENPAW_RUNTIME_API_URL")
    if not value:
        return None
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL:
        return None
    if url.scheme != "http" or not is_loopback_host(url.host):
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


def add_runtime_token(request: httpx.Request) -> None:
    """Scope the boundary token to each request, including redirects."""
    runtime = _runtime_url()
    if runtime is None:
        return
    target = request.url
    request.headers.pop(_TOKEN_HEADER, None)
    if (
        target.scheme == runtime.scheme
        and target.host == runtime.host
        and target.port == runtime.port
        and not target.userinfo
    ):
        request.headers[_TOKEN_HEADER] = os.environ[_TOKEN_ENV]


async def add_runtime_token_async(request: httpx.Request) -> None:
    """Apply the same boundary policy to asynchronous HTTP clients."""
    add_runtime_token(request)
