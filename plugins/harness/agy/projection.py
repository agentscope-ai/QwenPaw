# -*- coding: utf-8 -*-
"""Project QwenPaw MCP servers into ACP session parameters."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from acp.schema import (
    EnvVariable,
    HttpHeader,
    HttpMcpServer,
    McpServerStdio,
    SseMcpServer,
)

from qwenpaw.plugins.harnesses import HarnessRuntimeCapabilities

logger = logging.getLogger(__name__)

# ACP has no working directory for an MCP server, and the CLI starts one in
# the session's directory. A server configured with its own directory is
# started through this: change there, then become the server.
_RUN_IN_DIRECTORY = (
    "import os, sys; os.chdir(sys.argv[1]); "
    "os.execvp(sys.argv[2], sys.argv[2:])"
)


def mcp_servers(
    capabilities: HarnessRuntimeCapabilities,
    *,
    allow_http: bool = True,
    allow_sse: bool = True,
) -> list[Any]:
    """Convert resolved MCP servers to ACP ``mcpServers`` entries.

    ACP has no per-tool policy, so a server is passed whole or not at all:
    one whose default policy is "deny" is passed only when it names the
    tools it allows, as the other backends do. HTTP and SSE transports are
    included only when the ACP server advertised support for them during
    ``initialize``.
    """
    result: list[Any] = []
    for server in capabilities.mcp_servers:
        if server.tools is None and server.default_policy == "deny":
            continue
        if server.transport == "stdio":
            command, args = _in_directory(
                server.cwd,
                server.command,
                list(server.args),
            )
            result.append(
                McpServerStdio(
                    name=server.name,
                    command=command,
                    args=args,
                    env=[
                        EnvVariable(name=key, value=value)
                        for key, value in server.revealed_env().items()
                    ],
                ),
            )
            continue
        headers = [
            HttpHeader(name=key, value=value)
            for key, value in server.revealed_headers().items()
        ]
        if server.transport == "streamable_http":
            if not allow_http:
                logger.debug(
                    "agy: skipping HTTP MCP server %s (not supported by ACP "
                    "server)",
                    server.name,
                )
                continue
            result.append(
                HttpMcpServer(
                    name=server.name,
                    url=server.url,
                    headers=headers,
                    type="http",
                ),
            )
        else:
            if not allow_sse:
                logger.debug(
                    "agy: skipping SSE MCP server %s (not supported by ACP "
                    "server)",
                    server.name,
                )
                continue
            result.append(
                SseMcpServer(
                    name=server.name,
                    url=server.url,
                    headers=headers,
                    type="sse",
                ),
            )
    return result


def _in_directory(
    directory: Path | None,
    command: str,
    args: list[str],
) -> tuple[str, list[str]]:
    """The command line that runs ``command`` in ``directory``."""
    if directory is None:
        return command, args
    return sys.executable, [
        "-c",
        _RUN_IN_DIRECTORY,
        str(directory),
        command,
        *args,
    ]


__all__ = ["mcp_servers"]
