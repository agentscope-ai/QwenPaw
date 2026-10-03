# -*- coding: utf-8 -*-
"""Channel registry: built-in + plugin-registered channels."""

from __future__ import annotations

import importlib
import logging
import threading
from typing import Any, TYPE_CHECKING

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


def _import_channel_class(
    key: str,
    module_name: str,
    class_name: str,
) -> type[BaseChannel]:
    """Import one built-in channel class and validate the contract."""
    mod = importlib.import_module(module_name, package=__package__)
    cls = getattr(mod, class_name)
    if not (
        isinstance(cls, type)
        and issubclass(cls, BaseChannel)
        and cls is not BaseChannel
    ):
        raise TypeError(
            f"{key}: {module_name}.{class_name} is not a "
            f"BaseChannel subtype",
        )
    return cls


class _LazyChannelClass:
    """Stand-in for a built-in channel class until it is first used.

    Attribute access, instantiation, and ``from_config`` / ``from_env``
    resolve the real class once and then delegate. Registry listing and
    key iteration do not import the channel module.
    """

    __slots__ = ("_key", "_module_name", "_class_name", "_cls", "_lock")

    def __init__(
        self,
        key: str,
        module_name: str,
        class_name: str,
    ) -> None:
        self._key = key
        self._module_name = module_name
        self._class_name = class_name
        self._cls: type[BaseChannel] | None = None
        self._lock = threading.Lock()

    def _resolve(self) -> type[BaseChannel]:
        if self._cls is not None:
            return self._cls
        with self._lock:
            if self._cls is None:
                self._cls = _import_channel_class(
                    self._key,
                    self._module_name,
                    self._class_name,
                )
            return self._cls

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._resolve()(*args, **kwargs)

    def __repr__(self) -> str:
        if self._cls is not None:
            return f"<LazyChannel {self._key} -> {self._cls!r}>"
        return f"<LazyChannel {self._key} (unresolved)>"


def _load_builtin_channels() -> dict[str, type[BaseChannel]]:
    """Build the built-in channel map.

    Required channels (currently ``console``) are imported immediately so
    startup fails fast if they are broken. Optional channels are wrapped
    in a lazy proxy and imported on first attribute access, so unused
    channel SDKs (for example ``lark_oapi``) are not paid for at startup.
    """
    out: dict[str, type[BaseChannel]] = {}
    for key, (module_name, class_name) in _BUILTIN_SPECS.items():
        if key in _REQUIRED_CHANNEL_KEYS:
            try:
                out[key] = _import_channel_class(
                    key,
                    module_name,
                    class_name,
                )
            except Exception:
                logger.error(
                    'failed to load required built-in channel "%s"',
                    key,
                    exc_info=True,
                )
                raise
            continue
        out[key] = _LazyChannelClass(key, module_name, class_name)
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
