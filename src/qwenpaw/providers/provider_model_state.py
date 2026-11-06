# -*- coding: utf-8 -*-
"""Helpers for persisted runtime state of built-in provider models."""

import logging
from typing import Any

from pydantic import TypeAdapter, ValidationError

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


_LOOSE_INT_ADAPTER = TypeAdapter(int)


def _coerce_loose_int(value: Any) -> int | None:
    """Return *value* as an int the way Pydantic would, else None.

    Delegates to Pydantic's own lax int coercion, so the migration
    accepts exactly what model validation on load would accept:
    real ints, bools (coerced to 0/1), integral floats and numeric
    strings (``"100"``, ``"100.0"``) convert, while strings Python's
    ``float()`` would accept but Pydantic rejects (``"1."``,
    ``"1e3"``, ``"1.0e3"``) do not.
    """
    try:
        return _LOOSE_INT_ADAPTER.validate_python(value)
    except ValidationError:
        return None


def _coerce_range_ints(value: Any) -> list[int] | None:
    """Return *value* as a list of ints, or None when it is not numeric."""
    if not isinstance(value, list):
        return None
    result: list[int] = []
    for item in value:
        number = _coerce_loose_int(item)
        if number is None:
            return None
        result.append(number)
    return result


def _migrate_legacy_thinking_budget_range(
    owner: dict[str, Any],
    *,
    provider_level: bool = False,
) -> bool:
    """Normalize a persisted ``thinking_budget_range`` in place.

    Snapshots written before write-path validation could persist ranges
    that ``ModelInfo`` now rejects (a single bound, an unordered pair, or
    a max below 1); validating such a snapshot on load would fail and
    make the provider disappear. A single bound ``[v]`` is read as the
    cap it most plausibly meant and becomes ``[0, v]``. Any other invalid
    shape is dropped rather than guessed at: a model-level override
    becomes ``None`` (unset), while a provider-level value is removed
    entirely, because ``ProviderInfo.thinking_budget_range`` is a
    non-optional ``List[int]`` and only removal lets its default apply.
    Returns True when the value changed.
    """
    if "thinking_budget_range" not in owner:
        return False
    value = owner["thinking_budget_range"]
    numbers = _coerce_range_ints(value)
    if (
        numbers is not None
        and len(numbers) == 2
        and numbers[0] <= numbers[1]
        and numbers[1] >= 1
    ):
        return False
    if numbers is not None and len(numbers) == 1 and numbers[0] >= 1:
        owner["thinking_budget_range"] = [0, numbers[0]]
        outcome = "using [0, %d]" % numbers[0]
    elif provider_level:
        owner.pop("thinking_budget_range")
        outcome = "restoring the provider default"
    elif value is None:
        return False
    else:
        owner["thinking_budget_range"] = None
        outcome = "dropping the override"
    logger.warning(
        "Migrating legacy thinking_budget_range %r in a persisted "
        "provider config: %s.",
        value,
        outcome,
    )
    return True


# Per-model scalar fields bounded below by ``ModelInfo`` field
# constraints (``ge=``), as (field, minimum, optional). A snapshot
# written before write-path validation could persist a value below the
# bound; validating such a snapshot on load would fail and make the
# provider disappear. Optional fields fall back to ``None`` (unset);
# the non-optional ``max_input_length`` key is removed instead, so its
# field default applies.
_MODEL_SCALAR_MINIMUMS = (
    ("max_output_length", 1, True),
    ("max_input_length", 1000, False),
    ("max_input_length_auto_detected", 1000, True),
    ("input_token_limit", 1, True),
    ("thinking_budget", 1, True),
)


def _clear_max_input_length_override(model: dict[str, Any]) -> None:
    """Clear the explicit-override markers for ``max_input_length``.

    Mirrors the write path's clear operation: without this, a reset
    ``max_input_length`` would still be treated as an explicit user
    override (the configured flag and the ``config_overrides`` entries
    survive in the snapshot) and take precedence over auto-detected
    values.
    """
    if model.get("max_input_length_configured"):
        model["max_input_length_configured"] = False
    overrides = model.get("config_overrides")
    if isinstance(overrides, list):
        model["config_overrides"] = [
            field
            for field in overrides
            if field not in {"max_input_length", "max_input_length_configured"}
        ]


def _migrate_legacy_model_scalars(model: dict[str, Any]) -> bool:
    """Reset persisted model scalars that violate their field bounds.

    Values Pydantic would coerce and accept (ints in range, numeric
    strings) are left untouched; only values that would fail validation
    on load are reset. Returns True when any value changed.
    """
    changed = False
    for field, minimum, optional in _MODEL_SCALAR_MINIMUMS:
        if field not in model:
            continue
        value = model[field]
        if value is None and optional:
            continue
        number = _coerce_loose_int(value)
        if number is not None and number >= minimum:
            continue
        if optional:
            model[field] = None
            outcome = "dropping the value"
        else:
            model.pop(field)
            outcome = "restoring the field default"
            _clear_max_input_length_override(model)
        logger.warning(
            "Migrating legacy %s %r in a persisted provider config: %s.",
            field,
            value,
            outcome,
        )
        changed = True
    return changed


def migrate_provider_snapshot(data: dict[str, Any]) -> bool:
    """Upgrade a provider snapshot to the current schemas.

    The ``thinking_budget_range`` normalization and the bounded-scalar
    reset run on every load, independent of the snapshot schema
    version: a snapshot already at the current version can still carry
    values persisted before write-path validation existed.
    """
    changed = _migrate_legacy_thinking_budget_range(
        data,
        provider_level=True,
    )
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
            changed = _migrate_legacy_model_scalars(model) or changed
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
