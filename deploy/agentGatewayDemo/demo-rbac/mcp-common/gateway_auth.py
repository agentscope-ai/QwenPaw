"""MCP 后端鉴权：open（无校验）/ protected（仅接受网关内部凭证）。"""

from __future__ import annotations

import argparse
import hmac
import os
import sys
from typing import Any

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

DEFAULT_HEADER = "x-gateway-token"


class GatewayTokenMiddleware:
    """ASGI wrapper: reject requests that lack the gateway-only credential."""

    def __init__(self, app: Any, expected: str, header_name: str = DEFAULT_HEADER) -> None:
        self.app = app
        self.expected = expected.encode("utf-8")
        self.header_name = header_name.lower()

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        provided = Headers(scope=scope).get(self.header_name)
        if provided is not None and provided.lower().startswith("bearer "):
            provided = provided[7:].strip()
        if provided is None or not hmac.compare_digest(provided.encode("utf-8"), self.expected):
            response = JSONResponse(
                {"error": "unauthorized", "detail": "missing or invalid gateway token"},
                status_code=401,
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_mcp_server(name: str, host: str, port: int, path: str) -> Any:
    """Create FastMCP (legacy) or MCPServer (current SDK)."""
    try:
        from mcp.server.fastmcp import FastMCP

        return FastMCP(name, host=host, port=port, streamable_http_path=path)
    except ImportError:
        from mcp.server.mcpserver import MCPServer

        return MCPServer(name)


def _streamable_app(mcp: Any, host: str, path: str) -> Any:
    try:
        return mcp.streamable_http_app(streamable_http_path=path, host=host)
    except TypeError:
        return mcp.streamable_http_app()


def run_mcp_http(
    mcp: Any,
    *,
    host: str,
    port: int,
    path: str,
    auth_mode: str,
    gateway_token: str,
    header_name: str = DEFAULT_HEADER,
) -> None:
    mode = (auth_mode or "open").strip().lower()
    if mode not in {"open", "protected"}:
        print(f"ERROR: unknown auth mode: {auth_mode}", file=sys.stderr)
        raise SystemExit(2)

    if mode == "open":
        print(f"  Auth: OPEN (no credential required)  bind={host}:{port}{path}")
        try:
            mcp.run(transport="streamable-http", host=host, port=port, streamable_http_path=path)
            return
        except TypeError:
            mcp.run(transport="streamable-http")
            return

    token = (gateway_token or "").strip()
    if not token:
        print("ERROR: protected mode requires a non-empty gateway token", file=sys.stderr)
        raise SystemExit(2)

    print(f"  Auth: PROTECTED (header {header_name})  bind={host}:{port}{path}")
    import uvicorn

    app = GatewayTokenMiddleware(
        _streamable_app(mcp, host, path),
        expected=token,
        header_name=header_name,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")


def add_auth_args(parser: argparse.ArgumentParser, default_token_env: str) -> None:
    parser.add_argument(
        "--auth-mode",
        choices=("open", "protected"),
        default=os.getenv("MCP_AUTH_MODE", "open"),
        help="open=no auth (phase A); protected=require gateway token (phase B)",
    )
    parser.add_argument(
        "--gateway-token-env",
        default=default_token_env,
        help="Environment variable that holds the gateway-only credential",
    )
    parser.add_argument(
        "--gateway-token-header",
        default=os.getenv("MCP_GATEWAY_TOKEN_HEADER", DEFAULT_HEADER),
        help="HTTP header name the gateway injects",
    )


def resolve_gateway_token(env_name: str) -> str:
    return (os.getenv(env_name) or "").strip()
