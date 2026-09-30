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


class _BatchRejectingModel:
    """Fake provider: rejects multi-text requests, answers single texts."""

    def __init__(self, dimension: int = 3) -> None:
        self.calls: list[list[str]] = []
        self.dimension = dimension

    async def __call__(self, inputs, **_kwargs):
        self.calls.append(list(inputs))
        if len(inputs) > 1:
            raise RuntimeError(
                "Error code: 400 - {'error': {'message': "
                "'the input length exceeds the context length'}}",
            )
        if inputs[0] == "poison":
            raise RuntimeError("still over the per-item limit")
        return SimpleNamespace(embeddings=[[0.1] * self.dimension])


@pytest.mark.asyncio
async def test_batch_rejection_retries_item_by_item() -> None:
    """One over-limit text must not drop the healthy vectors of its batch."""
    inner = _BatchRejectingModel()

    wrapper = module.PerItemFallbackEmbeddingModel(inner)
    response = await wrapper(["fine", "fine", "poison"])

    assert [embedding is None for embedding in response.embeddings] == [
        False,
        False,
        True,
    ]
    assert inner.calls[0] == ["fine", "fine", "poison"]
    assert inner.calls[1:] == [["fine"], ["fine"], ["poison"]]


@pytest.mark.asyncio
async def test_totally_rejected_batch_reraises_original_error() -> None:
    """Real outages keep their original error for caller-side retries."""

    class AlwaysFailing(_BatchRejectingModel):
        async def __call__(self, inputs, **_kwargs):
            self.calls.append(list(inputs))
            raise TimeoutError("gateway timeout")

    inner = AlwaysFailing()
    wrapper = module.PerItemFallbackEmbeddingModel(inner)

    with pytest.raises(TimeoutError, match="gateway timeout"):
        await wrapper(["a", "b"])
    assert inner.calls == [["a", "b"], ["a"], ["b"]]


@pytest.mark.asyncio
async def test_single_text_failure_is_not_retried() -> None:
    """A one-text request carries no batch to salvage."""

    class Failing(_BatchRejectingModel):
        async def __call__(self, inputs, **_kwargs):
            self.calls.append(list(inputs))
            raise TimeoutError("gateway timeout")

    inner = Failing()
    wrapper = module.PerItemFallbackEmbeddingModel(inner)

    with pytest.raises(TimeoutError):
        await wrapper(["only"])
    assert inner.calls == [["only"]]


def test_fallback_wrapper_delegates_provider_attributes() -> None:
    """ReMe reads model attributes through the wrapper transparently."""
    wrapper = module.PerItemFallbackEmbeddingModel(
        SimpleNamespace(
            model="embedding-model",
            dimensions=3,
            client=object(),
        ),
    )

    assert wrapper.model == "embedding-model"
    assert wrapper.dimensions == 3
    assert wrapper.client is not None
