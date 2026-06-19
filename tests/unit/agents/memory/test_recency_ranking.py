# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Tests for recency-aware ranking in memory search."""
from contextlib import contextmanager
import json
import math
import sys
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

# Mock reme modules before importing memory manager
_MOCK_MODULES = [
    "reme",
    "reme.reme_light",
    "reme.memory",
    "reme.memory.file_based",
    "reme.memory.file_based.reme_in_memory_memory",
]
for _mod in _MOCK_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

_MOD = "qwenpaw.agents.memory.reme_light_memory_manager"


def _make_agent_config(
    recency_enabled=False,
    half_life_days=30,
):
    cfg = MagicMock()
    # Embed model configs
    emc = cfg.running.reme_light_memory_config.embedding_model_config
    emc.backend = "openai"
    emc.api_key = "testkey"
    emc.base_url = "http://localhost"
    emc.model_name = "text-emb-3"
    emc.dimensions = 1536
    emc.enable_cache = False
    emc.use_dimensions = False
    emc.max_cache_size = 100
    emc.max_input_length = 8192
    emc.max_batch_size = 32

    # Recency configs
    reme_cfg = cfg.running.reme_light_memory_config
    reme_cfg.memory_search_recency_boost_enabled = recency_enabled
    reme_cfg.memory_search_recency_half_life_days = half_life_days

    cfg.running.context_compact.memory_compact_ratio = 0.5
    cfg.running.context_compact.compact_with_thinking_block = False
    cfg.running.tool_result_compact.recent_max_bytes = 1024
    cfg.running.max_input_length = 100000
    cfg.language = "en"
    cfg.workspace_dir = "/tmp/test_ws"
    return cfg


