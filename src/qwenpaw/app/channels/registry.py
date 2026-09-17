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

_BUILTIN_CHANNEL_CACHE: dict[str, type[BaseChannel]] | None = None
_BUILTIN_CHANNEL_CACHE_LOCK = threading.Lock()


def _load_builtin_channels() -> dict[str, type[BaseChannel]]:
    """Load built-in channels safely.

    A single optional dependency failure should not break CLI startup.
    """
    out: dict[str, type[BaseChannel]] = {}
    for key, (module_name, class_name) in _BUILTIN_SPECS.items():
        try:
            mod = importlib.import_module(module_name, package=__package__)
            cls = getattr(mod, class_name)
            if not (
                isinstance(cls, type)
                and issubclass(cls, BaseChannel)
                and cls is not BaseChannel
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
            continue
        out[key] = cls
    return out


def _get_cached_builtin_channels() -> dict[str, type[BaseChannel]]:
    """Return cached built-in channels (loaded once per process)."""
    global _BUILTIN_CHANNEL_CACHE
    with _BUILTIN_CHANNEL_CACHE_LOCK:
        if _BUILTIN_CHANNEL_CACHE is None:
            _BUILTIN_CHANNEL_CACHE = _load_builtin_channels()
        return dict(_BUILTIN_CHANNEL_CACHE)


def clear_builtin_channel_cache() -> None:
    """Reset built-in channel cache. Primarily for tests."""
    global _BUILTIN_CHANNEL_CACHE
    with _BUILTIN_CHANNEL_CACHE_LOCK:
        _BUILTIN_CHANNEL_CACHE = None


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
