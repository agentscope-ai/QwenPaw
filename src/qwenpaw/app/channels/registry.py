# -*- coding: utf-8 -*-
"""Channel registry: built-in + plugin-registered channels."""

from __future__ import annotations

import importlib
import logging

from .base import BaseChannel

logger = logging.getLogger(__name__)

_BUILTIN_SPECS: dict[str, tuple[str, str]] = {
    "imessage": (".imessage", "IMessageChannel"),
    "discord": (".discord_", "DiscordChannel"),
    "feishu": (".feishu", "FeishuChannel"),
    "qq": (".qq", "QQChannel"),
    "telegram": (".telegram", "TelegramChannel"),
    "mattermost": (".mattermost", "MattermostChannel"),
    "mqtt": (".mqtt", "MQTTChannel"),
    "console": (".console", "ConsoleChannel"),
    "matrix": (".matrix", "MatrixChannel"),
    "slack": (".slack", "SlackChannel"),
    "voice": (".voice", "VoiceChannel"),
    "sip": (".sip", "SIPChannel"),
    "wecom": (".wecom", "WecomChannel"),
    "xiaoyi": (".xiaoyi", "XiaoYiChannel"),
    "yuanbao": (".yuanbao", "YuanbaoChannel"),
    "wechat": (".wechat", "WeChatChannel"),
    "onebot": (".onebot", "OneBotChannel"),
}

# Required channels must load; failures are raised, not skipped.
_REQUIRED_CHANNEL_KEYS: frozenset[str] = frozenset({"console"})

# Stable keys/config models survive removal of their implementation.
MIGRATED_CHANNELS = {"dingtalk": "dingtalk"}

BUILTIN_CHANNEL_KEYS = frozenset(_BUILTIN_SPECS.keys())


def get_available_keys() -> tuple[str, ...]:
    """Discover names without importing channel implementations or SDKs."""
    from ...plugins.registry import PluginRegistry

    return tuple(
        dict.fromkeys(
            [
                *_BUILTIN_SPECS,
                *MIGRATED_CHANNELS,
                *PluginRegistry().get_registered_channels(),
            ],
        ),
    )


def get_channel_class(key: str) -> type[BaseChannel] | None:
    """Resolve one implementation without caching removed plugin classes."""
    from ...plugins.registry import PluginRegistry

    try:
        if key in _BUILTIN_SPECS:
            module, name = _BUILTIN_SPECS[key]
            cls = getattr(
                importlib.import_module(module, package=__package__),
                name,
            )
        else:
            registration = PluginRegistry().get_channel_registration(key)
            if registration is None:
                return None
            cls = registration.channel_class
            if cls is None:
                if registration.channel_loader is None:
                    raise TypeError(f"Channel '{key}' has no implementation")
                cls = registration.channel_loader()
        if (
            not isinstance(cls, type)
            or not issubclass(cls, BaseChannel)
            or cls is BaseChannel
        ):
            raise TypeError(f"Invalid channel implementation: {key}")
        if cls.channel != key:
            raise ValueError(
                f"Channel implementation key does not match '{key}'",
            )
        return cls
    except Exception:
        if key in _REQUIRED_CHANNEL_KEYS:
            raise
        logger.warning("Channel '%s' could not be loaded", key, exc_info=True)
        return None


def _get_plugin_channels() -> dict[str, type[BaseChannel]]:
    from ...plugins.registry import PluginRegistry

    return {
        key: cls
        for key in PluginRegistry().get_registered_channels()
        if (cls := get_channel_class(key)) is not None
    }


def get_channel_registry() -> dict[str, type[BaseChannel]]:
    """Compatibility API for callers that explicitly need all classes."""
    return {
        key: cls
        for key in get_available_keys()
        if (cls := get_channel_class(key)) is not None
    }
