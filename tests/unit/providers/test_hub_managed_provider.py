# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
"""The org-managed Hub provider exports catalog windows, not overrides."""

from __future__ import annotations

import asyncio

import pytest

from qwenpaw.providers.hub_managed import managed_provider

INPUT_TOKEN_LIMIT = 262_144


@pytest.fixture
def hub_catalog() -> dict:
    """A minimal organization catalog as the Hub hands it to the provider."""
    return {
        "models": [
            {
                "id": "org-model",
                "name": "Org Model",
                "supports_image": False,
                "supports_agent_thinking": True,
                "input_token_limit": INPUT_TOKEN_LIMIT,
                "output_token_limit": 8_192,
            },
        ],
    }


@pytest.fixture
def hub_env(monkeypatch) -> None:
    monkeypatch.setenv("QWENPAW_HUB_MODEL_URL", "http://hub.invalid")
    monkeypatch.setenv("QWENPAW_HUB_MODEL_TOKEN", "hub-token")


def test_hub_window_is_catalog_data_not_a_user_override(
    hub_env,
    hub_catalog,
) -> None:
    """A directory window must not occupy the override slot.

    The console treats a non-null ``max_input_length`` as a user override, so
    an org-managed value there would render a "clear override" action that the
    hub routes then reject with 403. As catalog data it resolves exactly the
    same way (the Hub provider has no discovery, so nothing outranks it).
    """
    provider = managed_provider(catalog=hub_catalog)
    model = provider.models[0]

    assert model.max_input_length is None
    assert model.max_input_length_catalog == INPUT_TOKEN_LIMIT
    assert provider.get_context_size("org-model") == INPUT_TOKEN_LIMIT


def test_hub_info_carries_the_read_only_window_projection(
    hub_env,
    hub_catalog,
) -> None:
    """The Hub response is hand-built, so it adds the projection itself;
    without it the console would show an empty box with no inherited hint."""
    provider = managed_provider(catalog=hub_catalog)

    info = asyncio.run(provider.get_info())
    model = info.models[0]

    assert model.effective_max_input_length == INPUT_TOKEN_LIMIT
    assert model.effective_max_input_length_source == "catalog"
    # Derived state stays off the live model.
    assert provider.models[0].effective_max_input_length is None
