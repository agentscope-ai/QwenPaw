# -*- coding: utf-8 -*-
"""Tests for QwenPaw's streamable HTTP MCP compatibility patch."""

import importlib

import httpx
import pytest

from mcp.client.streamable_http import (
    RequestContext,
    StreamableHTTPTransport,
)
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCError, JSONRPCMessage, JSONRPCRequest

# Importing this package applies the streamable HTTP compatibility patch.
importlib.import_module("qwenpaw.app.mcp")


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self._request = httpx.Request("POST", "https://mcp.example.test")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self._request,
                response=httpx.Response(
                    self.status_code,
                    request=self._request,
                ),
            )


class _FakeStream:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, *_exc_info) -> None:
        return None


class _FakeClient:
    def __init__(self, status_code: int) -> None:
        self.response = _FakeResponse(status_code)

    def stream(self, *_args, **_kwargs) -> _FakeStream:
        return _FakeStream(self.response)


class _FakeWriter:
    def __init__(self) -> None:
        self.messages = []

    async def send(self, message) -> None:
        self.messages.append(message)


def _request_context(method: str, writer: _FakeWriter) -> RequestContext:
    message = JSONRPCMessage(
        JSONRPCRequest(
            jsonrpc="2.0",
            id=1,
            method=method,
        ),
    )
    return RequestContext(
        client=_FakeClient(401),
        session_id=None,
        session_message=SessionMessage(message),
        metadata=None,
        read_stream_writer=writer,
    )


@pytest.mark.asyncio
async def test_streamable_http_http_error_returns_jsonrpc_error():
    writer = _FakeWriter()
    transport = StreamableHTTPTransport("https://mcp.example.test")

    await transport._handle_post_request(  # pylint: disable=protected-access
        _request_context("tools/call", writer),
    )

    assert len(writer.messages) == 1
    root = writer.messages[0].message.root
    assert isinstance(root, JSONRPCError)
    assert root.id == 1
    assert root.error.code == -32603
    assert "HTTP 401" in root.error.message


@pytest.mark.asyncio
async def test_streamable_http_initialization_http_error_still_raises():
    writer = _FakeWriter()
    transport = StreamableHTTPTransport("https://mcp.example.test")

    with pytest.raises(httpx.HTTPStatusError):
        # pylint: disable=protected-access
        await transport._handle_post_request(
            _request_context("initialize", writer),
        )

    assert not writer.messages
