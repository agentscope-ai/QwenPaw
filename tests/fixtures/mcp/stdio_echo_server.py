# -*- coding: utf-8 -*-
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("qwenpaw-stdio-echo")


@mcp.tool()
def echo(text: str) -> str:
    return text


@mcp.tool()
def get_secret_status() -> dict[str, bool]:
    return {"has_secret": bool(os.environ.get("ECHO_SECRET"))}


if __name__ == "__main__":
    mcp.run()
