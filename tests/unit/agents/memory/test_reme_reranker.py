# -*- coding: utf-8 -*-
"""Unit tests for the reranker connectivity probe (test_reranker_model)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from qwenpaw.agents.memory import reme_reranker as module
from qwenpaw.config.config import RerankerConfig


def _config(**overrides) -> RerankerConfig:
    values = {
        "enabled": True,
        "api_key": "test-key",
        "base_url": "https://example.com/v1",
        "model_name": "test-reranker",
        "candidate_multiplier": 3,
        "timeout": 5.0,
    }
    values.update(overrides)
    return RerankerConfig(**values)


class _FakeResponse:
    def __init__(self, payload=None, status_error=None):
        self._payload = payload
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error is not None:
            raise self._status_error

    def json(self):
        return self._payload


class _FakeAsyncClient:
    posted: dict | None = None

    def __init__(self, response=None, post_error=None, **_kwargs):
        self._response = response
        self._post_error = post_error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, url, headers=None, json=None):
        type(self).posted = {"url": url, "headers": headers, "json": json}
        if self._post_error is not None:
            raise self._post_error
        return self._response


def _results(*scores):
    """Build a /rerank payload from per-document relevance scores."""
    return {
        "results": [
            {"index": i, "relevance_score": s} for i, s in enumerate(scores)
        ]
    }


def _install(monkeypatch, **client_kwargs) -> None:
    def factory(**kwargs):
        return _FakeAsyncClient(**kwargs, **client_kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_probe_reports_scores_and_correct_rank(monkeypatch) -> None:
    _install(
        monkeypatch,
        response=_FakeResponse(payload=_results(0.97, 0.11, 0.02)),
    )

    result = await module.test_reranker_model(_config())

    assert result.success is True
    assert result.scores == [0.97, 0.11, 0.02]
    assert result.ranking_correct is True
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_probe_flags_wrong_top_rank(monkeypatch) -> None:
    _install(
        monkeypatch,
        response=_FakeResponse(payload=_results(0.10, 0.95, 0.03)),
    )

    result = await module.test_reranker_model(_config())

    assert result.success is True
    assert result.ranking_correct is False


@pytest.mark.asyncio
async def test_probe_without_scores_skips_ranking_verdict(
    monkeypatch,
) -> None:
    payload = {"results": [{"index": 0}, {"index": 1}, {"index": 2}]}
    _install(monkeypatch, response=_FakeResponse(payload=payload))

    result = await module.test_reranker_model(_config())

    assert result.success is True
    assert result.scores is None
    assert result.ranking_correct is None


@pytest.mark.asyncio
async def test_probe_rejects_out_of_range_indices(monkeypatch) -> None:
    payload = {"results": [{"index": 0}, {"index": 1}, {"index": 9}]}
    _install(monkeypatch, response=_FakeResponse(payload=payload))

    result = await module.test_reranker_model(_config())

    assert result.success is False
    assert "invalid document indices" in result.message


@pytest.mark.asyncio
async def test_probe_reports_http_timeout(monkeypatch) -> None:
    _install(monkeypatch, post_error=httpx.TimeoutException("slow"))

    result = await module.test_reranker_model(_config())

    assert result.success is False
    assert "timed out" in result.message


@pytest.mark.asyncio
async def test_probe_hard_deadline_cancels_slow_drip(
    monkeypatch,
) -> None:
    _install(monkeypatch, post_error=asyncio.TimeoutError())

    result = await module.test_reranker_model(_config())

    assert result.success is False
    assert "timed out" in result.message


@pytest.mark.asyncio
async def test_probe_strips_html_from_http_error(monkeypatch) -> None:
    response = SimpleNamespace(
        status_code=500,
        text="<html><body>Internal Server Error</body></html>",
    )
    error = httpx.HTTPStatusError(
        "server error", request=MagicMock(), response=response
    )
    _install(
        monkeypatch,
        response=_FakeResponse(status_error=error),
    )

    result = await module.test_reranker_model(_config())

    assert result.success is False
    assert "HTTP 500" in result.message
    assert "Internal Server Error" in result.message
    assert "<html>" not in result.message


@pytest.mark.asyncio
async def test_probe_requires_base_url(monkeypatch) -> None:
    result = await module.test_reranker_model(_config(base_url=" "))

    assert result.success is False
    assert "base URL" in result.message
