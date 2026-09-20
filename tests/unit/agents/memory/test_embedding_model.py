# -*- coding: utf-8 -*-
"""Tests for AgentScope embedding model construction and probing."""

from types import SimpleNamespace

import pytest

from qwenpaw.agents.memory import embedding_model as module
from qwenpaw.config.config import EmbeddingModelConfig


def _config(**overrides) -> EmbeddingModelConfig:
    values = {
        "backend": "openai",
        "api_key": "test-key",
        "base_url": "https://example.com/v1/",
        "model_name": "embedding-model",
        "dimensions": 3,
        "use_dimensions": False,
    }
    values.update(overrides)
    return EmbeddingModelConfig(**values)


def test_create_openai_embedding_model_respects_pass_dimensions() -> None:
    model = module.create_embedding_model(
        _config(use_dimensions=False),
        max_retries=1,
    )

    assert model.model == "embedding-model"
    assert model.dimensions == 3
    assert model.pass_dimensions is False
    assert model.max_retries == 1


@pytest.mark.asyncio
async def test_probe_accepts_matching_finite_vector(monkeypatch) -> None:
    class FakeModel:
        async def __call__(self, _inputs):
            return SimpleNamespace(embeddings=[[0.1, 0.2, 0.3]])

    monkeypatch.setattr(
        module,
        "create_embedding_model",
        lambda *_args, **_kwargs: FakeModel(),
    )

    model, result = await module.test_embedding_model(_config())

    assert model is not None
    assert result.success is True
    assert result.actual_dimensions == 3


@pytest.mark.asyncio
async def test_probe_rejects_dimension_mismatch(monkeypatch) -> None:
    class FakeModel:
        async def __call__(self, _inputs):
            return SimpleNamespace(embeddings=[[0.1, 0.2]])

    monkeypatch.setattr(
        module,
        "create_embedding_model",
        lambda *_args, **_kwargs: FakeModel(),
    )

    model, result = await module.test_embedding_model(_config())

    assert model is None
    assert result.success is False
    assert result.actual_dimensions == 2
    assert "expected 3, got 2" in result.message


@pytest.mark.asyncio
async def test_probe_uses_configured_health_check_timeout(monkeypatch) -> None:
    observed = {}

    class FakeModel:
        async def __call__(self, _inputs):
            return SimpleNamespace(embeddings=[[0.1, 0.2, 0.3]])

    async def fake_wait_for(awaitable, timeout):
        observed["timeout"] = timeout
        return await awaitable

    monkeypatch.setattr(
        module,
        "create_embedding_model",
        lambda *_args, **_kwargs: FakeModel(),
    )
    monkeypatch.setattr(module.asyncio, "wait_for", fake_wait_for)

    _model, result = await module.test_embedding_model(
        _config(health_check_timeout=42),
    )

    assert result.success is True
    assert observed["timeout"] == 42


def test_vector_space_fingerprint_ignores_key_and_cache_settings() -> None:
    first = _config(api_key="old", max_cache_size=10)
    second = _config(api_key="new", max_cache_size=20)

    assert module.embedding_vector_space_fingerprint(
        first,
    ) == module.embedding_vector_space_fingerprint(second)


def test_tested_config_fingerprint_ignores_reme_store_settings() -> None:
    first = _config(
        enable_cache=True,
        max_cache_size=10,
        max_input_length=100,
        max_batch_size=2,
    )
    second = _config(
        enable_cache=False,
        max_cache_size=20,
        max_input_length=200,
        max_batch_size=4,
    )

    assert module.embedding_config_fingerprint(
        first,
    ) == module.embedding_config_fingerprint(second)


@pytest.mark.parametrize(
    "fingerprint",
    [
        module.embedding_config_fingerprint,
        module.embedding_vector_space_fingerprint,
    ],
)
def test_fingerprints_ignore_inapplicable_dashscope_use_dimensions(
    fingerprint,
) -> None:
    first = _config(backend="dashscope", use_dimensions=False)
    second = _config(backend="dashscope", use_dimensions=True)

    assert fingerprint(first) == fingerprint(second)


@pytest.mark.parametrize(
    "fingerprint",
    [
        module.embedding_config_fingerprint,
        module.embedding_vector_space_fingerprint,
    ],
)
def test_fingerprints_keep_openai_use_dimensions(fingerprint) -> None:
    first = _config(backend="openai", use_dimensions=False)
    second = _config(backend="openai", use_dimensions=True)

    assert fingerprint(first) != fingerprint(second)
