# -*- coding: utf-8 -*-
"""Plugin loader for discovering and loading plugins."""

import asyncio
import importlib.util
import inspect
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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

                # Register plugin manifest to registry
                self.registry.register_plugin_manifest(
                    plugin_id,
                    manifest_dict,
                )

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

    @staticmethod
    def _find_uv() -> Optional[str]:
        """Return the path to the ``uv`` binary, or ``None`` if not found.

        Checks PATH first, then well-known install locations for both
        Unix (``~/.local/bin/uv``, ``~/.cargo/bin/uv``) and
        Windows (``%LOCALAPPDATA%\\Programs\\uv\\uv.exe``,
        ``%USERPROFILE%\\.cargo\\bin\\uv.exe``).
        """
        # shutil.which honours PATHEXT on Windows and handles .exe
        if found := shutil.which("uv"):
            return found

        home = Path.home()
        candidates = [
            home / ".local" / "bin" / "uv",  # Linux/macOS script install
            home / ".cargo" / "bin" / "uv",  # Linux/macOS cargo install
        ]
        # Windows-specific locations
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(
                Path(local_app_data) / "Programs" / "uv" / "uv.exe",
            )
        candidates.append(home / ".cargo" / "bin" / "uv.exe")

        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None

    def _install_requirements(
        self,
        requirements_file: Path,
        plugin_id: str,
    ) -> None:
        """Install Python dependencies for a plugin (blocking).

        Tries ``python -m pip`` first (conda / pip-installed envs).
        If pip is not available in the current interpreter — which is
        the case for uv-managed venvs created by the QwenPaw script
        installer — falls back to ``uv pip install``.

        Intended to be called via ``asyncio.to_thread`` so that the
        package-manager call does not block the event loop.

        Args:
            requirements_file: Path to requirements.txt
            plugin_id: Plugin identifier (for log messages)

        Raises:
            RuntimeError: If all install attempts fail or time out
        """
        logger.info(
            f"Installing dependencies for plugin '{plugin_id}'...",
        )
        req = str(requirements_file)
        timeout = 300

        # ── Attempt 1: python -m pip ──────────────────────────────────
        try:
            result = subprocess.run(  # pylint: disable=subprocess-run-check
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-input",
                    "-r",
                    req,
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Dependency installation timed out for '{plugin_id}' "
                f"(300 s limit exceeded)",
            ) from exc

        if result.returncode == 0:
            logger.info(
                f"Dependencies installed for plugin '{plugin_id}'"
                " (via pip)",
            )
            return

        # If pip itself is missing, try uv as a fallback.
        pip_missing = (
            "No module named pip" in result.stderr
            or "No module named pip" in result.stdout
        )
        if not pip_missing:
            raise RuntimeError(
                f"Dependency installation failed for '{plugin_id}': "
                f"{result.stderr}",
            )

        # ── Attempt 2: uv pip install ─────────────────────────────────
        uv = self._find_uv()
        if uv is None:
            raise RuntimeError(
                f"pip is not available in the current Python environment "
                f"and 'uv' was not found on PATH.  Install dependencies "
                f"manually: pip install -r {req}",
            )

        logger.info(
            f"pip not available; retrying with uv for plugin '{plugin_id}'",
        )
        try:
            uv_result = subprocess.run(  # pylint: disable=subprocess-run-check
                [
                    uv,
                    "pip",
                    "install",
                    "--python",
                    sys.executable,
                    "-r",
                    req,
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Dependency installation timed out for '{plugin_id}' "
                f"(300 s limit exceeded, via uv)",
            ) from exc

        if uv_result.returncode != 0:
            raise RuntimeError(
                f"Dependency installation failed for '{plugin_id}' "
                f"(via uv): {uv_result.stderr}",
            )
        logger.info(
            f"Dependencies installed for plugin '{plugin_id}' (via uv)",
        )

    async def load_plugin_from_path(
        self,
        source_path: Path,
        config: Optional[Dict] = None,
        install_dir: Optional[Path] = None,
    ) -> PluginRecord:
        """Copy plugin files, install deps, and load plugin at runtime.

        The plugin directory is copied into ``install_dir`` (defaults
        to the first entry of ``self.plugin_dirs``) when it is not
        already located there.  Python dependencies listed in
        ``requirements.txt`` are installed before loading.

        Args:
            source_path: Directory that contains ``plugin.json``
            config: Optional plugin configuration dict
            install_dir: Target plugins directory.  Defaults to the
                first directory in ``self.plugin_dirs``.

        Returns:
            Loaded PluginRecord

        Raises:
            FileNotFoundError: If ``plugin.json`` not found
            ValueError: If the plugin is already loaded
            RuntimeError: If dependency installation fails
        """
        source_path = Path(source_path).resolve()
        manifest_path = source_path / "plugin.json"
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"plugin.json not found in {source_path}",
            )

        manifest = self._load_manifest(manifest_path)
        plugin_id = manifest.id

        if plugin_id in self._loaded_plugins:
            raise ValueError(
                f"Plugin '{plugin_id}' is already loaded. "
                "Uninstall it first before reinstalling.",
            )

        # Determine target directory
        if install_dir is None:
            if not self.plugin_dirs:
                raise RuntimeError("No plugin directories configured")
            install_dir = self.plugin_dirs[0]
        install_dir = Path(install_dir).resolve()
        target_dir = (install_dir / plugin_id).resolve()

        # Guard against path-traversal in plugin_id (e.g. "../../etc")
        if not target_dir.is_relative_to(install_dir):
            raise ValueError(
                f"Plugin id '{plugin_id}' resolves outside the plugin "
                f"directory ({install_dir}). Refusing to install.",
            )

        # Copy files when source is not already the target
        if source_path != target_dir:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source_path, target_dir)
            logger.info(
                f"Copied plugin '{plugin_id}' to {target_dir}",
            )

        # Install Python dependencies (off the event loop)
        requirements_file = target_dir / "requirements.txt"
        if requirements_file.exists():
            await asyncio.to_thread(
                self._install_requirements,
                requirements_file,
                plugin_id,
            )

        # Re-read manifest from the installed location so that
        # source_path in the record points to the correct directory
        installed_manifest = self._load_manifest(target_dir / "plugin.json")
        return await self.load_plugin(installed_manifest, target_dir, config)

    async def unload_plugin(
        self,
        plugin_id: str,
        delete_files: bool = False,
    ) -> None:
        """Unload a plugin from memory and optionally remove its files.

        Executes any registered shutdown hooks, removes the plugin
        module from ``sys.modules``, cleans up the plugin registry, and
        removes the plugin's tools from ``qwenpaw.agents.tools``.

        Args:
            plugin_id: Plugin identifier to unload
            delete_files: When ``True``, delete the plugin directory
                from disk after unloading.

        Raises:
            KeyError: If the plugin is not currently loaded
        """
        record = self._loaded_plugins.get(plugin_id)
        if record is None:
            raise KeyError(
                f"Plugin '{plugin_id}' is not loaded",
            )

        # Execute shutdown hooks registered by this plugin
        shutdown_hooks = [
            h
            for h in self.registry.get_shutdown_hooks()
            if h.plugin_id == plugin_id
        ]
        for hook in shutdown_hooks:
            try:
                result = hook.callback()
                if inspect.iscoroutine(result) or inspect.isawaitable(
                    result,
                ):
                    await result
            except Exception as exc:
                logger.error(
                    f"Error in shutdown hook '{hook.hook_name}' "
                    f"for plugin '{plugin_id}': {exc}",
                )

        # Remove Python module and all sub-modules so the next import
        # gets a fresh copy (e.g. plugin_foo.utils must not be reused).
        module_name = f"plugin_{plugin_id.replace('-', '_')}"
        prefix = module_name + "."
        stale = [
            k for k in sys.modules if k == module_name or k.startswith(prefix)
        ]
        for k in stale:
            sys.modules.pop(k, None)

        # Clear all in-memory registry entries for this plugin
        self.registry.unregister_plugin(plugin_id)

        # Remove from the loaded-plugins dict
        del self._loaded_plugins[plugin_id]

        # Remove tools that this plugin registered in agents.tools
        self._cleanup_plugin_tools(plugin_id, record)

        # Optionally delete files from disk
        if delete_files:
            source_path = record.source_path
            if source_path.exists():
                shutil.rmtree(source_path)
                logger.info(
                    f"Deleted plugin files at {source_path}",
                )

        logger.info(f"Unloaded plugin '{plugin_id}'")

    def _cleanup_plugin_tools(
        self,
        plugin_id: str,
        record: PluginRecord,
    ) -> None:
        """Remove plugin tools from ``qwenpaw.agents.tools``.

        Uses ``sys.modules`` directly to avoid the parent-package
        attribute cache that would bypass any test/runtime overrides.

        Args:
            plugin_id: Plugin identifier (for logging)
            record: PluginRecord whose tools should be removed
        """
        try:
            tools_module = sys.modules.get("qwenpaw.agents.tools")
            if tools_module is None:
                return

            meta: Dict = record.manifest.meta or {}
            tool_names: List[str] = []

            # Legacy single-tool format: meta.tool_name
            old_name = meta.get("tool_name")
            if old_name and isinstance(old_name, str):
                tool_names.append(old_name)

            # Multi-tool format: meta.tools[].name
            for tool in meta.get("tools", []):
                if isinstance(tool, dict) and tool.get("name"):
                    tool_names.append(tool["name"])

            for tool_name in tool_names:
                if hasattr(tools_module, tool_name):
                    delattr(tools_module, tool_name)
                if tool_name in tools_module.__all__:
                    tools_module.__all__.remove(tool_name)

            if tool_names:
                logger.info(
                    f"Removed tools {tool_names} from agents.tools "
                    f"for plugin '{plugin_id}'",
                )
        except Exception as exc:
            logger.warning(
                f"Failed to clean up tools for plugin '{plugin_id}': "
                f"{exc}",
            )

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
