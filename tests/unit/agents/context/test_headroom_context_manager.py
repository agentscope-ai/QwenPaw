# -*- coding: utf-8 -*-
"""Unit tests for HeadroomContextManager."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from qwenpaw.agents.context.headroom_context_manager import (
    HeadroomContextManager,
    HeadroomConfig,
    HeadroomCCRConfig,
    HeadroomMemoryConfig,
)


@pytest.fixture
def manager():
    """Create a HeadroomContextManager instance for testing."""
    return HeadroomContextManager(
        working_dir="/tmp/test_working_dir",
        agent_id="test_agent",
    )


class TestHeadroomContextManagerInit:
    """Test initialization."""

    def test_init(self, manager):
        """Verify basic init attributes."""
        assert manager.working_dir == "/tmp/test_working_dir"
        assert manager.agent_id == "test_agent"
        assert manager._config is None
        assert manager._headroom_available is False
        assert manager._context_tracker is None
        assert manager._agent_context is None


class TestHeadroomContextManagerStart:
    """Test start() lifecycle."""

    @patch("qwenpaw.agents.context.headroom_context_manager.HeadroomContextManager._load_config")
    async def test_start_headroom_not_installed(self, mock_load_config, manager):
        """When headroom is not installed, start should log warning."""
        mock_load_config.return_value = HeadroomConfig(enabled=True)

        with patch.dict("sys.modules", {"headroom": None}):
            await manager.start()

        assert manager._headroom_available is False
        assert manager._config is not None

    @patch("qwenpaw.agents.context.headroom_context_manager.HeadroomContextManager._load_config")
    async def test_start_headroom_disabled(self, mock_load_config, manager):
        """When headroom is disabled, start should skip initialization."""
        mock_load_config.return_value = HeadroomConfig(enabled=False)

        await manager.start()

        assert manager._headroom_available is True
        assert manager._config is not None
        assert manager._config.enabled is False

    @patch("qwenpaw.agents.context.headroom_context_manager.HeadroomContextManager._load_config")
    async def test_start_headroom_enabled(self, mock_load_config, manager):
        """When headroom is enabled, start should initialize."""
        mock_load_config.return_value = HeadroomConfig(enabled=True)

        await manager.start()

        assert manager._headroom_available is True
        assert manager._config is not None
        assert manager._config.enabled is True
        assert manager._agent_context is not None

    @patch("qwenpaw.agents.context.headroom_context_manager.HeadroomContextManager._load_config")
    async def test_start_with_ccr(self, mock_load_config, manager):
        """When CCR is enabled, start should initialize context tracker."""
        mock_load_config.return_value = HeadroomConfig(
            enabled=True,
            ccr=HeadroomCCRConfig(enabled=True),
        )

        await manager.start()

        assert manager._context_tracker is not None


class TestHeadroomContextManagerClose:
    """Test close() lifecycle."""

    async def test_close(self, manager):
        """Verify close resets state."""
        result = await manager.close()
        assert result is True
        assert manager._context_tracker is None
        assert manager._agent_context is None


class TestHeadroomContextManagerPreReasoning:
    """Test pre_reasoning compression."""

    async def test_pre_reasoning_disabled(self, manager):
        """When headroom is disabled, pre_reasoning returns None."""
        manager._headroom_available = True
        manager._config = HeadroomConfig(enabled=False)

        result = await manager.pre_reasoning(
            agent=MagicMock(),
            kwargs={"messages": []},
        )
        assert result is None

    async def test_pre_reasoning_no_messages(self, manager):
        """When there are no messages, pre_reasoning returns None."""
        manager._headroom_available = True
        manager._config = HeadroomConfig(enabled=True)

        result = await manager.pre_reasoning(
            agent=MagicMock(),
            kwargs={"messages": []},
        )
        assert result is None

    @patch("qwenpaw.agents.context.headroom_context_manager.headroom_compress")
    async def test_pre_reasoning_compression(self, mock_compress, manager):
        """Verify compression is called and kwargs are updated."""
        from headroom.compress import CompressResult

        manager._headroom_available = True
        manager._config = HeadroomConfig(enabled=True)

        mock_result = CompressResult(
            messages=[{"role": "user", "content": "compressed"}],
            tokens_before=1000,
            tokens_after=200,
            tokens_saved=800,
            compression_ratio=0.8,
            transforms_applied=["SmartCrusher"],
        )
        mock_compress.return_value = mock_result

        from agentscope.message import Msg
        msg = Msg(name="user", role="user", content="hello world " * 100)

        result = await manager.pre_reasoning(
            agent=MagicMock(),
            kwargs={"messages": [msg]},
        )

        assert result is not None
        assert "messages" in result
        assert mock_compress.called


class TestHeadroomContextManagerPostActing:
    """Test post_acting tool output compression."""

    async def test_post_acting_disabled(self, manager):
        """When headroom is disabled, post_acting returns None."""
        manager._headroom_available = True
        manager._config = HeadroomConfig(enabled=False)

        result = await manager.post_acting(
            agent=MagicMock(),
            kwargs={},
            output=MagicMock(),
        )
        assert result is None

    async def test_post_acting_non_msg_output(self, manager):
        """When output is not a Msg, post_acting returns None."""
        manager._headroom_available = True
        manager._config = HeadroomConfig(enabled=True, compress_tool_results=True)

        result = await manager.post_acting(
            agent=MagicMock(),
            kwargs={},
            output="not a msg",
        )
        assert result is None


class TestHeadroomContextManagerCompactContext:
    """Test compact_context."""

    async def test_compact_context_headroom_not_available(self, manager):
        """When headroom is not available, returns failure dict."""
        result = await manager.compact_context(messages=[])
        assert result["success"] is False
        assert "not available" in result["reason"]

    @patch("qwenpaw.agents.context.headroom_context_manager.headroom_compress")
    async def test_compact_context_success(self, mock_compress, manager):
        """Verify compact_context returns compressed summary."""
        from headroom.compress import CompressResult

        manager._headroom_available = True

        mock_result = CompressResult(
            messages=[{"role": "user", "content": "summary text"}],
            tokens_before=500,
            tokens_after=50,
            tokens_saved=450,
            compression_ratio=0.9,
            transforms_applied=["Kompress"],
        )
        mock_compress.return_value = mock_result

        from agentscope.message import Msg
        msg = Msg(name="user", role="user", content="long text " * 50)

        result = await manager.compact_context(messages=[msg])

        assert result["success"] is True
        assert "summary text" in result["history_compact"]
        assert result["before_tokens"] == 500
        assert result["after_tokens"] == 50


class TestHeadroomContextManagerHelpers:
    """Test internal helper methods."""

    def test_messages_to_dicts(self, manager):
        """Verify Msg objects are converted to dicts correctly."""
        from agentscope.message import Msg

        msgs = [
            Msg(name="user", role="user", content="hello"),
            Msg(name="assistant", role="assistant", content="world"),
        ]
        result = manager._messages_to_dicts(msgs)

        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "hello"
        assert result[1]["role"] == "assistant"
        assert result[1]["content"] == "world"

    def test_dicts_to_messages(self, manager):
        """Verify dicts are converted back to Msg objects correctly."""
        dicts = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        result = manager._dicts_to_messages(dicts)

        assert len(result) == 2
        assert result[0].role == "user"
        assert result[0].content == "hello"
        assert result[1].role == "assistant"
        assert result[1].content == "world"

    def test_get_agent_context(self, manager):
        """Verify get_agent_context returns an AgentContext."""
        context = manager.get_agent_context()
        assert context is not None
        assert context.working_dir == "/tmp/test_working_dir"
        assert context.agent_id == "test_agent"


class TestHeadroomConfig:
    """Test HeadroomConfig dataclass defaults."""

    def test_default_config(self):
        """Verify default config values."""
        config = HeadroomConfig()
        assert config.enabled is False
        assert config.mode == "token"
        assert config.protect_recent == 4
        assert config.min_tokens_to_compress == 250
        assert config.compress_user_messages is False
        assert config.compress_system_messages is True
        assert config.compress_tool_results is True
        assert config.ccr.enabled is False
        assert config.memory.enabled is False
        assert config.memory.backend == "local"

    def test_custom_config(self):
        """Verify custom config values."""
        config = HeadroomConfig(
            enabled=True,
            mode="cache",
            protect_recent=2,
            ccr=HeadroomCCRConfig(enabled=True),
            memory=HeadroomMemoryConfig(enabled=True, backend="qdrant-neo4j"),
        )
        assert config.enabled is True
        assert config.mode == "cache"
        assert config.protect_recent == 2
        assert config.ccr.enabled is True
        assert config.memory.enabled is True
        assert config.memory.backend == "qdrant-neo4j"
