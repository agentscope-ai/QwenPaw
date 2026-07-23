#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for ReMe memory reranker (over-fetch + rerank + cap).

Tests cover:
  - disabled: no rerank, behavior identical to plain search
  - enabled + API ok: results reordered by reranker, capped to max_results
  - over-fetch: search limit = N * candidate_multiplier
  - timeout / http error / index mismatch: graceful fallback to original order
  - no base_url: skip rerank entirely
  - empty results: no rerank call, returns NO_MEMORY_RESULTS

Run: python -m unittest tests.unit.test_memory_reranker -v
"""

import asyncio
import pathlib
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock

# Put source tree first so the manager (with reranker changes) imports from
# src/qwenpaw.
_SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# pylint: disable=wrong-import-position
import qwenpaw.agents.memory.reme_light_memory_manager as mgr  # noqa: E402

# pylint: enable=wrong-import-position

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


# pylint: disable=protected-access,unused-argument
class RerankerTests(unittest.TestCase):
    def setUp(self):
        self.m = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
        self.m._reranker_config_cache = None

    def _patch_run(self, results):
        resp = _make_response(results)
        self.m._run_reme_job = AsyncMock(return_value=resp)
        return resp

    def _run(self, query="q", max_results=2, min_score=0.0):
        return asyncio.get_event_loop().run_until_complete(
            self.m.memory_search(
                query,
                max_results=max_results,
                min_score=min_score,
            ),
        )

    # pylint: disable=unused-argument

    def test_disabled_no_rerank(self):
        self.m._get_reranker_config = MagicMock(return_value=None)
        rs = [_result(0), _result(1)]
        self._patch_run(rs)
        self.m._rerank_search_results = AsyncMock()
        _ = self._run()
        self.assertEqual(self.m._rerank_search_results.call_count, 0)
        # _run() returns the chunk, but we only care about call_count here

    def test_overfetch_multiplier(self):
        cfg = types.SimpleNamespace(
            enabled=True,
            base_url="https://x",
            model_name="m",
            candidate_multiplier=3,
            timeout=10.0,
        )
        self.m._get_reranker_config = MagicMock(return_value=cfg)
        self.m._rerank_search_results = AsyncMock()
        rs = [_result(i) for i in range(6)]
        self._patch_run(rs)
        self._run(max_results=2)
        limit = self.m._run_reme_job.call_args.kwargs["limit"]
        self.assertEqual(limit, 6, "limit should be max_results * multiplier")

    def test_enabled_rerank_ok_and_cap(self):
        cfg = types.SimpleNamespace(
            enabled=True,
            base_url="https://x",
            model_name="m",
            candidate_multiplier=3,
            timeout=10.0,
        )
        self.m._get_reranker_config = MagicMock(return_value=cfg)

        async def fake_api(query, docs, c):
            return list(range(len(docs)))[::-1]

        self.m._call_reranker_api = fake_api
        rs = [_result(i, text=f"t{i}") for i in range(6)]
        resp = self._patch_run(rs)
        _ = self._run(query="q", max_results=2)
        self.assertEqual(len(resp.metadata["results"]), 2)
        self.assertEqual(resp.metadata["results"][0]["text"], "t5")
        self.assertIn("t5", str(resp.answer))

    def test_rerank_timeout_fallback(self):
        cfg = types.SimpleNamespace(
            enabled=True,
            base_url="https://x",
            model_name="m",
            candidate_multiplier=3,
            timeout=10.0,
        )
        self.m._get_reranker_config = MagicMock(return_value=cfg)
        import httpx

        async def raise_timeout(query, docs, c):
            raise httpx.TimeoutException("timeout")

        self.m._call_reranker_api = raise_timeout
        rs = [_result(i, text=f"t{i}") for i in range(6)]
        resp = self._patch_run(rs)
        self._run(query="q", max_results=2)
        self.assertEqual(resp.metadata["results"][0]["text"], "t0")
        self.assertEqual(len(resp.metadata["results"]), 2)

    def test_rerank_http_error_fallback(self):
        cfg = types.SimpleNamespace(
            enabled=True,
            base_url="https://x",
            model_name="m",
            candidate_multiplier=2,
            timeout=10.0,
        )
        self.m._get_reranker_config = MagicMock(return_value=cfg)
        import httpx

        async def raise_http(query, docs, c):
            raise httpx.RequestError("boom", request=None)

        self.m._call_reranker_api = raise_http
        rs = [
            _result(0, text="a"),
            _result(1, text="b"),
            _result(2, text="c"),
            _result(3, text="d"),
        ]
        resp = self._patch_run(rs)
        self._run(query="q", max_results=2)
        self.assertEqual(resp.metadata["results"][0]["text"], "a")
        self.assertEqual(len(resp.metadata["results"]), 2)

    def test_rerank_index_mismatch_fallback(self):
        cfg = types.SimpleNamespace(
            enabled=True,
            base_url="https://x",
            model_name="m",
            candidate_multiplier=3,
            timeout=10.0,
        )
        self.m._get_reranker_config = MagicMock(return_value=cfg)

        async def bad_order(query, docs, c):
            return [0]  # wrong length

        self.m._call_reranker_api = bad_order
        rs = [_result(i) for i in range(6)]
        resp = self._patch_run(rs)
        self._run(query="q", max_results=2)
        self.assertEqual(resp.metadata["results"][0]["text"], "doc-0")
        self.assertEqual(len(resp.metadata["results"]), 2)

    def test_no_base_url_skip(self):
        cfg = types.SimpleNamespace(
            enabled=True,
            base_url="",
            model_name="m",
            candidate_multiplier=3,
            timeout=10.0,
        )
        self.m._get_reranker_config = MagicMock(return_value=cfg)
        called = {"n": 0}

        async def api(query, docs, c):
            called["n"] += 1
            return None

        self.m._call_reranker_api = api
        rs = [_result(i) for i in range(6)]
        resp = self._patch_run(rs)
        self._run(query="q", max_results=3)
        self.assertEqual(called["n"], 1)
        self.assertEqual(resp.metadata["results"][0]["text"], "doc-0")
        self.assertEqual(len(resp.metadata["results"]), 3)

    def test_empty_results(self):
        cfg = types.SimpleNamespace(
            enabled=True,
            base_url="https://x",
            model_name="m",
            candidate_multiplier=3,
            timeout=10.0,
        )
        self.m._get_reranker_config = MagicMock(return_value=cfg)
        self.m._rerank_search_results = AsyncMock()
        resp = _make_response([])
        self.m._run_reme_job = AsyncMock(return_value=resp)
        chunk = self._run()
        self.assertEqual(self.m._rerank_search_results.call_count, 0)
        text = "".join(b.text for b in chunk.content)
        self.assertIn(NO_MEMORY_RESULTS, text)

    def test_rebuild_answer_format(self):
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
        self.assertIn("a.md:2-4", out)
        self.assertIn("[score=0.1234]", out)
        self.assertIn("hello", out)


# pylint: enable=protected-access,unused-argument


if __name__ == "__main__":
    unittest.main(verbosity=2)
