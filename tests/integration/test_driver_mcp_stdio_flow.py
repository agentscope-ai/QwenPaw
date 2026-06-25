# -*- coding: utf-8 -*-
from pathlib import Path

import pytest

from qwenpaw.drivers.capabilities import DriverInvocation
from qwenpaw.drivers.contracts import CredentialRef, DriverCard, PolicyRule
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.credentials.types import CredentialRecord
from qwenpaw.drivers.handlers.mcp import MCPDriverHandler
from qwenpaw.drivers.manager import DriverManager
from qwenpaw.drivers.storage import card_path, dump_card
from tests.integration.driver_mcp_fakes import (
    FakeStdIOClient,
    patch_mcp_runtime_clients,
)


@pytest.mark.asyncio
async def test_driver_mcp_stdio_env_secret_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_mcp_runtime_clients(monkeypatch)
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    await store.put(
        CredentialRecord(
            ref="mcp/stdio_echo",
            kind="static",
            secrets={"ECHO_SECRET": "secret-value"},
        ),
    )
    dump_card(
        DriverCard(
            name="stdio_echo",
            protocol="mcp",
            endpoint={
                "transport": "stdio",
                "command": "python",
                "args": ["tests/fixtures/mcp/stdio_echo_server.py"],
                "env": {
                    "public": {"ECHO_PUBLIC_MODE": "test"},
                    "secret_refs": {"ECHO_SECRET": "ECHO_SECRET"},
                },
            },
            credentials={
                "default": CredentialRef("static", "mcp/stdio_echo"),
            },
            policy=[PolicyRule(subject="*", effect="allow")],
        ),
        card_path(tmp_path / "drivers", "stdio_echo", protocol="mcp"),
    )
    manager = DriverManager(tmp_path / "drivers", store)
    manager.register_handler_type("mcp", MCPDriverHandler)

    await manager.build_drivers()
    capability = next(
        item
        for item in await manager.list_capabilities(kind="tool")
        if item.name == "get_secret_status"
    )
    result = await manager.invoke_capability(
        DriverInvocation(
            capability_id=capability.capability_id,
            payload={},
            request_context={"session_id": "s1", "user_id": "user:alice"},
        ),
    )

    assert result.ok is True
    assert result.value == {"has_secret": True}
    assert FakeStdIOClient.instances[0].kwargs["env"] == {
        "ECHO_PUBLIC_MODE": "test",
        "ECHO_SECRET": "secret-value",
    }