@contextmanager
def _build_manager(tmp_path, mock_reme, agent_config):
    with (
        patch("reme.reme_light.ReMeLight", return_value=mock_reme),
        patch(
            f"{_MOD}.load_agent_config",
            return_value=agent_config,
        ),
        patch(
            f"{_MOD}.load_config",
            return_value=MagicMock(user_timezone=None),
        ),
        patch(
            f"{_MOD}.create_model_and_formatter",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch(
            f"{_MOD}.get_token_counter",
            return_value=MagicMock(),
        ),
        patch(f"{_MOD}.EnvVarLoader.get_str", return_value="local"),
        patch(f"{_MOD}.EnvVarLoader.get_bool", return_value=True),
        patch(f"{_MOD}.set_current_workspace_dir"),
        patch(f"{_MOD}.set_current_recent_max_bytes"),
    ):
        from qwenpaw.agents.memory.reme_light_memory_manager import (
            ReMeLightMemoryManager,
        )

        m = ReMeLightMemoryManager(
            working_dir=str(tmp_path),
            agent_id="test-agent",
        )
        m._reme = mock_reme
        m.chat_model = MagicMock()
        m.formatter = MagicMock()
        yield m


@pytest.fixture
def mock_reme():
    m = MagicMock()
    m._started = True
    return m


@pytest.mark.asyncio
async def test_recency_ranking_disabled(tmp_path, mock_reme):
    # Setup agent config with recency disabled
    cfg = _make_agent_config(recency_enabled=False)
    with _build_manager(tmp_path, mock_reme, cfg) as manager:
        # Mock the return value of reme.memory_search
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        old_date = (date.today() - timedelta(days=60)).isoformat()

        raw_results = [
            {"path": f"memory/{old_date}.md", "score": 0.8},
            {"path": f"memory/{yesterday}.md", "score": 0.7},
        ]
        mock_reme.memory_search = AsyncMock(
            return_value=ToolResponse(
                content=[TextBlock(type="text", text=json.dumps(raw_results))],
            ),
        )

        response = await manager.memory_search(query="test", min_score=0.1)
        results = json.loads(response.content[0]["text"])

        # Score order should remain exactly as returned by search
        # (old_date first)
        assert len(results) == 2
        assert results[0]["path"] == f"memory/{old_date}.md"
        assert results[0]["score"] == 0.8
        assert results[1]["path"] == f"memory/{yesterday}.md"
        assert results[1]["score"] == 0.7


@pytest.mark.asyncio
async def test_recency_ranking_enabled(tmp_path, mock_reme):
    # Setup agent config with recency enabled (half life = 30 days)
    cfg = _make_agent_config(recency_enabled=True, half_life_days=30)
    with _build_manager(tmp_path, mock_reme, cfg) as manager:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        old_date = (date.today() - timedelta(days=30)).isoformat()

        # Old date starts with slightly higher score but will decay much more
        raw_results = [
            {"path": f"memory/{old_date}.md", "score": 0.85},
            {"path": f"memory/{yesterday}.md", "score": 0.8},
            {"path": "MEMORY.md", "score": 0.75},
        ]
        mock_reme.memory_search = AsyncMock(
            return_value=ToolResponse(
                content=[TextBlock(type="text", text=json.dumps(raw_results))],
            ),
        )

        response = await manager.memory_search(query="test", min_score=0.1)
        results = json.loads(response.content[0]["text"])

        assert len(results) == 3

        # MEMORY.md should not decay (factor = 1.0) -> score stays 0.75
        # memory/yesterday.md (age = 1 day) ->
        # factor = exp(-ln(2) * 1 / 30) = 0.977 ->
        # score = 0.8 * 0.977 = 0.7816
        # memory/old_date.md (age = 30 days) ->
        # factor = exp(-ln(2) * 30 / 30) = 0.5 ->
        # score = 0.85 * 0.5 = 0.425
        # Sort order should now be: yesterday (0.7816), MEMORY.md (0.75),
        # old_date (0.425)

        assert results[0]["path"] == f"memory/{yesterday}.md"
        assert math.isclose(
            results[0]["score"],
            0.8 * math.exp(-math.log(2) * 1 / 30),
        )

        assert results[1]["path"] == "MEMORY.md"
        assert results[1]["score"] == 0.75

        assert results[2]["path"] == f"memory/{old_date}.md"
        assert results[2]["score"] == 0.425


@pytest.mark.asyncio
async def test_recency_ranking_no_min_score_filtering(tmp_path, mock_reme):
    # Setup agent config with recency enabled
    cfg = _make_agent_config(recency_enabled=True, half_life_days=30)
    with _build_manager(tmp_path, mock_reme, cfg) as manager:
        old_date = (date.today() - timedelta(days=30)).isoformat()

        # Starts with score 0.3, decays to 0.15 (below min_score 0.2)
        raw_results = [
            {"path": f"memory/{old_date}.md", "score": 0.3},
        ]
        mock_reme.memory_search = AsyncMock(
            return_value=ToolResponse(
                content=[TextBlock(type="text", text=json.dumps(raw_results))],
            ),
        )

        response = await manager.memory_search(query="test", min_score=0.2)
        results = json.loads(response.content[0]["text"])

        # Decayed score = 0.15, which is < min_score 0.2.
        # Result should NOT be filtered out (only re-ranked).
        assert len(results) == 1
        assert results[0]["path"] == f"memory/{old_date}.md"
        assert math.isclose(results[0]["score"], 0.15)


@pytest.mark.asyncio
async def test_recency_ranking_timezone_aware(tmp_path, mock_reme):
    # Setup agent config with recency enabled
    cfg = _make_agent_config(recency_enabled=True, half_life_days=30)

    # We patch load_config to return a specific timezone
    with (
        patch("reme.reme_light.ReMeLight", return_value=mock_reme),
        patch(
            f"{_MOD}.load_agent_config",
            return_value=cfg,
        ),
        patch(
            f"{_MOD}.load_config",
            return_value=MagicMock(user_timezone="Asia/Ho_Chi_Minh"),
        ),
        patch(
            f"{_MOD}.create_model_and_formatter",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch(
            f"{_MOD}.get_token_counter",
            return_value=MagicMock(),
        ),
        patch(f"{_MOD}.EnvVarLoader.get_str", return_value="local"),
        patch(f"{_MOD}.EnvVarLoader.get_bool", return_value=True),
        patch(f"{_MOD}.set_current_workspace_dir"),
        patch(f"{_MOD}.set_current_recent_max_bytes"),
    ):
        from qwenpaw.agents.memory.reme_light_memory_manager import (
            ReMeLightMemoryManager,
        )

        manager = ReMeLightMemoryManager(
            working_dir=str(tmp_path),
            agent_id="test-agent",
        )
        manager._reme = mock_reme

        from zoneinfo import ZoneInfo
        from datetime import datetime

        tz = ZoneInfo("Asia/Ho_Chi_Minh")
        tz_today = datetime.now(tz).date()

        yesterday = (tz_today - timedelta(days=1)).isoformat()
        raw_results = [
            {"path": f"memory/{yesterday}.md", "score": 0.8},
        ]
        mock_reme.memory_search = AsyncMock(
            return_value=ToolResponse(
                content=[TextBlock(type="text", text=json.dumps(raw_results))],
            ),
        )

        response = await manager.memory_search(query="test", min_score=0.1)
        results = json.loads(response.content[0]["text"])

        assert len(results) == 1
        assert results[0]["path"] == f"memory/{yesterday}.md"
        assert math.isclose(
            results[0]["score"],
            0.8 * math.exp(-math.log(2) * 1 / 30),
        )
