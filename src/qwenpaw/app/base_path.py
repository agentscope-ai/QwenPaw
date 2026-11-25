# -*- coding: utf-8 -*-
"""Mount the HTTP application and its prebuilt console below one URL prefix."""
from __future__ import annotations

import asyncio
import json
import os
from html import escape
from pathlib import Path
from unicodedata import category
from urllib.parse import unquote

from fastapi import Response
from fastapi.responses import FileResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_BASE_HREF_TOKEN = b'<base href="/" />'
_BASE_PATH_JSON_TOKEN = b'window.__qpBase = "";'
_BASE_PATH_ENV = "QWENPAW_BASE_PATH"
_server_base_path: str | None = None


def normalize_base_path(value: str | None) -> str:
    """Return a canonical absolute path prefix, or an empty root prefix."""
    raw_path = value or ""
    if any(category(char) == "Cc" for char in raw_path):
        raise ValueError(
            "QWENPAW_BASE_PATH must not contain control characters",
        )
    path = raw_path.strip()
    if not path or path == "/":
        return ""
    if not path.startswith("/"):
        raise ValueError("QWENPAW_BASE_PATH must start with '/'")
    if any(char in path for char in ("?", "#", "\\")):
        raise ValueError(
            "QWENPAW_BASE_PATH must be a URL path without query or fragment",
        )
    if "%" in path:
        raise ValueError(
            "QWENPAW_BASE_PATH must use decoded path segments, not percent encoding",
        )
    path = path.rstrip("/")
    if path and path[-1].isspace():
        raise ValueError(
            "QWENPAW_BASE_PATH must not end with whitespace after removing trailing slashes",
        )
    segments = [unquote(segment) for segment in path.split("/")[1:]]
    if any(
        segment in ("", ".", "..") or "/" in segment or "\\" in segment
        for segment in segments
    ):
        raise ValueError("QWENPAW_BASE_PATH contains an invalid path segment")
    return path


def initialize_server_base_path() -> str:
    """Resolve the serving process's prefix after loading startup settings."""
    global _server_base_path  # pylint: disable=global-statement
    _server_base_path = normalize_base_path(os.environ.get(_BASE_PATH_ENV))
    return _server_base_path


def get_runtime_base_path() -> str:
    """Use the active server mount, or the environment in standalone callers."""
    if _server_base_path is not None:
        return _server_base_path
    return normalize_base_path(os.environ.get(_BASE_PATH_ENV))


class BasePathMiddleware:
    """Accept one configured prefix and expose unprefixed routes to FastAPI."""

    def __init__(self, app: ASGIApp, base_path: str | None = None) -> None:
        self.app = app
        self.base_path = normalize_base_path(base_path)

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if not self.base_path or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path == self.base_path and scope["type"] == "http":
            query = scope.get("query_string", b"").decode("latin-1")
            suffix = f"?{query}" if query else ""
            response = RedirectResponse(f"{self.base_path}/{suffix}")
            await response(scope, receive, send)
            return
        if path != self.base_path and not path.startswith(
            f"{self.base_path}/",
        ):
            response = Response(status_code=404)
            await response(scope, receive, send)
            return

        child_scope = dict(scope)
        child_scope["root_path"] = (
            scope.get("root_path", "").rstrip("/") + self.base_path
        )
        await self.app(child_scope, receive, send)


class ConsoleIndexResponse(FileResponse):
    """Serve the entry file unchanged unless a deployment prefix is set."""

    def __init__(
        self,
        path: str | Path,
        *,
        base_path: str | None = None,
        **kwargs,
    ):
        self.base_path = normalize_base_path(base_path)
        super().__init__(path, media_type="text/html", **kwargs)

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if not self.base_path:
            await super().__call__(scope, receive, send)
            return

        content = await asyncio.to_thread(Path(self.path).read_bytes)
        base_href = f'<base href="{escape(self.base_path, quote=True)}/">'
        content = content.replace(_BASE_HREF_TOKEN, base_href.encode("utf-8"))
        base_path_json = (
            json.dumps(self.base_path)
            .replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")
        )
        runtime_config = f"window.__qpBase = {base_path_json};"
        content = content.replace(
            _BASE_PATH_JSON_TOKEN,
            runtime_config.encode("utf-8"),
        )
        self.body = content
        self.headers["content-length"] = str(len(content))
        await Response.__call__(self, scope, receive, send)
