# -*- coding: utf-8 -*-
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("qwenpaw-http-echo")


@mcp.tool()
def echo_http(text: str) -> str:
    return text


@mcp.tool()
def inspect_headers() -> dict[str, str]:
    # FastMCP tool functions do not receive raw HTTP headers directly in this
    # simple fixture; E2E tests that need header assertions use fake clients.
    return {"status": "headers inspected by fake client"}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
