# -*- coding: utf-8 -*-
"""Tests for shared effective model selection."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from qwenpaw.exceptions import ConfigurationException
from qwenpaw.providers.model_selection import require_effective_model
from qwenpaw.providers.provider_manager import ProviderManager


def _model(provider_id: str, model: str):
    return SimpleNamespace(provider_id=provider_id, model=model)


def test_prefers_agent_model(monkeypatch) -> None:
    manager = MagicMock()
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)
    agent_model = _model("openai", "gpt-agent")

    selected = require_effective_model(
        SimpleNamespace(active_model=agent_model),
    )

    assert selected is agent_model
    manager.get_active_model.assert_not_called()


def test_falls_back_to_global_model(monkeypatch) -> None:
    manager = MagicMock()
    global_model = _model("openai", "gpt-global")
    manager.get_active_model.return_value = global_model
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)

    selected = require_effective_model(
        SimpleNamespace(active_model=None),
    )

    assert selected is global_model


def test_raises_structured_error_when_no_model_exists(monkeypatch) -> None:
    manager = MagicMock()
    manager.get_active_model.return_value = None
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)

    with pytest.raises(ConfigurationException) as caught:
        require_effective_model(SimpleNamespace(active_model=None))

    assert caught.value.error_code == "MODEL_NOT_CONFIGURED"
