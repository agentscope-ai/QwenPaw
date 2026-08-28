# -*- coding: utf-8 -*-
"""Channel registry: built-in + plugin-registered channels."""

from __future__ import annotations

import importlib
import logging
import threading
from typing import TYPE_CHECKING

from .base import BaseChannel

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_BUILTIN_SPECS: dict[str, tuple[str, str]] = {
    "imessage": (".imessage", "IMessageChannel"),
    "discord": (".discord_", "DiscordChannel"),
    "dingtalk": (".dingtalk", "DingTalkChannel"),
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

_BUILTIN_CHANNEL_CACHE: dict[str, type[BaseChannel] | None] = {}
_BUILTIN_CHANNEL_CACHE_LOCK = threading.Lock()


def _load_builtin_channel(key: str) -> type[BaseChannel] | None:
    """Load one built-in channel without importing unrelated transports."""
    module_name, class_name = _BUILTIN_SPECS[key]
    try:
        module = importlib.import_module(module_name, package=__package__)
        channel_class = getattr(module, class_name)
        if not (
            isinstance(channel_class, type)
            and issubclass(channel_class, BaseChannel)
            and channel_class is not BaseChannel
        ):
            raise TypeError(
                f"{module_name}.{class_name} is not a BaseChannel subtype",
            )
    except Exception:
        if key in _REQUIRED_CHANNEL_KEYS:
            logger.error(
                'failed to load required built-in channel "%s"',
                key,
                exc_info=True,
            )
            raise
        logger.debug(
            "built-in channel unavailable: %s",
            key,
            exc_info=True,
        )
        return None
    return channel_class


def get_channel_class(key: str) -> type[BaseChannel] | None:
    """Return one channel class, importing only the requested built-in."""
    if key in _BUILTIN_SPECS:
        with _BUILTIN_CHANNEL_CACHE_LOCK:
            if key not in _BUILTIN_CHANNEL_CACHE:
                _BUILTIN_CHANNEL_CACHE[key] = _load_builtin_channel(key)
            return _BUILTIN_CHANNEL_CACHE[key]
    return _get_plugin_channels().get(key)


def get_channel_keys() -> tuple[str, ...]:
    """Return discoverable keys without importing built-in channel modules."""
    plugin_keys = tuple(
        key for key in _get_plugin_channels() if key not in _BUILTIN_SPECS
    )
    return (*_BUILTIN_SPECS, *plugin_keys)


def _get_cached_builtin_channels() -> dict[str, type[BaseChannel]]:
    """Return every available built-in channel for discovery commands."""
    channels = {key: get_channel_class(key) for key in _BUILTIN_SPECS}
    return {
        key: channel_class
        for key, channel_class in channels.items()
        if channel_class is not None
    }


def clear_builtin_channel_cache() -> None:
    """Reset built-in channel cache. Primarily for tests."""
    with _BUILTIN_CHANNEL_CACHE_LOCK:
        _BUILTIN_CHANNEL_CACHE.clear()


BUILTIN_CHANNEL_KEYS = frozenset(_BUILTIN_SPECS.keys())


def _get_plugin_channels() -> dict[str, type[BaseChannel]]:
    """Return channel classes registered via the plugin system."""
    try:
        from ...plugins.registry import PluginRegistry

        registry = PluginRegistry()
        return {
            key: reg.channel_class
            for key, reg in registry.get_registered_channels().items()
        }
    except ImportError:
        logger.debug("plugin channel discovery skipped (not installed)")
        return {}
    except Exception:
        logger.warning(
            "plugin channel discovery failed",
            exc_info=True,
        )
        return {}


def get_channel_registry() -> dict[str, type[BaseChannel]]:
    """Built-in + plugin-registered channels."""
    out = _get_cached_builtin_channels()
    for key, ch_cls in _get_plugin_channels().items():
        if key in out:
            logger.warning(
                "Plugin channel '%s' skipped: key already exists in "
                "built-in channels",
                key,
            )
            continue
        out[key] = ch_cls
    return out
