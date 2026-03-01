# -*- coding: utf-8 -*-
"""Tests for add_model/remove_model with custom providers."""

import pytest
from unittest.mock import patch, MagicMock

from copaw.providers.store import add_model, remove_model
from copaw.providers.models import (
    ProvidersData,
    ModelInfo,
    CustomProviderData,
    ModelSlotConfig,
)


def _make_data_with_custom(provider_id="my-custom", models=None):
    """Create a ProvidersData with a custom provider."""
    cpd = CustomProviderData(
        id=provider_id,
        name="My Custom",
        base_url="https://api.example.com/v1",
        models=models or [],
    )
    return ProvidersData(
        custom_providers={provider_id: cpd},
        active_llm=ModelSlotConfig(),
    )


class TestAddModelCustomProvider:
    """add_model should work with custom providers."""

    @patch("copaw.providers.store.save_providers_json")
    @patch("copaw.providers.store.load_providers_json")
    @patch("copaw.providers.store.register_custom_provider")
    def test_add_model_to_custom_provider(self, mock_reg, mock_load, mock_save):
        data = _make_data_with_custom("my-custom")
        mock_load.return_value = data

        result = add_model("my-custom", ModelInfo(id="gpt-4", name="GPT-4"))

        assert any(m.id == "gpt-4" for m in data.custom_providers["my-custom"].models)
        mock_save.assert_called_once()

    @patch("copaw.providers.store.load_providers_json")
    def test_add_model_unknown_provider_raises(self, mock_load):
        mock_load.return_value = ProvidersData(active_llm=ModelSlotConfig())

        with pytest.raises(ValueError, match="not found"):
            add_model("nonexistent", ModelInfo(id="x", name="x"))

    @patch("copaw.providers.store.save_providers_json")
    @patch("copaw.providers.store.load_providers_json")
    @patch("copaw.providers.store.register_custom_provider")
    def test_add_duplicate_model_raises(self, mock_reg, mock_load, mock_save):
        data = _make_data_with_custom(
            "my-custom",
            models=[ModelInfo(id="gpt-4", name="GPT-4")],
        )
        mock_load.return_value = data

        with pytest.raises(ValueError, match="already exists"):
            add_model("my-custom", ModelInfo(id="gpt-4", name="GPT-4"))


class TestRemoveModelCustomProvider:
    """remove_model should work with custom providers."""

    @patch("copaw.providers.store.save_providers_json")
    @patch("copaw.providers.store.load_providers_json")
    @patch("copaw.providers.store.register_custom_provider")
    def test_remove_model_from_custom_provider(self, mock_reg, mock_load, mock_save):
        data = _make_data_with_custom(
            "my-custom",
            models=[ModelInfo(id="gpt-4", name="GPT-4")],
        )
        mock_load.return_value = data

        remove_model("my-custom", "gpt-4")

        assert len(data.custom_providers["my-custom"].models) == 0
        mock_save.assert_called_once()

    @patch("copaw.providers.store.load_providers_json")
    def test_remove_model_unknown_provider_raises(self, mock_load):
        mock_load.return_value = ProvidersData(active_llm=ModelSlotConfig())

        with pytest.raises(ValueError, match="not found"):
            remove_model("nonexistent", "gpt-4")
