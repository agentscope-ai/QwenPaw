# -*- coding: utf-8 -*-
"""Unit tests for spawn_agent tool."""
# pylint: disable=protected-access,redefined-outer-name

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentscope.message import Msg
from agentscope.tool import ToolResponse

# Import the functions we test
from src.copaw.agents.tools.spawn_agent import (
    spawn_agent,
    set_multi_agent_manager,
    get_multi_agent_manager,
    _error_response,
    _success_response,
    _extract_text_from_result,
)


def is_text_block(obj):
    """Check if object is a valid TextBlock (TypedDict).

    TextBlock is a TypedDict, so isinstance() doesn't work.
    We check for the required keys and types.
    """
    return (
        isinstance(obj, dict)
        and obj.get("type") == "text"
        and "text" in obj
        and isinstance(obj["text"], str)
    )


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_error_response_format(self):
        """Test that _error_response returns correct ToolResponse format."""
        result = _error_response("Test error message")

        assert isinstance(result, ToolResponse)
        assert isinstance(result.content, list)
        assert len(result.content) == 1
        assert is_text_block(result.content[0])
        assert "Test error message" in result.content[0]["text"]

    def test_success_response_format(self):
        """Test that _success_response returns correct ToolResponse format."""
        result = _success_response("test_agent", "Hello from agent")

        assert isinstance(result, ToolResponse)
        assert isinstance(result.content, list)
        assert len(result.content) == 1
        assert is_text_block(result.content[0])
        assert "[Agent: test_agent]" in result.content[0]["text"]
        assert "Hello from agent" in result.content[0]["text"]

    def test_extract_text_from_string_content(self):
        """Test _extract_text_from_result with string content."""
        msg = MagicMock()
        msg.content = "Simple text response"
        result = _extract_text_from_result(msg)
        assert result == "Simple text response"

    def test_extract_text_from_list_content(self):
        """Test _extract_text_from_result with list content."""
        msg = MagicMock()
        msg.content = [
            {"type": "text", "text": "First part"},
            {"type": "text", "text": "Second part"},
        ]
        result = _extract_text_from_result(msg)
        assert "First part" in result
        assert "Second part" in result

    def test_extract_text_from_none(self):
        """Test _extract_text_from_result with None."""
        result = _extract_text_from_result(None)
        assert result == ""


class TestInputValidation:
    """Tests for input validation - these don't need any context."""

    @pytest.mark.asyncio
    async def test_empty_agent_id(self):
        """Test that empty agent_id returns error."""
        result = await spawn_agent("", "Hello")

        assert isinstance(result, ToolResponse)
        assert is_text_block(result.content[0])
        assert "agent_id cannot be empty" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_whitespace_agent_id(self):
        """Test that whitespace-only agent_id returns error."""
        result = await spawn_agent("   ", "Hello")

        assert isinstance(result, ToolResponse)
        assert is_text_block(result.content[0])
        assert "agent_id cannot be empty" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_empty_prompt(self):
        """Test that empty prompt returns error."""
        result = await spawn_agent("test_agent", "")

        assert isinstance(result, ToolResponse)
        assert is_text_block(result.content[0])
        assert "prompt cannot be empty" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_whitespace_prompt(self):
        """Test that whitespace-only prompt returns error."""
        result = await spawn_agent("test_agent", "   ")

        assert isinstance(result, ToolResponse)
        assert is_text_block(result.content[0])
        assert "prompt cannot be empty" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_zero_timeout(self):
        """Test that zero timeout returns error."""
        result = await spawn_agent("test_agent", "Hello", timeout=0)

        assert isinstance(result, ToolResponse)
        assert is_text_block(result.content[0])
        assert "timeout must be positive" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_negative_timeout(self):
        """Test that negative timeout returns error."""
        result = await spawn_agent("test_agent", "Hello", timeout=-10)

        assert isinstance(result, ToolResponse)
        assert is_text_block(result.content[0])
        assert "timeout must be positive" in result.content[0]["text"]


class TestManagerNotSet:
    """Tests when manager is not set."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Ensure manager is None before each test."""
        set_multi_agent_manager(None)
        yield
        set_multi_agent_manager(None)

    @pytest.mark.asyncio
    async def test_manager_not_available_returns_error(self):
        """Test error when MultiAgentManager is not set."""
        result = await spawn_agent("target_agent", "Hello")

        assert isinstance(result, ToolResponse)
        assert is_text_block(result.content[0])
        assert "Multi-agent system not available" in result.content[0]["text"]


