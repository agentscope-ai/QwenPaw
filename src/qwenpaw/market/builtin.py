# -*- coding: utf-8 -*-
"""Adapters and one-time local provisioning for the bundled Hub plugins."""

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from ..plugins.install_lock import plugin_install_lock
from ..utils.io_utils import write_json_atomic
from .providers.base import MarketProvider


class BuiltinMarketProvider:
    """Reuse existing search and URL import implementations unchanged."""

    def __init__(
        self,
        provider: MarketProvider,
        matcher: Callable | None = None,
        fetcher: Callable | None = None,
    ):
        self.key = provider.key
        self.label = provider.label
        self.supports_browse = provider.supports_browse
        self.available = provider.available
        self.search = provider.search
        if matcher is None or fetcher is None:
            from ..agents.skill_system.hub import PROVIDERS

            handlers = {key: (match, fetch) for key, match, fetch in PROVIDERS}
            default_matcher, default_fetcher = handlers[provider.key]
            matcher = default_matcher if matcher is None else matcher
            fetcher = default_fetcher if fetcher is None else fetcher
        self._matcher = matcher
        self.fetch_bundle = fetcher

    def matches_url(self, url: str) -> bool:
        return bool(self._matcher(url))


def get_builtin_hub_plugins_dir() -> Path:
    """Locate bundled resources in installed builds or the source checkout."""
    package_dir = Path(__file__).resolve().parents[1]
    bundled = package_dir / "plugins/bundled/hub"
    return (
        bundled
        if bundled.is_dir()
        else package_dir.parent.parent / "plugins/hub"
    )


def seed_builtin_hub_plugins(plugins_dir: Path) -> None:
    """Copy each default plugin once, respecting later user uninstalls.

    Templates are shipped as package data, including in desktop builds.
    Existing installations are never overwritten. A malformed marker fails
    closed so it cannot silently restore deliberately removed plugins.
    """
    plugins_dir.mkdir(parents=True, exist_ok=True)
    marker = plugins_dir / ".hub-defaults.json"
    with plugin_install_lock(plugins_dir / ".hub-defaults.lock") as locked:
        if not locked:
            raise TimeoutError("Could not lock default Hub initialization")
        processed: Any = (
            json.loads(marker.read_text()) if marker.exists() else []
        )
        if not isinstance(processed, list) or not all(
            isinstance(key, str) for key in processed
        ):
            raise ValueError("Invalid default Hub initialization record")
        templates = get_builtin_hub_plugins_dir()
        for source in sorted(templates.iterdir()):
            if not (source / "plugin.json").is_file():
                continue
            plugin_id = source.name
            if plugin_id in processed:
                continue
            target = plugins_dir / plugin_id
            if not target.exists():
                with tempfile.TemporaryDirectory(
                    prefix=".hub-seed-",
                    dir=plugins_dir,
                ) as staging:
                    staged = Path(staging) / plugin_id
                    shutil.copytree(
                        source,
                        staged,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                    )
                    staged.rename(target)
            processed.append(plugin_id)
            write_json_atomic(marker, processed)
