"""Runtime must consume committed PG revisions, never editable cache files."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from qwenpaw.app.driver_config_service import DriverConfigService
from qwenpaw.app.mcp.postgres_repository import MCPDriverRecord
from qwenpaw.drivers.capabilities import (
    DriverInvocation,
    DriverInvocationResult,
    format_capability_id,
)
from qwenpaw.drivers.credentials.providers import NoneProvider
from qwenpaw.drivers.credentials.types import ResolvedCredential
from qwenpaw.drivers.contracts import DriverCard
from qwenpaw.drivers.errors import DriverNotFoundError
from qwenpaw.drivers.manager import DriverManager
from qwenpaw.drivers.storage import card_path, dump_card


class Repository:
    def __init__(self):
        self.rows = {
            "echo": MCPDriverRecord(
                uuid4(),
                uuid4(),
                "echo",
                True,
                1,
                {
                    "endpoint": {"transport": "stdio", "command": "python"},
                    "config": {},
                    "credentials": {},
                },
                None,
                {"default_effect": "allow"},
            )
        }

    async def list_drivers(self, *, agent_key):
        return list(self.rows.values())

    async def get_driver(self, *, agent_key, client_key):
        return self.rows.get(client_key)


def make_store(tmp_path):
    from qwenpaw.app.mcp.postgres_card_store import PostgresMCPCardStore

    repository = Repository()
    return (
        PostgresMCPCardStore(
            tmp_path / "drivers", agent_key="agent", repository=repository
        ),
        repository,
    )


@pytest.mark.asyncio
async def test_database_card_load_does_not_need_or_trust_yaml(tmp_path):
    store, _ = make_store(tmp_path)
    workspace = SimpleNamespace(
        workspace_dir=tmp_path, driver_manager=SimpleNamespace(card_store=store)
    )
    actual = await DriverConfigService(workspace).load_card("echo", protocol="mcp")
    assert actual.endpoint["command"] == "python"
    path = card_path(tmp_path / "drivers", "echo", protocol="mcp")
    dump_card(DriverCard("echo", "mcp", {"command": "untrusted-yaml"}), path)
    assert (await store.load_path(path)).endpoint["command"] == "python"


@pytest.mark.asyncio
async def test_deleted_driver_cache_cannot_be_discovered_or_loaded(tmp_path):
    store, repository = make_store(tmp_path)
    card = await store.load("echo", protocol="mcp")
    path = await store.save(card)
    assert path.is_file()
    repository.rows.clear()
    assert await store.list_paths() == []
    assert await store.stored_path("echo") is None
    with pytest.raises(DriverNotFoundError):
        await store.load_path(path)
    assert path.is_file(), "Keep cache bytes; do not delete user files during read"


@pytest.mark.asyncio
async def test_materialization_projects_committed_card_not_supplied_mutation(tmp_path):
    store, _ = make_store(tmp_path)
    supplied = DriverCard("echo", "mcp", {"command": "must-not-write"})
    path = await store.save(supplied)
    assert "must-not-write" not in path.read_text()
    assert (await store.load_path(path)).endpoint["command"] == "python"


@pytest.mark.asyncio
async def test_credential_guard_rechecks_revision_after_approval_wait(tmp_path):
    store, repository = make_store(tmp_path)
    card = await store.load("echo", protocol="mcp")
    provider = store.guard_provider(card, NoneProvider())
    assert await provider.resolve() == ResolvedCredential.EMPTY
    repository.rows["echo"] = replace(repository.rows["echo"], revision=2)
    with pytest.raises(DriverNotFoundError):
        await provider.resolve()


@pytest.mark.asyncio
async def test_committed_whitelist_refresh_keeps_guard_and_transport_in_sync(
    tmp_path,
):
    from qwenpaw.drivers.handlers.mcp import MCPDriverHandler

    store, repository = make_store(tmp_path)
    card = await store.load("echo", protocol="mcp")
    handler = MCPDriverHandler(
        card, store.guard_provider(card, NoneProvider())
    )
    manager = DriverManager(
        tmp_path / "drivers", SimpleNamespace(), card_store=store
    )
    manager.register_handler_type("mcp", MCPDriverHandler)
    manager._handlers["echo"] = handler
    repository.rows["echo"] = replace(
        repository.rows["echo"], revision=2, tool_allowlist=[]
    )
    await manager.refresh_driver("echo")
    assert manager._handlers["echo"] is handler
    assert handler.card.config["tools"] == []
    assert (
        await handler._credential_provider.resolve()
        == ResolvedCredential.EMPTY
    )
    result = await handler.invoke_capability(
        DriverInvocation(
            format_capability_id("mcp", "echo", "tool", "invoke", "echo"), {}
        )
    )
    assert result.error_type == "tool_disabled"


@pytest.mark.asyncio
async def test_manager_does_not_invoke_stale_transport_or_report_active(tmp_path):
    store, repository = make_store(tmp_path)
    manager = DriverManager(tmp_path / "drivers", SimpleNamespace(), card_store=store)
    card = await store.load("echo", protocol="mcp")
    invoked = []

    async def invoke(_):
        invoked.append(True)
        return DriverInvocationResult(ok=True, value="wrong")

    manager._handlers["echo"] = SimpleNamespace(card=card, invoke_capability=invoke)
    repository.rows["echo"] = replace(repository.rows["echo"], revision=2)
    info = (await manager.list_drivers())[0]
    assert info.status != "active"
    result = await manager.invoke_capability(
        DriverInvocation(
            format_capability_id("mcp", "echo", "tool", "call", "echo"), {}, {}
        )
    )
    assert not result.ok and not invoked


@pytest.mark.asyncio
async def test_failed_activation_has_safe_runtime_error(tmp_path):
    store, _ = make_store(tmp_path)
    manager = DriverManager(tmp_path / "drivers", SimpleNamespace(), card_store=store)
    with pytest.raises(Exception):
        await manager.reload_driver("echo")
    info = (await manager.list_drivers())[0]
    assert info.status == "error"
    assert info.error == "Driver activation failed; check configuration and retry"
