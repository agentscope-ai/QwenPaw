# -*- coding: utf-8 -*-
"""Tests for provider model-state persistence and migrations."""

from copy import deepcopy
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


def test_migration_preserves_non_placeholder_request_limit() -> None:
    snapshot: dict[str, Any] = {
        "custom_headers": {"X-Legacy": "kept"},
        "models": [
            {
                "id": "configured-limit",
                "name": "Configured Limit",
                "max_tokens": 4096,
                "generate_kwargs": {"temperature": 0.2},
                "supports_image": True,
            },
        ],
    }

    migrate_provider_snapshot(snapshot)

    model = snapshot["models"][0]
    assert model["generate_kwargs"] == {
        "temperature": 0.2,
        "max_tokens": 4096,
    }
    assert "max_output_length" not in model
    assert model["supports_image"] is True
    assert snapshot["custom_headers"] == {"X-Legacy": "kept"}


def test_migration_preserves_existing_generate_kwargs_limit() -> None:
    snapshot: dict[str, Any] = {
        "models": [
            {
                "id": "configured-limit",
                "name": "Configured Limit",
                "max_tokens": 4096,
                "generate_kwargs": {"max_tokens": 2048},
            },
        ],
    }

    migrate_provider_snapshot(snapshot)

    model = snapshot["models"][0]
    assert model["generate_kwargs"]["max_tokens"] == 2048


def test_migration_applies_to_extra_models_and_is_idempotent() -> None:
    snapshot: dict[str, Any] = {
        "extra_models": [
            {
                "id": "custom-limit",
                "name": "Custom Limit",
                "max_tokens": 4096,
            },
        ],
    }

    assert migrate_provider_snapshot(snapshot) is True

    model = snapshot["extra_models"][0]
    assert model["generate_kwargs"]["max_tokens"] == 4096
    migrated = deepcopy(snapshot)
    assert migrate_provider_snapshot(snapshot) is False
    assert snapshot == migrated


def test_discovered_model_migration_preserves_secret() -> None:
    snapshot: dict[str, Any] = {
        "api_key": "ENC:encrypted-provider-key",
        "discovered_models": [
            {
                "id": "discovered-model",
                "name": "Discovered Model",
                "max_tokens": 4096,
            },
        ],
    }

    assert migrate_provider_snapshot(snapshot) is True

    model = snapshot["discovered_models"][0]
    assert "max_tokens" not in model
    assert model["generate_kwargs"]["max_tokens"] == 4096
    assert snapshot["api_key"] == "ENC:encrypted-provider-key"
