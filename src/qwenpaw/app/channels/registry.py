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
    "console": (".console", "ConsoleChannel"),
}

# Required channels must load; failures are raised, not skipped.
_REQUIRED_CHANNEL_KEYS: frozenset[str] = frozenset({"console"})

_BUILTIN_CHANNEL_CACHE: dict[str, type[BaseChannel]] | None = None
_BUILTIN_CHANNEL_CACHE_LOCK = threading.Lock()
_BUILTIN_CHANNEL_CACHE_SELECTION = None


def _load_builtin_channels() -> dict[str, type[BaseChannel]]:
    """Load built-in channels safely.

    A single optional dependency failure should not break CLI startup.
    """
    out: dict[str, type[BaseChannel]] = {}
    selected = selected_process_channels()
    for key, (module_name, class_name) in _BUILTIN_SPECS.items():
        if key in selected:
            continue
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
    global _BUILTIN_CHANNEL_CACHE, _BUILTIN_CHANNEL_CACHE_SELECTION
    with _BUILTIN_CHANNEL_CACHE_LOCK:
        selected = selected_process_channels()
        if (
            _BUILTIN_CHANNEL_CACHE is None
            or _BUILTIN_CHANNEL_CACHE_SELECTION != selected
        ):
            _BUILTIN_CHANNEL_CACHE = _load_builtin_channels()
            _BUILTIN_CHANNEL_CACHE_SELECTION = selected
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
            if reg.channel_class is not None
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
    selected = selected_process_channels()
    out = {
        k: v
        for k, v in _get_cached_builtin_channels().items()
        if k not in selected
    }
    for key, ch_cls in _get_plugin_channels().items():
        if key in selected:
            continue
        if key in out:
            logger.warning(
                "Plugin channel '%s' skipped: key already exists in "
                "built-in channels",
                key,
            )
            continue
        out[key] = ch_cls
    return out


def selected_process_channels() -> frozenset[str]:
    """Host rollout reservation is independent of installed registrations."""
    from ...plugins.registry import PluginRegistry

    registry = PluginRegistry()
    from ...plugins.official_channel_catalog import official_channel_owners

    return frozenset(official_channel_owners()) | frozenset(
        key
        for key, row in registry.get_channel_catalog().items()
        if row.description_record is not None
    )
