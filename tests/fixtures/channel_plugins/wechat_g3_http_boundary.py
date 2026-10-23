"""External HTTP substitution with a passive real-client close witness."""

import asyncio
import json
import os
from pathlib import Path

import httpx


def install(host, port, ledger):
    def observe(kind, **values):
        with Path(ledger).open("a") as stream:
            stream.write(
                json.dumps({"kind": kind, "pid": os.getpid(), **values}) + "\n"
            )

    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            row = {
                "pid": os.getpid(),
                "url": str(request.url),
                "method": request.method,
                "headers": dict(request.headers),
                "body": (await request.aread()).decode(),
                "timeout": request.extensions.get("timeout"),
            }
            observe("request", url=row["url"])
            reader, writer = await asyncio.open_connection(host, port)
            body = json.dumps(row).encode()
            try:
                writer.write(
                    b"POST /platform HTTP/1.1\r\nHost: localhost\r\n"
                    + f"Content-Length: {len(body)}\r\n".encode()
                    + b"Connection: close\r\n\r\n"
                    + body
                )
                await writer.drain()
                await reader.readuntil(b"\r\n\r\n")
                response = json.loads(await reader.read())
                if response.get("fault") == "transport":
                    raise httpx.ConnectError(
                        "controlled external failure", request=request
                    )
                return httpx.Response(
                    response.get("status", 200),
                    json=response["body"],
                    request=request,
                )
            finally:
                writer.close()
                await writer.wait_closed()

        async def aclose(self):
            await super().aclose()
            observe("transport.closed")

    original = httpx.AsyncClient

    class Client(original):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = Transport()
            kwargs["trust_env"] = False
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = Client
