# -*- coding: utf-8 -*-
"""Endpoint discovery and request authentication for managed local runtimes."""

from __future__ import annotations

import ipaddress
import re
import hashlib
import secrets
from contextlib import contextmanager
from functools import partial
from threading import Lock
from typing import Iterator, Mapping

import httpx
from starlette.requests import HTTPConnection

from ..constant import EnvVarLoader
from .http import trust_env_for_url

_TOKEN_ENV = "QWENPAW_RUNTIME_INTERNAL_TOKEN"
_TOKEN_HEADER = "X-QwenPaw-Runtime-Token"
TOOL_TOKEN_ENV = _TOKEN_ENV
TOOL_ORIGIN_ENV = "QWENPAW_RUNTIME_API_URL"
TOOL_SESSION_HEADER = _TOKEN_HEADER
TOOL_RUNTIME_ID = "desktop-tool"
TOOL_ENV_KEYS = ("QWENPAW_RUNTIME_ID", TOOL_ORIGIN_ENV, TOOL_TOKEN_ENV)


def _runtime_url() -> httpx.URL | None:
    """Read a managed endpoint, never a user API override."""
    from ..tauri.env import get_desktop_session

    session = get_desktop_session()
    if session is not None:
        return httpx.URL(session[0])
    runtime_id = EnvVarLoader.get_str("QWENPAW_RUNTIME_ID")
    value = EnvVarLoader.get_str("QWENPAW_RUNTIME_API_URL")
    if not runtime_id or not EnvVarLoader.get_str(_TOKEN_ENV) or not value:
        return None
    try:
        url = httpx.URL(value)
        address = ipaddress.ip_address(url.host)
    except (httpx.InvalidURL, ValueError):
        return None
    invalid_endpoint = url.scheme != "http" or not address.is_loopback
    if (
        invalid_endpoint
        or url.userinfo
        or url.path != "/"
        or url.query
        or url.fragment
    ):
        return None
    if runtime_id == TOOL_RUNTIME_ID and (
        url.host != "127.0.0.1"
        or not url.port
        or not re.fullmatch(
            r"[A-Za-z0-9_-]{43}",
            EnvVarLoader.get_str(_TOKEN_ENV),
        )
    ):
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
    from ..tauri.env import DESKTOP_SESSION_HEADER, get_desktop_session

    request.headers.pop(DESKTOP_SESSION_HEADER, None)
    request.headers.pop(_TOKEN_HEADER, None)
    session = get_desktop_session()
    if session is not None:
        origin, token = session
        runtime = httpx.URL(origin)
        if _same_origin(base_url, runtime) and _same_origin(
            request.url,
            runtime,
        ):
            request.headers[DESKTOP_SESSION_HEADER] = token
        return
    runtime = _runtime_url()
    if runtime is None:
        return
    if EnvVarLoader.get_str(
        "QWENPAW_RUNTIME_ID",
    ) == TOOL_RUNTIME_ID and not request.url.path.startswith("/api/"):
        return
    target = request.url
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


# HTTP operations used by the existing CLI. Borrowed tool credentials do not
# authorize MCP configuration, approval, files, WebSockets or arbitrary routes.
_CLI_ROUTES = (
    ("GET|HEAD", r"/api/(?:version|healthz|doctor/runtime)"),
    ("GET", r"/api/workspace/commands/available"),
    ("GET|POST", r"/api/cron/jobs"),
    ("GET|PUT|DELETE", r"/api/cron/jobs/[^/]+"),
    ("GET", r"/api/cron/jobs/[^/]+/state"),
    ("POST", r"/api/cron/jobs/[^/]+/(?:pause|resume|run)"),
    ("GET|POST", r"/api/crons/jobs"),
    ("DELETE", r"/api/crons/jobs/[^/]+"),
    ("GET|POST", r"/api/chats"),
    ("GET|PUT|DELETE", r"/api/chats/[^/]+"),
    ("GET", r"/api/agents"),
    ("GET|DELETE", r"/api/agents/[^/]+"),
    ("POST", r"/api/console/chat(?:/stop|/task)?"),
    ("GET", r"/api/console/chat/task/[^/]+"),
    ("POST", r"/api/fork/agent"),
    ("POST", r"/api/messages/send"),
    ("POST", r"/api/(?:api/)?chat/send"),
    ("POST", r"/api/plugins/(?:install|upload)"),
    ("DELETE", r"/api/plugins/[^/]+"),
)
_CLI_PATTERNS = tuple(
    (frozenset(methods.split("|")), re.compile(path))
    for methods, path in _CLI_ROUTES
)
_active_tools: dict[bytes, tuple[str, str]] = {}
_tool_lock = Lock()


@contextmanager
def tool_api_environment(base: Mapping[str, str]) -> Iterator[dict[str, str]]:
    """Lend runtime authentication to one authorized tool call."""
    from ..tauri.env import DESKTOP_SESSION_ENV, get_desktop_session

    child = dict(base)
    child.pop(DESKTOP_SESSION_ENV, None)
    identity = get_desktop_session()
    if identity or child.get("QWENPAW_RUNTIME_ID") == TOOL_RUNTIME_ID:
        for name in TOOL_ENV_KEYS:
            child.pop(name, None)
    if identity is None:
        yield child
        return
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode("ascii")).digest()
    with _tool_lock:
        _active_tools[digest] = identity
    child.update(
        {
            "QWENPAW_RUNTIME_ID": TOOL_RUNTIME_ID,
            TOOL_ORIGIN_ENV: identity[0],
            TOOL_TOKEN_ENV: token,
        },
    )
    try:
        yield child
    finally:
        with _tool_lock:
            _active_tools.pop(digest, None)
        for name in TOOL_ENV_KEYS:
            child.pop(name, None)


def verify_tool_session(request: HTTPConnection) -> bool:
    """Validate a live per-call credential and its CLI method/path scope."""
    from ..tauri.env import get_desktop_session

    if request.scope["type"] != "http":
        return False
    method, path = request.scope.get("method"), request.scope.get("path", "")
    if (
        "\\" in path
        or any(part in (".", "..") for part in path.split("/"))
        or not any(
            method in methods and pattern.fullmatch(path)
            for methods, pattern in _CLI_PATTERNS
        )
    ):
        return False
    values = request.headers.getlist(TOOL_SESSION_HEADER)
    if len(values) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{43}", values[0]):
        return False
    identity = get_desktop_session()
    if identity is None or request.headers.get("host") != identity[0][7:]:
        return False
    origin = request.headers.get("origin")
    if origin is not None and origin != identity[0]:
        return False
    digest = hashlib.sha256(values[0].encode("ascii")).digest()
    with _tool_lock:
        return _active_tools.get(digest) == identity
