# -*- coding: utf-8 -*-
"""Helpers for persisted runtime state of built-in provider models."""

import logging
from typing import Any

from .context_windows import DEFAULT_CONTEXT_WINDOW
from .provider import ModelInfo
from .thinking import ThinkingControl

logger = logging.getLogger(__name__)

PROVIDER_SNAPSHOT_SCHEMA_VERSION = 2

PERSISTED_MODEL_STATE_FIELDS = (
    f"source",
    "model_type",
    "generate_kwargs",
    "max_output_length",
    "max_output_length_source",
    "max_output_length_updated_at",
    "max_input_length",
    "max_input_length_configured",
    "max_input_length_auto_detected",
    "relay_reasoning",
    "thinking_enabled",
    f"thinking_control",
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
    f"billing",
    f"pricing",
    f"billing_source",
    f"billing_checked_at",
    f"supports_audio",
    f"supports_tool_calling",
    f"template_id",
    f"input_token_limit",
    f"input_token_limit_source",
    f"auto_enabled",
    f"requires_paid_confirmation",
    f"remote_missing",
    "config_overrides",
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


def _coerce_range_ints(value: Any) -> list[int] | None:
    """Return *value* as a list of ints, or None when it is not numeric."""
    if not isinstance(value, list):
        return None
    result: list[int] = []
    for item in value:
        if isinstance(item, bool):
            return None
        if isinstance(item, int):
            result.append(item)
        elif isinstance(item, float) and item.is_integer():
            result.append(int(item))
        else:
            return None
    return result


def _migrate_legacy_thinking_budget_range(owner: dict[str, Any]) -> bool:
    """Normalize a persisted ``thinking_budget_range`` in place.

    Snapshots written before write-path validation could persist ranges
    that ``ModelInfo`` now rejects (a single bound, an unordered pair, or
    a max below 1); validating such a snapshot on load would fail and
    make the provider disappear. A single bound ``[v]`` is read as the
    cap it most plausibly meant and becomes ``[0, v]``; any other invalid
    shape is dropped to ``None`` (unset) rather than guessed at. Returns
    True when the value changed.
    """
    if "thinking_budget_range" not in owner:
        return False
    value = owner["thinking_budget_range"]
    if value is None:
        return False
    numbers = _coerce_range_ints(value)
    if (
        numbers is not None
        and len(numbers) == 2
        and numbers[0] <= numbers[1]
        and numbers[1] >= 1
    ):
        return False
    migrated: list[int] | None = None
    if numbers is not None and len(numbers) == 1 and numbers[0] >= 1:
        migrated = [0, numbers[0]]
    logger.warning(
        "Migrating legacy thinking_budget_range %r to %r in a persisted "
        "provider config.",
        value,
        migrated,
    )
    owner["thinking_budget_range"] = migrated
    return True


def migrate_provider_snapshot(data: dict[str, Any]) -> bool:
    """Upgrade a provider snapshot to the current schemas.

    The ``thinking_budget_range`` normalization runs on every load,
    independent of the snapshot schema version: a snapshot already at
    the current version can still carry a range persisted before
    write-path validation existed.
    """
    changed = _migrate_legacy_thinking_budget_range(data)
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
            changed = _migrate_legacy_thinking_budget_range(model) or changed

    version = data.get("snapshot_schema_version", 1)
    if (
        isinstance(version, int)
        and version >= PROVIDER_SNAPSHOT_SCHEMA_VERSION
    ):
        return changed

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

    data["snapshot_schema_version"] = PROVIDER_SNAPSHOT_SCHEMA_VERSION
    return True


def serialize_model_state(model: ModelInfo) -> dict[str, Any]:
    """Return the mutable state which must survive a manager restart."""
    payload = model.model_dump()
    state = {field: payload[field] for field in PERSISTED_MODEL_STATE_FIELDS}
    if f"thinking_control" not in model.config_overrides:
        state.pop(f"thinking_control", None)
    if "max_input_length_configured" not in model.model_fields_set:
        state.pop("max_input_length_configured", None)
    return state


def restore_model_state(model: ModelInfo, state: dict[str, Any]) -> None:
    """Restore mutable persisted state onto a built-in model definition."""
    generate_kwargs = state.get("generate_kwargs")
    if generate_kwargs:
        model.generate_kwargs = generate_kwargs

    output_source = state.get("max_output_length_source")
    restore_output_capability = output_source in {"api", "adapter", "user"}
    for field in PERSISTED_MODEL_STATE_FIELDS:
        if field in {
            "generate_kwargs",
            "max_input_length_configured",
        }:
            continue
        if field.startswith("max_output_length") and not (
            restore_output_capability
        ):
            continue
        value = state.get(field)
        if value is not None:
            if field == f"thinking_control":
                value = ThinkingControl.model_validate(value)
            setattr(model, field, value)

    configured_flag = state.get("max_input_length_configured")
    if configured_flag is None:
        configured_length = state.get("max_input_length")
        configured_flag = (
            configured_length is not None
            and configured_length != DEFAULT_CONTEXT_WINDOW
        )
    model.max_input_length_configured = bool(configured_flag)
