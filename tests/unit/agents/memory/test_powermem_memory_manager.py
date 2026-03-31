# -*- coding: utf-8 -*-
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from copaw.agents.memory import powermem_memory_manager
from copaw.agents.memory.powermem_memory_manager import PowerMemMemoryManager


@pytest.fixture
def mock_pm():
    mock = MagicMock()
    mock.initialize = AsyncMock()
    mock.add = AsyncMock(return_value={"id": 1})
    mock.search = AsyncMock(
        return_value={
            "results": [{"content": {"content": "test"}, "score": 0.9}],
        },
    )
    mock.get_all = AsyncMock(return_value={"results": []})
    return mock


@pytest.fixture
def mock_config():
    return {
        "vector_store": {"config": {"database_path": "/tmp/test/powermem.db"}},
        "logging": {"file": "/tmp/test/logs/powermem.log"},
        "embedder": {"provider": "openai", "config": {}},
    }


@pytest.mark.asyncio
async def test_memory_search_returns_tool_response():
    mock_async_memory = MagicMock()
    mock_async_memory.initialize = AsyncMock()
    mock_async_memory.search = AsyncMock(
        return_value={
            "results": [{"content": {"content": "test"}, "score": 0.9}],
        },
    )
    mock_async_memory.get_all = AsyncMock(return_value={"results": []})

    mock_cfg = {
        "vector_store": {"config": {"database_path": "/tmp/test/powermem.db"}},
        "logging": {"file": "/tmp/test/logs/powermem.log"},
        "embedder": {"provider": "openai", "config": {}},
    }

    mock_emb_config = MagicMock()
    mock_emb_config.backend = "openai"
    mock_emb_config.api_key = ""
    mock_emb_config.base_url = ""
    mock_emb_config.model_name = ""
    mock_emb_config.dimensions = 1024
    mock_emb_config.enable_cache = True
    mock_emb_config.use_dimensions = True
    mock_emb_config.max_cache_size = 1000
    mock_emb_config.max_input_length = 8000
    mock_emb_config.max_batch_size = 100

    mock_running = MagicMock()
    mock_running.embedding_config = mock_emb_config
    mock_running.context_compact = MagicMock()
    mock_running.context_compact.memory_compact_ratio = 0.3
    mock_running.tool_result_compact = MagicMock()
    mock_running.tool_result_compact.recent_max_bytes = 10000

    with patch("powermem.AsyncMemory", return_value=mock_async_memory):
        with patch("powermem.auto_config", return_value=mock_cfg):
            with patch.object(
                powermem_memory_manager,
                "load_agent_config",
            ) as mock_load:
                mock_load.return_value.running = mock_running

                mgr = PowerMemMemoryManager(
                    working_dir="/tmp/test",
                    agent_id="test",
                )
                await mgr.start()

                result = await mgr.memory_search("test query")

                assert isinstance(result.content, list)
                assert len(result.content) > 0


@pytest.mark.asyncio
async def test_close_without_powermem():
    mgr = PowerMemMemoryManager(working_dir="/tmp/test", agent_id="test")
    result = await mgr.close()
    assert result is True


@pytest.mark.asyncio
async def test_compact_tool_result_truncates_old():
    from agentscope.message import Msg

    mgr = PowerMemMemoryManager(working_dir="/tmp/test", agent_id="test")

    old_msg = Msg(name="user", content="x" * 2000, role="user")
    old_msg.id = "old1"
    recent_msg = Msg(name="user", content="y" * 15000, role="user")
    recent_msg.id = "recent1"
    messages = [old_msg, recent_msg]

    await mgr.compact_tool_result(
        messages=messages,
        recent_n=1,
        old_max_bytes=1000,
        recent_max_bytes=10000,
    )

    assert len(messages[0].content) <= 1000 + len("... [truncated]")
    assert len(messages[1].content) <= 10000 + len("... [truncated]")


@pytest.mark.asyncio
async def test_check_context_no_compaction_needed():
    mgr = PowerMemMemoryManager(working_dir="/tmp/test", agent_id="test")

    mock_msg = MagicMock()
    mock_msg.role = "user"
    mock_msg.__len__ = MagicMock(return_value=100)

    mock_counter = MagicMock(return_value=100)
    mock_counter.side_effect = None

    mock_agent_config = MagicMock()
    mock_agent_config.language = "en"
    mock_agent_config.running.max_input_length = 8000
    mock_agent_config.running.embedding_config = MagicMock()
    mock_agent_config.running.embedding_config.backend = "openai"
    mock_agent_config.running.embedding_config.api_key = ""
    mock_agent_config.running.embedding_config.base_url = ""
    mock_agent_config.running.embedding_config.model_name = ""
    mock_agent_config.running.embedding_config.dimensions = 1024
    mock_agent_config.running.embedding_config.enable_cache = True
    mock_agent_config.running.embedding_config.use_dimensions = True
    mock_agent_config.running.embedding_config.max_cache_size = 1000
    mock_agent_config.running.embedding_config.max_input_length = 8000
    mock_agent_config.running.embedding_config.max_batch_size = 100

    mock_token_counter = MagicMock()
    mock_token_counter.side_effect = lambda msg: 100

    with patch.object(
        powermem_memory_manager,
        "load_agent_config",
        return_value=mock_agent_config,
    ):
        with patch.object(
            powermem_memory_manager,
            "get_copaw_token_counter",
            return_value=mock_token_counter,
        ):
            removed, remaining, is_valid = await mgr.check_context(
                messages=[mock_msg],
                max_input_length=8000,
            )

    assert removed == []
    assert remaining == [mock_msg]
    assert is_valid is True


@pytest.mark.asyncio
async def test_check_context_requires_compaction():
    from agentscope.message import Msg

    mgr = PowerMemMemoryManager(working_dir="/tmp/test", agent_id="test")

    msg1 = Msg(name="user", content="hello", role="user")
    msg1.id = "1"
    msg2 = Msg(name="assistant", content="world", role="assistant")
    msg2.id = "2"

    mock_agent_config = MagicMock()
    mock_agent_config.language = "en"
    mock_agent_config.running.max_input_length = 50
    mock_agent_config.running.embedding_config = MagicMock()
    mock_agent_config.running.embedding_config.backend = "openai"
    mock_agent_config.running.embedding_config.api_key = ""
    mock_agent_config.running.embedding_config.base_url = ""
    mock_agent_config.running.embedding_config.model_name = ""
    mock_agent_config.running.embedding_config.dimensions = 1024
    mock_agent_config.running.embedding_config.enable_cache = True
    mock_agent_config.running.embedding_config.use_dimensions = True
    mock_agent_config.running.embedding_config.max_cache_size = 1000
    mock_agent_config.running.embedding_config.max_input_length = 8000
    mock_agent_config.running.embedding_config.max_batch_size = 100

    mock_token_counter = MagicMock()
    token_counts = {id(msg1): 100, id(msg2): 100}

    def count(msg):
        return token_counts.get(id(msg), 100)

    mock_token_counter.side_effect = count

    with patch.object(
        powermem_memory_manager,
        "load_agent_config",
        return_value=mock_agent_config,
    ):
        with patch.object(
            powermem_memory_manager,
            "get_copaw_token_counter",
            return_value=mock_token_counter,
        ):
            removed, _, is_valid = await mgr.check_context(
                messages=[msg1, msg2],
                max_input_length=50,
            )

    assert len(removed) > 0
    assert is_valid is True
