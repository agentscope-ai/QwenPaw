# -*- coding: utf-8 -*-
"""Plugin loader for discovering and loading plugins."""

import asyncio
import importlib.util
import inspect
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version
from packaging.requirements import Requirement

from .architecture import PluginManifest, PluginRecord
from .api import PluginApi
from .registry import PluginRegistry

logger = logging.getLogger(__name__)

# Distribution name -> import name, for the common cases where they differ.
_IMPORT_NAME_OVERRIDES = {
    "pillow": "PIL",
    "pyyaml": "yaml",
    "beautifulsoup4": "bs4",
    "python-dateutil": "dateutil",
    "opencv-python": "cv2",
    "scikit-learn": "sklearn",
    "protobuf": "google.protobuf",
}


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _desktop_python() -> Optional[str]:
    """Bundled standalone CPython used to install plugin deps in the frozen
    desktop build. Its absolute path is injected by the Tauri shell."""
    path = os.environ.get("QWENPAW_DESKTOP_PY_RUNTIME", "").strip()
    return path if path and Path(path).is_file() else None


def _plugin_runtime_dir() -> Path:
    """Root dir holding plugin runtime data (installed deps, locks)."""
    from ..constant import WORKING_DIR

    return Path(WORKING_DIR) / "plugin_runtime"


def _plugin_site_dir() -> Path:
    """User-writable, ABI-bucketed directory holding installed plugin deps."""
    bucket = (
        f"py{sys.version_info.major}.{sys.version_info.minor}"
        f"-{platform.system().lower()}-{platform.machine().lower()}"
    )
    site_dir = _plugin_runtime_dir() / bucket / "site"
    site_dir.mkdir(parents=True, exist_ok=True)
    return site_dir


def _install_lock_path(plugin_id: str) -> Path:
    """Path to the inter-process lock guarding *plugin_id* installs.

    Keyed per plugin so unrelated plugins can install concurrently, but
    every process installing the *same* plugin serialises through one lock.
    """
    safe_id = "".join(
        c if c.isalnum() or c in "-_." else "_" for c in plugin_id
    )
    return _plugin_runtime_dir() / "install-locks" / f"{safe_id}.lock"


def _is_disabled_plugin_dir(path: Path) -> bool:
    """Return whether *path* is a hidden or explicitly disabled plugin dir.

    A plugin is "disabled" by renaming its directory with a ``.disabled``
    suffix (e.g. ``remote-ssh.disabled``); hidden dirs (``.git`` etc.) are
    never plugins. Both are skipped during discovery so a disabled plugin no
    longer loads or installs its dependencies (issue #5550).
    """
    name = path.name
    return name.startswith(".") or name.endswith(".disabled")


