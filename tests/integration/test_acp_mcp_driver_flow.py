# -*- coding: utf-8 -*-
"""Integration coverage for ACP MCP cards through DriverManager."""

from __future__ import annotations

from pathlib import Path

import pytest
from acp.schema import EnvVariable, McpServerStdio

from qwenpaw.agents.acp.session_mcp import (
    acp_mcp_scope_id,
    build_acp_mcp_driver_cards,
)
from qwenpaw.drivers.capabilities import DriverInvocation
from qwenpaw.drivers.constants import DRIVER_SCOPE_CONTEXT_KEY
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.handlers.mcp import (
    MCPDriverHandler,
    validate_mcp_endpoint,
)
from qwenpaw.drivers.manager import DriverManager
from qwenpaw.drivers.policy import DriverInvocationContext
from tests.integration.driver_mcp_fakes import (
    FakeStdIOClient,
    patch_mcp_runtime_clients,
)


class _AutoApprovalGate:
    def __init__(self) -> None:
        self.contexts: list[DriverInvocationContext] = []

    async def request_approval(
        self,
        context: DriverInvocationContext,
    ) -> None:
        self.contexts.append(context)


@pytest.mark.p1
@pytest.mark.asyncio
async def test_acp_mcp_card_discovers_approves_and_invokes_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_mcp_runtime_clients(monkeypatch)
    gate = _AutoApprovalGate()
    manager = DriverManager(
        tmp_path / "drivers",
        AsyncCredentialStore(tmp_path / "credentials.yaml"),
        approval_gate=gate,
    )
    manager.register_handler_type(
        "mcp",
        MCPDriverHandler,
        validate_mcp_endpoint,
    )
    session_id = "session-1"
    scope_id = acp_mcp_scope_id(session_id)
    cards = build_acp_mcp_driver_cards(
        session_id,
        [
            McpServerStdio(
                name="benchmark",
                command="python",
                args=["server.py"],
                env=[
                    EnvVariable(
                        name="ECHO_SECRET",
                        value="session-secret",
                    ),
                ],
            ),
        ],
        session_cwd=str(tmp_path),
    )

    await manager.replace_transient_drivers(scope_id, cards)
    request_context = {
        DRIVER_SCOPE_CONTEXT_KEY: scope_id,
        "approval_level": "smart",
        "session_id": session_id,
        "user_id": "user:test",
    }
    capabilities = await manager.list_capabilities(
        kind="tool",
        request_context=request_context,
    )
    capability = next(
        item for item in capabilities if item.name == "get_secret_status"
    )

    result = await manager.invoke_capability(
        DriverInvocation(
            capability_id=capability.capability_id,
            payload={},
            request_context=request_context,
        ),
    )

    assert result.ok is True
    assert result.value == {"has_secret": True}
    assert len(gate.contexts) == 1
    assert gate.contexts[0].target.name == "get_secret_status"
    assert FakeStdIOClient.instances[0].kwargs["env"] == {
        "ECHO_SECRET": "session-secret",
    }
    assert await manager.card_store.list_paths() == []


@pytest.mark.p1
@pytest.mark.asyncio
async def test_acp_mcp_tool_cannot_be_invoked_without_session_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_mcp_runtime_clients(monkeypatch)
    manager = DriverManager(
        tmp_path / "drivers",
        AsyncCredentialStore(tmp_path / "credentials.yaml"),
    )
    manager.register_handler_type(
        "mcp",
        MCPDriverHandler,
        validate_mcp_endpoint,
    )
    scope_id = acp_mcp_scope_id("session-1")
    cards = build_acp_mcp_driver_cards(
        "session-1",
        [
            McpServerStdio(
                name="benchmark",
                command="python",
                args=["server.py"],
                env=[],
            ),
        ],
        session_cwd=str(tmp_path),
    )
    await manager.replace_transient_drivers(scope_id, cards)
    capability = (
        await manager.list_capabilities(
            kind="tool",
            request_context={DRIVER_SCOPE_CONTEXT_KEY: scope_id},
        )
    )[0]

    result = await manager.invoke_capability(
        DriverInvocation(
            capability_id=capability.capability_id,
            payload={"value": "blocked"},
            request_context={},
        ),
    )

    assert result.ok is False
    assert result.error_type == "driver_scope_mismatch"
