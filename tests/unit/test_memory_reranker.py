#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument,redefined-outer-name
"""Unit tests for ReMe memory reranker (over-fetch + rerank + cap).

Tests cover:
  - disabled: no rerank, behavior identical to plain search
  - enabled + API ok: results reordered by reranker, capped to max_results
  - over-fetch: search limit = N * candidate_multiplier
  - timeout / http error / index mismatch / duplicate index: graceful fallback
  - no base_url: skip rerank entirely
  - empty results: no rerank call, returns NO_MEMORY_RESULTS
  - answer: preserved when order unchanged, rebuilt when changed or truncated
  - link expansions: preserved in reconstructed answer after rerank+cap,
    truncation-only, and fallback+truncation scenarios
"""

import types
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import qwenpaw.agents.memory.reme_light_memory_manager as mgr

ReMeLightMemoryManager = mgr.ReMeLightMemoryManager
NO_MEMORY_RESULTS = mgr.NO_MEMORY_RESULTS


def _make_response(results, answer="", link_expansion=None):
    """Build a fake ReMe Response-like object."""
    r = types.SimpleNamespace()
    r.success = True
    r.answer = answer
    r.metadata = {"results": list(results)}
    if link_expansion:
        r.metadata["link_expansion"] = link_expansion
    return r


def _make_reme_answer(results, link_expansion=None):
    """Build a ReMe-formatted answer string with sections and expansions.

    Produces the same format as ReMe's ``search_step``::

        ========== path:start_line-end_line [score=...] ==========
        text
          outlinks (N):
            → linked/path  [meta]
              via anchor=#123
          inlinks (N):
            ...

    If *link_expansion* is provided, renders expansion lines for each
    result whose path has an entry.
    """
    from reme.utils import render_expansion_lines

    lines = []
    for r in results:
        path = r.get("path", "")
        sl = r.get("start_line", 0)
        el = r.get("end_line", 0)
        score = ReMeLightMemoryManager._extract_score(r)
        text = r.get("text", "")
        header = (
            f"========== {path}:{sl}-{el} " f"[score={score:.4f}] =========="
        )
        lines.append(f"{header}\n{text}")
        if link_expansion:
            expansion = link_expansion.get(path, {})
            if expansion:
                lines.extend(render_expansion_lines(expansion))
    return "\n".join(lines)


def _make_link_expansion():
    """Build a realistic link_expansion metadata dict.

    Uses ``anchors`` (ReMe 0.4.1.4+ shape).
    """
    return {
        "memory/0.md": {
            "outlinks": [
                {
                    "path": "memory/other.md:5-8",
                    "meta": {"score": 0.8, "name": "Other doc"},
                    "anchors": [123],
                },
            ],
            "inlinks": [],
        },
        "memory/2.md": {
            "outlinks": [],
            "inlinks": [
                {
                    "path": "memory/third.md:10-12",
                    "meta": {"score": 0.7, "name": "Third doc"},
                    "anchors": [456],
                },
            ],
        },
    }


def _result(i, text=None):
    return {
        "path": f"memory/{i}.md",
        "start_line": 1,
        "end_line": 3,
        "scores": {"score": 0.5 - i * 0.05},
        "text": text or f"doc-{i}",
    }


def _make_config(**overrides):
    """Build a dummy RerankerConfig with sensible defaults."""
    d = {
        "enabled": True,
        "base_url": "https://x",
        "model_name": "m",
        "candidate_multiplier": 3,
        "timeout": 10.0,
    }
    d.update(overrides)
    return types.SimpleNamespace(**d)


@pytest.fixture
def manager():
    m = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    return m


# ── disabled ──


@pytest.mark.asyncio
async def test_disabled_no_rerank(manager):
    manager._get_reranker_config = MagicMock(return_value=None)
    rs = [_result(0), _result(1)]
    resp = _make_response(rs)
    manager._run_reme_job = AsyncMock(return_value=resp)
    manager._rerank_search_results = AsyncMock()

    await manager.memory_search("q", max_results=2)

    assert manager._rerank_search_results.call_count == 0


# ── over-fetch ──


@pytest.mark.asyncio
async def test_overfetch_multiplier(manager):
    manager._get_reranker_config = MagicMock(
        return_value=_make_config(candidate_multiplier=3),
    )
    manager._rerank_search_results = AsyncMock()
    rs = [_result(i) for i in range(6)]
    resp = _make_response(rs)
    manager._run_reme_job = AsyncMock(return_value=resp)

    await manager.memory_search("q", max_results=2)

    limit = manager._run_reme_job.call_args.kwargs["limit"]
    assert limit == 6, "limit should be max_results * multiplier"


