# -*- coding: utf-8 -*-
"""Cache and compression policy for content-hashed Console assets."""

from __future__ import annotations

from pathlib import Path

from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"
_COMPRESSIBLE_SUFFIXES = frozenset(
    {
        ".css",
        ".csv",
        ".html",
        ".js",
        ".json",
        ".map",
        ".mjs",
        ".svg",
        ".txt",
        ".wasm",
        ".xml",
    },
)


def _is_compressible_path(path: str) -> bool:
    return Path(path).suffix.lower() in _COMPRESSIBLE_SUFFIXES


def _accepts_gzip(headers: Headers) -> bool:
    """Return whether ``Accept-Encoding`` explicitly permits gzip."""
    for item in headers.get("accept-encoding", "").split(","):
        coding, *parameters = (part.strip() for part in item.split(";"))
        if coding.lower() != "gzip":
            continue
        quality = 1.0
        for parameter in parameters:
            name, separator, value = parameter.partition("=")
            if separator and name.strip().lower() == "q":
                try:
                    quality = float(value.strip())
                except ValueError:
                    quality = 0.0
        return quality > 0
    return False


class _ImmutableStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code in {200, 206, 304}:
            response.headers["Cache-Control"] = ASSET_CACHE_CONTROL
        return response


class ConsoleAssetFiles:
    """Serve hashed Console assets.

    Applies immutable caching and selective gzip compression.
    """

    def __init__(
        self,
        directory: str,
        *,
        gzip_minimum_size: int = 1024,
        gzip_compresslevel: int = 6,
    ) -> None:
        self._files = _ImmutableStaticFiles(directory=directory)
        self._gzip_files = GZipMiddleware(
            self._files,
            minimum_size=gzip_minimum_size,
            compresslevel=gzip_compresslevel,
        )

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        headers = Headers(scope=scope)
        is_compressible = _is_compressible_path(
            str(scope.get("path", "")),
        )

        async def send_with_vary(message) -> None:
            if message["type"] == "http.response.start" and message[
                "status"
            ] in {200, 206, 304}:
                response_headers = MutableHeaders(
                    scope=message,
                )
                vary_values = {
                    value.strip().lower()
                    for value in response_headers.get("vary", "").split(",")
                }
                if "accept-encoding" not in vary_values:
                    response_headers.add_vary_header("Accept-Encoding")
                etag = response_headers.get("etag")
                if (
                    message["status"] in {200, 304}
                    and etag
                    and etag[:2] != "W/"
                ):
                    # Identity and gzip share one opaque validator. Mark it
                    # weak because their representation bytes differ.
                    response_headers["etag"] = f"W/{etag}"
            await send(message)

        asset_send = send_with_vary if is_compressible else send
        should_compress = (
            scope.get("method") == "GET"
            and is_compressible
            and _accepts_gzip(headers)
            and "range" not in headers
        )
        if not should_compress:
            await self._files(scope, receive, asset_send)
            return

        # FileResponse may delegate directly to servers that advertise
        # pathsend. Remove that optional fast path only for gzip responses so
        # the middleware always receives the file bytes to compress.
        extensions = dict(scope.get("extensions") or {})
        if "http.response.pathsend" in extensions:
            extensions.pop("http.response.pathsend")
            scope = {**scope, "extensions": extensions}
        await self._gzip_files(scope, receive, asset_send)
