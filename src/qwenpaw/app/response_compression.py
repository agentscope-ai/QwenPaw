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
        if scope[f"type"] != f"http":
            await self.app(scope, receive, send)
            return

        accepts_gzip = False
        encodings = Headers(scope=scope).get(f"accept-encoding", f"")
        for entry in encodings.split(f","):
            parts = entry.strip().lower().split(f";")
            if parts[0] == f"gzip":
                quality = 1.0
                for parameter in parts[1:]:
                    key, _, value = parameter.strip().partition(f"=")
                    if key == f"q":
                        try:
                            quality = float(value)
                        except ValueError:
                            quality = 0.0
                accepts_gzip = quality > 0

        start: Message | None = None

        async def send_response(message: Message) -> None:
            nonlocal start
            if message[f"type"] == f"http.response.start":
                start = message
                return
            if start is not None:
                headers = MutableHeaders(scope=start)
                content_type = headers.get(f"content-type", f"")
                media_type = content_type.split(f";", 1)[0].strip().lower()
                body = message.get(f"body", b"")
                eligible = (
                    message[f"type"] == f"http.response.body"
                    and not message.get(f"more_body", False)
                    and start[f"status"] == 200
                    and len(body) >= self.minimum_size
                    and media_type in {f"application/json", f"text/plain"}
                    and f"content-encoding" not in headers
                    and f"content-disposition" not in headers
                    and f"content-range" not in headers
                )
                if eligible:
                    headers.add_vary_header(f"Accept-Encoding")
                    if accepts_gzip:
                        body = await asyncio.to_thread(
                            gzip.compress,
                            body,
                            compresslevel=6,
                        )
                        headers[f"content-encoding"] = f"gzip"
                        headers[f"content-length"] = f"{len(body)}"
                        message = {**message, f"body": body}
                await send(start)
                start = None
            await send(message)

        await self.app(scope, receive, send_response)
