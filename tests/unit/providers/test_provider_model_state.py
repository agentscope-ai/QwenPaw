# -*- coding: utf-8 -*-
"""Tests for provider model-state persistence and migrations."""

from typing import Any

from qwenpaw.providers.provider_model_state import (
    PROVIDER_SNAPSHOT_SCHEMA_VERSION,
    migrate_provider_snapshot,
)


def test_migration_drops_legacy_placeholder_output_limit() -> None:
    snapshot = {
        "models": [
            {
                "id": "unknown-limit",
                "name": "Unknown Limit",
                "max_tokens": 8192,
            },
        ],
    }

    assert migrate_provider_snapshot(snapshot) is True

    model = snapshot["models"][0]
    assert "max_tokens" not in model
    assert "max_output_length" not in model
    assert snapshot["snapshot_schema_version"] == (
        PROVIDER_SNAPSHOT_SCHEMA_VERSION
    )
    assert migrate_provider_snapshot(snapshot) is False


def test_migration_preserves_user_request_limit_of_8192() -> None:
    snapshot = {
        "models": [
            {
                "id": "configured-limit",
                "name": "Configured Limit",
                "max_tokens": 8192,
                "generate_kwargs": {"temperature": 0.2},
                "config_overrides": ["max_tokens"],
            },
        ],
    }

    migrate_provider_snapshot(snapshot)

    model = snapshot["models"][0]
    assert model["generate_kwargs"] == {
        "temperature": 0.2,
        "max_tokens": 8192,
    }
    assert model["config_overrides"] == ["generate_kwargs"]
    assert "max_output_length" not in model


def test_migration_preserves_existing_generate_kwargs_limit() -> None:
    snapshot: dict[str, Any] = {
        "models": [
            {
                "id": "configured-limit",
                "name": "Configured Limit",
                "max_tokens": 4096,
                "generate_kwargs": {"max_tokens": 2048},
                "config_overrides": ["max_tokens"],
            },
        ],
    }

    migrate_provider_snapshot(snapshot)

    model = snapshot["models"][0]
    assert model["generate_kwargs"]["max_tokens"] == 2048
    assert model["config_overrides"] == ["generate_kwargs"]


def test_migration_preserves_api_capability_of_8192() -> None:
    snapshot: dict[str, Any] = {
        "models_last_synced_at": "2026-08-27T00:00:00Z",
        "discovered_models": [
            {
                "id": "api-limit",
                "name": "API Limit",
                "max_tokens": 8192,
            },
        ],
    }

    migrate_provider_snapshot(snapshot)

    model = snapshot["discovered_models"][0]
    assert model["max_output_length"] == 8192
    assert model["max_output_length_source"] == "api"
    assert model["max_output_length_updated_at"] == ("2026-08-27T00:00:00Z")
    assert "max_tokens" not in model.get("generate_kwargs", {})
