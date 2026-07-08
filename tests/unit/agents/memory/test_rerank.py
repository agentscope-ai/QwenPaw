# -*- coding: utf-8 -*-
"""Tests for the reranker helper and its integration in memory manager."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.agents.memory.reranker import build_search_answer, rerank

# ---------------------------------------------------------------------------
# build_search_answer
# ---------------------------------------------------------------------------


class TestBuildSearchAnswer:
    """Tests for the build_search_answer helper."""

    def test_formats_candidates_in_reme_style(self) -> None:
        candidates = [
            {
                "path": "memory/2026-07-01.md",
                "start_line": 1,
                "end_line": 4,
                "text": "User enjoys Sichuan cuisine",
                "scores": {"score": 0.0164, "rerank": 0.7145},
            },
        ]
        answer = build_search_answer(candidates)
        assert "memory/2026-07-01.md:1-4" in answer
        assert "score=0.0164" in answer
        assert "rerank=0.7145" in answer
        assert "User enjoys Sichuan cuisine" in answer

    def test_missing_scores_render_as_dash(self) -> None:
        candidates = [
            {
                "path": "memory/test.md",
                "start_line": 1,
                "end_line": 2,
                "text": "hello",
                "scores": {},
            },
        ]
        answer = build_search_answer(candidates)
        assert "score=0.0000" in answer
        assert "vector=-" in answer
        assert "keyword=-" in answer
        assert "rerank=-" in answer

    def test_multiple_candidates(self) -> None:
        candidates = [
            {
                "path": f"memory/day{i}.md",
                "start_line": 1,
                "end_line": 3,
                "text": f"content {i}",
                "scores": {"score": 0.1 * i, "rerank": 0.9 - 0.1 * i},
            }
            for i in range(3)
        ]
        answer = build_search_answer(candidates)
        for i in range(3):
            assert f"memory/day{i}.md" in answer
            assert f"content {i}" in answer


# ---------------------------------------------------------------------------
# rerank
# ---------------------------------------------------------------------------


def _make_candidate(path: str = "memory/test.md", text: str = "hello") -> dict:
    return {
        "path": path,
        "start_line": 1,
        "end_line": 3,
        "text": text,
        "scores": {"score": 0.5},
    }


class TestRerank:
    """Tests for the rerank function."""

    @pytest.fixture()
    def mock_httpx(self) -> Any:
        """Patch httpx.AsyncClient to return a canned response."""
        with patch(
            "qwenpaw.agents.memory.reranker.httpx.AsyncClient",
        ) as mock_client_ctx:
            mock_client = AsyncMock()
            mock_client_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_client_ctx.return_value.__aexit__ = AsyncMock(
                return_value=False,
            )
            yield mock_client

    @pytest.mark.asyncio()
    async def test_reorders_by_relevance(
        self,
        mock_httpx: Any,
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"index": 1, "relevance_score": 0.99},
                {"index": 0, "relevance_score": 0.42},
            ],
        }
        mock_httpx.post = AsyncMock(return_value=mock_resp)

        c0 = _make_candidate(text="less relevant doc")
        c1 = _make_candidate(text="more relevant doc")
        result = await rerank(
            "test query",
            [c0, c1],
            api_key="test-key",
            endpoint_url="https://api.example.com/v1/rerank",
            model_name="bge-reranker-v2-m3",
        )

        assert len(result) == 2
        # The high-score doc (index=1) should come first
        assert result[0]["text"] == "more relevant doc"
        assert result[1]["text"] == "less relevant doc"
        # check rerank score was attached
        assert result[0]["scores"]["rerank"] == 0.99

    @pytest.mark.asyncio()
    async def test_includes_top_n_in_request(
        self,
        mock_httpx: Any,
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "results": [{"index": 0, "relevance_score": 0.9}],
        }
        mock_httpx.post = AsyncMock(return_value=mock_resp)

        candidates = [_make_candidate(text=f"doc{i}") for i in range(5)]
        await rerank(
            "query",
            candidates,
            api_key="k",
            endpoint_url="https://api.example.com/v1/rerank",
            model_name="m",
            top_n=3,
        )

        call_kwargs = mock_httpx.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["top_n"] == 3

    @pytest.mark.asyncio()
    async def test_result_count_may_be_fewer_than_input(
        self,
        mock_httpx: Any,
    ) -> None:
        """Many rerank APIs return only top_n results."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"index": 2, "relevance_score": 0.95},
                {"index": 0, "relevance_score": 0.8},
            ],
        }
        mock_httpx.post = AsyncMock(return_value=mock_resp)

        candidates = [_make_candidate(text=f"doc{i}") for i in range(5)]
        result = await rerank(
            "query",
            candidates,
            api_key="k",
            endpoint_url="https://api.example.com/v1/rerank",
            model_name="m",
            top_n=2,
        )

        assert len(result) == 2
        assert result[0]["text"] == "doc2"
        assert result[1]["text"] == "doc0"

    @pytest.mark.asyncio()
    async def test_timeout_falls_back_to_original(self) -> None:
        import httpx

        with patch(
            "qwenpaw.agents.memory.reranker.httpx.AsyncClient",
        ) as mock_ctx:
            mock_client = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(
                side_effect=httpx.TimeoutException("timeout"),
            )

            candidates = [_make_candidate(text=f"doc{i}") for i in range(3)]
            result = await rerank(
                "query",
                candidates,
                api_key="k",
                endpoint_url="https://api.example.com/v1/rerank",
                model_name="m",
                top_n=2,
            )
            assert len(result) == 2
            assert result[0]["text"] == "doc0"

    @pytest.mark.asyncio()
    async def test_api_error_falls_back(self) -> None:
        import httpx

        with patch(
            "qwenpaw.agents.memory.reranker.httpx.AsyncClient",
        ) as mock_ctx:
            mock_client = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(
                side_effect=httpx.RequestError("conn"),
            )

            candidates = [_make_candidate()]
            result = await rerank(
                "query",
                candidates,
                api_key="k",
                endpoint_url="https://api.example.com/v1/rerank",
                model_name="m",
            )
            assert len(result) == 1

    def test_candidates_must_have_required_keys(self) -> None:
        """Ensure build_search_answer handles missing scores gracefully."""
        candidates = [
            {
                "path": "memory/a.md",
                "start_line": 1,
                "end_line": 2,
                "text": "hello",
                # no scores key at all
            },
        ]
        answer = build_search_answer(candidates)
        assert "memory/a.md" in answer


