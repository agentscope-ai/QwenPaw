# -*- coding: utf-8 -*-
"""Regression tests for request-context model consumption in AgentBuilder."""

from types import SimpleNamespace
from unittest.mock import patch

from qwenpaw.runtime.builder import AgentBuilder


def test_builder_delegates_model_resolution_to_factory() -> None:
    """Builder must not pass an already-resolved slot back as an override."""
    model = SimpleNamespace()
    with patch(
        "qwenpaw.agents.model_factory.create_model_and_formatter",
        return_value=(model, None),
    ) as create_model:
        result = AgentBuilder().build_model(SimpleNamespace(id="agent-1"))

    assert result == (model, None)
    create_model.assert_called_once_with(agent_id="agent-1")
