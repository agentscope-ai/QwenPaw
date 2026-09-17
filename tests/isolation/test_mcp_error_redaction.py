# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.drivers.capabilities import DriverInvocation, format_capability_id
from qwenpaw.drivers.contracts import DriverCard
from qwenpaw.drivers.credentials.providers import NoneProvider
from qwenpaw.drivers.handlers.mcp import MCPDriverHandler


@pytest.mark.asyncio
async def test_mcp_invocation_failure_uses_fixed_safe_message(caplog):
    leaked = "synthetic-token C:/private/host/path"
    handler = MCPDriverHandler(
        DriverCard(
            name="safe",
            protocol="mcp",
            endpoint={"transport": "stdio", "command": "safe"},
        ),
        NoneProvider(),
    )

    async def fail(*_args, **_kwargs):
        raise RuntimeError(leaked)

    handler._guarded_execute = fail
    result = await handler.invoke_capability(
        DriverInvocation(
            capability_id=format_capability_id(
                "mcp", "safe", "tool", "invoke", "lookup"
            ),
            payload={},
            request_context={"channel": "console", "user_id": "user"},
        )
    )
    assert result.ok is False
    assert result.message == "mcp_tool_execution_failed"
    assert leaked not in caplog.text
