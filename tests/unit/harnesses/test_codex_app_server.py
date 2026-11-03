# -*- coding: utf-8 -*-
"""Tests for Codex app-server JSON-RPC request handling."""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.harnesses.codex.app_server import (
    CodexAppServerClient,
    _STDIO_STREAM_LIMIT_BYTES,
)


@pytest.mark.asyncio
async def test_server_request_handler_returns_decision() -> None:
    client = CodexAppServerClient()
    client._send = AsyncMock()  # type: ignore[method-assign]
    handler = AsyncMock(return_value={"decision": "accept"})
    client.set_server_request_handler(handler)
    message = {
        "id": 7,
        "method": "item/commandExecution/requestApproval",
        "params": {"command": "pytest"},
    }

    await client._dispatch(message)

    handler.assert_awaited_once_with(message)
    client._send.assert_awaited_once_with(
        {"id": 7, "result": {"decision": "accept"}},
    )


@pytest.mark.asyncio
async def test_app_server_uses_large_bounded_stdio_limit(monkeypatch) -> None:
    stream = SimpleNamespace(readline=AsyncMock(return_value=b""))
    process = SimpleNamespace(
        returncode=None,
        stdin=SimpleNamespace(),
        stdout=stream,
        stderr=stream,
    )
    create = AsyncMock(return_value=process)
    monkeypatch.setattr(
        "qwenpaw.harnesses.codex.app_server.resolve_codex_binary_info",
        lambda _binary: SimpleNamespace(path=Path("/tmp/codex")),
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    client = CodexAppServerClient()
    client.request = AsyncMock(return_value={})  # type: ignore[method-assign]
    client.notify = AsyncMock()  # type: ignore[method-assign]

    await client.start()
    await asyncio.sleep(0)

    assert create.await_args.kwargs["limit"] == _STDIO_STREAM_LIMIT_BYTES
