# -*- coding: utf-8 -*-
"""Local MCP peer and OAuth provider for the two plugin acceptance flows."""

import asyncio
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs

import uvicorn

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

transport, port, evidence = sys.argv[1:]
mcp = FastMCP("optional-runtime-peer", host="127.0.0.1", port=int(port))
_sessions = {}
_requests = []
_admission = {"blocked": False, "deny": False}


class _ObserveSessions:
    """Record real handshake/termination responses without changing streams."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        authorization = headers.get(b"authorization")
        if scope["path"] == "/mcp":
            _requests.append((authorization or b"").decode())
            if scope["method"] == "POST":
                while _admission["blocked"]:
                    await asyncio.sleep(0.01)
                if _admission["deny"]:
                    return await JSONResponse({}, status_code=403)(
                        scope,
                        receive,
                        send,
                    )

        async def observed(message):
            if message["type"] == "http.response.start":
                status = message["status"]
                session_id = dict(message["headers"]).get(b"mcp-session-id")
                if session_id and 200 <= status < 300:
                    _sessions.setdefault(
                        session_id,
                        {
                            "authorization": authorization,
                            "delete": None,
                        },
                    )
                if scope["method"] == "DELETE":
                    row = _sessions.get(headers.get(b"mcp-session-id"))
                    if row is not None:
                        row["delete"] = {
                            "status": status,
                            "auth_matches": authorization
                            == row["authorization"],
                        }
            await send(message)

        await self.app(scope, receive, observed)


@mcp.custom_route("/control", methods=["POST"])
async def control(request):
    _admission.update(await request.json())
    return JSONResponse(_admission)


@mcp.custom_route("/requests", methods=["GET"])
async def requests(_request):
    return JSONResponse(_requests)


@mcp.custom_route("/sessions", methods=["GET"])
async def sessions(_request):
    return JSONResponse(
        [
            {
                "terminated": mcp.session_manager._server_instances[
                    session_id.decode()
                ].is_terminated,
                "delete": row["delete"],
            }
            for session_id, row in _sessions.items()
        ],
    )


@mcp.tool()
def echo(text: str) -> str:
    """Return the supplied string through real JSON-RPC."""
    return text


@mcp.tool()
def process_info() -> dict:
    """Return controlled process identity for ownership and cwd assertions."""
    return {
        "pid": os.getpid(),
        "cwd": os.getcwd(),
        "has_controlled_env": os.environ.get("MCP_CONTROLLED_ENV")
        == "present",
    }


@mcp.custom_route("/oauth/token", methods=["POST"])
async def token(request):
    body = parse_qs((await request.body()).decode())
    assert body["grant_type"] == ["authorization_code"]
    assert body["code"] == ["controlled-code"]
    assert body["client_id"] == ["controlled-client"]
    assert body.get("code_verifier")
    Path(evidence).write_text(json.dumps({"token_requests": 1, "pkce": True}))
    return JSONResponse(
        {
            "access_token": "controlled-access-token",
            "refresh_token": "controlled-refresh-token",
            "expires_in": 3600,
            "scope": "read",
        },
    )


if __name__ == "__main__":
    if transport == "streamable-http":
        app = mcp.streamable_http_app()
        app.add_middleware(_ObserveSessions)
        uvicorn.run(app, host="127.0.0.1", port=int(port), log_level="warning")
    else:
        mcp.run(transport=transport)
