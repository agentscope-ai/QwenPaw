# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
# pylint: disable=unnecessary-lambda
"""Core tests for memory search rerank integration."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

AGENT_ID = "test-agent"
RERANK_URL = "https://api.siliconflow.cn/v1/rerank"
REAL_API_KEY = os.environ.get("RERANK_TEST_API_KEY", "")


def _real_rerank_available() -> bool:
    return bool(REAL_API_KEY)


rerank_api = pytest.mark.skipif(
    not _real_rerank_available(),
    reason="RERANK_TEST_API_KEY not set",
)


# -- fixtures -----------------------------------------------------------


@pytest.fixture
def mock_agent_config_real_key():
    from qwenpaw.config.config import (
        AgentProfileConfig,
        AgentsRunningConfig,
        AutoMemorySearchConfig,
        ReMeLightMemoryConfig,
    )

    memory_cfg = ReMeLightMemoryConfig(
        rerank_enabled=True,
        rerank_model="BAAI/bge-reranker-v2-m3",
        api_key=REAL_API_KEY,
        rerank_base_url=RERANK_URL,
        auto_memory_search_config=AutoMemorySearchConfig(
            enabled=True,
            max_results=3,
        ),
    )
    return AgentProfileConfig(
        id=AGENT_ID,
        name="TestAgent",
        description="",
        workspace_dir="/tmp/test-ws",
        running=AgentsRunningConfig(reme_light_memory_config=memory_cfg),
    )


def _create_manager(tmp_path, agent_config, monkeypatch):
    from qwenpaw.agents.memory import reme_light_memory_manager as rlmm

    monkeypatch.setattr(
        rlmm,
        "load_agent_config",
        lambda _id: agent_config,
        raising=False,
    )
    monkeypatch.setattr(
        rlmm,
        "load_config",
        lambda: MagicMock(),
        raising=False,
    )
    return rlmm.ReMeLightMemoryManager(
        working_dir=str(tmp_path),
        agent_id=AGENT_ID,
    )


_SIX_RESULTS = [
    {
        "path": f"memory/test{i}.md",
        "start_line": 1,
        "end_line": 3,
        "text": t,
        "scores": {"score": s, "vector": s - 0.02, "keyword": s + 0.05},
    }
    for i, (t, s) in enumerate(
        [
            ("重排序模型广泛应用于搜索引擎", 0.85),
            ("量子计算是计算科学的前沿领域", 0.72),
            ("预训练语言模型带来了新进展", 0.65),
            ("今天天气很好适合出去玩", 0.30),
            ("Python 是最流行的编程语言", 0.25),
            ("红楼梦是中国古典名著", 0.20),
        ],
        start=1,
    )
]


@pytest.fixture
def manager_with_reme(mock_agent_config_real_key, tmp_path, monkeypatch):
    mgr = _create_manager(tmp_path, mock_agent_config_real_key, monkeypatch)
    _wire_reme(mgr)
    return mgr


def _wire_reme(mgr):
    from reme.schema import Response

    mgr._reme = MagicMock()
    mgr._reme.is_started = True
    mgr._reme.run_job = AsyncMock(
        return_value=Response(
            success=True,
            answer="dummy raw answer",
            metadata={"results": _SIX_RESULTS},
        ),
    )


# -- _build_search_answer -----------------------------------------------

_SAMPLE_CANDIDATES: list[dict[str, Any]] = [
    {
        "path": "memory/2025-01-15.md",
        "start_line": 10,
        "end_line": 15,
        "text": "用户喜欢吃川菜，水煮鱼是最爱",
        "scores": {"score": 0.8534, "vector": 0.8200, "keyword": 0.9100},
    },
]


class TestBuildSearchAnswer:
    def test_formats_candidates_in_reme_style(self):
        from qwenpaw.agents.memory.reranker import build_search_answer

        answer = build_search_answer(_SAMPLE_CANDIDATES)
        assert "==========" in answer
        assert "score=0.8534" in answer
        assert "用户喜欢吃川菜" in answer


# -- config reading -----------------------------------------------------


class TestConfigReading:
    def test_load_agent_config_end_to_end(self, tmp_path, monkeypatch):
        """端到端：写真实文件，调真正的 load_agent_config。"""
        import json
        import qwenpaw.config.config as cfg
        from qwenpaw.config import utils as cfg_utils

        ws = tmp_path / "ws"
        ws.mkdir()

        config_json = {
            "agents": {
                "profiles": {
                    AGENT_ID: {"id": AGENT_ID, "workspace_dir": str(ws)},
                },
            },
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config_json), encoding="utf-8")

        (ws / "agent.json").write_text(
            json.dumps(
                {
                    "id": AGENT_ID,
                    "name": "TestAgent",
                    "description": "",
                    "workspace_dir": str(ws),
                    "running": {
                        "reme_light_memory_config": {
                            "rerank_enabled": True,
                            "rerank_model": "BAAI/bge-reranker-v2-m3",
                            "api_key": "sk-e2e-test",
                            "rerank_base_url": RERANK_URL,
                        },
                    },
                },
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(cfg_utils, "get_config_path", lambda: config_path)
        monkeypatch.setattr(cfg_utils, "_config_cache", None, raising=False)
        monkeypatch.setattr(cfg_utils, "_config_mtime", None, raising=False)
        monkeypatch.setattr(cfg_utils, "_agent_config_cache", {})

        agent_config = cfg.load_agent_config(AGENT_ID)
        memory_cfg = agent_config.running.reme_light_memory_config
        assert memory_cfg.rerank_enabled is True
        assert memory_cfg.rerank_model == "BAAI/bge-reranker-v2-m3"
        assert memory_cfg.api_key == "sk-e2e-test"
        assert memory_cfg.rerank_base_url == RERANK_URL

    def test_rerank_disabled_by_default(self):
        from qwenpaw.config.config import ReMeLightMemoryConfig

        cfg = ReMeLightMemoryConfig()
        assert cfg.rerank_enabled is False


# -- rerank() real-API --------------------------------------------------

REAL_CANDIDATES: list[dict[str, Any]] = [
    {
        "path": "memory/test1.md",
        "start_line": 1,
        "end_line": 3,
        "text": "重排序模型广泛应用于搜索引擎和推荐系统，按相关性对候选文本进行排序",
        "scores": {"score": 0.85, "vector": 0.82, "keyword": 0.90},
    },
    {
        "path": "memory/test2.md",
        "start_line": 1,
        "end_line": 3,
        "text": "量子计算是计算科学的前沿领域",
        "scores": {"score": 0.72, "vector": 0.75, "keyword": 0.68},
    },
    {
        "path": "memory/test3.md",
        "start_line": 1,
        "end_line": 3,
        "text": "预训练语言模型的发展为重排序模型带来了新的进展",
        "scores": {"score": 0.65, "vector": 0.70, "keyword": 0.58},
    },
]


class TestRerank:
    @rerank_api
    @pytest.mark.asyncio
    async def test_returns_top_n_results(self):
        from qwenpaw.agents.memory.reranker import rerank

        result = await rerank(
            query="什么是重排序模型",
            candidates=REAL_CANDIDATES,
            api_key=REAL_API_KEY,
            base_url=RERANK_URL,
            model_name="BAAI/bge-reranker-v2-m3",
            top_n=2,
        )
        assert len(result) == 2
        for c in result:
            assert "rerank" in c.get("scores", {})

    @rerank_api
    @pytest.mark.asyncio
    async def test_relevant_doc_ranks_higher(self):
        from qwenpaw.agents.memory.reranker import rerank

        result = await rerank(
            query="什么是重排序模型",
            candidates=REAL_CANDIDATES,
            api_key=REAL_API_KEY,
            base_url=RERANK_URL,
            model_name="BAAI/bge-reranker-v2-m3",
            top_n=3,
        )
        texts = [c["text"] for c in result]
        qc_idx = next(i for i, t in enumerate(texts) if "量子" in t)
        rerank_idx = next(i for i, t in enumerate(texts) if "预训练" in t)
        assert (
            rerank_idx < qc_idx
        ), f"rerank-related doc should rank above quantum, got: {texts}"

    @pytest.mark.asyncio
    async def test_no_api_key_falls_back(self):
        from qwenpaw.agents.memory.reranker import rerank

        result = await rerank(
            query="test",
            candidates=REAL_CANDIDATES,
            api_key="",
            base_url=RERANK_URL,
            model_name="BAAI/bge-reranker-v2-m3",
            top_n=2,
        )
        assert len(result) == 2
        assert "搜索引擎" in result[0]["text"]


# -- memory_search integration ------------------------------------------


class TestMemorySearch:
    @pytest.mark.asyncio
    async def test_rerank_disabled_uses_original_answer(
        self,
        tmp_path,
        monkeypatch,
    ):
        from qwenpaw.config.config import (
            AgentProfileConfig,
            AgentsRunningConfig,
            ReMeLightMemoryConfig,
        )
        from qwenpaw.agents.memory import reme_light_memory_manager as rlmm

        memory_cfg = ReMeLightMemoryConfig(rerank_enabled=False)
        agent_config = AgentProfileConfig(
            id=AGENT_ID,
            name="TestAgent",
            description="",
            workspace_dir="/tmp/test-ws",
            running=AgentsRunningConfig(reme_light_memory_config=memory_cfg),
        )
        monkeypatch.setattr(
            rlmm,
            "load_agent_config",
            lambda _id: agent_config,
            raising=False,
        )
        monkeypatch.setattr(
            rlmm,
            "load_config",
            lambda: MagicMock(),
            raising=False,
        )
        mgr = rlmm.ReMeLightMemoryManager(
            working_dir=str(tmp_path),
            agent_id=AGENT_ID,
        )
        _wire_reme(mgr)
        chunk = await mgr.memory_search("test")
        assert "dummy raw answer" in str(chunk.content[0].text)

    @pytest.mark.asyncio
    async def test_rerank_enabled_uses_larger_limit(
        self,
        manager_with_reme,
    ):
        await manager_with_reme.memory_search("test", max_results=3)
        _, kwargs = manager_with_reme._reme.run_job.call_args
        assert kwargs["limit"] == 9  # 3 * 3

    @rerank_api
    @pytest.mark.asyncio
    async def test_rerank_enabled_produces_rerank_score(
        self,
        manager_with_reme,
    ):
        chunk = await manager_with_reme.memory_search("重排序", max_results=3)
        assert "rerank=" in str(chunk.content[0].text)

    @rerank_api
    @pytest.mark.asyncio
    async def test_rerank_reorders_results(
        self,
        manager_with_reme,
    ):
        chunk = await manager_with_reme.memory_search("经典名著", max_results=3)
        text = str(chunk.content[0].text)
        assert "红楼梦" in text, f"红楼梦 should appear, got:\n{text}"
