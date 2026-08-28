# -*- coding: utf-8 -*-
"""Pure provider discovery normalization and error classification."""

from __future__ import annotations

import json
import re
from typing import List, Literal

from pydantic import BaseModel, Field

from .provider import ModelInfo, Provider

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
    "max_input_length_auto_detected",
    "max_output_length",
    "max_output_length_source",
    "max_output_length_updated_at",
    "supports_multimodal",
    "supports_image",
    "supports_video",
    "probe_source",
    "is_free",
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
    for configured in provider.configured_models():
        remote = fetched_by_id.get(configured.id)
        if remote is None:
            continue
        overridden = set(configured.config_overrides)
        user_output_capability = configured.max_output_length_source == "user"
        for field in DISCOVERY_MODEL_FIELDS:
            if (
                field in remote.model_fields_set
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
    status = int(status_match.group(1)) if status_match else None
    if isinstance(exc, TimeoutError):
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
