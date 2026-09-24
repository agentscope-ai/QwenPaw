# -*- coding: utf-8 -*-
"""Read-only /model commands must survive an unreadable configuration.

A configuration that cannot be read is not a reason to refuse ``/model`` or
``/model list``: both only report what is already known from the provider
manager. A write still needs the real file.
"""

# pylint: disable=protected-access,redefined-outer-name

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.exceptions import (
    AGENT_CONFIG_UNAVAILABLE,
    ConfigurationException,
)
from qwenpaw.runtime.commands.control.base import ControlContext
from qwenpaw.runtime.commands.control.model_handler import (
    ModelCommandHandler,
    _get_agent_config,
)

pytestmark = [pytest.mark.unit, pytest.mark.p1]


def _unavailable() -> ConfigurationException:
    return ConfigurationException(
        "Agent model configuration is temporarily unavailable",
        config_key="agent",
        error_code=AGENT_CONFIG_UNAVAILABLE,
    )


def _context(raw_args="", agent_config_error=None):
    return ControlContext(
        workspace=SimpleNamespace(agent_id="default"),
        payload={},
        channel=None,
        session_id="console:user1",
        user_id="user1",
        agent_id="default",
        args={"_raw_args": raw_args},
        agent_config=None,
        agent_config_error=agent_config_error,
    )


def _manager(slot):
    return SimpleNamespace(
        get_active_model=lambda: slot,
        list_provider_info=AsyncMock(return_value=[]),
    )


@pytest.fixture
def handler():
    return ModelCommandHandler()


class TestReadOnlyCommandsWithoutConfig:
    async def test_show_current_model_reports_the_global_model(self, handler):
        slot = SimpleNamespace(provider_id="openai", model="gpt-4o")
        with patch(
            "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
            return_value=_manager(slot),
        ):
            result = await handler._show_current_model(
                _context(agent_config_error=_unavailable()),
            )

        assert "Current Model" in result
        assert "global default" in result
        assert "openai" in result

    async def test_list_models_still_answers(self, handler):
        slot = SimpleNamespace(provider_id="openai", model="gpt-4o")
        with patch(
            "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
            return_value=_manager(slot),
        ):
            result = await handler._list_models(
                _context(raw_args="list", agent_config_error=_unavailable()),
            )

        # An empty provider list is a valid answer; the unreadable agent
        # configuration must not turn the command into a failure.
        assert (
            "No Providers Configured" in result or "Available Models" in result
        )

    async def test_show_current_model_without_any_model(self, handler):
        with patch(
            "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
            return_value=_manager(None),
        ):
            result = await handler._show_current_model(
                _context(agent_config_error=_unavailable()),
            )

        assert "No Active Model" in result


class TestGetAgentConfig:
    """The snapshot loader the read paths share, and the write paths call."""

    async def test_reports_a_stored_failure(self):
        with pytest.raises(ConfigurationException) as caught:
            await _get_agent_config(
                _context(agent_config_error=_unavailable()),
            )

        assert caught.value.error_code == AGENT_CONFIG_UNAVAILABLE

    async def test_returns_the_request_snapshot(self):
        snapshot = SimpleNamespace(id="default")
        context = _context()
        context.agent_config = snapshot

        assert await _get_agent_config(context) is snapshot
