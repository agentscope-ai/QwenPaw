# -*- coding: utf-8 -*-
import asyncio
import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentscope.message import Msg

from copaw.agents.react_agent import CoPawAgent
from copaw.config import load_config


@pytest.mark.asyncio
async def test_copaw_agent_reasoning_retries_on_ssl_error() -> None:
    # Setup agent
    agent = object.__new__(CoPawAgent)
    agent.toolkit = MagicMock()
    agent.toolkit.get_json_schemas.return_value = []

    # Mock super()._reasoning
    # Patch ReActAgent._reasoning as CoPawAgent calls it via super()
    with patch(
        "agentscope.agent.ReActAgent._reasoning",
        new_callable=AsyncMock,
    ) as mock_super_reasoning:
        # First call fails with SSLError, second succeeds
        mock_super_reasoning.side_effect = [
            ssl.SSLError("decryption failed or bad record mac"),
            Msg("assistant", "success after retry", role="assistant"),
        ]

        # Configure retries
        config = load_config()
        config.agents.running.llm_retries = 1
        config.agents.running.llm_retry_delay = 0.01

        with patch(
            "copaw.agents.react_agent.load_config",
            return_value=config,
        ):
            # pylint: disable=protected-access
            result = await agent._reasoning(tool_choice="none")

            assert result.content == "success after retry"
            assert mock_super_reasoning.call_count == 2


@pytest.mark.asyncio
async def test_copaw_agent_reasoning_retries_on_timeout_error() -> None:
    agent = object.__new__(CoPawAgent)
    agent.toolkit = MagicMock()
    agent.toolkit.get_json_schemas.return_value = []

    with patch(
        "agentscope.agent.ReActAgent._reasoning",
        new_callable=AsyncMock,
    ) as mock_super_reasoning:
        mock_super_reasoning.side_effect = [
            asyncio.TimeoutError("request timed out"),
            Msg("assistant", "success after timeout retry", role="assistant"),
        ]

        config = load_config()
        config.agents.running.llm_retries = 1
        config.agents.running.llm_retry_delay = 0.01

        with patch(
            "copaw.agents.react_agent.load_config",
            return_value=config,
        ):
            # pylint: disable=protected-access
            result = await agent._reasoning(tool_choice="none")

            assert result.content == "success after timeout retry"
            assert mock_super_reasoning.call_count == 2


@pytest.mark.asyncio
async def test_copaw_agent_reasoning_fails_after_max_retries() -> None:
    agent = object.__new__(CoPawAgent)
    agent.toolkit = MagicMock()
    agent.toolkit.get_json_schemas.return_value = []

    with patch(
        "agentscope.agent.ReActAgent._reasoning",
        new_callable=AsyncMock,
    ) as mock_super_reasoning:
        mock_super_reasoning.side_effect = ssl.SSLError("persistent ssl error")

        config = load_config()
        config.agents.running.llm_retries = 2
        config.agents.running.llm_retry_delay = 0.01

        with patch(
            "copaw.agents.react_agent.load_config",
            return_value=config,
        ):
            with pytest.raises(ssl.SSLError, match="persistent ssl error"):
                # pylint: disable=protected-access
                await agent._reasoning(tool_choice="none")

            assert mock_super_reasoning.call_count == 3