class TestSelfSpawning:
    """Tests for self-spawning prevention."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup and teardown for each test."""
        self.manager = MagicMock()
        set_multi_agent_manager(self.manager)
        yield
        set_multi_agent_manager(None)

    @pytest.mark.asyncio
    async def test_self_spawning_blocked(self):
        """Test that an agent cannot spawn itself."""
        # Patch the source modules
        with (
            patch(
                "src.copaw.app.agent_context.get_current_agent_id",
            ) as mock_get_id,
            patch(
                "src.copaw.app.agent_context.get_spawn_depth",
            ) as mock_get_depth,
        ):
            mock_get_id.return_value = "default"
            mock_get_depth.return_value = 0

            result = await spawn_agent("default", "Hello")

            assert isinstance(result, ToolResponse)
            assert is_text_block(result.content[0])
            assert "cannot spawn itself" in result.content[0]["text"]
            assert "infinite loop" in result.content[0]["text"]


class TestPermissionChecks:
    """Tests for orchestration permission checks."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup and teardown for each test."""
        self.manager = MagicMock()
        self.manager.get_agent = AsyncMock()
        set_multi_agent_manager(self.manager)
        yield
        set_multi_agent_manager(None)

    def _create_config(self, can_spawn=True, allowed=None, max_depth=3):
        """Create a mock agent config."""
        config = MagicMock()
        config.orchestration = MagicMock()
        config.orchestration.can_spawn_agents = can_spawn
        config.orchestration.allowed_agents = allowed or ["target_agent"]
        config.orchestration.max_spawn_depth = max_depth
        return config

    @pytest.mark.asyncio
    async def test_spawning_disabled(self):
        """Test error when can_spawn_agents is False."""
        config = self._create_config(can_spawn=False)

        with (
            patch(
                "src.copaw.app.agent_context.get_current_agent_id",
            ) as mock_get_id,
            patch(
                "src.copaw.app.agent_context.get_spawn_depth",
            ) as mock_get_depth,
            patch(
                "src.copaw.config.config.load_agent_config",
            ) as mock_load_config,
        ):
            mock_get_id.return_value = "caller_agent"
            mock_get_depth.return_value = 0
            mock_load_config.return_value = config

            result = await spawn_agent("target_agent", "Hello")

            assert isinstance(result, ToolResponse)
            assert is_text_block(result.content[0])
            assert (
                "not allowed to spawn other agents"
                in result.content[0]["text"]
            )

    @pytest.mark.asyncio
    async def test_agent_not_in_allowed_list(self):
        """Test error when target agent is not in allowed_agents list."""
        config = self._create_config(allowed=["allowed_agent"])

        with (
            patch(
                "src.copaw.app.agent_context.get_current_agent_id",
            ) as mock_get_id,
            patch(
                "src.copaw.app.agent_context.get_spawn_depth",
            ) as mock_get_depth,
            patch(
                "src.copaw.config.config.load_agent_config",
            ) as mock_load_config,
        ):
            mock_get_id.return_value = "caller_agent"
            mock_get_depth.return_value = 0
            mock_load_config.return_value = config

            result = await spawn_agent("unauthorized_agent", "Hello")

            assert isinstance(result, ToolResponse)
            assert is_text_block(result.content[0])
            assert "not in the allowed list" in result.content[0]["text"]
            assert "allowed_agent" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_max_spawn_depth_exceeded(self):
        """Test error when max_spawn_depth is exceeded."""
        config = self._create_config(max_depth=3)

        with (
            patch(
                "src.copaw.app.agent_context.get_current_agent_id",
            ) as mock_get_id,
            patch(
                "src.copaw.app.agent_context.get_spawn_depth",
            ) as mock_get_depth,
            patch(
                "src.copaw.config.config.load_agent_config",
            ) as mock_load_config,
        ):
            mock_get_id.return_value = "caller_agent"
            mock_get_depth.return_value = 3  # Equal to max_spawn_depth
            mock_load_config.return_value = config

            result = await spawn_agent("target_agent", "Hello")

            assert isinstance(result, ToolResponse)
            assert is_text_block(result.content[0])
            assert "Maximum spawn depth" in result.content[0]["text"]
            assert "exceeded" in result.content[0]["text"]


