#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal MCP stdio server for integration testing.

Exposes a single tool ``ping`` that returns ``pong``.
Designed to be launched as a subprocess via stdio transport.
"""
import asyncio

from mcp.server import Server
from mcp import types


def build_server() -> Server:
    app = Server("test-mcp-server")

    @app.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="ping",
                description="Returns pong — used for health-check testing",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    @app.call_tool()
    async def _call_tool(
        name: str,
        _arguments: dict,
    ) -> list[types.TextContent]:
        if name == "ping":
            return [types.TextContent(type="text", text="pong")]
        raise ValueError(f"Unknown tool: {name}")

    return app


async def main() -> None:
    from mcp.server.stdio import stdio_server

    app = build_server()
    options = app.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, options)


if __name__ == "__main__":
    asyncio.run(main())
