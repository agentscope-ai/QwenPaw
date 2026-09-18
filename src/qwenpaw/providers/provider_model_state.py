# -*- coding: utf-8 -*-
"""Helpers for persisted runtime state of built-in provider models."""

from typing import Any

from .context_windows import DEFAULT_CONTEXT_WINDOW
from .provider import ModelInfo

PROVIDER_SNAPSHOT_SCHEMA_VERSION = 3

# Names that may legitimately appear in ``ModelInfo.config_overrides``.
_CONFIG_OVERRIDE_FIELDS = frozenset(ModelInfo.model_fields)

PERSISTED_MODEL_STATE_FIELDS = (
    "generate_kwargs",
    "max_output_length",
    "max_output_length_source",
    "max_output_length_updated_at",
    "max_input_length",
    "max_input_length_catalog",
    "max_input_length_auto_detected",
    "relay_reasoning",
    "thinking_enabled",
    "thinking_budget",
    "reasoning_effort",
    "supports_multimodal",
    "supports_image",
    "supports_video",
    "availability_status",
    "availability_message",
    "availability_http_status",
    "availability_retryable",
    "availability_checked_at",
    "availability_verification",
    "probe_source",
    "is_free",
    "config_overrides",
)

# Response-only projections of the runtime window resolution. They are derived
# into every provider response and must never be persisted, so the snapshot
# writer drops them; a validator on ModelInfo cannot do it, because responses
# validate through the same class.
DERIVED_MODEL_STATE_FIELDS = (
    "effective_max_input_length",
    "effective_max_input_length_source",
)


def _migrate_legacy_model_output_limit(
    model: dict[str, Any],
) -> None:
    """Migrate a stable v2.1.0 per-model request limit."""
    legacy_limit = model.pop("max_tokens", None)
    if legacy_limit is None or legacy_limit == 8192:
        return

    generate_kwargs = dict(model.get("generate_kwargs") or {})
    generate_kwargs.setdefault("max_tokens", legacy_limit)
    model["generate_kwargs"] = generate_kwargs


def _migrate_context_window_override(model: dict[str, Any]) -> None:
    """Split the legacy override+flag pair into the two window slots.

    Before schema v3, ``max_input_length`` carried the user override and the
    provider/catalog value at the same time, told apart by
    ``max_input_length_configured``. A value that was never flagged as
    explicit belonged to the catalog level (and a legacy 128k there meant
    "not provided", which the catalog loader now normalizes itself).
    """
    configured = bool(model.pop("max_input_length_configured", False))
    value = model.get("max_input_length")
    if value is None or configured:
        # Nothing stored, or a user override: both keep the value as-is.
        return
    model["max_input_length"] = None
    if value != DEFAULT_CONTEXT_WINDOW:
        model["max_input_length_catalog"] = value


def prune_model_overrides(model: dict[str, Any]) -> None:
    """Drop ``config_overrides`` names whose field no longer exists.

    Removing a model field (for example the old
    ``max_input_length_configured``) would otherwise leave its name pinned in
    every snapshot forever: the restore path filters it, but the write path
    serializes the model directly. Applied to the payload before it is
    written, so snapshots converge on their next save.
    """
    overrides = model.get("config_overrides")
    if not isinstance(overrides, list):
        return
    model["config_overrides"] = [
        field for field in overrides if field in _CONFIG_OVERRIDE_FIELDS
    ]


def strip_derived_model_state(model: dict[str, Any]) -> None:
    """Drop response-only derived fields from a persisted model payload.

    ``effective_max_input_length`` and its source are projections that the
    response builders fill on purpose; persisting them would let a stale value
    come back as "the effective window" on any path that does not recompute
    the projection. Snapshots converge on their next save.
    """
    for field in DERIVED_MODEL_STATE_FIELDS:
        model.pop(field, None)


def migrate_provider_snapshot(data: dict[str, Any]) -> bool:
    """Upgrade a provider snapshot to the current output-limit schema."""
    version = data.get("snapshot_schema_version", 1)
    if (
        isinstance(version, int)
        and version >= PROVIDER_SNAPSHOT_SCHEMA_VERSION
    ):
        return False

    for collection_name in (
        "models",
        "extra_models",
        "discovered_models",
    ):
        models = data.get(collection_name)
        if not isinstance(models, list):
            continue
        for model in models:
            if not isinstance(model, dict):
                continue
            _migrate_legacy_model_output_limit(model)
            _migrate_context_window_override(model)

    data["snapshot_schema_version"] = PROVIDER_SNAPSHOT_SCHEMA_VERSION
    return True


def serialize_model_state(model: ModelInfo) -> dict[str, Any]:
    """Return the mutable state which must survive a manager restart."""
    state = {
        field: getattr(model, field) for field in PERSISTED_MODEL_STATE_FIELDS
    }
    state["config_overrides"] = list(model.config_overrides)
    prune_model_overrides(state)
    return state


def restore_model_state(model: ModelInfo, state: dict[str, Any]) -> None:
    """Restore mutable persisted state onto a built-in model definition."""
    generate_kwargs = state.get("generate_kwargs")
    if generate_kwargs:
        model.generate_kwargs = generate_kwargs

    output_source = state.get("max_output_length_source")
    restore_output_capability = output_source in {"api", "adapter", "user"}
    for field in PERSISTED_MODEL_STATE_FIELDS:
        if field == "generate_kwargs":
            continue
        if field.startswith("max_output_length") and not (
            restore_output_capability
        ):
            continue
        value = state.get(field)
        if value is None:
            continue
        if field == "max_input_length_catalog" and (
            getattr(model, field, None) is not None
        ):
            # The window currently documented by the packaged/OTA/local catalog
            # wins over the persisted copy, otherwise a catalog update would
            # never reach an existing install. The persisted value is only a
            # fallback for models the current catalog does not cover.
            continue
        setattr(model, field, value)
