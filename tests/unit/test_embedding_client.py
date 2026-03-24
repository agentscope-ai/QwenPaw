# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for EmbeddingClient backend factory behavior."""

from __future__ import annotations

from typing import Any

from copaw.agents.memory.embedding_client import EmbeddingClient
from copaw.config.config import LocalEmbeddingConfig


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


def test_embedding_client_requires_explicit_backend_type() -> None:
    client = EmbeddingClient(
        model_name="demo",
        dimensions=3,
        raise_exception=True,
    )
    try:
        client._get_embeddings_sync(["hello"])
        raise AssertionError("Expected ValueError for missing backend_type")
    except ValueError as exc:
        assert "requires explicit backend_type" in str(exc)


def test_embedding_client_transformers_backend_from_config_dict() -> None:
    client = EmbeddingClient(
        model_name="BAAI/bge-small-zh",
        dimensions=512,
        backend_type="transformers",
        local_embedding_config={
            "enabled": True,
            "model_id": "BAAI/bge-small-zh",
            "device": "cpu",
            "dtype": "fp32",
            "download_source": "huggingface",
        },
    )

    vectors = client._get_embeddings_sync(["hello world"])
    assert len(vectors) == 1
    assert isinstance(vectors[0], list)


def test_embedding_client_transformers_backend_from_config_object() -> None:
    local_cfg = LocalEmbeddingConfig(
        enabled=True,
        model_id="BAAI/bge-small-zh",
        device="cpu",
        dtype="fp32",
        download_source="huggingface",
    )
    client = EmbeddingClient(
        model_name="BAAI/bge-small-zh",
        dimensions=512,
        backend_type="transformers",
        local_embedding_config=local_cfg,
    )

    vectors = client._get_embeddings_sync(["hello world"])
    assert len(vectors) == 1
    assert isinstance(vectors[0], list)


def test_embedding_client_ollama_backend_uses_api_embed(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_httpx_client(*args, **kwargs):
        _ = (args, kwargs)
        return _FakeClient(captured)

    monkeypatch.setattr(
        "copaw.agents.memory.embedding.backends.ollama_backend.httpx.Client",
        _fake_httpx_client,
    )

    client = EmbeddingClient(
        backend_type="ollama",
        base_url="http://127.0.0.1:11434/v1",
        model_name="mxbai-embed-large",
        dimensions=3,
    )

    vectors = client._get_embeddings_sync(["hello world"])
    assert captured["url"] == "http://127.0.0.1:11434/api/embed"
    assert captured["payload"]["model"] == "mxbai-embed-large"
    assert vectors == [[0.1, 0.2, 0.3]]
