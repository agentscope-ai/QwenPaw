"""Child-only HTTP transport preserving the native HTTPX client behavior."""

import asyncio
import json
import os

import httpx


def install(host, port):
    class Transport(httpx.AsyncBaseTransport):
        def __init__(self, follow_redirects):
            self.follow_redirects = follow_redirects

        async def handle_async_request(self, request):
            reader, writer = await asyncio.open_connection(host, port)
            payload = json.dumps(
                {
                    "pid": os.getpid(),
                    "url": str(request.url),
                    "method": request.method,
                    "headers": dict(request.headers),
                    "body": (await request.aread()).decode(),
                    "timeout": request.extensions.get("timeout"),
                    "follow_redirects": self.follow_redirects,
                }
            ).encode()
            try:
                writer.write(
                    b"POST /platform HTTP/1.1\r\nHost: localhost\r\n"
                    + f"Content-Length: {len(payload)}\r\n".encode()
                    + b"Connection: close\r\n\r\n"
                    + payload
                )
                await writer.drain()
                await reader.readuntil(b"\r\n\r\n")
                response = json.loads(await reader.read())
                content = (
                    {"text": response["text"]}
                    if "text" in response
                    else {"json": response["body"]}
                )
                return httpx.Response(
                    response.get("status_code", 200),
                    headers=response.get("headers", {}),
                    request=request,
                    **content,
                )
            finally:
                writer.close()
                await writer.wait_closed()

    original = httpx.AsyncClient

    class Client(original):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = Transport(
                kwargs.get("follow_redirects", False)
            )
            kwargs["trust_env"] = False
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = Client
