# -*- coding: utf-8 -*-
"""Tests for LightContextManager._prune_tool_result with absolute_max_bytes."""
# pylint: disable=protected-access,redefined-outer-name

from unittest.mock import patch, MagicMock

import pytest
from agentscope.message import Msg

from qwenpaw.agents.context.light_context_manager import LightContextManager
from qwenpaw.config.config import ToolResultPruningConfig


def _make_tool_result_msg(
    tool_id: str,
    output_text: str,
    tool_name: str = "test_tool",
) -> Msg:
    """Helper to create a message containing a tool_result block."""
    return Msg(
        name="system",
        role="system",
        content=[
            {
                "type": "tool_result",
                "id": tool_id,
                "name": tool_name,
                "output": [{"type": "text", "text": output_text}],
            },
        ],
    )


def _make_tool_use_msg(tool_id: str, tool_name: str = "test_tool") -> Msg:
    """Helper to create a message containing a tool_use block."""
    return Msg(
        name="assistant",
        role="assistant",
        content=[
            {
                "type": "tool_use",
                "id": tool_id,
                "name": tool_name,
                "input": {},
                "raw_input": "",
            },
        ],
    )


def _mock_agent_config():
    """Create a mock agent config with default pruning settings."""
    mock_config = MagicMock()
    trc = mock_config.running.light_context_config.tool_result_pruning_config
    trc.exempt_file_extensions = [".md"]
    trc.exempt_tool_names = ["chat_with_agent"]
    trc.tool_results_cache = "tool_results"
    return mock_config


@pytest.fixture
def ctx_mgr(tmp_path):
    """Create a LightContextManager instance for testing."""
    with patch(
        "qwenpaw.agents.context.light_context_manager.load_agent_config",
        return_value=_mock_agent_config(),
    ):
        return LightContextManager(
            working_dir=str(tmp_path),
            agent_id="test-agent",
        )


