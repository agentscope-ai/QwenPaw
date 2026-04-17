# -*- coding: utf-8 -*-
"""Plugin loader for discovering and loading plugins."""

import importlib.util
import inspect
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging

from .architecture import PluginManifest, PluginRecord
from .api import PluginApi
from .registry import PluginRegistry

logger = logging.getLogger(__name__)


class PluginLoader:
    """Plugin loader for discovering and loading plugins."""

    def __init__(self, plugin_dirs: List[Path]):
        """Initialize plugin loader.

        Args:
            plugin_dirs: List of directories to search for plugins
        """
        self.plugin_dirs = [Path(d) for d in plugin_dirs]
        self.registry = PluginRegistry()
        self._loaded_plugins: Dict[str, PluginRecord] = {}

    def discover_plugins(self) -> List[Tuple[PluginManifest, Path]]:
        """Discover all plugins in plugin directories.

        Returns:
            List of (manifest, plugin_dir) tuples
        """
        discovered = []

        for plugin_dir in self.plugin_dirs:
            if not plugin_dir.exists():
                logger.debug(f"Plugin directory not found: {plugin_dir}")
                continue

            logger.info(f"Scanning plugin directory: {plugin_dir}")

            for item in plugin_dir.iterdir():
                if not item.is_dir():
                    continue

                manifest_path = item / "plugin.json"
                if not manifest_path.exists():
                    continue

                try:
                    manifest = self._load_manifest(manifest_path)
                    discovered.append((manifest, item))
                    logger.info(f"Discovered plugin: {manifest.id}")
                except Exception as e:
                    logger.error(
                        f"Failed to load manifest from {manifest_path}: {e}",
                        exc_info=True,
                    )

        return discovered

    def _load_manifest(self, manifest_path: Path) -> PluginManifest:
        """Load plugin manifest from JSON file.

        Args:
            manifest_path: Path to plugin.json

        Returns:
            PluginManifest instance

        Raises:
            json.JSONDecodeError: If manifest is invalid JSON
            KeyError: If required fields are missing
        """
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return PluginManifest.from_dict(data)

    async def load_plugin(
        self,
        manifest: PluginManifest,
        source_path: Path,
        config: Optional[Dict] = None,
    ) -> PluginRecord:
        """Load a single plugin.

        Args:
            manifest: Plugin manifest
            source_path: Path to plugin directory
            config: Optional plugin configuration

        Returns:
            PluginRecord instance

        Raises:
            FileNotFoundError: If entry point not found
            AttributeError: If plugin module doesn't export required objects
            Exception: If plugin registration fails
        """
        plugin_id = manifest.id

        if plugin_id in self._loaded_plugins:
            logger.warning(f"Plugin '{plugin_id}' already loaded")
            return self._loaded_plugins[plugin_id]

        # Load backend module (if declared and exists)
        backend_entry = manifest.entry.backend
        frontend_entry = manifest.entry.frontend
        backend_entry_file = (
            source_path / backend_entry if backend_entry else None
        )
        frontend_entry_file = (
            source_path / frontend_entry if frontend_entry else None
        )
        plugin_def = None

        if backend_entry_file is None and frontend_entry_file is None:
            raise FileNotFoundError(
                f"Plugin '{plugin_id}' has no entry points declared "
                f"(entry.backend or entry.frontend)",
            )

        backend_exists = (
            backend_entry_file is not None and backend_entry_file.exists()
        )
        frontend_exists = (
            frontend_entry_file is not None and frontend_entry_file.exists()
        )

        if not backend_exists and not frontend_exists:
            raise FileNotFoundError(
                f"Plugin '{plugin_id}' entry point files not found: "
                + (f"{backend_entry_file}" if backend_entry_file else "")
                + (f", {frontend_entry_file}" if frontend_entry_file else ""),
            )

        if not backend_exists:
            # Frontend-only plugin — skip backend loading
            logger.info(
                f"Plugin '{plugin_id}' has no backend entry point "
                f"— loading as frontend-only plugin",
            )
        else:
            try:
                # Dynamic import of plugin module
                # Use unique module name to avoid conflicts
                module_name = f"plugin_{plugin_id.replace('-', '_')}"
                plugin_dir_str = str(source_path)

                # submodule_search_locations enables relative imports
                # within plugin without polluting global sys.path
                spec = importlib.util.spec_from_file_location(
                    module_name,
                    backend_entry_file,
                    submodule_search_locations=[plugin_dir_str],
                )
                if spec is None or spec.loader is None:
                    raise ImportError(
                        f"Failed to load module spec for {backend_entry_file}",
                    )

                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module

                # Set __package__ and __path__ to enable relative imports
                module.__package__ = module_name
                module.__path__ = [plugin_dir_str]

                spec.loader.exec_module(module)

                # Get plugin definition
                if not hasattr(module, "plugin"):
                    raise AttributeError(
                        "Plugin module must export 'plugin' object",
                    )

                plugin_def = module.plugin

                # Create plugin API instance with manifest
                manifest_dict = {
                    "id": manifest.id,
                    "name": manifest.name,
                    "version": manifest.version,
                    "description": manifest.description,
                    "author": manifest.author,
                    "dependencies": manifest.dependencies,
                    "min_version": manifest.min_version,
                    "meta": manifest.meta,
                }
                api = PluginApi(plugin_id, config or {}, manifest_dict)
                api.set_registry(self.registry)

                # Call plugin's register method (support both sync and async)
                if hasattr(plugin_def, "register"):
                    result = plugin_def.register(api)
                    if inspect.iscoroutine(result) or inspect.isawaitable(
                        result,
                    ):
                        await result
                else:
                    raise AttributeError(
                        "Plugin must implement 'register(api)' method",
                    )

            except Exception as e:
                logger.error(
                    f"Failed to load plugin '{plugin_id}': {e}",
                    exc_info=True,
                )
                raise

        # Create plugin record
        record = PluginRecord(
            manifest=manifest,
            source_path=source_path,
            enabled=True,
            instance=plugin_def,
        )

        self._loaded_plugins[plugin_id] = record
        logger.info(f"✓ Loaded plugin '{plugin_id}' successfully")

        return record

    async def load_all_plugins(
        self,
        configs: Optional[Dict[str, Dict]] = None,
    ) -> Dict[str, PluginRecord]:
        """Discover and load all plugins.

        Args:
            configs: Optional dictionary of plugin_id -> config

        Returns:
            Dictionary of plugin_id -> PluginRecord
        """
        discovered = self.discover_plugins()

        for manifest, plugin_dir in discovered:
            config = configs.get(manifest.id) if configs else None

            try:
                await self.load_plugin(manifest, plugin_dir, config)
            except Exception as e:
                logger.error(f"Failed to load plugin '{manifest.id}': {e}")

        return self._loaded_plugins

    def get_loaded_plugin(self, plugin_id: str) -> Optional[PluginRecord]:
        """Get loaded plugin record.

        Args:
            plugin_id: Plugin identifier

        Returns:
            PluginRecord or None if not found
        """
        return self._loaded_plugins.get(plugin_id)

    def get_all_loaded_plugins(self) -> Dict[str, PluginRecord]:
        """Get all loaded plugin records.

        Returns:
            Dictionary of plugin_id -> PluginRecord
        """
        return self._loaded_plugins.copy()
