# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Explicit helpers for model-routing tests; no automatic model mocking."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)


@pytest.fixture
def make_memory_model_manager():
    """Create the host shell without mocking its model factory or providers."""

    def make(agent_id="default"):
        manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
        manager.agent_id = agent_id
        manager._reme = SimpleNamespace(
            update_component=AsyncMock(),
            start=AsyncMock(),
        )
        return manager

    return make
