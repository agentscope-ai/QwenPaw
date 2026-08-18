# -*- coding: utf-8 -*-
"""Shared field contracts for provider snapshot updates."""

from __future__ import annotations

from typing import Literal

PluginUpdateKind = Literal[
    "replace",
    "config",
    "discovery",
    "availability",
    "configured_add",
    "configured_delete",
    "configured_update",
    "capability",
]

AVAILABILITY_MODEL_FIELDS = (
    "availability_status",
    "availability_message",
    "availability_http_status",
    "availability_retryable",
    "availability_checked_at",
    "availability_verification",
)
CAPABILITY_MODEL_FIELDS = (
    "supports_image",
    "supports_video",
    "supports_multimodal",
    "probe_source",
)
CONNECTION_CONFIG_FIELDS = frozenset(
    {
        "api_key",
        "base_url",
        "auth_mode",
        "custom_headers",
        "chat_model",
        "api_key_prefix",
        "api_key_prefixes",
    },
)
