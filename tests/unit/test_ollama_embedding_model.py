# -*- coding: utf-8 -*-
"""Unit tests for OllamaEmbeddingModel URL normalization and requests."""
# pylint: disable=protected-access

from __future__ import annotations

from typing import Any

import pytest

from copaw.agents.memory.ollama_embedding_model import OllamaEmbeddingModel


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(self, recorder: dict[str, Any]) -> None:
        self._recorder = recorder

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _ = (exc_type, exc, tb)

    def post(self, url: str, json: dict[str, Any]) -> _FakeResponse:
        self._recorder["url"] = url
        self._recorder["payload"] = json
        return _FakeResponse({"embeddings": [[0.1, 0.2, 0.3]]})


def test_normalize_base_defaults_to_localhost() -> None:
    model = OllamaEmbeddingModel(model_name="mxbai-embed-large")
    assert model._normalize_base() == "http://127.0.0.1:11434"


@pytest.mark.parametrize(
    ("raw_base", "expected"),
    [
        ("http://localhost:11434", "http://localhost:11434"),
        ("http://localhost:11434/", "http://localhost:11434"),
        ("http://localhost:11434/v1", "http://localhost:11434"),
        ("http://localhost:11434/v1/", "http://localhost:11434"),
        ("http://localhost:11434/api", "http://localhost:11434"),
    ],
)
def test_normalize_base_strips_openai_style_suffixes(
    raw_base: str,
    expected: str,
) -> None:
    model = OllamaEmbeddingModel(
        base_url=raw_base,
        model_name="mxbai-embed-large",
    )
    assert model._normalize_base() == expected


def test_embed_sync_posts_to_api_embed(monkeypatch) -> None:
    model = OllamaEmbeddingModel(
        base_url="http://localhost:11434/v1",
        model_name="mxbai-embed-large",
        dimensions=3,
    )

    captured: dict[str, Any] = {}

    def _fake_httpx_client(*args, **kwargs):
        _ = (args, kwargs)
        return _FakeClient(captured)

    monkeypatch.setattr(
        "copaw.agents.memory.ollama_embedding_model.httpx.Client",
        _fake_httpx_client,
    )

    embeddings = model._get_embeddings_sync(["hello world"])

    assert captured["url"] == "http://localhost:11434/api/embed"
    assert captured["payload"]["model"] == "mxbai-embed-large"
    assert captured["payload"]["input"] == ["hello world"]
    assert embeddings == [[0.1, 0.2, 0.3]]
