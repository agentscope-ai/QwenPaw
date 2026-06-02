# -*- coding: utf-8 -*-
"""Shared fixtures for ``tests/unit/app/routers/``.

Only truly shared building blocks live here: the ``workspace_mock`` /
``manager_mock`` mocks that every router test will want. Each
``test_xxx_router.py`` builds its own ``app`` fixture mounting just the
router under test — keeping that local avoids the "messages-only app"
trap a contributor would otherwise hit when adding a new router test.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def workspace_mock() -> Any:
    """A workspace mock with a ``channel_manager`` exposing ``send_text``."""
    workspace = MagicMock(name="Workspace")
    workspace.channel_manager = MagicMock(name="ChannelManager")
    workspace.channel_manager.send_text = AsyncMock(return_value=None)
    return workspace


@pytest.fixture
def manager_mock(workspace_mock) -> Any:
    """Default MultiAgentManager mock: ``get_agent`` returns the workspace."""
    manager = MagicMock(name="MultiAgentManager")
    manager.get_agent = AsyncMock(return_value=workspace_mock)
    return manager