class TestPruneToolResultAbsoluteMax:
    """Tests for absolute_max_bytes enforcement in _prune_tool_result."""

    @pytest.mark.asyncio
    async def test_recent_capped_by_absolute_max(self, ctx_mgr):
        """Recent tool result should be capped at absolute_max_bytes."""
        big_output = "A" * 200000  # 200KB
        messages = [_make_tool_result_msg("id-1", big_output)]

        with patch(
            "qwenpaw.agents.context.light_context_manager.load_agent_config",
            return_value=_mock_agent_config(),
        ):
            result = await ctx_mgr._prune_tool_result(
                messages=messages,
                recent_n=2,
                old_max_bytes=3000,
                recent_max_bytes=50000,
                absolute_max_bytes=10000,
            )

        output_text = result[0].content[0]["output"][0]["text"]
        # Should be truncated well under 200KB; must not exceed absolute max
        assert (
            len(output_text.encode("utf-8")) <= 10000 + 500
        )  # slack for notice

    @pytest.mark.asyncio
    async def test_old_capped_by_smaller_of_old_and_absolute(self, ctx_mgr):
        """Old tool result uses min(old_max_bytes, absolute_max_bytes)."""
        big_output = "B" * 200000
        # Insert a non-tool_result message to break the recent chain,
        # making the first tool_result "old"
        messages = [
            _make_tool_result_msg("id-1", big_output),  # old (before user msg)
            Msg(name="user", role="user", content="question"),  # break
            _make_tool_result_msg("id-2", "small"),  # recent
        ]

        with patch(
            "qwenpaw.agents.context.light_context_manager.load_agent_config",
            return_value=_mock_agent_config(),
        ):
            result = await ctx_mgr._prune_tool_result(
                messages=messages,
                recent_n=2,
                old_max_bytes=3000,
                recent_max_bytes=50000,
                absolute_max_bytes=50000,  # > old_max_bytes, so old uses 3000
            )

        old_output = result[0].content[0]["output"][0]["text"]
        # Old messages use old_max_bytes since it's smaller than absolute
        assert len(old_output.encode("utf-8")) <= 3000 + 600

    @pytest.mark.asyncio
    async def test_absolute_lower_than_recent(self, ctx_mgr):
        """When absolute_max < recent_max, absolute wins for recent msgs."""
        big_output = "C" * 100000
        messages = [_make_tool_result_msg("id-1", big_output)]

        with patch(
            "qwenpaw.agents.context.light_context_manager.load_agent_config",
            return_value=_mock_agent_config(),
        ):
            result = await ctx_mgr._prune_tool_result(
                messages=messages,
                recent_n=2,
                old_max_bytes=3000,
                recent_max_bytes=50000,
                absolute_max_bytes=10000,  # < recent_max_bytes
            )

        output_text = result[0].content[0]["output"][0]["text"]
        assert len(output_text.encode("utf-8")) <= 10000 + 500

    @pytest.mark.asyncio
    async def test_exempt_tool_respects_absolute_max(self, ctx_mgr):
        """Exempt tool results should still be capped at absolute_max_bytes."""
        big_output = "D" * 200000
        messages = [
            _make_tool_use_msg("id-1", tool_name="chat_with_agent"),
            _make_tool_result_msg(
                "id-1",
                big_output,
                tool_name="chat_with_agent",
            ),
        ]

        with patch(
            "qwenpaw.agents.context.light_context_manager.load_agent_config",
            return_value=_mock_agent_config(),
        ):
            result = await ctx_mgr._prune_tool_result(
                messages=messages,
                recent_n=2,
                old_max_bytes=3000,
                recent_max_bytes=50000,
                absolute_max_bytes=10000,
            )

        output_text = result[1].content[0]["output"][0]["text"]
        # Even exempt tool is capped at min(recent_max, absolute_max)
        assert len(output_text.encode("utf-8")) <= 10000 + 500

    @pytest.mark.asyncio
    async def test_small_output_unchanged(self, ctx_mgr):
        """Tool result under absolute_max_bytes should not be truncated."""
        small_output = "hello world"
        messages = [_make_tool_result_msg("id-1", small_output)]

        with patch(
            "qwenpaw.agents.context.light_context_manager.load_agent_config",
            return_value=_mock_agent_config(),
        ):
            result = await ctx_mgr._prune_tool_result(
                messages=messages,
                recent_n=2,
                old_max_bytes=3000,
                recent_max_bytes=50000,
                absolute_max_bytes=100000,
            )

        output_text = result[0].content[0]["output"][0]["text"]
        assert output_text == small_output

    @pytest.mark.asyncio
    async def test_default_absolute_max_allows_recent_max(self, ctx_mgr):
        """With default absolute_max=100000, recent_max=50000 should win."""
        output_40k = "E" * 40000
        messages = [_make_tool_result_msg("id-1", output_40k)]

        with patch(
            "qwenpaw.agents.context.light_context_manager.load_agent_config",
            return_value=_mock_agent_config(),
        ):
            result = await ctx_mgr._prune_tool_result(
                messages=messages,
                recent_n=2,
                old_max_bytes=3000,
                recent_max_bytes=50000,
                absolute_max_bytes=100000,
            )

        output_text = result[0].content[0]["output"][0]["text"]
        # 40KB < 50KB recent_max, should pass through
        assert output_text == output_40k


class TestToolResultPruningConfigAbsoluteMax:
    """Tests for pruning_absolute_max_bytes config field."""

    def test_default_value(self):
        config = ToolResultPruningConfig()
        assert config.pruning_absolute_max_bytes == 100000

    def test_custom_value(self):
        config = ToolResultPruningConfig(pruning_absolute_max_bytes=50000)
        assert config.pruning_absolute_max_bytes == 50000

    def test_minimum_value(self):
        config = ToolResultPruningConfig(pruning_absolute_max_bytes=10000)
        assert config.pruning_absolute_max_bytes == 10000

    def test_below_minimum_raises(self):
        with pytest.raises(Exception):
            ToolResultPruningConfig(pruning_absolute_max_bytes=9999)

    def test_absolute_greater_than_recent(self):
        """Typical config: absolute_max > recent_max."""
        config = ToolResultPruningConfig(
            pruning_recent_msg_max_bytes=50000,
            pruning_absolute_max_bytes=100000,
        )
        assert (
            config.pruning_absolute_max_bytes
            > config.pruning_recent_msg_max_bytes
        )