class TestAgentAvailability:
    """Tests for agent/workspace availability."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup and teardown for each test."""
        self.manager = MagicMock()
        self.manager.get_agent = AsyncMock()
        set_multi_agent_manager(self.manager)
        yield
        set_multi_agent_manager(None)

    def _create_config(self):
        """Create a mock agent config with spawning enabled."""
        config = MagicMock()
        config.orchestration = MagicMock()
        config.orchestration.can_spawn_agents = True
        config.orchestration.allowed_agents = ["target_agent"]
        config.orchestration.max_spawn_depth = 3
        return config

    @pytest.mark.asyncio
    async def test_agent_not_found(self):
        """Test error when target agent is not found."""
        self.manager.get_agent.return_value = None
        config = self._create_config()

        with (
            patch(
                "src.copaw.app.agent_context.get_current_agent_id",
            ) as mock_get_id,
            patch(
                "src.copaw.app.agent_context.get_spawn_depth",
            ) as mock_get_depth,
            patch(
                "src.copaw.config.config.load_agent_config",
            ) as mock_load_config,
        ):
            mock_get_id.return_value = "caller_agent"
            mock_get_depth.return_value = 0
            mock_load_config.return_value = config

            result = await spawn_agent("target_agent", "Hello")

            assert isinstance(result, ToolResponse)
            assert is_text_block(result.content[0])
            assert "not found" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_runner_not_available(self):
        """Test error when workspace.runner is None."""
        mock_workspace = MagicMock()
        mock_workspace.runner = None
        self.manager.get_agent.return_value = mock_workspace
        config = self._create_config()

        with (
            patch(
                "src.copaw.app.agent_context.get_current_agent_id",
            ) as mock_get_id,
            patch(
                "src.copaw.app.agent_context.get_spawn_depth",
            ) as mock_get_depth,
            patch(
                "src.copaw.config.config.load_agent_config",
            ) as mock_load_config,
        ):
            mock_get_id.return_value = "caller_agent"
            mock_get_depth.return_value = 0
            mock_load_config.return_value = config

            result = await spawn_agent("target_agent", "Hello")

            assert isinstance(result, ToolResponse)
            assert is_text_block(result.content[0])
            assert "not running" in result.content[0]["text"]


