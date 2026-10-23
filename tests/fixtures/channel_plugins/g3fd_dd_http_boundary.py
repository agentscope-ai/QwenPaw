"""Child-only external HTTP transport; real httpx client/cookies stay intact."""
import asyncio
import json
import importlib.abc
import sys
import os

import httpx


def install(host, port, forbid_lark=False):
    if forbid_lark:

        class Guard(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "lark_oapi" or fullname.startswith(
                    "lark_oapi."
                ):
                    raise AssertionError("STATIC_MANAGEMENT_IMPORTED_LARK")

        sys.meta_path.insert(0, Guard())

    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            reader, writer = await asyncio.open_connection(host, port)
            body = json.dumps(
                {
                    "pid": os.getpid(),
                    "sdk_guard_active": forbid_lark,
                    "lark_modules": [
                        name
                        for name in sys.modules
                        if name == "lark_oapi" or name.startswith("lark_oapi.")
                    ],
                    "platform_imported": "feishu.platform" in sys.modules,
                    "url": str(request.url),
                    "method": request.method,
                    "headers": dict(request.headers),
                    "body": (await request.aread()).decode(),
                }
            ).encode()
            try:
                writer.write(
                    b"POST /platform HTTP/1.1\r\nHost: localhost\r\n"
                    + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                    + body
                )
                await writer.drain()
                await reader.readuntil(b"\r\n\r\n")
                response = json.loads(await reader.read())
                if response.get("transport_error") == "read":
                    raise httpx.ReadError(
                        "fixture network failure", request=request
                    )
                return httpx.Response(
                    response.get("status_code", 200),
                    headers=response.get("headers", {}),
                    json=response["body"],
                    request=request,
                )
            finally:
                writer.close()
                await writer.wait_closed()

    original = httpx.AsyncClient

    class Client(original):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = Transport()
            kwargs["trust_env"] = False
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = Client