# ── enabled + API ok ──


@pytest.mark.asyncio
async def test_enabled_rerank_ok_and_cap(manager):
    manager._get_reranker_config = MagicMock(
        return_value=_make_config(candidate_multiplier=3),
    )

    async def fake_api(query, docs, c):
        return list(range(len(docs)))[::-1]

    manager._call_reranker_api = fake_api
    rs = [_result(i, text=f"t{i}") for i in range(6)]
    resp = _make_response(rs)
    manager._run_reme_job = AsyncMock(return_value=resp)

    await manager.memory_search("q", max_results=2)

    assert len(resp.metadata["results"]) == 2
    assert resp.metadata["results"][0]["text"] == "t5"
    assert "t5" in str(resp.answer)


# ── fallback: timeout ──


@pytest.mark.asyncio
async def test_rerank_timeout_fallback(manager):
    manager._get_reranker_config = MagicMock(
        return_value=_make_config(),
    )

    async def raise_timeout(query, docs, c):
        raise httpx.TimeoutException("timeout")

    manager._call_reranker_api = raise_timeout
    rs = [_result(i, text=f"t{i}") for i in range(6)]
    resp = _make_response(rs)
    manager._run_reme_job = AsyncMock(return_value=resp)

    await manager.memory_search("q", max_results=2)

    assert resp.metadata["results"][0]["text"] == "t0"
    assert len(resp.metadata["results"]) == 2


# ── fallback: HTTP error ──


@pytest.mark.asyncio
async def test_rerank_http_error_fallback(manager):
    manager._get_reranker_config = MagicMock(
        return_value=_make_config(candidate_multiplier=2),
    )

    async def raise_http(query, docs, c):
        raise httpx.RequestError("boom", request=None)

    manager._call_reranker_api = raise_http
    rs = [
        _result(0, text="a"),
        _result(1, text="b"),
        _result(2, text="c"),
        _result(3, text="d"),
    ]
    resp = _make_response(rs)
    manager._run_reme_job = AsyncMock(return_value=resp)

    await manager.memory_search("q", max_results=2)

    assert resp.metadata["results"][0]["text"] == "a"
    assert len(resp.metadata["results"]) == 2


# ── fallback: wrong index count ──


@pytest.mark.asyncio
async def test_rerank_index_mismatch_fallback(manager):
    manager._get_reranker_config = MagicMock(
        return_value=_make_config(),
    )

    async def bad_order(query, docs, c):
        return [0]  # wrong length

    manager._call_reranker_api = bad_order
    rs = [_result(i) for i in range(6)]
    resp = _make_response(rs)
    manager._run_reme_job = AsyncMock(return_value=resp)

    await manager.memory_search("q", max_results=2)

    assert resp.metadata["results"][0]["text"] == "doc-0"
    assert len(resp.metadata["results"]) == 2


# ── fallback: duplicate index (should be rejected as not a permutation) ──


@pytest.mark.asyncio
async def test_rerank_duplicate_index_fallback(manager):
    manager._get_reranker_config = MagicMock(
        return_value=_make_config(),
    )

    async def duplicate_indices(query, docs, c):
        return [0, 0, 1, 2]  # duplicates — not a permutation

    manager._call_reranker_api = duplicate_indices
    rs = [_result(i) for i in range(4)]
    resp = _make_response(rs)
    manager._run_reme_job = AsyncMock(return_value=resp)

    await manager.memory_search("q", max_results=2)

    # Should fall back to original order
    assert resp.metadata["results"][0]["text"] == "doc-0"
    assert len(resp.metadata["results"]) == 2


# ── no base_url: reranker called but returns None, no reorder ──


@pytest.mark.asyncio
async def test_no_base_url_skip(manager):
    """When base_url is empty, _call_reranker_api returns None early,
    so no reorder occurs.  If there is no truncation either, the original
    ReMe answer (including link expansions) is preserved."""
    manager._get_reranker_config = MagicMock(
        return_value=_make_config(base_url=""),
    )
    called = {"n": 0}

    async def api(query, docs, c):
        called["n"] += 1
        return None

    manager._call_reranker_api = api
    rs = [_result(i) for i in range(6)]
    original_answer = "original answer with link expansion context"
    resp = _make_response(rs, answer=original_answer)
    manager._run_reme_job = AsyncMock(return_value=resp)

    # max_results=6 → no truncation expected
    await manager.memory_search("q", max_results=6)

    assert called["n"] == 1
    assert resp.metadata["results"][0]["text"] == "doc-0"
    assert len(resp.metadata["results"]) == 6
    # Answer should be preserved (not rebuilt) because order didn't change
    # and no truncation occurred
    assert resp.answer == original_answer


