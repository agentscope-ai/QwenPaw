# -*- coding: utf-8 -*-
"""Model-level synchronization policy independent of API protocols."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .model_info import ModelInfo

if TYPE_CHECKING:
    from .provider import Provider


def sync_due(provider: Provider) -> bool:
    """Refresh free inventories more often than paid candidate lists."""
    if not provider.models_last_synced_at:
        return True
    try:
        synced = datetime.fromisoformat(provider.models_last_synced_at)
        if synced.tzinfo is None:
            synced = synced.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    has_free = any(
        model.is_free for model in provider.models + provider.discovered_models
    ) or provider.id in {f"opencode", f"kilo"}
    ttl = (6 if has_free else 24) * 3600
    age = (datetime.now(timezone.utc) - synced).total_seconds()
    return age < 0 or age >= ttl


def reconcile_models(
    provider: Provider,
    models: list[ModelInfo],
    remote_ids: set[str],
) -> list[ModelInfo]:
    """Retain preferences and gate formerly free models after price changes."""
    previous = {
        model.id: model
        for model in provider.models + provider.discovered_models
    }
    removed = set(provider.removed_model_ids)
    by_id = {model.id: model for model in models}
    for model_id, old in previous.items():
        if model_id in removed:
            continue
        if model_id not in by_id and old.discovery_origin in {f"api", f"both"}:
            by_id[model_id] = old.model_copy(deep=True)
        current = by_id.get(model_id)
        if current is None:
            continue
        current.remote_missing = model_id not in remote_ids and (
            old.discovery_origin in {f"api", f"both"}
            or old.auto_enabled
            or old.is_free
        )
        current.auto_enabled = old.auto_enabled or old.is_free
        if current.auto_enabled:
            current.requires_paid_confirmation = (
                current.billing != f"free" or current.remote_missing
            )
    for model in by_id.values():
        if model.billing == f"free" and not model.remote_missing:
            model.auto_enabled = True
            model.requires_paid_confirmation = False
    return list(by_id.values())


def automatic_models(provider: Provider) -> list[ModelInfo]:
    """Expose live free discoveries while retaining user choices."""
    hidden = set(provider.hidden_model_ids) | set(provider.removed_model_ids)
    configured = {
        model.id for model in provider.models + provider.extra_models
    }
    return [
        model
        for model in provider.discovered_models
        if model.auto_enabled
        and model.id not in hidden | configured
        and not model.remote_missing
        and not model.requires_paid_confirmation
        and model.billing == f"free"
        and provider.model_recommendation(model).eligible
    ]


def invalidate_api_metadata(provider: Provider) -> None:
    """Discard endpoint facts on connection changes, retaining user choices."""
    provider.discovered_models = []
    provider.models_last_synced_at = None
    provider.models_last_sync_error = None
    for model in provider.models + provider.extra_models:
        model.max_input_length_auto_detected = None
        model.discovered_at = None
        for field in (f"input_token_limit", f"max_output_length"):
            if getattr(model, f"{field}_source") == f"api":
                setattr(model, field, None)
                setattr(model, f"{field}_source", f"unknown")
        if model.auto_enabled:
            model.requires_paid_confirmation = True
        model.billing = f"unknown"
        model.is_free = False
