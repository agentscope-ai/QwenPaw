# -*- coding: utf-8 -*-
"""Tool credential binding and runtime-cache contracts."""

from uuid import uuid4

import pytest

from qwenpaw.app.tools.credentials import (
    ToolCredentialService,
    load_agent_tool_credentials,
    tool_credential_consumer_id,
)
from qwenpaw.app.tools.runtime_credentials import ToolCredentialRuntimeCache
from qwenpaw.drivers.credentials.types import CredentialRecord
from qwenpaw.drivers.errors import CredentialNotFoundError


class MemoryStore:
    def __init__(self) -> None:
        self.values = {}

    async def create_and_bind(self, **kwargs):
        key = (
            kwargs["consumer_type"],
            kwargs["consumer_id"],
            kwargs["purpose"],
            kwargs["scope_type"],
            kwargs["scope_id"],
        )
        self.values[key] = kwargs["record"]
        return uuid4()

    async def resolve(self, **kwargs):
        key = (
            kwargs["consumer_type"],
            kwargs["consumer_id"],
            kwargs["purpose"],
            kwargs["scope_type"],
            kwargs["scope_id"],
        )
        try:
            return self.values[key]
        except KeyError as exc:
            raise CredentialNotFoundError(str(key)) from exc

    async def revoke_binding(self, **kwargs):
        key = (
            kwargs["consumer_type"],
            kwargs["consumer_id"],
            kwargs["purpose"],
            kwargs["scope_type"],
            kwargs["scope_id"],
        )
        return self.values.pop(key, None) is not None


class TransactionalMemoryStore(MemoryStore):
    def __init__(self) -> None:
        super().__init__()
        self.commits = 0

    def transaction(self):
        store = self

        class Transaction:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, exc_type, _exc, _tb):
                if exc_type is None:
                    store.commits += 1

        return Transaction()


def test_tool_credential_consumer_is_stable_and_scoped_to_agent() -> None:
    agent_a = uuid4()
    agent_b = uuid4()

    assert tool_credential_consumer_id(agent_a, "image") == (
        tool_credential_consumer_id(agent_a, "image")
    )
    assert tool_credential_consumer_id(agent_a, "image") != (
        tool_credential_consumer_id(agent_a, "video")
    )
    assert tool_credential_consumer_id(agent_a, "image") != (
        tool_credential_consumer_id(agent_b, "image")
    )


@pytest.mark.asyncio
async def test_replace_resolve_status_and_delete_are_binding_scoped() -> None:
    store = MemoryStore()
    cache = ToolCredentialRuntimeCache()
    service = ToolCredentialService(store=store, cache=cache)
    agent_id = uuid4()
    actor_id = uuid4()

    await service.replace(
        agent_id=agent_id,
        tool_name="generate_image",
        field_name="api_key",
        value="synthetic-secret",
        actor_user_id=actor_id,
    )

    assert await service.status(
        agent_id=agent_id,
        tool_name="generate_image",
        field_name="api_key",
    ) == "configured"
    assert cache.get(str(agent_id), "generate_image") == {
        "api_key": "synthetic-secret"
    }
    assert cache.get(str(uuid4()), "generate_image") == {}

    assert await service.delete(
        agent_id=agent_id,
        tool_name="generate_image",
        field_name="api_key",
    )
    assert await service.status(
        agent_id=agent_id,
        tool_name="generate_image",
        field_name="api_key",
    ) == "missing"
    assert cache.get(str(agent_id), "generate_image") == {}


@pytest.mark.asyncio
async def test_reload_clears_stale_cache_when_binding_cannot_resolve() -> None:
    store = MemoryStore()
    cache = ToolCredentialRuntimeCache()
    service = ToolCredentialService(store=store, cache=cache)
    agent_id = uuid4()
    cache.replace(str(agent_id), "image", {"api_key": "stale"})

    loaded = await service.load_tool(
        agent_id=agent_id,
        tool_name="image",
        password_fields=["api_key"],
    )

    assert loaded == {}
    assert cache.get(str(agent_id), "image") == {}


@pytest.mark.asyncio
async def test_apply_actions_updates_cache_only_after_one_transaction() -> None:
    store = TransactionalMemoryStore()
    cache = ToolCredentialRuntimeCache()
    service = ToolCredentialService(store=store, cache=cache)
    agent_id = uuid4()

    await service.apply_actions(
        agent_id=agent_id,
        tool_name="image",
        actions={"api_key": ("replace", "secret")},
        actor_user_id=uuid4(),
    )

    assert store.commits == 1
    assert cache.get(str(agent_id), "image") == {"api_key": "secret"}


def test_runtime_cache_returns_copies_and_never_exposes_other_agent() -> None:
    cache = ToolCredentialRuntimeCache()
    cache.replace("agent-a", "image", {"api_key": "secret-a"})
    first = cache.get("agent-a", "image")
    first["api_key"] = "mutated"

    assert cache.get("agent-a", "image") == {"api_key": "secret-a"}
    assert cache.get("agent-b", "image") == {}


def test_plugin_registry_merges_runtime_credentials_without_persisting_them(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from qwenpaw.app.tools.runtime_credentials import TOOL_CREDENTIAL_CACHE
    from qwenpaw.plugins.registry import PluginRegistry

    tool = SimpleNamespace(config={"endpoint": "https://example.test"})
    agent_config = SimpleNamespace(
        tools=SimpleNamespace(builtin_tools={"image": tool})
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: agent_config,
    )
    monkeypatch.setattr(
        "qwenpaw.identity.runtime.is_multi_user_enabled",
        lambda: True,
    )
    TOOL_CREDENTIAL_CACHE.replace(
        "agent-a",
        "image",
        {"api_key": "runtime-only"},
    )
    try:
        assert PluginRegistry().get_tool_config("image", "agent-a") == {
            "endpoint": "https://example.test",
            "api_key": "runtime-only",
        }
        assert tool.config == {"endpoint": "https://example.test"}
    finally:
        TOOL_CREDENTIAL_CACHE.clear_agent("agent-a")


@pytest.mark.asyncio
async def test_agent_startup_loads_declared_password_fields_into_cache() -> None:
    store = MemoryStore()
    cache = ToolCredentialRuntimeCache()
    service = ToolCredentialService(store=store, cache=cache)
    agent_id = "agent-restart"
    await service.replace(
        agent_id=agent_id,
        tool_name="image",
        field_name="api_key",
        value="restart-secret",
        actor_user_id=uuid4(),
    )
    cache.clear_agent(agent_id)

    await load_agent_tool_credentials(
        agent_key=agent_id,
        tool_fields={"image": ["api_key"]},
        service=service,
    )

    assert cache.get(agent_id, "image") == {"api_key": "restart-secret"}
