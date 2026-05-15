# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Compatibility patches for MCP streamable HTTP transport."""

from __future__ import annotations

import inspect
from typing import Any

import mcp.client.streamable_http as _streamable_http_mod
from mcp.shared.message import SessionMessage
from mcp.types import (
    ErrorData,
    INTERNAL_ERROR,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCRequest,
    RequestId,
)


async def _send_status_error(
    read_stream_writer: Any,
    request_id: RequestId,
    status_code: int,
) -> None:
    """Send an HTTP status failure as a JSON-RPC response error."""
    await read_stream_writer.send(
        SessionMessage(
            JSONRPCMessage(
                JSONRPCError(
                    jsonrpc="2.0",
                    id=request_id,
                    error=ErrorData(
                        code=INTERNAL_ERROR,
                        message=(
                            f"MCP streamable HTTP server returned "
                            f"HTTP {status_code}."
                        ),
                    ),
                ),
            ),
        ),
    )


def _needs_status_error_patch() -> bool:
    """Return True when the installed MCP SDK lacks the >=400 fix."""
    try:
        source = inspect.getsource(
            _streamable_http_mod.StreamableHTTPTransport._handle_post_request,
        )
    except (OSError, TypeError):
        return True
    return "response.status_code >= 400" not in source


async def _handle_post_request_with_status_errors(
    self: Any,
    ctx: Any,
) -> None:
    """Backport MCP SDK's fail-fast handling for HTTP >=400 responses."""
    headers = self._prepare_headers()
    message = ctx.session_message.message
    root = getattr(message, "root", message)
    is_initialization = self._is_initialization_request(message)

    async with ctx.client.stream(
        "POST",
        self.url,
        json=message.model_dump(by_alias=True, mode="json", exclude_none=True),
        headers=headers,
    ) as response:
        if response.status_code == 202:
            _streamable_http_mod.logger.debug("Received 202 Accepted")
            return

        if response.status_code == 404:
            if isinstance(root, JSONRPCRequest):
                await self._send_session_terminated_error(
                    ctx.read_stream_writer,
                    root.id,
                )
            return

        if response.status_code >= 400:
            # Keep setup failures as HTTP exceptions so QwenPaw's connect
            # path can surface OAuth/setup errors immediately. Normal request
            # failures are returned to the waiting request as JSON-RPC errors.
            if is_initialization:
                response.raise_for_status()
            if isinstance(root, JSONRPCRequest):
                await _send_status_error(
                    ctx.read_stream_writer,
                    root.id,
                    response.status_code,
                )
            return

        response.raise_for_status()
        if is_initialization:
            self._maybe_extract_session_id_from_response(response)

        if isinstance(root, JSONRPCRequest):
            content_type = response.headers.get(
                _streamable_http_mod.CONTENT_TYPE,
                "",
            ).lower()
            if content_type.startswith(_streamable_http_mod.JSON):
                await self._handle_json_response(
                    response,
                    ctx.read_stream_writer,
                    is_initialization,
                )
            elif content_type.startswith(_streamable_http_mod.SSE):
                await self._handle_sse_response(
                    response,
                    ctx,
                    is_initialization,
                )
            else:
                await self._handle_unexpected_content_type(
                    content_type,
                    ctx.read_stream_writer,
                )


def apply_streamable_http_error_patch() -> None:
    """Patch old MCP SDK versions so HTTP errors do not hang requests."""
    if not _needs_status_error_patch():
        return
    _streamable_http_mod.StreamableHTTPTransport._handle_post_request = (
        _handle_post_request_with_status_errors
    )
