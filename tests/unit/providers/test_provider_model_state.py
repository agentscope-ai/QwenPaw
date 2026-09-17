# -*- coding: utf-8 -*-
"""Tests for provider model-state persistence and migrations."""

from copy import deepcopy
from typing import Any

from qwenpaw.providers.context_windows import DEFAULT_CONTEXT_WINDOW
from qwenpaw.providers.provider_model_state import (
    PROVIDER_SNAPSHOT_SCHEMA_VERSION,
    migrate_provider_snapshot,
)


def _migrate_context_windows(model: dict[str, Any]) -> dict[str, Any]:
    snapshot = {"snapshot_schema_version": 2, "models": [deepcopy(model)]}
    assert migrate_provider_snapshot(snapshot) is True
    migrated = snapshot["models"][0]
    assert "max_input_length_configured" not in migrated
    return migrated


def test_context_window_migration_keeps_a_user_override() -> None:
    """The legacy explicit flag told a user choice apart from a data value."""
    migrated = _migrate_context_windows(
        {
            "id": "claude-sonnet-4-5",
            "max_input_length": 131_072,
            "max_input_length_configured": True,
        },
    )

    assert migrated["max_input_length"] == 131_072
    assert "max_input_length_catalog" not in migrated


def test_context_window_migration_moves_data_values_to_the_catalog() -> None:
    migrated = _migrate_context_windows(
        {
            "id": "claude-sonnet-4-5",
            "max_input_length": 1_000_000,
            "max_input_length_configured": False,
        },
    )

    assert migrated["max_input_length"] is None
    assert migrated["max_input_length_catalog"] == 1_000_000


def test_context_window_migration_drops_the_legacy_default_placeholder() -> (
    None
):
    """A stored 128k that was never flagged was "not provided" (the catalog
    generator writes the field default for windows it never collected)."""
    migrated = _migrate_context_windows(
        {
            "id": "gpt-5",
            "max_input_length": DEFAULT_CONTEXT_WINDOW,
            "max_input_length_configured": False,
        },
    )

    assert migrated["max_input_length"] is None
    assert "max_input_length_catalog" not in migrated


def test_context_window_migration_handles_flagless_legacy_records() -> None:
    # Very old snapshots serialized every default field without the flag.
    migrated = _migrate_context_windows(
        {"id": "gpt-5", "max_input_length": DEFAULT_CONTEXT_WINDOW},
    )
    assert migrated["max_input_length"] is None

    migrated = _migrate_context_windows(
        {"id": "gpt-5", "max_input_length": 200_000},
    )
    assert migrated["max_input_length"] is None
    assert migrated["max_input_length_catalog"] == 200_000


def test_context_window_migration_is_idempotent() -> None:
    snapshot = {
        "snapshot_schema_version": 2,
        "models": [
            {
                "id": "gpt-5",
                "max_input_length": 131_072,
                "max_input_length_configured": False,
            },
        ],
    }
    assert migrate_provider_snapshot(snapshot) is True
    assert migrate_provider_snapshot(snapshot) is False


def test_serialized_state_drops_dead_override_names() -> None:
    """Removing a field (e.g. the old configured flag) must not leave its
    name pinned in every snapshot's config_overrides forever."""
    from qwenpaw.providers.provider import ModelInfo
    from qwenpaw.providers.provider_model_state import serialize_model_state

    model = ModelInfo(
        id="gpt-5",
        name="GPT-5",
        max_input_length=65_536,
        config_overrides=[
            "max_input_length",
            "max_input_length_configured",
            "generate_kwargs",
        ],
    )

    state = serialize_model_state(model)

    assert state["config_overrides"] == [
        "max_input_length",
        "generate_kwargs",
    ]
    assert state["max_input_length"] == 65_536


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
