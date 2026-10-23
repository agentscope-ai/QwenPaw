"""Native test platform copied into a normal third-party child artifact."""

import asyncio
import hmac
import json
import os
from pathlib import Path
import traceback

from aiohttp import WSMsgType, web

from qwenpaw.channel_protocol.models import EndpointParams


class Listener:
    def __init__(self, driver):
        self.driver = driver
        self.runner = None
        self.runners = []
        self.site = None
        self.binding = None
        self.public_base_url = None
        self.rows = []
        self.websockets = set()
        self.emit_report = None
        self.release = asyncio.Event()

    async def start(self, operation="register"):
        app = web.Application(client_max_size=2 * 1024 * 1024)
        app.router.add_route("*", "/sample/{tail:.*}", self.handle)
        self.runner = web.AppRunner(app)
        self.runners.append(self.runner)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        await self.report_endpoint(operation)

    async def report_endpoint(self, operation):
        endpoint = EndpointParams.from_mapping(
            {
                **self.driver._context.identity.to_mapping(),
                "protocol": "http+ws",
                "host": "127.0.0.1",
                "port": self.site._server.sockets[0].getsockname()[1],
                "path": "/sample",
                "public_base_url": self.public_base_url,
                "readiness": "ready",
                "bound_externally": False,
                "auth_required": True,
                "quiescing": False,
            }
        )
        result = await self.driver._context.peer.call(
            "ingress.endpoint." + operation,
            endpoint.to_mapping(),
        )
        self.binding = result["forwarding"]
        self.port = endpoint.port

    async def stop(self):
        self.release.set()
        for websocket in tuple(self.websockets):
            await websocket.close(code=1001, message=b"listener stop")
        for runner in self.runners:
            await runner.cleanup()
        self.runners.clear()
        self.runner = None

    async def control(self, params, _request):
        action = params.get("action", "inspect")
        if action == "body_count":
            expected = (bytes([params["byte"]]) * params["size"]).hex()
            return {
                "exact_body_count": sum(
                    row.get("body_hex") == expected for row in self.rows
                )
            }
        if action == "ws_emit_report":
            return self.emit_report
        if action == "ws_emit":
            selected = tuple(self.websockets)
            self.emit_report = {
                "attempt_id": params.get("attempt_id"),
                "kind": params["kind"],
                "size": params["size"],
                "selected_socket_ids": [id(socket) for socket in selected],
                "attempts": [],
            }
            for socket in selected:
                binary = params["kind"] == "binary"
                data = (b"z" if binary else "é") * params["size"]
                attempt = {
                    "socket_id": id(socket),
                    "open_before": not socket.closed,
                    "payload_bytes": len(data if binary else data.encode()),
                    "completed": False,
                }
                self.emit_report["attempts"].append(attempt)
                try:
                    if binary:
                        await socket.send_bytes(data)
                    else:
                        await socket.send_str(data)
                    attempt["completed"] = True
                except Exception as error:
                    # Passive fixture evidence: preserve the original error
                    # through the real control RPC and its original assertions.
                    evidence = {
                        "pid": os.getpid(),
                        "kind": params["kind"],
                        "size": params["size"],
                        "socket_count": len(self.websockets),
                        "socket_closed": socket.closed,
                        "close_code": socket.close_code,
                        "exception_type": type(error).__qualname__,
                        "exception_module": type(error).__module__,
                        "exception": str(error)[:2048],
                        "traceback": traceback.format_exc(limit=12)[-12000:],
                    }
                    attempt["error"] = evidence
                    try:
                        root = Path(self.driver._config["workspace_dir"])
                        (root / "g4-ws-emit-diagnostic.json").write_text(
                            json.dumps(evidence, indent=2)
                        )
                    except (KeyError, OSError):
                        pass
                    raise
            return {"sockets": len(selected)}
        if action == "release":
            self.release.set()
        elif action == "rebind":
            # Keep the old listener alive: only host revision fencing may
            # terminate its forwarded connection during this operation.
            await self.start("update")
        elif action == "canonical":
            self.public_base_url = params["public_base_url"]
            await self.report_endpoint("update")
        elif action == "crash":
            os._exit(47)
        return {
            "pid": os.getpid(),
            "port": self.port,
            "forwarding": self.binding,
            "rows": self.rows,
            "ws_count": len(self.websockets),
        }

    async def handle(self, request):
        authenticated = hmac.compare_digest(
            request.headers.get("X-Qwenpaw-Ingress-Token", ""),
            self.binding["bridge_token"],
        )
        if not authenticated:
            return web.Response(status=401)
        row = {
            "method": request.method,
            "raw_path": request.raw_path,
            "query": list(request.query.items()),
            "headers": [
                [key.decode("latin1"), value.decode("latin1")]
                for key, value in request.raw_headers
                if key.lower() != b"x-qwenpaw-ingress-token"
            ],
            "authenticated": authenticated,
        }
        self.rows.append(row)
        if request.path == "/sample/ws-reject":
            return web.Response(status=403, text="handshake denied")
        if request.path == "/sample/ws":
            socket = web.WebSocketResponse(protocols=("sample.v1",))
            await socket.prepare(request)
            self.websockets.add(socket)
            try:
                async for message in socket:
                    if message.type == WSMsgType.TEXT:
                        if message.data == "close":
                            await socket.close(code=1000, message=b"done")
                        else:
                            await socket.send_str(message.data)
                    elif message.type == WSMsgType.BINARY:
                        await socket.send_bytes(message.data)
            finally:
                self.websockets.discard(socket)
            return socket
        body = await request.read()
        row["body_hex"] = body.hex()
        if request.path == "/sample/signature":
            from twilio.request_validator import RequestValidator

            form = await request.post()
            valid = RequestValidator("local-test-auth-token").validate(
                request.headers["X-Qwenpaw-Ingress-Original-URL"],
                form,
                request.headers.get("X-Twilio-Signature", ""),
            )
            return web.Response(status=200 if valid else 403, text="signed")
        if request.path == "/sample/hold":
            await self.release.wait()
        if request.path == "/sample/redirect":
            return web.Response(
                status=307, headers={"Location": "/sample/target"}
            )
        return web.Response(
            status=201,
            body=body,
            headers=[
                ("Content-Type", "application/x-test"),
                ("X-Reply", "first"),
                ("X-Reply", "second"),
            ],
        )
