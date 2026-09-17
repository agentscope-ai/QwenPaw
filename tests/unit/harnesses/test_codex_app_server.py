# -*- coding: utf-8 -*-
"""Tests for Codex app-server JSON-RPC request handling."""

# pylint: disable=protected-access

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from qwenpaw.harnesses.codex.app_server import CodexAppServerClient


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
