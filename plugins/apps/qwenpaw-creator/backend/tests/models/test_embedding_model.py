# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Embedding thin-client batching, backoff and config resolution tests."""
from __future__ import annotations

import asyncio

import pytest

from models import embedding_model
from utils.exceptions import ModelError


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = "throttled" if status_code != 200 else "ok"

    def json(self) -> dict:
        return self._payload


class _Client:
    """httpx.AsyncClient stand-in yielding queued responses per call."""

    calls: list[dict] = []
    queue: list[_Response] = []

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *args) -> None:
        del args

    async def post(self, url, headers=None, json=None):
        _Client.calls.append({"url": url, "headers": headers, "json": json})
        return _Client.queue.pop(0)


def _ok_response(texts: list[str]) -> _Response:
    return _Response(
        200,
        {
            "output": {
                "embeddings": [
                    {"embedding": [float(i), 0.0]} for i, _ in enumerate(texts)
                ],
            },
        },
    )


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    _Client.calls = []
    _Client.queue = []
    monkeypatch.setattr(embedding_model.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(
        embedding_model.model_config,
        "get_embedding_api_key",
        lambda: "embed-key",
    )
    monkeypatch.setattr(
        embedding_model.model_config,
        "get_embedding_model_name",
        lambda: "qwen3-vl-embedding",
    )
    monkeypatch.setattr(
        embedding_model.model_config,
        "get_embedding_base_url",
        lambda: "https://dashscope.aliyuncs.com/api/v1",
    )

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(embedding_model.asyncio, "sleep", no_sleep)
    yield


def test_embed_splits_batches_at_native_cap() -> None:
    texts = [f"text-{i}" for i in range(23)]
    _Client.queue = [
        _ok_response(texts[0:10]),
        _ok_response(texts[10:20]),
        _ok_response(texts[20:23]),
    ]
    vectors = asyncio.run(embedding_model.embed(texts))
    assert len(vectors) == 23
    assert len(_Client.calls) == 3
    sizes = [len(call["json"]["input"]["contents"]) for call in _Client.calls]
    assert sizes == [10, 10, 3]
    first = _Client.calls[0]
    assert first["url"].endswith(
        "/services/embeddings/multimodal-embedding/multimodal-embedding",
    )
    assert first["headers"]["Authorization"] == "Bearer embed-key"
    assert first["json"]["parameters"]["dimension"] == 2560


def test_embed_retries_throttling_with_backoff() -> None:
    _Client.queue = [
        _Response(429),
        _Response(429),
        _ok_response(["a", "b"]),
    ]
    vectors = asyncio.run(embedding_model.embed(["a", "b"]))
    assert len(vectors) == 2
    assert len(_Client.calls) == 3


def test_embed_fails_fast_on_non_retryable_status() -> None:
    _Client.queue = [_Response(400)]
    with pytest.raises(ModelError):
        asyncio.run(embedding_model.embed(["a"]))
    assert len(_Client.calls) == 1