# ---------------------------------------------------------------------------
# Integration: ReMeLightMemoryManager memory_search & auto_memory_search
# ---------------------------------------------------------------------------


class TestManagerRerankIntegration:
    """Tests for reranker integration in the memory manager."""

    @pytest.fixture()
    def mock_reme_and_config(self) -> Any:
        """Set up mocks for ReMe and the agent config."""
        reranker_cfg = MagicMock()
        reranker_cfg.enabled = True
        reranker_cfg.api_key = "test-key"
        reranker_cfg.endpoint_url = "https://api.example.com/v1/rerank"
        reranker_cfg.model_name = "bge-reranker"

        auto_cfg = MagicMock()
        auto_cfg.enabled = True
        auto_cfg.max_results = 3

        reme_cfg = MagicMock()
        reme_cfg.reranker_config = reranker_cfg
        reme_cfg.auto_memory_search_config = auto_cfg

        running_cfg = MagicMock()
        running_cfg.reme_light_memory_config = reme_cfg

        agent_cfg = MagicMock()
        agent_cfg.running = running_cfg

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.answer = "original answer"
        mock_response.metadata = {
            "results": [
                {
                    "path": "memory/a.md",
                    "start_line": 1,
                    "end_line": 3,
                    "text": "doc A",
                    "scores": {"score": 0.1},
                },
                {
                    "path": "memory/b.md",
                    "start_line": 1,
                    "end_line": 3,
                    "text": "doc B",
                    "scores": {"score": 0.2},
                },
            ],
        }

        mgr_mod = "qwenpaw.agents.memory.reme_light_memory_manager"
        with (
            patch(f"{mgr_mod}.load_agent_config") as mock_load_cfg,
            patch(f"{mgr_mod}.rerank") as mock_rerank_fn,
        ):
            mock_load_cfg.return_value = agent_cfg
            res = mock_response.metadata["results"]
            mock_rerank_fn.return_value = res[::-1]
            yield {
                "load_cfg": mock_load_cfg,
                "rerank_fn": mock_rerank_fn,
                "reranker_cfg": reranker_cfg,
                "response": mock_response,
            }

    @pytest.mark.asyncio()
    async def test_rerank_enabled_uses_larger_limit(
        self,
        mock_reme_and_config: Any,
    ) -> None:
        from qwenpaw.agents.memory.reme_light_memory_manager import (
            ReMeLightMemoryManager,
        )

        mgr = ReMeLightMemoryManager.__new__(  # noqa: WPS437
            ReMeLightMemoryManager,
        )
        mgr.agent_id = "test-agent"
        mgr._reme = MagicMock()  # pylint: disable=protected-access
        mgr._reme.is_started = True  # pylint: disable=protected-access

        with patch.object(
            mgr,
            "_run_reme_job",
            new_callable=AsyncMock,
        ) as mock_run:
            mock_run.return_value = mock_reme_and_config["response"]
            await mgr.memory_search("test query", max_results=5)

            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["limit"] == 15  # 5 * 3

    @pytest.mark.asyncio()
    async def test_rerank_disabled_uses_original_limit(
        self,
        mock_reme_and_config: Any,
    ) -> None:
        from qwenpaw.agents.memory.reme_light_memory_manager import (
            ReMeLightMemoryManager,
        )

        # Disable the reranker
        mock_reme_and_config["reranker_cfg"].enabled = False

        mgr = ReMeLightMemoryManager.__new__(  # noqa: WPS437
            ReMeLightMemoryManager,
        )
        mgr.agent_id = "test-agent"
        mgr._reme = MagicMock()  # pylint: disable=protected-access
        mgr._reme.is_started = True  # pylint: disable=protected-access

        with patch.object(
            mgr,
            "_run_reme_job",
            new_callable=AsyncMock,
        ) as mock_run:
            mock_run.return_value = mock_reme_and_config["response"]
            await mgr.memory_search("test query", max_results=5)

            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["limit"] == 5  # unchanged

    @pytest.mark.asyncio()
    async def test_auto_memory_search_uses_rerank(
        self,
        mock_reme_and_config: Any,
    ) -> None:
        from qwenpaw.agents.memory.reme_light_memory_manager import (
            ReMeLightMemoryManager,
        )

        mock_reme_and_config["reranker_cfg"].enabled = True
        mock_reme_and_config["response"].metadata["results"] = [
            {
                "path": "memory/x.md",
                "start_line": 1,
                "end_line": 2,
                "text": "relevant doc",
                "scores": {"score": 0.9},
            },
        ]

        mgr = ReMeLightMemoryManager.__new__(  # noqa: WPS437
            ReMeLightMemoryManager,
        )
        mgr.agent_id = "test-agent"
        mgr._reme = MagicMock()  # pylint: disable=protected-access
        mgr._reme.is_started = True  # pylint: disable=protected-access

        mock_msg = MagicMock()
        mock_msg.role = "user"
        mock_msg.get_text_content.return_value = "hello"

        with (
            patch.object(
                mgr,
                "_run_reme_job",
                new_callable=AsyncMock,
            ) as mock_run,
            patch(
                "qwenpaw.agents.memory.reme_light_memory_manager.uuid",
            ) as mock_uuid,
        ):
            mock_run.return_value = mock_reme_and_config["response"]
            mock_uuid.uuid4.return_value.hex = "test-uuid"

            result = await mgr.auto_memory_search([mock_msg], "test-agent")

            # Should have called with auto_memory_search_config.max_results
            assert result is not None
            assert "relevant doc" in result["text"]
            # Larger fetch limit
            assert mock_run.call_args.kwargs["limit"] == 9  # 3 * 3
