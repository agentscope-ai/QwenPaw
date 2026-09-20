# -*- coding: utf-8 -*-
"""Legacy discovery placeholders do not override real context metadata."""

import pytest

from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider import ModelInfo
from qwenpaw.providers.provider_discovery import merge_discovered_model


@pytest.mark.parametrize("previous", [None, 131_072, 262_144])
def test_legacy_placeholder_clears_stale_discovery_catalog(previous):
    model = ModelInfo(id="gpt-4.1", name="GPT")
    provider = OpenAIProvider(
        id="test",
        name="Test",
        models=[model],
        discovered_models=[
            model.model_copy(
                update={
                    "max_input_length_catalog": previous,
                }
            )
        ],
    )
    remote = model.model_copy(update={"max_input_length": 131_072})

    merged = merge_discovered_model(provider, remote, "2026-09-20")
    provider.discovered_models = [merged]

    assert merged.max_input_length_catalog is None
    assert provider.get_context_size(model.id) == 1_047_576


@pytest.mark.parametrize(
    ("metadata", "expected", "source"),
    [
        ({}, 262_144, "catalog"),
        ({"max_input_length": 400_000}, 400_000, "catalog"),
        ({"max_input_length_auto_detected": 131_072}, 131_072, "api"),
        ({"max_input_length_catalog": 131_072}, 131_072, "catalog"),
        (
            {
                "max_input_length": 131_072,
                "max_input_length_auto_detected": 131_072,
            },
            131_072,
            "api",
        ),
        (
            {"max_input_length": 131_072, "max_input_length_catalog": 131_072},
            131_072,
            "catalog",
        ),
    ],
)
def test_discovery_preserves_real_values_and_omitted_metadata(
    metadata,
    expected,
    source,
):
    model = ModelInfo(id="gpt-4.1", name="GPT")
    provider = OpenAIProvider(
        id="test",
        name="Test",
        models=[model],
        discovered_models=[
            model.model_copy(
                update={
                    "max_input_length_catalog": 262_144,
                }
            )
        ],
    )
    remote = ModelInfo(id=model.id, name=model.name, **metadata)

    merged = merge_discovered_model(provider, remote, "2026-09-20")
    provider.discovered_models = [merged]
    window = provider.get_context_window_details(model.id)

    assert window.value == expected
    assert window.source == source


def test_legacy_placeholder_preserves_user_override():
    model = ModelInfo(id="gpt-4.1", name="GPT", max_input_length=131_072)
    provider = OpenAIProvider(id="test", name="Test", models=[model])
    remote = ModelInfo(id=model.id, name=model.name, max_input_length=131_072)

    merged = merge_discovered_model(provider, remote, "2026-09-20")
    provider.discovered_models = [merged]

    assert merged.max_input_length == 131_072
    assert model.max_input_length == 131_072
    assert provider.get_context_window_details(model.id).source == "user"


def test_legacy_placeholder_keeps_a_declared_configured_window():
    """A provider-declared catalog window outlives the discovery placeholder.

    The declaration lives on the configured entry, which the merge never
    mutates, so resetting the discovery slot cannot hide it.
    """
    declared = ModelInfo(
        id="plugin-model",
        name="Plugin",
        max_input_length_catalog=400_000,
    )
    provider = OpenAIProvider(id="test", name="Test", models=[declared])
    remote = ModelInfo(
        id=declared.id, name=declared.name, max_input_length=131_072
    )

    merged = merge_discovered_model(provider, remote, "2026-09-20")
    provider.discovered_models = [merged]
    window = provider.get_context_window_details(declared.id)

    assert merged.max_input_length_catalog is None
    assert declared.max_input_length_catalog == 400_000
    assert (window.value, window.source) == (400_000, "catalog")