# ── no base_url + truncation: answer rebuilt, expansions preserved ──


@pytest.mark.asyncio
async def test_no_base_url_skip_with_truncation(manager):
    """When base_url is empty but truncation is needed, the answer is
    rebuilt from the parsed sections (preserving expansions) rather than
    from raw metadata."""
    manager._get_reranker_config = MagicMock(
        return_value=_make_config(base_url=""),
    )

    async def api(query, docs, c):
        return None

    manager._call_reranker_api = api
    rs = [_result(i) for i in range(6)]
    expansion = _make_link_expansion()
    original_answer = _make_reme_answer(rs, link_expansion=expansion)
    resp = _make_response(rs, answer=original_answer, link_expansion=expansion)
    manager._run_reme_job = AsyncMock(return_value=resp)

    await manager.memory_search("q", max_results=3)

    # Truncation: 6 → 3
    assert len(resp.metadata["results"]) == 3
    # Answer is rebuilt with capped results
    assert "doc-0" in str(resp.answer)
    assert "doc-5" not in str(resp.answer)
    assert resp.answer != original_answer
    # Link expansions survive in the rebuilt answer
    assert "outlinks" in str(resp.answer)
    assert "anchor=#123" in str(resp.answer)


# ── successful rerank preserves expansions ──


@pytest.mark.asyncio
async def test_rerank_preserves_expansions(manager):
    """When reranker reorders and truncates, the reconstructed answer
    preserves link expansions and hybrid score details from the original
    ReMe answer sections."""
    manager._get_reranker_config = MagicMock(
        return_value=_make_config(candidate_multiplier=3),
    )

    async def partial_rerank(query, docs, c):
        # Return [2, 1, 0, 3, 4, 5] — promote 2/0 to top, push 5/4 down
        return [2, 1, 0, 3, 4, 5]

    manager._call_reranker_api = partial_rerank
    rs = [_result(i, text=f"t{i}") for i in range(6)]
    expansion = _make_link_expansion()
    original_answer = _make_reme_answer(rs, link_expansion=expansion)
    resp = _make_response(rs, answer=original_answer, link_expansion=expansion)
    manager._run_reme_job = AsyncMock(return_value=resp)

    await manager.memory_search("q", max_results=3)

    # Reordered + capped
    assert len(resp.metadata["results"]) == 3
    assert resp.metadata["results"][0]["text"] == "t2"
    # Expansions survive in the reconstructed answer
    answer = str(resp.answer)
    assert "outlinks" in answer
    assert "anchor=#123" in answer
    # memory/0.md (index 0) is in the capped set (position 2 after
    # reranking) → its outlinks expansion survives.
    # memory/2.md (index 2) is the top result after reranking → its
    # inlinks expansion also survives.
    assert "inlinks" in answer
    # The answer format is preserved (sections with score headers)
    assert "score=" in answer


# ── fallback preserves answer sections ──


@pytest.mark.asyncio
async def test_rerank_timeout_preserves_answer_sections(manager):
    """When reranker times out but truncation occurs, the answer is
    rebuilt from the parsed sections, preserving expansions."""
    manager._get_reranker_config = MagicMock(
        return_value=_make_config(candidate_multiplier=3),
    )

    async def raise_timeout(query, docs, c):
        raise httpx.TimeoutException("timeout")

    manager._call_reranker_api = raise_timeout
    rs = [_result(i) for i in range(6)]
    expansion = _make_link_expansion()
    original_answer = _make_reme_answer(rs, link_expansion=expansion)
    resp = _make_response(rs, answer=original_answer, link_expansion=expansion)
    manager._run_reme_job = AsyncMock(return_value=resp)

    await manager.memory_search("q", max_results=3)

    # Original order preserved, capped
    assert len(resp.metadata["results"]) == 3
    assert resp.metadata["results"][0]["text"] == "doc-0"
    # Expansions survive in the reconstructed answer
    answer = str(resp.answer)
    assert "outlinks" in answer
    assert "anchor=#123" in answer
    # memory/0.md is in the top 3 → its expansion (outlinks) should be
    # in the answer
    # memory/2.md is also in the top 3 → its expansion (inlinks) should
    # be in the answer
    assert "inlinks" in answer


# ── empty results ──


