# -*- coding: utf-8 -*-
"""Pure provider discovery normalization and error classification."""

from __future__ import annotations

import json
import re
from typing import List, Literal

from pydantic import BaseModel, Field

from .provider import ModelInfo, Provider
from .model_metadata import provider_catalog_models
from .model_sync import reconcile_models

DiscoveryErrorKind = Literal[
    "authentication",
    "authorization",
    "timeout",
    "network",
    "invalid_response",
    "unsupported",
    "provider_unavailable",
    "configuration",
]

DISCOVERY_MODEL_FIELDS = (
    f"released_at",
    "max_input_length_auto_detected",
    "max_output_length",
    "max_output_length_source",
    "max_output_length_updated_at",
    "supports_multimodal",
    "supports_image",
    "supports_video",
    "probe_source",
    "is_free",
    f"pricing",
    f"billing",
    f"billing_source",
    f"billing_checked_at",
    f"supports_audio",
    f"supports_tool_calling",
    f"input_token_limit",
    f"input_token_limit_source",
    f"auto_enabled",
    f"requires_paid_confirmation",
    f"remote_missing",
)


class ProviderModelDiscoveryResult(BaseModel):
    """Normalized result of a provider model discovery attempt."""

    success: bool
    models: List[ModelInfo] = Field(default_factory=list)
    discovered_count: int = 0
    last_synced_at: str | None = None
    used_static_fallback: bool = False
    error: str | None = None
    error_kind: DiscoveryErrorKind | None = None


def merge_discovered_model(
    provider: Provider,
    remote: ModelInfo,
    discovered_at: str,
) -> ModelInfo:
    """Merge fresh API fields over existing non-user model metadata."""
    base = next(
        (
            model
            for model in provider.discovered_models + provider.models
            if model.id == remote.id
        ),
        None,
    )
    payload = base.model_dump() if base is not None else {}
    config_overrides = set(getattr(base, "config_overrides", []))
    user_output_capability = (
        base is not None and base.max_output_length_source == "user"
    )
    for field in remote.model_fields_set:
        if getattr(remote, field) is None:
            continue
        if base is not None:
            if field in config_overrides:
                continue
            if (
                field.startswith("max_output_length")
                and user_output_capability
            ):
                continue
            if base.max_input_length_configured and field in {
                "max_input_length",
                "max_input_length_configured",
            }:
                continue
        payload[field] = getattr(remote, field)
    payload.update(
        {
            "id": remote.id,
            "name": remote.name or remote.id,
            "source": "discovered",
            "discovered_at": discovered_at,
            f"billing_source": remote.billing_source,
            f"billing_checked_at": (
                discovered_at
                if remote.billing_source == f"api"
                else remote.billing_checked_at
            ),
        },
    )
    if remote.max_output_length is not None and not user_output_capability:
        payload["max_output_length_source"] = "api"
        payload["max_output_length_updated_at"] = discovered_at
    return ModelInfo.model_validate(payload)


def apply_discovery_metadata(
    provider: Provider,
    fetched: List[ModelInfo],
    discovered_at: str,
) -> None:
    """Apply API metadata to matching configured models."""
    fetched_by_id = {model.id: model for model in fetched}
    for configured in provider.all_models():
        remote = fetched_by_id.get(configured.id)
        if remote is None:
            continue
        overridden = set(configured.config_overrides)
        user_output_capability = configured.max_output_length_source == "user"
        for field in DISCOVERY_MODEL_FIELDS:
            if (
                field in remote.model_fields_set
                and getattr(remote, field) is not None
                and field not in overridden
                and not (
                    field.startswith("max_output_length")
                    and user_output_capability
                )
            ):
                setattr(configured, field, getattr(remote, field))
        if (
            remote.max_output_length is not None
            and "max_output_length" not in overridden
            and not user_output_capability
        ):
            configured.max_output_length_source = "api"
            configured.max_output_length_updated_at = discovered_at


def classify_discovery_error(
    exc: Exception,
    message: str,
) -> DiscoveryErrorKind:
    """Map a discovery failure to a stable public category."""
    normalized = message.lower()
    status_match = re.search(
        r"\bstatus\s*[=:]\s*(\d{3})\b",
        normalized,
    )
    status = getattr(exc, f"status_code", None) or getattr(
        getattr(exc, f"response", None), f"status_code", None
    )
    if status is None and status_match:
        status = int(status_match.group(1))
    if (
        isinstance(exc, TimeoutError)
        or f"timeout" in type(exc).__name__.lower()
    ):
        return "timeout"
    status_kinds: dict[int, DiscoveryErrorKind] = {
        401: "authentication",
        403: "authorization",
        404: "unsupported",
        405: "unsupported",
    }
    kind = status_kinds.get(status) if status is not None else None
    if kind is None and "unsupported endpoint" in normalized:
        kind = "unsupported"
    if kind is None and status is not None and 500 <= status < 600:
        kind = "provider_unavailable"
    if kind is not None:
        return kind
    if isinstance(exc, (ValueError, TypeError, json.JSONDecodeError)):
        return "invalid_response"
    if isinstance(exc, (ConnectionError, OSError)):
        return "network"
    return "provider_unavailable"


def normalize_discovered_models(
    provider: Provider, fetched: list[ModelInfo], synced_at: str
) -> tuple[list[ModelInfo], set[str]]:
    """Merge API results with offline cards without recycling old API rows."""
    removed = set(provider.removed_model_ids)
    by_id = {}
    for model in fetched:
        if model.id in removed:
            continue
        card = merge_discovered_model(provider, model, synced_at)
        card.discovery_origin = f"api"
        by_id.setdefault(card.id, card)
    api_ids = set(by_id)
    if provider.merge_with_catalog:
        catalog = provider_catalog_models(provider.id, provider.base_url)
        for model in catalog + provider.models:
            if model.id in removed:
                continue
            if model.id in api_ids:
                by_id[model.id].discovery_origin = f"both"
            elif model.id not in by_id:
                card = model.model_copy(deep=True)
                card.discovery_origin = f"catalog"
                card.source = f"discovered"
                by_id[card.id] = card
    return reconcile_models(provider, list(by_id.values()), api_ids), api_ids
