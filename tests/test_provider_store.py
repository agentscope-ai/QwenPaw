# -*- coding: utf-8 -*-
"""Regression tests for provider store add_model / remove_model (#95).

Verifies that custom providers created via ``create_custom_provider`` are
visible to ``add_model`` and ``remove_model`` in a fresh process (i.e. when
the in-memory PROVIDERS registry has not yet been populated with custom
providers from providers.json).
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from copaw.providers.models import ModelInfo
from copaw.providers.registry import PROVIDERS, unregister_custom_provider
from copaw.providers.store import (
    add_model,
    create_custom_provider,
    load_providers_json,
    remove_model,
    save_providers_json,
)


@pytest.fixture()
def tmp_providers(monkeypatch, tmp_path):
    """Redirect providers.json to a temp directory and clean up PROVIDERS."""
    json_path = tmp_path / "providers.json"

    # Patch get_providers_json_path to use temp file
    monkeypatch.setattr(
        "copaw.providers.store.get_providers_json_path",
        lambda: json_path,
    )

    yield json_path

    # Clean up any custom providers we registered during the test
    for pid in list(PROVIDERS):
        try:
            unregister_custom_provider(pid)
        except (ValueError, KeyError):
            pass


class TestAddModelCustomProvider:
    """Regression: add_model must find custom providers (#95)."""

    def test_add_model_finds_custom_provider(self, tmp_providers):
        """add_model should succeed for a freshly created custom provider."""
        create_custom_provider(
            "myprovider",
            "My Provider",
            default_base_url="https://api.example.com/v1",
        )

        # Simulate a fresh process: clear custom providers from PROVIDERS
        unregister_custom_provider("myprovider")
        assert "myprovider" not in PROVIDERS

        # This was failing before the fix: "Provider 'myprovider' not found."
        result = add_model(
            "myprovider",
            ModelInfo(id="my-model", name="My Model"),
        )

        assert "myprovider" in result.custom_providers
        cpd = result.custom_providers["myprovider"]
        assert any(m.id == "my-model" for m in cpd.models)

    def test_remove_model_finds_custom_provider(self, tmp_providers):
        """remove_model should succeed for a custom provider with models."""
        create_custom_provider(
            "myprovider",
            "My Provider",
            default_base_url="https://api.example.com/v1",
            models=[ModelInfo(id="my-model", name="My Model")],
        )

        # Simulate fresh process
        unregister_custom_provider("myprovider")
        assert "myprovider" not in PROVIDERS

        result = remove_model("myprovider", "my-model")

        cpd = result.custom_providers["myprovider"]
        assert not any(m.id == "my-model" for m in cpd.models)

    def test_add_model_builtin_still_works(self, tmp_providers):
        """Built-in providers should still work after the fix."""
        # Initialize providers.json so built-ins are populated
        load_providers_json()

        result = add_model(
            "modelscope",
            ModelInfo(id="test-builtin-model", name="Test Builtin"),
        )

        settings = result.providers.get("modelscope")
        assert settings is not None
        assert any(m.id == "test-builtin-model" for m in settings.extra_models)

    def test_add_model_nonexistent_provider_raises(self, tmp_providers):
        """add_model should still raise for truly nonexistent providers."""
        load_providers_json()

        with pytest.raises(ValueError, match="not found"):
            add_model(
                "does-not-exist",
                ModelInfo(id="x", name="X"),
            )