class TestSuccessfulSpawn:
    """Tests for successful agent spawning."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup and teardown for each test."""
        self.manager = MagicMock()
        self.manager.get_agent = AsyncMock()
        set_multi_agent_manager(self.manager)
        yield
        set_multi_agent_manager(None)

    def _create_config(self, allowed=None):
        """Create a mock agent config with spawning enabled.

        Args:
            allowed: List of allowed agents. None defaults to ["target_agent"].
                     Use [] for empty list (allow all agents).
        """
        config = MagicMock()
        config.orchestration = MagicMock()
        config.orchestration.can_spawn_agents = True
        # Only default to ["target_agent"] if allowed is None
        # Empty list [] should be preserved (it means allow all)
        if allowed is None:
            config.orchestration.allowed_agents = ["target_agent"]
        else:
            config.orchestration.allowed_agents = allowed
        config.orchestration.max_spawn_depth = 3
        return config

    def _create_workspace(self, response_text, delay=0):
        """Create a mock workspace with runner."""
        workspace = MagicMock()
        workspace.runner = MagicMock()

        async def mock_query_handler(
            _args,
            **kwargs,
        ):  # pylint: disable=unused-argument
            if delay > 0:
                await asyncio.sleep(delay)
            msg = Msg(
                name="assistant",
                content=response_text,
                role="assistant",
            )
            yield msg, True

        workspace.runner.query_handler = mock_query_handler
        return workspace

    @pytest.mark.asyncio
    async def test_successful_spawn(self):
        """Test successful agent spawn with response."""
        workspace = self._create_workspace("Hello! I'm the spawned agent.")
        self.manager.get_agent.return_value = workspace
        config = self._create_config()

        with (
            patch(
                "src.copaw.app.agent_context.get_current_agent_id",
            ) as mock_get_id,
            patch(
                "src.copaw.app.agent_context.get_spawn_depth",
            ) as mock_get_depth,
            patch(
                "src.copaw.config.config.load_agent_config",
            ) as mock_load_config,
            patch(
                "src.copaw.app.agent_context.SpawnDepthContext",
            ),
        ):
            mock_get_id.return_value = "caller_agent"
            mock_get_depth.return_value = 0
            mock_load_config.return_value = config

            result = await spawn_agent("target_agent", "Say hello")

            assert isinstance(result, ToolResponse)
            assert is_text_block(result.content[0])
            assert "[Agent: target_agent]" in result.content[0]["text"]
            assert "Hello! I'm the spawned agent." in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_spawn_with_empty_allowed_list(self):
        """Test that empty allowed_agents list allows spawning any agent."""
        workspace = self._create_workspace("Hello from any agent!")
        self.manager.get_agent.return_value = workspace
        config = self._create_config(allowed=[])  # Empty = allow all

        with (
            patch(
                "src.copaw.app.agent_context.get_current_agent_id",
            ) as mock_get_id,
            patch(
                "src.copaw.app.agent_context.get_spawn_depth",
            ) as mock_get_depth,
            patch(
                "src.copaw.config.config.load_agent_config",
            ) as mock_load_config,
            patch(
                "src.copaw.app.agent_context.SpawnDepthContext",
            ),
        ):
            mock_get_id.return_value = "caller_agent"
            mock_get_depth.return_value = 0
            mock_load_config.return_value = config

            # Spawn an agent not in any list - should work since list is empty
            result = await spawn_agent("any_agent", "Say hello")

            assert isinstance(result, ToolResponse)
            assert is_text_block(result.content[0])
            assert "[Agent: any_agent]" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_spawn_timeout(self):
        """Test that timeout is handled correctly."""
        workspace = self._create_workspace("Too late", delay=10)
        self.manager.get_agent.return_value = workspace
        config = self._create_config()

        with (
            patch(
                "src.copaw.app.agent_context.get_current_agent_id",
            ) as mock_get_id,
            patch(
                "src.copaw.app.agent_context.get_spawn_depth",
            ) as mock_get_depth,
            patch(
                "src.copaw.config.config.load_agent_config",
            ) as mock_load_config,
            patch(
                "src.copaw.app.agent_context.SpawnDepthContext",
            ),
        ):
            mock_get_id.return_value = "caller_agent"
            mock_get_depth.return_value = 0
            mock_load_config.return_value = config

            # Use very short timeout
            result = await spawn_agent(
                "target_agent",
                "Say hello",
                timeout=0.1,
            )

            assert isinstance(result, ToolResponse)
            assert is_text_block(result.content[0])
            assert "timed out" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_spawn_no_response(self):
        """Test handling when agent returns no response."""
        workspace = MagicMock()
        workspace.runner = MagicMock()

        async def mock_query_handler(
            _args,
            **kwargs,
        ):  # pylint: disable=unused-argument
            return
            yield  # Make it a generator

        workspace.runner.query_handler = mock_query_handler
        self.manager.get_agent.return_value = workspace
        config = self._create_config()

        with (
            patch(
                "src.copaw.app.agent_context.get_current_agent_id",
            ) as mock_get_id,
            patch(
                "src.copaw.app.agent_context.get_spawn_depth",
            ) as mock_get_depth,
            patch(
                "src.copaw.config.config.load_agent_config",
            ) as mock_load_config,
            patch(
                "src.copaw.app.agent_context.SpawnDepthContext",
            ),
        ):
            mock_get_id.return_value = "caller_agent"
            mock_get_depth.return_value = 0
            mock_load_config.return_value = config

            result = await spawn_agent("target_agent", "Say hello")

            assert isinstance(result, ToolResponse)
            assert is_text_block(result.content[0])
            assert "returned no response" in result.content[0]["text"]


class TestSetGetManager:
    """Tests for set/get multi_agent_manager."""

    def test_set_and_get_multi_agent_manager(self):
        """Test set_multi_agent_manager and get_multi_agent_manager."""
        mock_manager = MagicMock()
        set_multi_agent_manager(mock_manager)

        assert get_multi_agent_manager() == mock_manager

        # Reset
        set_multi_agent_manager(None)


class TestToolResponseFormat:
    """Tests for ToolResponse format consistency."""

    def test_response_uses_textblock_format(self):
        """Test that all responses use TextBlock format."""
        # Test error response
        error_result = _error_response("Test error")
        assert isinstance(error_result.content, list)
        assert len(error_result.content) == 1
        assert is_text_block(error_result.content[0])

        # Test success response
        success_result = _success_response("agent_id", "Test response")
        assert isinstance(success_result.content, list)
        assert len(success_result.content) == 1
        assert is_text_block(success_result.content[0])
