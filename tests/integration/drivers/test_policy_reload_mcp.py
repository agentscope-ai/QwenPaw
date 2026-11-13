# -*- coding: utf-8 -*-
"""Use real stdio MCP traffic to verify stale reload policy enforcement."""

import asyncio
import copy
import sys
from pathlib import Path

import pytest

from qwenpaw.drivers.capabilities import (
    DriverInvocation,
    DriverInvocationResult,
)
from qwenpaw.drivers.contracts import DriverCard, DriverPolicy
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.errors import DriverCardError
from qwenpaw.drivers.handler import DriverHandler
from qwenpaw.drivers.handlers.mcp import (
    MCPDriverHandler,
    validate_mcp_endpoint,
)
from qwenpaw.drivers.manager import DriverManager

_SERVER = """from pathlib import Path
from mcp.server.fastmcp import FastMCP
server = FastMCP("reload-fixture")
@server.tool(annotations={"readOnlyHint": True})
def echo(value: str) -> str:
    with Path("calls.txt").open("a") as output:
        output.write(value + "\\n")
    return value
server.run()
"""


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.p1
async def test_deny_ack_survives_reload_with_real_mcp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_home: Path,
) -> None:
    """A completed deny keeps both the live handler and disk authoritative."""
    del isolated_home
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(tmp_path))
    server = tmp_path / "server.py"
    server.write_text(_SERVER, encoding="utf-8")
    calls = tmp_path / "calls.txt"
    manager = DriverManager(
        tmp_path / "drivers",
        AsyncCredentialStore(tmp_path / "credentials.yaml"),
    )
    manager.register_handler_type(
        "mcp",
        MCPDriverHandler,
        validate_mcp_endpoint,
    )
    card = DriverCard(
        name="reload-fixture",
        protocol="mcp",
        endpoint={
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(server)],
            "cwd": str(tmp_path),
        },
        policy=DriverPolicy(default_effect="allow"),
    )
    initialized, release = asyncio.Event(), asyncio.Event()
    real_build = manager._build_and_init_handler
    candidates = []
    reloading = None

    async def paused_build(candidate: DriverCard) -> DriverHandler:
        # Only publication timing is controlled; connection and calls are real.
        handler = await real_build(candidate)
        candidates.append(handler)
        initialized.set()
        try:
            await release.wait()
        except BaseException:
            await manager._shutdown_handler(handler)
            raise
        return handler

    try:
        await asyncio.wait_for(manager.register_driver(card), timeout=20)
        capabilities = await manager.list_driver_capabilities(card.name)
        assert len(capabilities) == 1
        capability_id = capabilities[0].capability_id

        async def invoke(value: str) -> DriverInvocationResult:
            return await asyncio.wait_for(
                manager.invoke_capability(
                    DriverInvocation(capability_id, {"value": value}),
                ),
                timeout=10,
            )

        assert (await invoke("before-race")).ok
        monkeypatch.setattr(manager, "_build_and_init_handler", paused_build)
        reloading = asyncio.create_task(manager.reload_driver(card.name))
        await asyncio.wait_for(initialized.wait(), timeout=20)
        denied = copy.deepcopy(card)
        denied.policy = DriverPolicy(default_effect="deny")
        await asyncio.wait_for(manager.sync_driver_policy(denied), timeout=2)
        assert (
            manager._handlers[card.name].card.policy.default_effect == "deny"
        )
        release.set()
        with pytest.raises(DriverCardError):
            await asyncio.wait_for(reloading, timeout=20)
        assert candidates[0]._client is None
        monkeypatch.setattr(manager, "_build_and_init_handler", real_build)

        stored_path = await manager._card_store.stored_path(card.name)
        persisted = await manager._card_store.load_path(stored_path)
        assert persisted.policy.default_effect == "deny"
        assert (
            manager._handlers[card.name].card.policy.default_effect == "deny"
        )
        result = await invoke("must-not-run")
        assert not result.ok
        assert result.error_type == "driver_policy_denied"
        assert calls.read_text(encoding="utf-8").splitlines() == [
            "before-race",
        ]

        await asyncio.wait_for(manager.reload_driver(card.name), timeout=20)
        result = await invoke("also-must-not-run")
        assert not result.ok
        assert result.error_type == "driver_policy_denied"
        await manager.sync_driver_policy(card)
        await asyncio.wait_for(manager.reload_driver(card.name), timeout=20)
        assert (await invoke("after-recovery")).ok
        assert calls.read_text(encoding="utf-8").splitlines() == [
            "before-race",
            "after-recovery",
        ]
    finally:
        release.set()
        if reloading is not None and not reloading.done():
            await asyncio.wait_for(
                asyncio.gather(reloading, return_exceptions=True),
                timeout=20,
            )
        await manager.shutdown_all()
