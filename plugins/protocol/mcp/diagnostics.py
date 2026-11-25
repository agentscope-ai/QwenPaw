# -*- coding: utf-8 -*-
"""Route MCP source diagnostics through the host's SDK logger."""

from functools import partialmethod
from ssl import SSLCertVerificationError

import httpx
from mcp.shared.exceptions import McpError

# The public SDK exports StaleContextError lazily.
# pylint: disable-next=no-name-in-module
from qwenpaw.plugins import StaleContextError


class MCPLogger:
    def __init__(self, context):
        self._logger = context.logger
        self._fields = {
            "workspace_id": context.workspace_id,
            "source_id": context.source_id,
        }

    def _write(self, level, message, *args):
        try:
            getattr(self._logger, level)(
                message % args if args else message,
                fields=self._fields,
            )
        except StaleContextError:
            # A late cleanup log must not interrupt a retired generation.
            pass

    debug = partialmethod(_write, "debug")
    info = partialmethod(_write, "info")
    warning = partialmethod(_write, "warning")
    error = partialmethod(_write, "error")


def error_summary(error):
    """Keep useful failure codes without persisting exception payloads."""
    pending = [error]
    seen = set()
    details = []
    while pending and len(seen) < 8:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        detail = type(current).__name__
        if isinstance(current, httpx.HTTPStatusError):
            detail += f" (HTTP {current.response.status_code})"
        elif isinstance(current, McpError):
            detail += f" (JSON-RPC {current.error.code})"
        elif isinstance(current, SSLCertVerificationError):
            code = getattr(current, "verify_code", None)
            if isinstance(code, int):
                detail += f" (verify_code={code})"
        elif isinstance(current, OSError) and isinstance(current.errno, int):
            detail += f" (errno={current.errno})"
        details.append(detail)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(reversed(current.exceptions[:8]))
        cause = current.__cause__
        if cause is None and not current.__suppress_context__:
            cause = current.__context__
        if cause is not None:
            pending.append(cause)
    return " / ".join(details)
