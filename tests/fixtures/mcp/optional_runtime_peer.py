# -*- coding: utf-8 -*-
"""Real local MCP peer and OAuth provider used by cold-process acceptance."""

import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

transport, port, evidence = sys.argv[1:]
mcp = FastMCP("optional-runtime-peer", host="127.0.0.1", port=int(port))


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
    mcp.run(transport=transport)
