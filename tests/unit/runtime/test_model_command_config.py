# -*- coding: utf-8 -*-
"""Tests for request-scoped configuration in the model command."""

from types import SimpleNamespace

import pytest

from qwenpaw.runtime.commands.control.base import ControlContext
from qwenpaw.runtime.commands.control import model_handler as model_module
from qwenpaw.runtime.commands.control.model_handler import ModelCommandHandler
from qwenpaw.exceptions import ConfigurationException


@pytest.mark.asyncio
async def test_model_command_uses_injected_config_snapshot() -> None:
    """Showing the model must not touch the synchronous workspace property."""

    class WorkspaceWithoutSyncConfig:
        @property
        def config(self):
            raise AssertionError("synchronous config access is forbidden")

    context = ControlContext(
        workspace=WorkspaceWithoutSyncConfig(),
        payload=None,
        channel=None,
        session_id="console:test",
        user_id="test",
        agent_id="agent-1",
        args={},
        agent_config=SimpleNamespace(
            active_model=SimpleNamespace(
                provider_id="openai",
                model="gpt-test",
            ),
        ),
    )

    result = await ModelCommandHandler().handle(context)

    assert "openai" in result
    assert "gpt-test" in result


@pytest.mark.asyncio
async def test_model_command_falls_back_to_global_when_config_unavailable(
    monkeypatch,
) -> None:
    """The read-only current-model command remains useful during outages."""
    async def fail_config_read(_agent_id):
        raise ConfigurationException(
            "config offline",
            config_key="agent",
            error_code="AGENT_CONFIG_UNAVAILABLE",
        )

    class ProviderManagerStub:
        @classmethod
        def get_instance(cls):
            return cls()

        def get_active_model(self):
            return SimpleNamespace(provider_id="openai", model="gpt-global")

    monkeypatch.setattr(
        model_module,
        "load_runtime_agent_config",
        fail_config_read,
    )
    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager",
        ProviderManagerStub,
    )
    context = ControlContext(
        workspace=SimpleNamespace(agent_id="agent-1"),
        payload=None,
        channel=None,
        session_id="console:test",
        user_id="test",
        agent_id="agent-1",
        args={},
    )

    result = await ModelCommandHandler().handle(context)

    assert "openai" in result
    assert "gpt-global" in result
