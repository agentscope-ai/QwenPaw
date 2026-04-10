# -*- coding: utf-8 -*-
"""Tests for Workspace class."""
import tempfile
from pathlib import Path
import pytest


@pytest.mark.asyncio
async def test_workspace_creation():
    """Test workspace instance creation."""
    from copaw.app.workspace import Workspace

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_dir = Path(tmpdir) / "test_agent"
        workspace = Workspace(
            agent_id="test123",
            workspace_dir=str(workspace_dir),
        )

        assert workspace.agent_id == "test123"
        assert workspace.workspace_dir == workspace_dir
        assert workspace_dir.exists()
        assert not workspace._started  # pylint: disable=W0212


@pytest.mark.asyncio
async def test_workspace_components_none_before_start():
    """Test that workspace components are None before start()."""
    from copaw.app.workspace import Workspace

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_dir = Path(tmpdir) / "test_agent"
        workspace = Workspace(
            agent_id="test123",
            workspace_dir=str(workspace_dir),
        )

        assert workspace.runner is None
        assert workspace.channel_manager is None
        assert workspace.memory_manager is None
        assert workspace.mcp_manager is None
        assert workspace.cron_manager is None
        assert workspace.chat_manager is None


@pytest.mark.asyncio
async def test_workspace_default_agent():
    """Test workspace with 'default' agent ID."""
    from copaw.app.workspace import Workspace

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_dir = Path(tmpdir) / "default"
        workspace = Workspace(
            agent_id="default",
            workspace_dir=str(workspace_dir),
        )

        assert workspace.agent_id == "default"
        assert workspace.workspace_dir.name == "default"


@pytest.mark.asyncio
async def test_workspace_short_uuid_agent():
    """Test workspace with short UUID agent ID."""
    from copaw.app.workspace import Workspace
    from copaw.config.config import generate_short_agent_id

    short_id = generate_short_agent_id()

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_dir = Path(tmpdir) / short_id
        workspace = Workspace(
            agent_id=short_id,
            workspace_dir=str(workspace_dir),
        )

        assert workspace.agent_id == short_id
        assert len(workspace.agent_id) == 6
        assert workspace.workspace_dir.name == short_id


def test_workspace_repr():
    """Test workspace string representation."""
    from copaw.app.workspace import Workspace

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_dir = Path(tmpdir) / "test_agent"
        workspace = Workspace(
            agent_id="test123",
            workspace_dir=str(workspace_dir),
        )

        repr_str = repr(workspace)
        assert "test123" in repr_str
        assert "stopped" in repr_str
        assert "Workspace" in repr_str
