#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""Unit tests for ReMe memory reranker (over-fetch + rerank + cap).

Tests cover:
  - disabled: no rerank, behavior identical to plain search
  - enabled + API ok: results reordered by reranker, capped to max_results
  - over-fetch: search limit = N * candidate_multiplier
  - timeout / http error / index mismatch / duplicate index: graceful fallback
  - no base_url: skip rerank entirely
  - empty results: no rerank call, returns NO_MEMORY_RESULTS
  - answer: preserved when order unchanged, rebuilt when changed or truncated
"""

import types
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import qwenpaw.agents.memory.reme_light_memory_manager as mgr

ReMeLightMemoryManager = mgr.ReMeLightMemoryManager
NO_MEMORY_RESULTS = mgr.NO_MEMORY_RESULTS


def _make_response(results, answer=""):
    """Build a fake ReMe Response-like object."""
    r = types.SimpleNamespace()
    r.success = True
    r.answer = answer
    r.metadata = {"results": list(results)}
    return r


def _result(i, text=None):
    return {
        "path": f"memory/{i}.md",
        "start_line": 1,
        "end_line": 3,
        "score": 0.5 - i * 0.05,
        "text": text or f"doc-{i}",
    }


def _make_config(**overrides):
    """Build a dummy RerankerConfig with sensible defaults."""
    d = dict(
        enabled=True,
        base_url="https://x",
        model_name="m",
        candidate_multiplier=3,
        timeout=10.0,
    )
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


# ── no base_url + truncation: answer rebuilt ──


@pytest.mark.asyncio
async def test_no_base_url_skip_with_truncation(manager):
    """When base_url is empty but truncation is needed, the answer is
    still rebuilt with the capped result set."""
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

    await manager.memory_search("q", max_results=3)

    assert called["n"] == 1
    assert len(resp.metadata["results"]) == 3
    # Answer is rebuilt because truncation occurred
    assert "doc-0" in str(resp.answer)
    assert "doc-5" not in str(resp.answer)
    assert resp.answer != original_answer


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


def test_rebuild_answer_format():
    rs = [
        {
            "path": "a.md",
            "start_line": 2,
            "end_line": 4,
            "score": 0.1234,
            "text": "hello",
        },
    ]
    out = ReMeLightMemoryManager._rebuild_search_answer(rs)
    assert "a.md:2-4" in out
    assert "[score=0.1234]" in out
    assert "hello" in out


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
