# -*- coding: utf-8 -*-
"""Helpers for detecting duplicate Bot identities across channels."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional


_CHANNEL_IDENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "discord": ("bot_token",),
    "telegram": ("bot_token",),
    "slack": ("bot_token",),
    "mattermost": ("url", "bot_token"),
    "wechat": ("bot_token",),
    "dingtalk": ("client_id",),
    "feishu": ("app_id",),
    "qq": ("app_id",),
    "wecom": ("bot_id",),
    "matrix": ("homeserver", "user_id"),
    "voice": ("phone_number_sid",),
    "xiaoyi": ("agent_id",),
    "yuanbao": ("app_id",),
}


def _config_value(config: Any, field: str) -> Any:
    """Read a field from either a mapping or a config model."""
    if isinstance(config, Mapping):
        return config.get(field)
    return getattr(config, field, None)


def _normalize_identity_value(field: str, value: Any) -> str:
    """Normalize an identity value without exposing it outside this module."""
    normalized = str(value or "").strip()
    if field in {"homeserver", "url"}:
        normalized = normalized.rstrip("/")
    return normalized


def get_channel_bot_identity(
    channel_name: str,
    config: Any,
) -> Optional[tuple[tuple[str, str], ...]]:
    """Return a comparable Bot identity, or None when it is unavailable."""
    if config is None:
        return None

    fields = _CHANNEL_IDENTITY_FIELDS.get(channel_name)
    if fields is None:
        return None

    identity = tuple(
        (
            field,
            _normalize_identity_value(
                field,
                _config_value(config, field),
            ),
        )
        for field in fields
    )
    if any(not value for _, value in identity):
        return None
    return identity


def get_channel_config(channels: Any, channel_name: str) -> Any:
    """Read a built-in channel config by name."""
    if channels is None:
        return None
    if isinstance(channels, Mapping):
        return channels.get(channel_name)
    return getattr(channels, channel_name, None)