@pytest.mark.asyncio
async def test_empty_results(manager):
    manager._get_reranker_config = MagicMock(
        return_value=_make_config(),
    )
    manager._rerank_search_results = AsyncMock()
    resp = _make_response([])
    manager._run_reme_job = AsyncMock(return_value=resp)

    chunk = await manager.memory_search("q")

    assert manager._rerank_search_results.call_count == 0
    text = "".join(b.text for b in chunk.content)
    assert NO_MEMORY_RESULTS in text


# ── rebuild answer format ──


def test_rebuild_answer_with_expansions_format():
    """_rebuild_search_answer_with_expansions produces correct header."""
    rs = [
        {
            "path": "a.md",
            "start_line": 2,
            "end_line": 4,
            "scores": {"score": 0.1234},
            "text": "hello",
        },
    ]
    out = ReMeLightMemoryManager._rebuild_search_answer_with_expansions(
        rs,
        {},
    )
    assert "a.md:2-4" in out
    assert "[score=0.1234]" in out
    assert "hello" in out


def test_rebuild_answer_with_expansions_hybrid_scores():
    """Hybrid scores (vector + keyword) appear in the rebuilt header."""
    rs = [
        {
            "path": "b.md",
            "start_line": 5,
            "end_line": 8,
            "scores": {"score": 0.9, "vector": 0.85, "keyword": 0.65},
            "text": "hybrid",
        },
    ]
    out = ReMeLightMemoryManager._rebuild_search_answer_with_expansions(
        rs,
        {},
    )
    assert "b.md:5-8" in out
    assert "score=0.9000" in out
    assert "vector=0.8500" in out
    assert "keyword=0.6500" in out
    assert "hybrid" in out


# ── answer preserved when reranker returns same order ──


@pytest.mark.asyncio
async def test_answer_preserved_when_reranker_no_op(manager):
    """When reranker returns indices [0, 1, 2, ...], the original answer
    must be preserved because the order has not changed."""
    manager._get_reranker_config = MagicMock(
        return_value=_make_config(),
    )

    async def identity_order(query, docs, c):
        return list(range(len(docs)))  # same order

    manager._call_reranker_api = identity_order
    rs = [_result(i, text=f"t{i}") for i in range(4)]
    original_answer = "ReMe: expanded link context […]"
    resp = _make_response(rs, answer=original_answer)
    manager._run_reme_job = AsyncMock(return_value=resp)

    await manager.memory_search("q", max_results=4)

    # No truncation, no reorder → answer should be preserved
    assert resp.answer == original_answer


# ── auto_memory_search with reranker ──


@pytest.mark.asyncio
async def test_auto_memory_search_uses_reranker(manager):
    """auto_memory_search() must over-fetch, rerank, and cap results,
    just like memory_search()."""
    from unittest.mock import patch

    search_cfg = types.SimpleNamespace(
        enabled=True,
        max_results=2,
    )
    memory_cfg = types.SimpleNamespace(
        auto_memory_search_config=search_cfg,
    )
    agent_config = types.SimpleNamespace(
        running=types.SimpleNamespace(
            reme_light_memory_config=memory_cfg,
        ),
    )

    manager._get_reranker_config = MagicMock(
        return_value=_make_config(candidate_multiplier=3),
    )
    manager._call_reranker_api = AsyncMock(
        return_value=[2, 1, 0, 3, 4, 5],
    )
    manager._build_query = MagicMock(return_value="test query")
    manager._build_auto_memory_search_msg = MagicMock(
        return_value="fake_msg",
    )
    manager.agent_id = "test-agent"
    rs = [_result(i, text=f"t{i}") for i in range(6)]
    resp = _make_response(rs)
    manager._run_reme_job = AsyncMock(return_value=resp)

    with patch.object(
        mgr,
        "load_agent_config",
        return_value=agent_config,
    ):
        result = await manager.auto_memory_search(
            messages="dummy message",
        )

    # Over-fetch: limit should be 2 * 3 = 6
    limit = manager._run_reme_job.call_args.kwargs["limit"]
    assert limit == 6, (
        f"auto_memory_search should over-fetch: " f"expected 6, got {limit}"
    )

    # Reranked: first result should be doc-2 (index 2 promoted by reranker)
    assert result is not None
    first_result = resp.metadata["results"][0]
    assert (
        first_result["text"] == "t2"
    ), f"expected t2 at position 0, got {first_result['text']}"

    # Capped: only 2 results
    assert (
        len(resp.metadata["results"]) == 2
    ), f"expected 2 results, got {len(resp.metadata['results'])}"
