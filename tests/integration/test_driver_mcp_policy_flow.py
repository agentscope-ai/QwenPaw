# -*- coding: utf-8 -*-
import asyncio
from pathlib import Path

import pytest

from qwenpaw.app.approvals.driver_gate import QwenPawDriverApprovalGate
from qwenpaw.app.approvals.service import ApprovalService
from qwenpaw.drivers.capabilities import DriverInvocation
from qwenpaw.drivers.contracts import DriverCard, PolicyRule
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.handlers.mcp import MCPDriverHandler
from qwenpaw.drivers.manager import DriverManager
from qwenpaw.drivers.storage import card_path, dump_card
from qwenpaw.security.tool_guard.approval import ApprovalDecision
from tests.integration.driver_mcp_fakes import (
    FakeStdIOClient,
    patch_mcp_runtime_clients,
)


async def _registry_with_policy(
    tmp_path: Path,
    policy: list[PolicyRule],
) -> DriverManager:
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    dump_card(
        DriverCard(
            name="policy_echo",
            protocol="mcp",
            endpoint={"transport": "stdio", "command": "python"},
            policy=policy,
        ),
        card_path(tmp_path / "drivers", "policy_echo", protocol="mcp"),
    )
    manager = DriverManager(
        tmp_path / "drivers",
        store,
        approval_gate=QwenPawDriverApprovalGate(),
    )
    manager.register_handler_type("mcp", MCPDriverHandler)
    await manager.build_drivers()
    return manager


async def _next_pending_request(
    service: ApprovalService,
    task: asyncio.Task,
):
    # pylint: disable=protected-access
    for _ in range(1000):
        if service._pending:
            return next(iter(service._pending.values()))
        if task.done():
            result = await task
            raise AssertionError(
                "Driver invocation completed before creating approval "
                f"request: {result}",
            )
        await asyncio.sleep(0)
    raise AssertionError("Timed out waiting for approval request")


@pytest.mark.asyncio
async def test_driver_mcp_policy_deny_blocks_client_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_mcp_runtime_clients(monkeypatch)
    manager = await _registry_with_policy(
        tmp_path,
        [PolicyRule(subject="*", effect="deny")],
    )
    capability = next(
        item
        for item in await manager.list_capabilities(kind="tool")
        if item.name == "echo"
    )
    result = await manager.invoke_capability(
        DriverInvocation(
            capability.capability_id,
            {"text": "blocked"},
            {"session_id": "s1"},
        ),
    )

    assert result.error_type == "driver_policy_denied"
    assert FakeStdIOClient.instances[0].calls == []


@pytest.mark.asyncio
async def test_driver_mcp_policy_ask_approve_resumes_client_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_mcp_runtime_clients(monkeypatch)
    service = ApprovalService()
    monkeypatch.setattr(
        "qwenpaw.app.approvals.get_approval_service",
        lambda: service,
    )
    manager = await _registry_with_policy(
        tmp_path,
        [PolicyRule(subject="*", effect="ask")],
    )
    capability = next(
        item
        for item in await manager.list_capabilities(kind="tool")
        if item.name == "echo"
    )
    task = asyncio.create_task(
        manager.invoke_capability(
            DriverInvocation(
                capability.capability_id,
                {"text": "ok"},
                {"session_id": "s1", "agent_id": "agent", "user_id": "alice"},
            ),
        ),
    )

    pending = await _next_pending_request(service, task)
    assert pending.result_summary == (
        "Tool 'echo' from 'mcp:policy_echo' requires approval for invoke."
    )
    assert pending.extra["display"] == {
        "tool_name": "echo",
        "tool_source": "mcp:policy_echo",
    }
    await service.resolve_request(
        pending.request_id,
        ApprovalDecision.APPROVED,
    )
    result = await task

    assert result.ok is True
    assert result.value == {"echo": {"text": "ok"}}
    assert FakeStdIOClient.instances[0].calls == [("echo", {"text": "ok"})]
