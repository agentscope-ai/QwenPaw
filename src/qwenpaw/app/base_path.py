# -*- coding: utf-8 -*-
"""Mount the HTTP application and its prebuilt console below one URL prefix."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import unquote

from fastapi import Response
from fastapi.responses import FileResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_BASE_HREF_TOKEN = b'<base href="/" />'
_BASE_PATH_JSON_TOKEN = b'window.__qpBase = "";'


def normalize_base_path(value: str | None) -> str:
    """Return a canonical absolute path prefix, or an empty root prefix."""
    path = (value or "").strip()
    if not path or path == "/":
        return ""
    if not path.startswith("/"):
        raise ValueError("QWENPAW_BASE_PATH must start with '/'")
    if any(char in path for char in ("?", "#", "\\")):
        raise ValueError(
            "QWENPAW_BASE_PATH must be a URL path without query or fragment",
        )
    path = path.rstrip("/")
    segments = [unquote(segment) for segment in path.split("/")[1:]]
    if any(
        segment in ("", ".", "..") or "/" in segment or "\\" in segment
        for segment in segments
    ):
        raise ValueError("QWENPAW_BASE_PATH contains an invalid path segment")
    return path


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
    """Serve the small HTML entry with its two explicit deployment tokens set."""

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
        content = await asyncio.to_thread(Path(self.path).read_bytes)
        base_href = f'<base href="{self.base_path}/">'
        content = content.replace(_BASE_HREF_TOKEN, base_href.encode("utf-8"))
        runtime_config = f"window.__qpBase = {json.dumps(self.base_path)};"
        content = content.replace(
            _BASE_PATH_JSON_TOKEN,
            runtime_config.encode("utf-8"),
        )
        self.body = content
        self.headers["content-length"] = str(len(content))
        await Response.__call__(self, scope, receive, send)
