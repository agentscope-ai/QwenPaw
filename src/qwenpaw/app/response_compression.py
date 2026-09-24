# -*- coding: utf-8 -*-
"""Compress complete JSON and text responses without delaying streams."""

import asyncio
import gzip

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class ResponseCompressionMiddleware:
    """Offload compression and leave downloads and streaming bodies alone."""

    def __init__(self, app: ASGIApp, minimum_size: int = 1000) -> None:
        self.app = app
        self.minimum_size = minimum_size

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        qualities: dict[str, float] = {}
        encodings = ",".join(
            Headers(scope=scope).getlist("accept-encoding"),
        )
        for entry in encodings.split(","):
            parts = entry.strip().lower().split(";")
            encoding = parts[0].strip()
            if encoding in {"gzip", "*"}:
                quality = 1.0
                for parameter in parts[1:]:
                    key, _, value = parameter.strip().partition("=")
                    if key == "q":
                        try:
                            quality = float(value)
                        except ValueError:
                            quality = 0.0
                qualities[encoding] = quality
        # An explicit gzip preference takes precedence over the wildcard.
        accepts_gzip = qualities.get("gzip", qualities.get("*", 0.0)) > 0

        start: Message | None = None

        async def send_response(message: Message) -> None:
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
                return
            if start is not None:
                headers = MutableHeaders(scope=start)
                content_type = headers.get("content-type", "")
                media_type = content_type.split(";", 1)[0].strip().lower()
                body = message.get("body", b"")
                eligible = (
                    message["type"] == "http.response.body"
                    and not message.get("more_body", False)
                    and start["status"] == 200
                    and len(body) >= self.minimum_size
                    and media_type in {"application/json", "text/plain"}
                    and "content-encoding" not in headers
                    and "content-disposition" not in headers
                    and "content-range" not in headers
                )
                if eligible:
                    headers.add_vary_header("Accept-Encoding")
                    if accepts_gzip:
                        body = await asyncio.to_thread(
                            gzip.compress,
                            body,
                            compresslevel=6,
                        )
                        headers["content-encoding"] = "gzip"
                        headers["content-length"] = f"{len(body)}"
                        message = {**message, "body": body}
                await send(start)
                start = None
            await send(message)

        await self.app(scope, receive, send_response)