def _ensure_plugin_site_on_path() -> None:
    """Put the plugin-deps site dir on ``sys.path`` (idempotent).

    Only relevant for the frozen desktop build, where plugin dependencies are
    installed into a user-writable target dir; in normal installs they go into
    the active environment, so this is a no-op.
    """
    if not _is_frozen():
        return
    try:
        site_dir = str(_plugin_site_dir())
    except Exception:
        return
    # Expose the dir so plugins that spawn the bundled Python (e.g. the pet
    # desktop window) can put their installed deps on the child's PYTHONPATH.
    os.environ["QWENPAW_PLUGIN_SITE"] = site_dir
    if site_dir in sys.path:
        return
    import site as _site

    _site.addsitedir(site_dir)
    if site_dir not in sys.path:
        sys.path.insert(0, site_dir)
    importlib.invalidate_caches()


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

                if _is_disabled_plugin_dir(item):
                    logger.info(
                        "Skipping disabled/hidden plugin directory: %s",
                        item.name,
                    )
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
                        f"Failed to load manifest from {item}: {e}",
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

    @staticmethod
    def _check_version_compatibility(
        manifest: "PluginManifest",
    ) -> tuple:
        """Check plugin compatibility with current QwenPaw version.

        Uses left-closed, right-open semantics: ``>=min, <max``.
        When ``qwenpaw_version`` is absent, falls back to legacy
        ``min_version`` / ``max_version`` top-level fields.

        Returns:
            (compatible, message) tuple.
        """
        from .._version_compat import check_plugin_version_compat

        return check_plugin_version_compat(manifest)

    @staticmethod
    def _is_requirement_satisfied(req: Requirement) -> bool:
        """Return True if *req* is already available.

        Two complementary probes are combined so neither environment causes a
        spurious reinstall on every launch:

        * ``importlib.metadata`` — authoritative for deps installed via
          ``pip install --target`` (they keep a proper ``.dist-info``) and the
          only way to honour version specifiers. It is keyed by *distribution*
          name, so import-name/dist-name mismatches (``pillow`` -> ``PIL``)
          never cause false negatives.
        * ``find_spec`` import probe — covers deps already bundled into the
          frozen desktop build, whose ``.dist-info`` is often stripped, so they
          are not misreported as missing (issue #5209).
        """
        # 1) Metadata probe: reliable for --target installs and version checks.
        try:
            installed = _dist_version(req.name)
        except PackageNotFoundError:
            installed = None
        if installed is not None:
            if not req.specifier:
                return True
            try:
                return req.specifier.contains(installed)
            except Exception:
                return True
        # 2) Import probe: frozen-bundled deps that lack ``.dist-info``.
        dist = req.name.lower().replace("_", "-")
        import_name = _IMPORT_NAME_OVERRIDES.get(
            dist,
            req.name.replace("-", "_"),
        )
        top = import_name.split(".")[0]
        try:
            return importlib.util.find_spec(top) is not None
        except (ImportError, ValueError):
            return False

    @staticmethod
    def _find_unsatisfied_dependencies(
        requirements_file: Path,
    ) -> List[str]:
        """Return requirement lines that are not importable / out of spec."""
        if not requirements_file.exists():
            return []

        missing: List[str] = []
        for line in requirements_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            try:
                req = Requirement(line)
            except Exception:
                continue
            if not PluginLoader._is_requirement_satisfied(req):
                missing.append(line)

        return missing

    async def _ensure_dependencies_installed(
        self,
        source_path: Path,
        plugin_id: str,
    ) -> None:
        """Check and install missing dependencies for a plugin.

        Inspects ``requirements.txt`` in the plugin directory; if any
        packages are missing or version-incompatible, installs them via
        pip/uv before the plugin module is imported.

        Args:
            source_path: Plugin directory containing requirements.txt
            plugin_id: Plugin identifier (for log messages)
        """
        # Previously installed plugin deps live in a user-writable site dir;
        # ensure it is importable before checking and before plugin import.
        _ensure_plugin_site_on_path()

        requirements_file = source_path / "requirements.txt"
        missing_deps = self._find_unsatisfied_dependencies(requirements_file)
        if not missing_deps:
            return
        logger.info(
            "Plugin '%s' has %d unsatisfied dependency(ies): %s. "
            "Installing...",
            plugin_id,
            len(missing_deps),
            ", ".join(missing_deps),
        )
        await asyncio.to_thread(
            self._install_requirements_locked,
            requirements_file,
            plugin_id,
        )

    def _install_requirements_locked(
        self,
        requirements_file: Path,
        plugin_id: str,
    ) -> None:
        """Install deps under a per-plugin inter-process lock (blocking).

        Multiple backend processes (e.g. an orphaned one plus a new launch,
        issue #5550) must not run ``pip install`` for the same plugin into
        the same target dir concurrently. The lock serialises them, and the
        double-check after acquiring it means only the first installer does
        the work — the rest see the dependencies already satisfied and skip,
        avoiding the reinstall storm that exhausted memory.
        """
        from .install_lock import plugin_install_lock

        with plugin_install_lock(_install_lock_path(plugin_id)):
            # Another process may have installed while we waited; re-probe
            # with fresh import caches before spending resources on pip.
            _ensure_plugin_site_on_path()
            importlib.invalidate_caches()
            if not self._find_unsatisfied_dependencies(requirements_file):
                logger.info(
                    "Plugin '%s' dependencies already satisfied by a "
                    "concurrent installer; skipping pip install",
                    plugin_id,
                )
                return
            self._install_requirements(requirements_file, plugin_id)

    def _validate_entry_points(
        self,
        plugin_id: str,
        backend_entry_file: Path | None,
        frontend_entry_file: Path | None,
    ) -> tuple[bool, bool]:
        """Validate plugin entry points exist.

        Returns:
            Tuple of (backend_exists, frontend_exists).

        Raises:
            FileNotFoundError: If no entry points declared or files missing.
        """
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
            missing = []
            if backend_entry_file:
                missing.append(str(backend_entry_file))
            if frontend_entry_file:
                missing.append(str(frontend_entry_file))
            raise FileNotFoundError(
                f"Plugin '{plugin_id}' entry point files not found: "
                + ", ".join(missing),
            )

        return backend_exists, frontend_exists

    async def _load_backend_module(
        self,
        plugin_id: str,
        backend_entry_file: Path,
        source_path: Path,
        config: Optional[Dict],
        manifest: "PluginManifest",
    ) -> Any:
        """Dynamically load and register backend plugin module.

        Returns:
            Plugin definition object.

        Raises:
            ImportError: If module spec cannot be created.
            AttributeError: If plugin doesn't export required objects.
        """
        module_name = f"plugin_{plugin_id.replace('-', '_')}"
        plugin_dir_str = str(source_path)

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

        try:
            sys.modules[module_name] = module
            module.__package__ = module_name
            module.__path__ = [plugin_dir_str]
            spec.loader.exec_module(module)

            plugin_def = getattr(module, "plugin", None)
            if plugin_def is None:
                # PawApp ('app'-type) modules export a PawApp instance named
                # 'app' that implements the same register(api) contract.
                plugin_def = getattr(module, "app", None)
            if plugin_def is None:
                raise AttributeError(
                    "Plugin module must export a 'plugin' object "
                    "(or a PawApp 'app' instance)",
                )

            if manifest.qwenpaw_version is not None:
                qv_dict = manifest.qwenpaw_version.model_dump()
            else:
                qv_dict = {
                    "min": manifest.min_version,
                    "max": manifest.max_version,
                }
            manifest_dict = {
                "id": manifest.id,
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description,
                "author": manifest.author,
                "dependencies": manifest.dependencies,
                "qwenpaw_version": qv_dict,
                "meta": manifest.meta,
            }
            api = PluginApi(plugin_id, config or {}, manifest_dict)
            api.set_registry(self.registry)
            self.registry.register_plugin_manifest(plugin_id, manifest_dict)

            if hasattr(plugin_def, "register"):
                result = plugin_def.register(api)
                if inspect.iscoroutine(result) or inspect.isawaitable(result):
                    await result
            else:
                raise AttributeError(
                    "Plugin must implement 'register(api)' method",
                )
        except Exception:
            self._cleanup_failed_load(
                plugin_id,
                module_name,
                source_path,
            )
            raise

        return plugin_def

    def _cleanup_failed_load(
        self,
        plugin_id: str,
        module_name: str,
        source_path: Path,
    ) -> None:
        """Roll back side effects after a failed plugin load.

        Mirrors the cleanup logic in ``unload_plugin`` (registry,
        ``sys.modules``, ``sys.path``) so that a failed load leaves no
        orphan state that could interfere with other plugins or a
        subsequent retry.

        .. note::
            NOT thread-safe.  ``sys.modules`` and ``sys.path`` mutations
            are not guarded by a lock.  This is fine because
            ``load_all_plugins`` loads plugins sequentially, but callers
            must not invoke this method concurrently.
        """
        logger.warning(
            "Cleaning up failed plugin load for '%s'",
            plugin_id,
        )

        # 1. Registry (manifest, providers, hooks, middleware, routes, …)
        self.registry.unregister_plugin(plugin_id)

        # 2. sys.modules — by module-name prefix
        prefix = module_name + "."
        stale = [
            k for k in sys.modules if k == module_name or k.startswith(prefix)
        ]
        for k in stale:
            sys.modules.pop(k, None)

        # 3. sys.modules — by __file__ path (catches bare imports that
        #    bypassed the plugin_<id> namespace, e.g. ``import utils``
        #    after the plugin inserted its dir into sys.path).
        source_resolved = os.path.realpath(str(source_path)) + os.sep
        stale_by_file = [
            k
            for k, mod in list(sys.modules.items())
            if (mod_file := getattr(mod, "__file__", None)) is not None
            and os.path.realpath(mod_file).startswith(source_resolved)
        ]
        for k in stale_by_file:
            sys.modules.pop(k, None)

        # 4. sys.path — remove the plugin directory if it was added
        plugin_dir_real = os.path.realpath(str(source_path))
        sys.path[:] = [
            p for p in sys.path if os.path.realpath(p) != plugin_dir_real
        ]

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

        compatible, compat_msg = self._check_version_compatibility(manifest)
        if not compatible:
            logger.warning(
                "Plugin '%s' is incompatible: %s",
                plugin_id,
                compat_msg,
            )
            record = PluginRecord(
                manifest=manifest,
                source_path=source_path,
                enabled=False,
                diagnostics=[compat_msg],
            )
            self._loaded_plugins[plugin_id] = record
            return record

        # Ensure plugin dependencies are installed before loading
        await self._ensure_dependencies_installed(source_path, plugin_id)

        backend_entry = manifest.entry.backend
        frontend_entry = manifest.entry.frontend
        backend_entry_file = (
            source_path / backend_entry if backend_entry else None
        )
        frontend_entry_file = (
            source_path / frontend_entry if frontend_entry else None
        )

        backend_exists, _ = self._validate_entry_points(
            plugin_id,
            backend_entry_file,
            frontend_entry_file,
        )

        plugin_def = None
        if not backend_exists:
            logger.info(
                "Plugin '%s' has no backend entry point "
                "— loading as frontend-only plugin",
                plugin_id,
            )
        else:
            assert backend_entry_file is not None
            try:
                plugin_def = await self._load_backend_module(
                    plugin_id,
                    backend_entry_file,
                    source_path,
                    config,
                    manifest,
                )
            except Exception as e:
                logger.error(
                    f"Failed to load plugin '{plugin_id}': {e}",
                    exc_info=True,
                )
                raise

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
        types: Optional[List[str]] = None,
    ) -> Dict[str, PluginRecord]:
        """Discover and load all plugins.

        Args:
            configs: Optional dictionary of plugin_id -> config
            types: Optional list of plugin types to load (e.g.
                ``["channel"]``).  When ``None``, all types are loaded.
                Plugins already loaded are always skipped (see
                :meth:`load_plugin`), so calling this twice — first
                with ``types`` then without — is safe.

        Returns:
            Dictionary of plugin_id -> PluginRecord
        """
        discovered = self.discover_plugins()

        for manifest, plugin_dir in discovered:
            if types is not None and manifest.plugin_type not in types:
                continue
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

    @staticmethod
    def _run_subprocess_with_streaming_log(
        cmd: list[str],
        *,
        timeout: int,
        plugin_id: str,
    ) -> subprocess.CompletedProcess:
        """Run *cmd*; stream stdout/stderr to debug logs in real time."""
        logger.debug(
            "Running install command for plugin '%s': %s",
            plugin_id,
            " ".join(cmd),
        )
        output_lines: List[str] = []
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        ) as proc:

            def _read_output() -> None:
                assert proc.stdout is not None
                for line in proc.stdout:
                    stripped = line.rstrip("\n\r")
                    if stripped:
                        output_lines.append(stripped)
                        logger.debug("[%s] %s", plugin_id, stripped)

            reader = threading.Thread(target=_read_output, daemon=True)
            reader.start()
            try:
                returncode = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                reader.join(timeout=2)
                raise
            reader.join(timeout=2)

        combined = "\n".join(output_lines)
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=returncode,
            stdout=combined,
            stderr="",
        )

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

        # In a frozen desktop build ``sys.executable`` is the backend binary,
        # not a Python interpreter; install via the bundled runtime instead.
        if _is_frozen():
            self._install_requirements_frozen(req, plugin_id, timeout)
            return

        # ── Attempt 1: python -m pip ──────────────────────────────────
        try:
            result = self._run_subprocess_with_streaming_log(
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
                timeout=timeout,
                plugin_id=plugin_id,
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
            uv_result = self._run_subprocess_with_streaming_log(
                [
                    uv,
                    "pip",
                    "install",
                    "--python",
                    sys.executable,
                    "-r",
                    req,
                ],
                timeout=timeout,
                plugin_id=plugin_id,
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

    def _install_requirements_frozen(
        self,
        req: str,
        plugin_id: str,
        timeout: int,
    ) -> None:
        """Install plugin deps in the frozen desktop build.

        Uses the bundled standalone CPython (same ``X.Y``/arch as the frozen
        runtime) to ``pip install --target`` into a user-writable, ABI-bucketed
        directory. Never runs ``sys.executable`` — that is the frozen backend
        binary, and invoking it re-launches the backend and crash-loops the
        desktop app (issue #5209).
        """
        python = _desktop_python()
        if python is None:
            raise RuntimeError(
                f"Cannot install dependencies for plugin '{plugin_id}': the "
                "bundled Python runtime is unavailable "
                "(QWENPAW_DESKTOP_PY_RUNTIME not set). Reinstall QwenPaw "
                "Desktop, or install the plugin's dependencies manually.",
            )
        target = str(_plugin_site_dir())
        try:
            result = self._run_subprocess_with_streaming_log(
                [
                    python,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-input",
                    "--target",
                    target,
                    "-r",
                    req,
                ],
                timeout=timeout,
                plugin_id=plugin_id,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Dependency installation timed out for '{plugin_id}' "
                f"(300 s limit exceeded)",
            ) from exc

        if result.returncode != 0:
            raise RuntimeError(
                f"Dependency installation failed for '{plugin_id}': "
                f"{result.stdout}",
            )
        importlib.invalidate_caches()
        logger.info(
            "Dependencies installed for plugin '%s' into %s",
            plugin_id,
            target,
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
                self._install_requirements_locked,
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

        # Execute uninstall hooks (only run on explicit unload/remove)
        uninstall_hooks = [
            h
            for h in self.registry.get_uninstall_hooks()
            if h.plugin_id == plugin_id
        ]
        for hook in uninstall_hooks:
            try:
                result = hook.callback(
                    plugin_id=plugin_id,
                    delete_files=delete_files,
                )
                if inspect.iscoroutine(result) or inspect.isawaitable(
                    result,
                ):
                    await result
            except Exception as exc:
                logger.error(
                    f"Error in uninstall hook '{hook.hook_name}' "
                    f"for plugin '{plugin_id}': {exc}",
                    exc_info=True,
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

        # Plugins that manipulate ``sys.path`` (e.g. inserting their own
        # directory) and use bare ``from sibling import …`` load sibling
        # modules as top-level entries in ``sys.modules`` — the prefix
        # cleanup above misses them.  Sweep any module whose ``__file__``
        # lives inside the plugin directory so a reinstall always gets
        # fresh code.
        source_resolved = str(record.source_path.resolve()) + os.sep
        stale_by_file = [
            k
            for k, mod in list(sys.modules.items())
            if (mod_file := getattr(mod, "__file__", None)) is not None
            and os.path.realpath(mod_file).startswith(source_resolved)
        ]
        for k in stale_by_file:
            sys.modules.pop(k, None)

        # Remove the plugin directory from sys.path (plugins add it at
        # import time for sibling imports; leaving it leaks into later
        # imports and prevents clean hot-reload).  Compare by realpath
        # so symlinks or non-resolved spellings of the same directory
        # are also caught.
        plugin_dir_real = os.path.realpath(record.source_path)
        sys.path[:] = [
            p for p in sys.path if os.path.realpath(p) != plugin_dir_real
        ]

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
