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
import tempfile
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from packaging.requirements import Requirement

from .architecture import PluginManifest, PluginRecord
from .api import PluginApi
from .dependency_gate import (
    DependencyGate,
    GateDecision,
    is_requirement_satisfied,
)
from .lifecycle import (
    PluginLifecycle,
    PluginState,
    ReloadReport,
    UnloadMode,
    UnloadReport,
    await_with_budget,
    REGISTER_WALL_CLOCK_SECONDS,
)
from .module_isolation import (
    build_plugin_builtins,
    compile_plugin_import_closure,
    get_namespace_finder,
    probe_plugin_source,
    restore_plugin_import_state,
    snapshot_plugin_import_state,
    strip_plugin_sys_path,
    sweep_bare_tree_modules,
    unregister_namespace,
)
from .safe_fs import safe_remove, same_location
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
_PAWPORT_MARKER = ".qwenpaw-pawport.json"


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


def _backend_entry_file(
    source_path: Path,
    manifest: PluginManifest,
) -> Path | None:
    backend = getattr(manifest.entry, "backend", None)
    if not backend:
        return None
    return source_path / backend


async def _probe_incoming(
    plugin_id: str,
    source_path: Path,
    entry_file: Path | None,
) -> ReloadReport | None:
    """Return a failed report when probe import does not succeed."""
    if entry_file is None:
        return None
    try:
        from ..utils.io_utils import run_sync_io

        plugin_dir = str(source_path)
        entry_dir = str(entry_file.parent)
        search_paths = [entry_dir]
        if _norm_realpath(entry_dir) != _norm_realpath(plugin_dir):
            search_paths.append(plugin_dir)
        await run_sync_io(
            compile_plugin_import_closure,
            entry_file,
            search_paths,
        )
        probe_plugin_source(
            plugin_id,
            source_path,
            entry_file,
            compiled=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Probe import failed for plugin '%s': %s",
            plugin_id,
            exc,
            exc_info=True,
        )
        return ReloadReport(
            plugin_id=plugin_id,
            ok=False,
            unchanged=True,
            errors=[f"probe failed: {exc}"],
        )
    return None


def _remove_dir(path: Path | None) -> None:
    if path is None:
        return
    raw = str(path).strip()
    if not raw:
        return
    safe_remove(path, purpose="remove plugin directory")


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


def _norm_realpath(path: Any) -> str:
    """``realpath`` + ``normcase`` for cross-platform path identity.

    Windows filesystems are typically case-insensitive; without
    ``normcase``, hot-reload cleanup can miss modules / ``sys.path``
    entries that differ only by drive/directory letter case.
    """
    return os.path.normcase(os.path.realpath(str(path)))


def resolved_plugin_manifest_path(source_dir: Path) -> Path:
    """Return the resolved ``plugin.json`` path under *source_dir*.

    Joins only the fixed basename ``plugin.json``, then normalizes with
    ``realpath`` and rejects any result that escapes *source_dir*
    (``os.path.commonpath`` guard — CodeQL path-injection sanitizer).

    Raises:
        FileNotFoundError: If the directory or manifest file is missing
        ValueError: If the resolved path escapes *source_dir*
    """
    try:
        root = os.path.realpath(str(source_dir))
    except OSError as exc:
        raise FileNotFoundError(
            f"plugin.json not found in {source_dir}",
        ) from exc
    if not os.path.isdir(root):
        raise FileNotFoundError(
            f"plugin.json not found in {source_dir}",
        )
    full = os.path.realpath(os.path.join(root, "plugin.json"))
    try:
        common = os.path.commonpath([root, full])
    except ValueError as exc:
        raise ValueError(
            f"plugin.json path escapes source directory ({source_dir})",
        ) from exc
    if common != root:
        raise ValueError(
            f"plugin.json path escapes source directory ({source_dir})",
        )
    if not os.path.isfile(full):
        raise FileNotFoundError(
            f"plugin.json not found in {source_dir}",
        )
    return Path(full)


def _is_disabled_plugin_dir(path: Path) -> bool:
    """Return whether *path* is a hidden or explicitly disabled plugin dir.

    A plugin is "disabled" by renaming its directory with a ``.disabled``
    suffix (e.g. ``remote-ssh.disabled``); hidden dirs (``.git`` etc.) are
    never plugins. Both are skipped during discovery so a disabled plugin no
    longer loads or installs its dependencies (issue #5550).
    """
    name = path.name
    if name.startswith(".") or name.endswith(".disabled"):
        return True
    try:
        marker = json.loads((path / _PAWPORT_MARKER).read_text())
    except (OSError, ValueError, TypeError):
        return False
    return marker.get("state") == "prepared"


def _marker_matches(marker: dict[str, Any], owner: dict[str, Any]) -> bool:
    return all(
        marker.get(key) == owner.get(key)
        for key in ("owner", "provider", "source_id")
    )


# Re-entrancy token for PluginLoader.plugin_lifecycle.
# Key is (loader_id, task_id, plugin_id) so:
# - nested calls on the *same* task can re-enter;
# - asyncio.create_task() children that inherit ContextVar cannot bypass;
# - different PluginLoader instances never share re-entrancy.
_LifecycleHoldKey = tuple[int, int, str]
_LIFECYCLE_HELD: ContextVar[Optional[_LifecycleHoldKey]] = ContextVar(
    "qwenpaw_plugin_lifecycle_held",
    default=None,
)


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
        self.lifecycle = PluginLifecycle(self)
        self._loaded_plugins: Dict[str, PluginRecord] = {}
        # In-process per-plugin serialization for load/unload/reinstall.
        # Distinct from the inter-process install-deps file lock.
        self._lifecycle_locks: Dict[str, asyncio.Lock] = {}
        self._lifecycle_locks_mu = threading.Lock()

    def _lifecycle_lock_for(self, plugin_id: str) -> asyncio.Lock:
        """Return the asyncio lock that serializes *plugin_id* lifecycle."""
        with self._lifecycle_locks_mu:
            lock = self._lifecycle_locks.get(plugin_id)
            if lock is None:
                lock = asyncio.Lock()
                self._lifecycle_locks[plugin_id] = lock
            return lock

    def _lifecycle_hold_key(
        self,
        plugin_id: str,
    ) -> Optional[_LifecycleHoldKey]:
        """Return re-entrancy key for this loader + current task + plugin."""
        task = asyncio.current_task()
        if task is None:
            return None
        return (id(self), id(task), plugin_id)

    @asynccontextmanager
    async def plugin_lifecycle(
        self,
        plugin_id: str,
    ) -> AsyncIterator[None]:
        """Serialize load/unload/reinstall for one *plugin_id*.

        Re-entrant only when the *same* ``PluginLoader`` instance, the
        *same* ``asyncio`` task, and the *same* ``plugin_id`` already
        hold the section — so nested ``load_plugin_from_path`` →
        ``load_plugin`` works, but ``asyncio.create_task`` children that
        inherit ContextVar cannot bypass the lock.
        Unrelated plugin IDs may proceed concurrently.
        """
        if not plugin_id:
            yield
            return
        hold_key = self._lifecycle_hold_key(plugin_id)
        if hold_key is not None and _LIFECYCLE_HELD.get() == hold_key:
            yield
            return
        lock = self._lifecycle_lock_for(plugin_id)
        async with lock:
            if hold_key is None:
                yield
                return
            token = _LIFECYCLE_HELD.set(hold_key)
            try:
                yield
            finally:
                _LIFECYCLE_HELD.reset(token)

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
        """Return True if *req* is already available or not applicable."""
        return is_requirement_satisfied(req)

    @staticmethod
    def _find_unsatisfied_dependencies(
        requirements_file: Path,
    ) -> List[str]:
        """Return requirement lines that are not importable / out of spec."""
        decision = DependencyGate().evaluate(
            requirements_file,
            allow_install=False,
            plugin_id="recheck",
        )
        return list(decision.missing)

    async def _ensure_dependencies_installed(
        self,
        source_path: Path,
        plugin_id: str,
        *,
        allow_install: bool = False,
    ) -> GateDecision:
        """Run the dependency gate, optionally installing packages.

        Boot paths pass ``allow_install=False`` (check only). User-facing
        install / update / repair pass ``True`` so the gate may install.
        """
        _ensure_plugin_site_on_path()
        requirements_file = source_path / "requirements.txt"
        if not self.lifecycle.delegate.owns_dependency_env(plugin_id):
            return GateDecision(
                allow_install=False,
                already_satisfied=True,
                reason="dependency env not owned by this process",
            )
        decision = DependencyGate().evaluate(
            requirements_file,
            allow_install=allow_install,
            plugin_id=plugin_id,
        )
        if decision.unsupported:
            return decision
        if decision.already_satisfied or not decision.allow_install:
            return decision
        logger.info(
            "Plugin '%s' has %d unsatisfied dependency(ies): %s. "
            "Installing...",
            plugin_id,
            len(decision.missing),
            ", ".join(decision.missing),
        )
        from ..utils.io_utils import run_sync_io

        await run_sync_io(
            self._install_requirements_locked,
            requirements_file,
            plugin_id,
        )
        recheck = DependencyGate().evaluate(
            requirements_file,
            allow_install=False,
            plugin_id=plugin_id,
        )
        if recheck.already_satisfied:
            return recheck
        recheck.allow_install = False
        if not recheck.reason:
            recheck.reason = (
                f"Plugin '{plugin_id}' is still missing dependencies "
                f"after install: {', '.join(recheck.missing)}"
            )
        return recheck

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
        # Plugins with a nested entry (e.g. ``backend/main.py``) resolve
        # their bare imports against the entry file's directory, so it
        # must be searchable alongside the plugin root.  The entry
        # directory comes first: nested-entry plugins put it at
        # ``sys.path[0]``, so it must win over a same-named module in
        # the plugin root.
        entry_dir_str = str(backend_entry_file.parent)
        search_paths = [entry_dir_str]
        if _norm_realpath(entry_dir_str) != _norm_realpath(plugin_dir_str):
            search_paths.append(plugin_dir_str)

        spec = importlib.util.spec_from_file_location(
            module_name,
            backend_entry_file,
            submodule_search_locations=search_paths,
        )
        if spec is None or spec.loader is None:
            raise ImportError(
                f"Failed to load module spec for {backend_entry_file}",
            )

        modules_before = dict(sys.modules)
        module = importlib.util.module_from_spec(spec)

        # Redirect the plugin's bare absolute imports (``import utils``)
        # into its private ``plugin_<id>`` namespace so plugins cannot
        # collide with each other's top-level module names (#6683).
        plugin_builtins = build_plugin_builtins(
            module_name,
            search_paths,
            entry_file=backend_entry_file,
        )
        module.__dict__["__builtins__"] = plugin_builtins
        get_namespace_finder().register(module_name, plugin_builtins)

        skip_module_cleanup = False
        try:
            sys.modules[module_name] = module
            module.__package__ = module_name
            module.__path__ = search_paths
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
                "description_i18n": manifest.description_i18n,
                "author": manifest.author,
                "dependencies": manifest.dependencies,
                "qwenpaw_version": qv_dict,
                "meta": manifest.meta,
            }
            await self._invoke_plugin_register(
                plugin_id,
                plugin_def,
                config,
                manifest_dict,
            )
        except BaseException:
            instance = self.lifecycle.get_instance(plugin_id)
            if instance is not None and instance.state is PluginState.FAILED:
                skip_module_cleanup = True
                logger.warning(
                    "Skipping failed-load cleanup for '%s': "
                    "hosted resources did not go quiescent",
                    plugin_id,
                )
            else:
                if (
                    instance is not None
                    and instance.state is PluginState.DISPOSED
                ):
                    self.lifecycle.drop_instance(plugin_id)
                self._cleanup_failed_load(
                    plugin_id,
                    module_name,
                    source_path,
                )
            raise
        finally:
            # A loaded plugin no longer needs the sys.path entries it
            # inserted: its bare imports resolve through the private
            # namespace (search_paths), not sys.path.  Sweeping here —
            # on success, failure, AND BaseException (a cancelled
            # startup) — keeps other plugins' non-local fallthrough
            # imports from ever resolving into this plugin's source
            # tree (data-dir fallthrough, uncached stdlib names, or
            # plain bare imports would otherwise pick up the residue).
            # Shared dependency locations (plugin site dir) are
            # untouched — only paths under the plugin's own tree go.
            # Unquiescent failed register keeps modules and sys.path:
            # hosted threads may still import from this tree.
            if not skip_module_cleanup:
                strip_plugin_sys_path(source_path)
                sweep_bare_tree_modules(source_path, modules_before)

        return plugin_def

    async def _invoke_plugin_register(
        self,
        plugin_id: str,
        plugin_def: Any,
        config: Optional[Dict],
        manifest_dict: Dict[str, Any],
    ) -> None:
        """Bind the current instance and run ``plugin_def.register``."""
        from .settings import runtime_config

        api = PluginApi(plugin_id, runtime_config(config), manifest_dict)
        api.set_registry(self.registry)
        instance = self.lifecycle.ensure_instance(plugin_id)
        instance.refuse_unquiescent_reregister()
        api.bind_instance(instance)
        self.registry.register_plugin_manifest(plugin_id, manifest_dict)
        instance.record_runtime(
            "plugin_manifest",
            lambda: self.registry.drop_plugin_manifest(plugin_id),
            kind="manifest",
        )
        if not hasattr(plugin_def, "register"):
            raise AttributeError(
                "Plugin must implement 'register(api)' method",
            )
        try:
            result = plugin_def.register(api)
            await await_with_budget(
                result,
                seconds=REGISTER_WALL_CLOCK_SECONDS,
                what="register()",
                plugin_id=plugin_id,
            )
        except BaseException as exc:
            instance.mark_failed(str(exc) or type(exc).__name__)
            await self._dispose_then_undo_txn_disk(plugin_id, instance)
            raise

    async def _dispose_then_undo_txn_disk(
        self,
        plugin_id: str,
        instance,
        *,
        use_teardown: bool = False,
        undo_disk=None,
    ) -> None:
        """Dispose first; only then undo this-txn create/migrate."""
        if instance is None:
            return
        try:
            if use_teardown:
                report = await instance.teardown_runtime()
            else:
                report = await instance.dispose(UnloadMode.UNLOAD)
        except BaseException:
            instance.add_diagnostic("needs_restart")
            raise
        if not report.quiescent:
            instance.add_diagnostic("needs_restart")
            return
        try:
            if undo_disk is not None:
                maybe = undo_disk()
                if inspect.isawaitable(maybe):
                    await maybe
            else:
                await self._undo_failed_txn_disk(plugin_id, instance)
            instance.clear_txn_escapes()
            instance.clear_created_dests()
        except Exception as undo_exc:  # noqa: BLE001
            instance.add_diagnostic(
                str(undo_exc) or type(undo_exc).__name__,
            )

    async def _undo_failed_txn_disk(self, plugin_id: str, instance) -> None:
        """Undo this-txn create/migrate after a quiescent dispose."""
        from ..utils.io_utils import run_sync_io
        from .provision import (
            recover_migrating_inventory,
            undo_created_locations,
            undo_this_txn_escapes,
        )

        dests = instance.created_dests() if instance is not None else []
        escapes = instance.txn_escapes() if instance is not None else []

        def _undo() -> None:
            undo_this_txn_escapes(plugin_id, escapes)
            undo_created_locations(plugin_id, dests)
            recover_migrating_inventory(plugin_id)

        await run_sync_io(_undo)

    def _record_failed_backend(
        self,
        manifest: PluginManifest,
        source_path: Path,
        exc: BaseException,
    ) -> PluginRecord:
        """Persist a failed record so cancel is visible to reload/repair."""
        plugin_id = manifest.id
        live = self.lifecycle.ensure_instance(plugin_id)
        live.mark_failed(str(exc) or type(exc).__name__)
        live.source_path = source_path
        if isinstance(exc, asyncio.CancelledError):
            live.add_diagnostic("needs_restart")
        record = PluginRecord(
            manifest=manifest,
            source_path=source_path,
            enabled=False,
            diagnostics=list(live.diagnostics),
            status="failed",
        )
        self._loaded_plugins[plugin_id] = record
        return record

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

        # 3. Import redirection — after the sys.modules sweep, so a
        #    concurrent lazy import cannot resolve a plugin submodule
        #    without the plugin builtins in the window between the two.
        #    Bare (non-namespaced) residue is swept by the caller's
        #    finally, AFTER strip_plugin_sys_path — sweeping while the
        #    plugin's sys.path entries are still present could merge
        #    plugin-tree portions into a shared namespace package's
        #    __path__ recalculation and evict a host package.
        unregister_namespace(module_name)

        # 4. sys.path — remove the plugin directory and its subdirs
        strip_plugin_sys_path(source_path)

    async def load_plugin(
        self,
        manifest: PluginManifest,
        source_path: Path,
        config: Optional[Dict] = None,
        *,
        allow_install: bool = False,
        activate: bool = True,
    ) -> PluginRecord:
        """Load a single plugin.

        Args:
            manifest: Plugin manifest
            source_path: Path to plugin directory
            config: Optional plugin configuration
            activate: When True (default), project and start before
                reporting success. Boot two-phase load must pass False.

        Returns:
            PluginRecord instance

        Raises:
            FileNotFoundError: If entry point not found
            AttributeError: If plugin module doesn't export required objects
            Exception: If plugin registration fails
        """
        async with self.plugin_lifecycle(manifest.id):
            return await self._load_plugin_unlocked(
                manifest,
                source_path,
                config,
                allow_install=allow_install,
                activate=activate,
            )

    # pylint: disable=too-many-statements,too-many-return-statements
    # pylint: disable=too-many-branches
    async def _load_plugin_unlocked(
        self,
        manifest: PluginManifest,
        source_path: Path,
        config: Optional[Dict] = None,
        *,
        allow_install: bool = False,
        activate: bool = False,
        generation: int | None = None,
        saved_plugin_def: Any = None,
        allow_existing: bool = True,
    ) -> PluginRecord:
        """Load a plugin; caller must hold :meth:`plugin_lifecycle`."""
        plugin_id = manifest.id

        if plugin_id in self._loaded_plugins:
            if not allow_existing:
                raise RuntimeError(
                    f"Plugin '{plugin_id}' is still loaded; "
                    "refuse to restore over an existing record",
                )
            logger.warning(f"Plugin '{plugin_id}' already loaded")
            return self._loaded_plugins[plugin_id]

        instance = self.lifecycle.ensure_instance(
            plugin_id,
            generation=generation,
        )
        instance.source_path = source_path
        from .settings import runtime_config

        instance.config = runtime_config(config)

        compatible, compat_msg = self._check_version_compatibility(manifest)
        if not compatible:
            logger.warning(
                "Plugin '%s' is incompatible: %s",
                plugin_id,
                compat_msg,
            )
            instance.mark_failed(compat_msg)
            record = PluginRecord(
                manifest=manifest,
                source_path=source_path,
                enabled=False,
                diagnostics=list(instance.diagnostics),
                status="failed",
            )
            self._loaded_plugins[plugin_id] = record
            return record

        decision = await self._ensure_dependencies_installed(
            source_path,
            plugin_id,
            allow_install=allow_install,
        )
        if decision.require_restart:
            raise RuntimeError(decision.reason)
        if decision.unsupported or (
            decision.missing and not decision.allow_install
        ):
            instance.mark_failed(decision.reason)
            logger.error(
                "Plugin '%s' marked FAILED: %s",
                plugin_id,
                decision.reason,
            )
            record = PluginRecord(
                manifest=manifest,
                source_path=source_path,
                enabled=False,
                diagnostics=list(instance.diagnostics),
                status="failed",
            )
            self._loaded_plugins[plugin_id] = record
            return record

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

        plugin_def = saved_plugin_def
        if plugin_def is None and not backend_exists:
            logger.info(
                "Plugin '%s' has no backend entry point "
                "— loading as frontend-only plugin",
                plugin_id,
            )
        elif plugin_def is None:
            assert backend_entry_file is not None
            try:
                plugin_def = await self._load_backend_module(
                    plugin_id,
                    backend_entry_file,
                    source_path,
                    config,
                    manifest,
                )
            except BaseException as exc:
                record = self._record_failed_backend(
                    manifest,
                    source_path,
                    exc,
                )
                if isinstance(exc, asyncio.CancelledError):
                    raise
                logger.error(
                    f"Failed to load plugin '{plugin_id}': {exc}",
                    exc_info=True,
                )
                return record
        elif saved_plugin_def is not None:
            try:
                await self._reregister_body(
                    plugin_id,
                    saved_plugin_def,
                    config,
                    _manifest_as_dict(manifest),
                )
            except BaseException as exc:
                record = self._record_failed_backend(
                    manifest,
                    source_path,
                    exc,
                )
                if isinstance(exc, asyncio.CancelledError):
                    raise
                return record

        record = PluginRecord(
            manifest=manifest,
            source_path=source_path,
            enabled=True,
            instance=plugin_def,
            diagnostics=list(instance.diagnostics),
            status="registered",
        )
        self._loaded_plugins[plugin_id] = record
        if activate:
            try:
                await self.activate_plugin_unlocked(plugin_id)
            except BaseException as exc:
                if instance.activated or record.status == "active":
                    raise
                if isinstance(exc, asyncio.CancelledError):
                    raise
                instance.mark_failed(str(exc))
                record.status = "failed"
                record.enabled = False
                record.diagnostics = list(instance.diagnostics)
                return record
        logger.info(f"✓ Loaded plugin '{plugin_id}' successfully")
        return record

    async def load_all_plugins(
        self,
        configs: Optional[Dict[str, Dict]] = None,
        types: Optional[List[str]] = None,
        *,
        activate: bool = False,
    ) -> Dict[str, PluginRecord]:
        """Discover and load all plugins.

        Args:
            configs: Optional dictionary of plugin_id -> config
            types: Optional list of plugin types to load (e.g.
                ``["channel"]``).  When ``None``, all types are loaded.
                Plugins already loaded are always skipped (see
                :meth:`load_plugin`), so calling this twice — first
                with ``types`` then without — is safe.
            activate: Boot two-phase load keeps this False so register
                happens before workspace projection. Other callers that
                want a ready plugin should pass True or call
                :meth:`load_plugin` instead.

        Returns:
            Dictionary of plugin_id -> PluginRecord
        """
        from ..utils.io_utils import run_sync_io
        from .provision import recover_migrating_inventory
        from .updates import recover_interrupted_updates

        try:
            await run_sync_io(
                recover_interrupted_updates,
                self.lifecycle.delegate.owns_commit,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Interrupted update recovery failed; "
                "continuing plugin discovery",
            )
        try:
            await run_sync_io(
                recover_migrating_inventory,
                None,
                owns_commit=self.lifecycle.delegate.owns_commit,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Provision migration recovery failed; "
                "continuing plugin discovery",
            )

        discovered = self.discover_plugins()

        for manifest, plugin_dir in discovered:
            if types is not None and manifest.plugin_type not in types:
                continue
            from .settings import is_plugin_enabled, runtime_config

            config = configs.get(manifest.id) if configs else None
            if not is_plugin_enabled(config):
                logger.info(
                    "Skipping disabled plugin '%s'",
                    manifest.id,
                )
                continue

            try:
                await self.load_plugin(
                    manifest,
                    plugin_dir,
                    runtime_config(config),
                    activate=activate,
                )
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

    def read_source_manifest(
        self,
        source_path: Path,
    ) -> Tuple[Path, PluginManifest]:
        """Resolve and load ``plugin.json`` under *source_path* (sync I/O)."""
        manifest_path = resolved_plugin_manifest_path(source_path)
        return manifest_path, self._load_manifest(manifest_path)

    def _read_source_manifest(
        self,
        source_path: Path,
    ) -> Tuple[Path, PluginManifest]:
        """Resolve and load ``plugin.json`` under *source_path* (sync I/O)."""
        return self.read_source_manifest(source_path)

    async def reload_plugin_unlocked(
        self,
        plugin_id: str,
        *,
        new_source: Optional[Path] = None,
        config: Optional[Dict] = None,
        allow_install: bool = False,
        owns_dependency_env: bool = True,
        after_unload: Optional[Any] = None,
    ) -> ReloadReport:
        """Reload one plugin. Caller must hold the lifecycle lock."""
        # pylint: disable=too-many-return-statements,too-many-branches
        if not self.lifecycle.delegate.owns_commit(plugin_id):
            return ReloadReport(
                plugin_id=plugin_id,
                ok=False,
                unchanged=True,
                errors=["commit is not owned by this process"],
            )
        record = self._loaded_plugins.get(plugin_id)
        if record is None:
            return ReloadReport(
                plugin_id=plugin_id,
                ok=False,
                errors=[f"Plugin '{plugin_id}' is not loaded"],
            )
        old_path = Path(record.source_path)
        old_config = dict(
            getattr(self.lifecycle.get_instance(plugin_id), "config", {})
            or {},
        )
        old_generation = 0
        inst = self.lifecycle.get_instance(plugin_id)
        if inst is not None:
            old_generation = inst.generation
        old_plugin_def = record.instance
        incoming = Path(new_source).resolve() if new_source else old_path
        in_place = same_location(incoming, old_path)
        incoming_manifest = record.manifest
        if not in_place:
            _, incoming_manifest = await asyncio.to_thread(
                self._read_source_manifest,
                incoming,
            )
        if owns_dependency_env:
            decision = await self._ensure_dependencies_installed(
                incoming,
                plugin_id,
                allow_install=allow_install,
            )
            if decision.require_restart or decision.unsupported:
                return ReloadReport(
                    plugin_id=plugin_id,
                    ok=False,
                    unchanged=True,
                    errors=[decision.reason],
                )
            if decision.missing and not decision.allow_install:
                return ReloadReport(
                    plugin_id=plugin_id,
                    ok=False,
                    unchanged=True,
                    errors=[decision.reason],
                )
        entry = _backend_entry_file(incoming, incoming_manifest)
        failed = await _probe_incoming(
            plugin_id,
            incoming,
            entry,
        )
        if failed is not None:
            return failed
        snapshot = snapshot_plugin_import_state(plugin_id, old_path)
        swapped: Path | None = None
        activated_new = False
        cleanup_errors: list[str] = []
        try:
            unload_report = await self._unload_plugin_unlocked(
                plugin_id,
                delete_files=False,
                mode=UnloadMode.UNLOAD,
            )
            if not unload_report.quiescent:
                return ReloadReport(
                    plugin_id=plugin_id,
                    ok=False,
                    needs_restart=True,
                    errors=list(unload_report.errors)
                    or ["hosted resources did not go quiescent"],
                    generation=old_generation,
                )
            await _invoke_after_unload(after_unload, plugin_id)
            swapped = await self._swap_plugin_dir(
                plugin_id,
                old_path,
                incoming,
            )
            target = old_path if swapped or in_place else incoming
            _, installed_manifest = await asyncio.to_thread(
                self._read_source_manifest,
                target,
            )
            new_record = await self._load_plugin_unlocked(
                installed_manifest,
                target,
                config if config is not None else old_config,
                allow_install=allow_install,
                activate=True,
                generation=old_generation + 1,
            )
            if new_record.status == "failed":
                raise RuntimeError(
                    new_record.diagnostics[0]
                    if new_record.diagnostics
                    else f"Plugin '{plugin_id}' failed to load",
                )
            activated_new = True
            cleanup_errors = await self._finish_committed_reload(
                plugin_id,
                swapped,
            )
            live = self.lifecycle.get_instance(plugin_id)
            if live is not None:
                for item in live.diagnostics:
                    if (
                        item.startswith("post-commit cleanup:")
                        and item not in cleanup_errors
                    ):
                        cleanup_errors.append(item)
        except BaseException as exc:
            occupied = "restart required" in str(exc)
            committed = self._reload_already_committed(
                plugin_id,
                activated_new,
            )
            restore: ReloadReport | None = None
            if not committed and (not occupied or old_path.exists()):
                restore = await self._rollback_reload(
                    plugin_id,
                    old_path,
                    old_config,
                    snapshot,
                    swapped,
                    incoming_manifest=record.manifest,
                    in_place=in_place,
                    saved_plugin_def=old_plugin_def,
                    generation=old_generation,
                )
            if committed:
                await self._finish_committed_reload(plugin_id, swapped)
            if isinstance(exc, asyncio.CancelledError):
                raise
            if committed:
                return ReloadReport(
                    plugin_id=plugin_id,
                    ok=True,
                    needs_restart=True,
                    errors=[str(exc)],
                    generation=old_generation + 1,
                )
            errors = [str(exc)]
            needs_restart = occupied
            if restore is not None:
                errors.extend(restore.errors)
                needs_restart = needs_restart or (
                    restore.needs_restart or not restore.ok
                )
            return ReloadReport(
                plugin_id=plugin_id,
                ok=False,
                needs_restart=needs_restart,
                errors=errors,
                generation=old_generation,
            )
        return ReloadReport(
            plugin_id=plugin_id,
            ok=True,
            needs_restart=bool(cleanup_errors),
            errors=cleanup_errors,
            generation=old_generation + 1,
        )

    def _reload_already_committed(
        self,
        plugin_id: str,
        activated_new: bool,
    ) -> bool:
        """Whether the new version is already the committed service."""
        if activated_new:
            return True
        instance = self.lifecycle.get_instance(plugin_id)
        if instance is not None and instance.activated:
            return True
        current = self._loaded_plugins.get(plugin_id)
        if current is not None and current.status == "active":
            return True
        from .updates import STATUS_COMMITTED, update_marker_status

        return update_marker_status(plugin_id) == STATUS_COMMITTED

    async def _finish_committed_reload(
        self,
        plugin_id: str,
        swapped: Path | None,
    ) -> list[str]:
        """Persist committed and drop leftovers. Never rolls back.

        Prepared provision rows must be finished before the update
        marker is unlinked. Otherwise boot recovery treats leftover
        ``migrating=prepared`` as uncommitted and restores old dests.
        """
        from ..utils.io_utils import run_sync_io
        from .provision import commit_prepared_migrations
        from .updates import clear_updating_marker, mark_update_committed

        errors: list[str] = []
        try:
            await run_sync_io(mark_update_committed, plugin_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"mark committed failed: {exc}")
        try:
            await run_sync_io(commit_prepared_migrations, plugin_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"commit prepared migrations failed: {exc}")
            return errors
        if swapped is not None:
            try:
                await run_sync_io(_remove_dir, swapped)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"committed backup cleanup failed: {exc}")
        try:
            await run_sync_io(clear_updating_marker, plugin_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"committed marker cleanup failed: {exc}")
        return errors

    async def _recover_or_refuse_prepared_update(
        self,
        plugin_id: str,
    ) -> None:
        """Restore a live prepared backup, or refuse a new directory swap."""
        from ..utils.io_utils import run_sync_io
        from .updates import live_prepared_backup, recover_one_update

        if live_prepared_backup(plugin_id) is None:
            return
        try:
            await run_sync_io(recover_one_update, plugin_id)
        except (OSError, shutil.Error) as exc:
            raise RuntimeError(
                f"plugin directory is in use; restart required: {exc}",
            ) from exc
        if live_prepared_backup(plugin_id) is not None:
            raise RuntimeError(
                "plugin directory is in use; restart required",
            )

    async def _swap_plugin_dir(
        self,
        plugin_id: str,
        old_path: Path,
        incoming: Path,
    ) -> Path | None:
        """Stage on the same volume, then short-swap. None if in-place."""
        if not self.lifecycle.delegate.owns_commit(plugin_id):
            return None
        if same_location(incoming, old_path):
            return None
        from ..utils.io_utils import run_sync_io
        from .updates import allocate_update_backup_path, write_updating_marker

        await self._recover_or_refuse_prepared_update(plugin_id)
        backup = allocate_update_backup_path(old_path, plugin_id)
        staging = old_path.with_name(old_path.name + f".{plugin_id}.staging")

        def _swap() -> None:
            if staging.exists():
                safe_remove(staging, purpose="clear plugin staging")
            shutil.copytree(incoming, staging)
            if not (staging / "plugin.json").exists():
                raise RuntimeError("staged plugin is missing plugin.json")
            if backup.exists():
                raise RuntimeError(
                    f"refusing to clobber existing plugin backup: {backup}",
                )
            shutil.move(str(old_path), str(backup))
            shutil.move(str(staging), str(old_path))

        write_updating_marker(
            plugin_id,
            backup_path=backup,
            target_path=old_path,
            staging_path=staging,
        )
        try:
            await run_sync_io(_swap)
        except PermissionError as exc:
            await self._restore_failed_swap(
                plugin_id,
                old_path,
                backup,
                staging,
                clear_marker_if_restored=False,
            )
            raise RuntimeError(
                f"plugin directory is in use; restart required: {exc}",
            ) from exc
        except Exception:
            await self._restore_failed_swap(
                plugin_id,
                old_path,
                backup,
                staging,
                clear_marker_if_restored=True,
            )
            raise
        return backup

    async def _restore_failed_swap(
        self,
        plugin_id: str,
        old_path: Path,
        backup: Path,
        staging: Path,
        *,
        clear_marker_if_restored: bool,
    ) -> None:
        """Put the previous directory back after a failed short-swap."""
        from ..utils.io_utils import run_sync_io
        from .updates import clear_updating_marker

        def _restore() -> None:
            if staging.exists():
                safe_remove(staging, purpose="remove failed staging")
            if backup.exists():
                if old_path.exists():
                    safe_remove(
                        old_path,
                        purpose="remove partial swap target",
                    )
                shutil.move(str(backup), str(old_path))

        try:
            await run_sync_io(_restore)
        except PermissionError:
            logger.exception(
                "Could not restore plugin '%s' after a failed swap",
                plugin_id,
            )
            return
        if clear_marker_if_restored and old_path.exists():
            await run_sync_io(clear_updating_marker, plugin_id)
            if backup.exists():
                await run_sync_io(_remove_dir, backup)

    async def _rollback_reload(
        self,
        plugin_id: str,
        old_path: Path,
        old_config: Dict,
        snapshot: dict,
        backup: Path | None,
        *,
        incoming_manifest: PluginManifest,
        in_place: bool = False,
        saved_plugin_def: Any = None,
        generation: int = 0,
    ) -> ReloadReport:
        """Restore the previous service after a failed reload.

        Unquiescent leftover handles abort restore. The updating marker
        stays until the old version is active again.
        """
        from ..utils.io_utils import run_sync_io
        from .provision import recover_migrating_inventory
        from .updates import clear_updating_marker

        failed = ReloadReport(
            plugin_id=plugin_id,
            ok=False,
            needs_restart=True,
            generation=generation,
        )
        leftover = self.lifecycle.get_instance(plugin_id)
        if (
            plugin_id not in self._loaded_plugins
            and leftover is not None
            and leftover.state is PluginState.FAILED
        ):
            failed.errors.append(
                "unquiescent instance remains; refuse to restore directories",
            )
            return failed
        if plugin_id in self._loaded_plugins:
            try:
                unload_report = await self._unload_plugin_unlocked(
                    plugin_id,
                    delete_files=False,
                    mode=UnloadMode.UNLOAD,
                    skip_legacy=True,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Rollback unload failed for plugin '%s'",
                    plugin_id,
                )
                failed.errors.append(f"rollback unload failed: {exc}")
                return failed
            if (
                not unload_report.quiescent
                or plugin_id in self._loaded_plugins
            ):
                failed.errors.extend(
                    unload_report.errors
                    or ["rollback unload did not go quiescent"],
                )
                return failed
        await run_sync_io(recover_migrating_inventory, plugin_id)
        if backup is not None and backup.exists():

            def _restore_dir() -> None:
                if old_path.exists():
                    safe_remove(old_path, purpose="remove failed reload dest")
                shutil.move(str(backup), str(old_path))

            await run_sync_io(_restore_dir)
        restore_plugin_import_state(snapshot)
        try:
            record = await self._load_plugin_unlocked(
                incoming_manifest,
                old_path,
                old_config,
                allow_install=False,
                activate=True,
                generation=generation,
                saved_plugin_def=saved_plugin_def if in_place else None,
                allow_existing=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Failed to restore previous plugin '%s' after reload",
                plugin_id,
            )
            failed.errors.append(f"restore failed: {exc}")
            return failed
        instance = self.lifecycle.get_instance(plugin_id)
        if (
            record.status != "active"
            or instance is None
            or not instance.activated
        ):
            failed.errors.append(
                f"restore load returned status={record.status}",
            )
            failed.errors.extend(list(record.diagnostics or []))
            return failed
        if old_path.exists():
            await run_sync_io(clear_updating_marker, plugin_id)
        return ReloadReport(
            plugin_id=plugin_id,
            ok=True,
            generation=generation,
        )

    async def load_plugin_from_path(
        self,
        source_path: Path,
        config: Optional[Dict] = None,
        install_dir: Optional[Path] = None,
        *,
        force: bool = False,
        before_force_unload: Optional[Any] = None,
        after_force_unload: Optional[Any] = None,
        after_load: Optional[Any] = None,
        pawport_owner: Optional[dict[str, Any]] = None,
        recover_incomplete: bool = False,
    ) -> PluginRecord:
        """Copy plugin files, install deps, and load plugin at runtime.

        The plugin directory is copied into ``install_dir`` (defaults
        to the first entry of ``self.plugin_dirs``) when it is not
        already located there.  Python dependencies listed in
        ``requirements.txt`` are installed before loading.

        When *force* is true and the plugin id is already loaded, the
        existing instance is replaced via :meth:`reload_plugin_unlocked`
        (probe first; failure leaves the old instance serving). Optional
        *before_force_unload* / *after_force_unload* run around that
        inner unload.

        *after_load* runs still inside the lifecycle lock so router
        post-load setup (providers / commands / agent config) cannot
        race a concurrent uninstall.

        Args:
            source_path: Directory that contains ``plugin.json``
            config: Optional plugin configuration dict
            install_dir: Target plugins directory.  Defaults to the
                first directory in ``self.plugin_dirs``.
            force: Replace a same-id loaded plugin via reload
            before_force_unload: ``callback(plugin_id)`` before unload
            after_force_unload: ``callback(plugin_id)`` after unload
            after_load: ``callback(record)`` after successful load

        Returns:
            Loaded PluginRecord

        Raises:
            FileNotFoundError: If ``plugin.json`` not found
            ValueError: If the plugin is already loaded (and not *force*)
            RuntimeError: If dependency installation fails
        """
        # pylint: disable=too-many-branches
        source_path = await asyncio.to_thread(Path(source_path).resolve)
        _manifest_path, manifest = await asyncio.to_thread(
            self._read_source_manifest,
            source_path,
        )
        del _manifest_path
        plugin_id = manifest.id
        async with self.plugin_lifecycle(plugin_id):
            if force and plugin_id in self._loaded_plugins:
                if before_force_unload is not None:
                    maybe_before = before_force_unload(plugin_id)
                    if inspect.isawaitable(maybe_before):
                        await maybe_before
                report = await self.reload_plugin_unlocked(
                    plugin_id,
                    new_source=source_path,
                    config=config,
                    allow_install=True,
                    owns_dependency_env=(
                        self.lifecycle.delegate.owns_dependency_env(
                            plugin_id,
                        )
                    ),
                    after_unload=after_force_unload,
                )
                if not report.ok:
                    detail = (
                        report.errors[0]
                        if report.errors
                        else f"Reload of '{plugin_id}' failed"
                    )
                    raise RuntimeError(detail)
                record = self._loaded_plugins[plugin_id]
                if after_load is not None:
                    maybe_loaded = after_load(record)
                    if inspect.isawaitable(maybe_loaded):
                        await maybe_loaded
                if pawport_owner is not None:
                    await asyncio.to_thread(
                        (record.source_path / _PAWPORT_MARKER).unlink,
                        missing_ok=True,
                    )
                return record
            record = None
            try:
                record = await self._load_plugin_from_path_unlocked(
                    source_path,
                    manifest,
                    config,
                    install_dir,
                    replace_files=force,
                    pawport_owner=pawport_owner,
                    recover_incomplete=recover_incomplete,
                )
                if record.status in {"active", "registered"}:
                    await self.activate_plugin_unlocked(plugin_id)
                if after_load is not None:
                    maybe_loaded = after_load(record)
                    if inspect.isawaitable(maybe_loaded):
                        await maybe_loaded
                if pawport_owner is not None:
                    await asyncio.to_thread(
                        (record.source_path / _PAWPORT_MARKER).unlink,
                        missing_ok=True,
                    )
                return record
            except BaseException:
                inst = self.lifecycle.get_instance(plugin_id)
                already_committed = record is not None and (
                    record.status == "active"
                    or (inst is not None and inst.activated)
                )
                if (
                    record is not None
                    and plugin_id in self._loaded_plugins
                    and not already_committed
                ):
                    await self._unload_plugin_unlocked(
                        plugin_id,
                        delete_files=False,
                    )
                if pawport_owner is not None and not already_committed:
                    await asyncio.to_thread(
                        self._remove_incomplete_pawport_plugin,
                        install_dir,
                        plugin_id,
                        pawport_owner,
                    )
                raise

    async def _load_plugin_from_path_unlocked(
        self,
        source_path: Path,
        manifest: PluginManifest,
        config: Optional[Dict] = None,
        install_dir: Optional[Path] = None,
        *,
        replace_files: bool = False,
        pawport_owner: Optional[dict[str, Any]] = None,
        recover_incomplete: bool = False,
    ) -> PluginRecord:
        """Install+load from path; caller must hold lifecycle for id."""
        # pylint: disable=too-many-statements,too-many-branches
        plugin_id = manifest.id
        if not self.lifecycle.delegate.owns_commit(plugin_id):
            raise RuntimeError(
                f"Plugin '{plugin_id}' commit is not owned by this process",
            )

        if plugin_id in self._loaded_plugins:
            raise ValueError(
                f"Plugin '{plugin_id}' is already loaded. "
                "Uninstall it first before reinstalling.",
            )

        # Determine target directory (resolve off the event loop).
        if install_dir is None:
            if not self.plugin_dirs:
                raise RuntimeError("No plugin directories configured")
            install_base: Path = self.plugin_dirs[0]
        else:
            install_base = Path(install_dir)

        def _resolve_install_paths() -> Tuple[Path, Path]:
            resolved_install = install_base.resolve()
            resolved_target = (resolved_install / plugin_id).resolve()
            return resolved_install, resolved_target

        resolved_install_dir, target_dir = await asyncio.to_thread(
            _resolve_install_paths,
        )

        # Guard against path-traversal in plugin_id (e.g. "../../etc")
        if (
            target_dir == resolved_install_dir
            or not target_dir.is_relative_to(resolved_install_dir)
        ):
            raise ValueError(
                f"Plugin id '{plugin_id}' does not resolve to a safe child "
                f"of the plugin directory ({resolved_install_dir}). "
                "Refusing to install.",
            )

        # Copy files when source is not already the target (off the loop).
        # Identity, not string equality: a case-alias of the same
        # directory must not be deleted then copied onto itself.
        # An existing unique install uses the same swap as reload:
        # never rmtree the only copy, then copytree.
        swapped = None
        if not same_location(source_path, target_dir):
            from ..utils.io_utils import run_sync_io

            def _recover_incomplete() -> None:
                if not target_dir.exists():
                    return
                marker_file = target_dir / _PAWPORT_MARKER
                try:
                    marker = json.loads(marker_file.read_text())
                except (OSError, ValueError, TypeError):
                    marker = {}
                if (
                    recover_incomplete
                    and pawport_owner is not None
                    and marker.get("state") == "prepared"
                    and _marker_matches(marker, pawport_owner)
                ):
                    safe_remove(
                        target_dir,
                        purpose="recover incomplete pawport plugin",
                    )

            def _first_install() -> None:
                target_dir.parent.mkdir(parents=True, exist_ok=True)
                stage_root = Path(
                    tempfile.mkdtemp(
                        prefix=f".{plugin_id}.install-",
                        dir=target_dir.parent,
                    ),
                )
                stage_dir = stage_root / plugin_id
                try:
                    shutil.copytree(source_path, stage_dir)
                    if pawport_owner is not None:
                        (stage_dir / _PAWPORT_MARKER).write_text(
                            json.dumps(
                                {**pawport_owner, "state": "prepared"},
                                sort_keys=True,
                            ),
                            encoding="utf-8",
                        )
                    os.rename(stage_dir, target_dir)
                finally:
                    if stage_root.exists():
                        safe_remove(
                            stage_root,
                            purpose="clear plugin install staging",
                        )

            def _write_pawport() -> None:
                owner = pawport_owner
                if owner is None:
                    return
                (target_dir / _PAWPORT_MARKER).write_text(
                    json.dumps(
                        {**owner, "state": "prepared"},
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )

            await self._recover_or_refuse_prepared_update(plugin_id)
            await run_sync_io(_recover_incomplete)
            target_exists = await asyncio.to_thread(target_dir.exists)
            if target_exists and not replace_files:
                raise ValueError(
                    f"Plugin installation target already exists: "
                    f"{target_dir}",
                )
            if target_exists and replace_files:
                swapped = await self._swap_plugin_dir(
                    plugin_id,
                    target_dir,
                    source_path,
                )
                if pawport_owner is not None:
                    await run_sync_io(_write_pawport)
            else:
                await run_sync_io(_first_install)
            logger.info(
                f"Copied plugin '{plugin_id}' to {target_dir}",
            )

        staging_hint = target_dir.with_name(
            target_dir.name + f".{plugin_id}.staging",
        )
        try:
            # Re-read manifest from the installed location so that
            # source_path in the record points to the correct directory
            _installed_path, installed_manifest = await asyncio.to_thread(
                self._read_source_manifest,
                target_dir,
            )
            del _installed_path
            record = await self.load_plugin(
                installed_manifest,
                target_dir,
                config,
                allow_install=True,
            )
            if record.status == "failed":
                reason = (
                    record.diagnostics[0]
                    if record.diagnostics
                    else f"Plugin '{plugin_id}' failed to load"
                )
                raise RuntimeError(reason)
            if swapped is not None:
                await self._finish_committed_reload(plugin_id, swapped)
            return record
        except BaseException:
            instance = self.lifecycle.get_instance(plugin_id)
            current = self._loaded_plugins.get(plugin_id)
            committed = (
                current is not None and current.status == "active"
            ) or (instance is not None and instance.activated)
            live = instance is not None and instance.has_runtime_ledger()
            if swapped is not None and not committed and live:
                instance.add_diagnostic("needs_restart")
            elif swapped is not None and not committed:
                try:
                    await self._restore_failed_swap(
                        plugin_id,
                        target_dir,
                        swapped,
                        staging_hint,
                        clear_marker_if_restored=True,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Failed to restore plugin '%s' after "
                        "unloaded force install",
                        plugin_id,
                    )
            raise

    def _remove_incomplete_pawport_plugin(
        self,
        install_dir: Optional[Path],
        plugin_id: str,
        owner: dict[str, Any],
    ) -> None:
        base = Path(install_dir or self.plugin_dirs[0]).resolve()
        target = (base / plugin_id).resolve()
        if target.parent != base or not target.is_dir():
            return
        try:
            marker = json.loads((target / _PAWPORT_MARKER).read_text())
        except (OSError, ValueError, TypeError):
            return
        if marker.get("state") == "prepared" and _marker_matches(
            marker,
            owner,
        ):
            safe_remove(
                target,
                purpose="remove incomplete pawport plugin",
            )

    async def unload_plugin(
        self,
        plugin_id: str,
        delete_files: bool = False,
        *,
        mode: UnloadMode | None = None,
    ) -> UnloadReport:
        """Unload a plugin.

        ``delete_files`` maps to uninstall when *mode* is omitted.
        """
        resolved = mode
        if resolved is None:
            resolved = (
                UnloadMode.UNINSTALL if delete_files else UnloadMode.UNLOAD
            )
        return await self.lifecycle.unload(
            plugin_id,
            resolved,
            delete_files=delete_files,
        )

    async def repair_dependencies(self, plugin_id: str) -> PluginRecord:
        """Explicit repair: gate + install + load a FAILED or disk plugin."""
        async with self.plugin_lifecycle(plugin_id):
            record = self._loaded_plugins.get(plugin_id)
            if record is not None:
                source_path = record.source_path
                manifest = record.manifest
            else:
                source_path = self._find_installed_plugin_dir(plugin_id)
                if source_path is None:
                    raise KeyError(f"Plugin '{plugin_id}' is not installed")
                _path, manifest = await asyncio.to_thread(
                    self._read_source_manifest,
                    source_path,
                )
                del _path
            decision = await self._ensure_dependencies_installed(
                source_path,
                plugin_id,
                allow_install=True,
            )
            if decision.require_restart:
                raise RuntimeError(decision.reason)
            from ..config.utils import load_config
            from .settings import is_plugin_enabled, runtime_config

            raw = (load_config().plugins or {}).get(plugin_id)
            saved_config = None
            inst = self.lifecycle.get_instance(plugin_id)
            if inst is not None:
                saved_config = dict(inst.config or {})
            if record is not None and record.status == "failed":
                if inst is not None:
                    teardown = await inst.teardown_runtime()
                    if not teardown.quiescent:
                        record.diagnostics = list(inst.diagnostics)
                        record.diagnostics.append(
                            "Repair refused: hosted resources did "
                            "not go quiescent; restart required.",
                        )
                        return record
                self.registry.unregister_plugin(plugin_id)
                self.registry.projector.drop_plugin(plugin_id)
                self._loaded_plugins.pop(plugin_id, None)
                self.lifecycle.drop_instance(plugin_id)
            elif plugin_id in self._loaded_plugins and record is not None:
                if record.status != "failed" and record.enabled:
                    return record
            if not is_plugin_enabled(raw):
                return PluginRecord(
                    manifest=manifest,
                    source_path=source_path,
                    enabled=False,
                    status="inactive",
                    diagnostics=[
                        "dependencies installed; plugin remains disabled",
                    ],
                )
            if saved_config is None:
                saved_config = runtime_config(raw)
            return await self._load_plugin_unlocked(
                manifest,
                source_path,
                saved_config,
                allow_install=False,
                activate=True,
            )

    async def unload_plugin_with_mode(
        self,
        plugin_id: str,
        mode: UnloadMode,
        *,
        instance,
        delete_files: bool = False,
    ) -> UnloadReport:
        """Unlocked unload used by ``PluginLifecycle``.

        Caller must hold the per-plugin lifecycle lock.
        """
        return await self._unload_plugin_unlocked(
            plugin_id,
            delete_files,
            mode=mode,
            instance=instance,
        )

    async def _unload_plugin_unlocked(
        self,
        plugin_id: str,
        delete_files: bool = False,
        *,
        mode: UnloadMode | None = None,
        instance=None,
        skip_legacy: bool = False,
    ) -> UnloadReport:
        """Unload a plugin and release a failed unload reservation."""
        from qwenpaw.memory import memory_registry

        try:
            return await self._unload_plugin_reserved(
                plugin_id,
                delete_files,
                mode=mode,
                instance=instance,
                skip_legacy=skip_legacy,
            )
        except BaseException:
            memory_registry.cancel_owner_unload(plugin_id)
            raise

    async def _unload_plugin_reserved(
        self,
        plugin_id: str,
        delete_files: bool = False,
        *,
        mode: UnloadMode | None = None,
        instance=None,
        skip_legacy: bool = False,
    ) -> UnloadReport:
        """Unload a plugin; caller must hold :meth:`plugin_lifecycle`."""
        # pylint: disable=too-many-branches,too-many-statements
        if mode is None:
            mode = UnloadMode.UNINSTALL if delete_files else UnloadMode.UNLOAD
        record = self._loaded_plugins.get(plugin_id)
        if record is None:
            if mode is UnloadMode.UNINSTALL:
                return await self._uninstall_without_instance(plugin_id)
            raise KeyError(
                f"Plugin '{plugin_id}' is not loaded",
            )
        if instance is None:
            instance = self.lifecycle.ensure_instance(plugin_id)

        from qwenpaw.memory import memory_registry

        if mode is not UnloadMode.SHUTDOWN:
            self.registry.assert_memory_backends_not_in_use(plugin_id)

        # Author hooks must run while they are still in the registry.
        # Ledger teardowns only drop the rows; they do not invoke them.
        report = UnloadReport(plugin_id=plugin_id, mode=mode)
        await self._run_shutdown_hooks(plugin_id, report)
        if mode is UnloadMode.SHUTDOWN:
            report.absorb(await instance.dispose(mode))
            logger.info("Shutdown hooks finished for plugin '%s'", plugin_id)
            return report
        if not skip_legacy:
            await self._run_legacy_uninstall_hooks(
                plugin_id,
                report,
                delete_files=delete_files or mode is UnloadMode.UNINSTALL,
            )
        was_committed = record.status == "active" or bool(
            instance is not None and instance.activated,
        )
        report.absorb(await instance.dispose(mode))
        if report.quiescent and not was_committed:
            try:
                await self._undo_failed_txn_disk(plugin_id, instance)
                instance.clear_txn_escapes()
                instance.clear_created_dests()
            except Exception as undo_exc:  # noqa: BLE001
                report.clean = False
                report.errors.append(
                    str(undo_exc) or type(undo_exc).__name__,
                )
        if not report.quiescent and mode is not UnloadMode.SHUTDOWN:
            record.status = "failed"
            record.diagnostics = list(
                getattr(instance, "diagnostics", []) or [],
            )
            report.needs_restart = True
            memory_registry.cancel_owner_unload(plugin_id)
            return report
        self._record_workspace_scan(plugin_id, report)
        leftovers = self.registry.leftover_registrations(plugin_id)
        if leftovers:
            report.clean = False
            report.leftovers.extend(leftovers)

        # Remove Python module and all sub-modules so the next import
        # gets a fresh copy (e.g. plugin_foo.utils must not be reused).
        module_name = f"plugin_{plugin_id.replace('-', '_')}"
        prefix = module_name + "."
        stale = [
            k for k in sys.modules if k == module_name or k.startswith(prefix)
        ]
        for k in stale:
            sys.modules.pop(k, None)

        # Remove the plugin directory and its subdirectories from
        # sys.path BEFORE the location-based sweep below: a namespace
        # package's __path__ recalculation reads the live sys.path, and
        # sweeping while the plugin's entries are still present could
        # merge plugin-tree portions into a shared host package's
        # portions and evict it.
        strip_plugin_sys_path(record.source_path)

        # Bypass imports (e.g. importlib.import_module after the plugin
        # inserted its dir into sys.path) land as top-level entries in
        # ``sys.modules`` — the prefix cleanup above misses them.
        # Sweep by module location (including __file__-less namespace
        # packages) so a reinstall always gets fresh code.
        sweep_bare_tree_modules(record.source_path)

        # Drop the import redirection after the sys.modules sweeps, so
        # a concurrent lazy import cannot resolve a plugin submodule
        # without the plugin builtins in the window between the two.
        unregister_namespace(module_name)

        # Remove tools from agents.tools + runtime registries while
        # ownership records still exist, then drop plugin registry state.
        self._cleanup_plugin_tools(plugin_id, record)

        # Clear all in-memory registry entries for this plugin
        self.registry.unregister_plugin(plugin_id)

        # Remove from the loaded-plugins dict
        del self._loaded_plugins[plugin_id]

        if mode is UnloadMode.UNINSTALL:
            from .provision import recorded_tool_names

            tool_names = recorded_tool_names(plugin_id)
            await _recheck_created_locations(plugin_id, report)
            await self._drop_uninstalled_settings(plugin_id, tool_names)

        # Optionally delete files from disk (off the event loop).
        should_delete = delete_files or mode is UnloadMode.UNINSTALL
        if should_delete:
            source_path = record.source_path
            if await asyncio.to_thread(source_path.exists):
                from ..utils.io_utils import run_sync_io

                await run_sync_io(
                    safe_remove,
                    source_path,
                    purpose="uninstall plugin directory",
                )
                logger.info(
                    f"Deleted plugin files at {source_path}",
                )

        if mode is not UnloadMode.SHUTDOWN:
            self.lifecycle.drop_instance(plugin_id)

        logger.info(f"Unloaded plugin '{plugin_id}'")
        return report

    def _record_workspace_scan(
        self,
        plugin_id: str,
        report: UnloadReport,
    ) -> None:
        """Scan live workspace tables after ledger teardown (report only)."""
        from .workspace_projector import (
            default_live_workspaces,
            scan_owner_rows,
        )

        scan = scan_owner_rows(plugin_id, default_live_workspaces())
        report.workspace_leaks.extend(scan.stamped_leaks)
        if scan.saw_unstamped:
            report.workspace_leaks.append("未标注归属、未覆盖")
        if scan.stamped_leaks:
            report.clean = False
        from .custody import scan_unhosted_tasks

        for item in scan_unhosted_tasks(plugin_id):
            report.leftovers.append(item)
            report.clean = False
        self.registry.projector.drop_plugin(plugin_id)

    def _cleanup_plugin_tools(
        self,
        plugin_id: str,
        record: PluginRecord,
    ) -> None:
        """Remove plugin tools from agents.tools and runtime registries.

        Uses ``sys.modules`` directly to avoid the parent-package
        attribute cache that would bypass any test/runtime overrides.
        Also unbridges workspace ``ToolRegistry`` / ``builtin_tool_funcs``
        so hot-reload cannot keep a stale callable.

        Args:
            plugin_id: Plugin identifier (for logging)
            record: PluginRecord whose tools should be removed
        """
        try:
            from .api import (
                _TOOL_PLUGIN_OWNERS,
                _TOOL_PLUGIN_OWNERS_LOCK,
                _unbridge_from_runtime,
            )

            tools_module = sys.modules.get("qwenpaw.agents.tools")
            meta: Dict = record.manifest.meta or {}
            # Manifest names are candidates only — never deletion authority.
            # A misconfigured / malicious plugin must not unload another
            # plugin's tool, a builtin, or a hot-reload replacement.
            manifest_candidates: List[str] = []

            # Legacy single-tool format: meta.tool_name
            old_name = meta.get("tool_name")
            if old_name and isinstance(old_name, str):
                manifest_candidates.append(old_name)

            # Multi-tool format: meta.tools[].name
            # Tolerate malformed meta.tools (null / non-list) — same as
            # routers.plugins._tool_names_from_meta.
            raw_tools = meta.get("tools")
            for tool in raw_tools if isinstance(raw_tools, list) else ():
                name = tool.get("name") if isinstance(tool, dict) else None
                if isinstance(name, str) and name.strip():
                    manifest_candidates.append(name.strip())

            with _TOOL_PLUGIN_OWNERS_LOCK:
                tool_names = [
                    name
                    for name, owner in _TOOL_PLUGIN_OWNERS.items()
                    if owner == plugin_id
                ]

            for claimed in manifest_candidates:
                if claimed not in tool_names:
                    logger.warning(
                        "Skipping unload cleanup for tool '%s': "
                        "manifest of plugin '%s' claims it but "
                        "ownership is held by %r",
                        claimed,
                        plugin_id,
                        _TOOL_PLUGIN_OWNERS.get(claimed),
                    )

            for tool_name in tool_names:
                tool_func = (
                    getattr(tools_module, tool_name, None)
                    if tools_module is not None
                    else None
                )
                try:
                    _unbridge_from_runtime(
                        tool_name,
                        tool_func,
                        self.registry,
                        expected=getattr(
                            tool_func,
                            "_tool_descriptor",
                            None,
                        ),
                    )
                except Exception as unbridge_exc:  # noqa: BLE001
                    logger.debug(
                        "Runtime unbridge failed for '%s' "
                        "(plugin '%s'): %s",
                        tool_name,
                        plugin_id,
                        unbridge_exc,
                        exc_info=True,
                    )

                if tools_module is None:
                    continue
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

    async def _run_shutdown_hooks(
        self,
        plugin_id: str,
        report: UnloadReport,
    ) -> None:
        """Run registry shutdown hooks and record failures on *report*."""
        hooks = [
            h
            for h in self.registry.get_shutdown_hooks()
            if h.plugin_id == plugin_id
        ]
        for hook in hooks:
            try:
                result = hook.callback()
                if inspect.iscoroutine(result) or inspect.isawaitable(result):
                    await await_with_budget(
                        result,
                        seconds=REGISTER_WALL_CLOCK_SECONDS,
                        what=f"shutdown hook '{hook.hook_name}'",
                        plugin_id=plugin_id,
                    )
            except Exception as exc:
                logger.error(
                    f"Error in shutdown hook '{hook.hook_name}' "
                    f"for plugin '{plugin_id}': {exc}",
                )
                report.errors.append(f"shutdown:{hook.hook_name}:{exc}")
                report.clean = False

    async def _run_legacy_uninstall_hooks(
        self,
        plugin_id: str,
        report: UnloadReport,
        *,
        delete_files: bool,
    ) -> None:
        """Run historical uninstall hooks (unload and uninstall modes)."""
        hooks = [
            h
            for h in self.registry.get_uninstall_hooks()
            if h.plugin_id == plugin_id
        ]
        for hook in hooks:
            try:
                result = hook.callback(
                    plugin_id=plugin_id,
                    delete_files=delete_files,
                )
                if inspect.iscoroutine(result) or inspect.isawaitable(result):
                    await result
            except Exception as exc:
                logger.error(
                    f"Error in uninstall hook '{hook.hook_name}' "
                    f"for plugin '{plugin_id}': {exc}",
                    exc_info=True,
                )
                report.errors.append(f"uninstall:{hook.hook_name}:{exc}")
                report.clean = False

    def find_installed_plugin_dir(self, plugin_id: str) -> Optional[Path]:
        """Return the on-disk directory for *plugin_id*, if present."""
        for plugin_dir in self.plugin_dirs:
            candidate = plugin_dir / plugin_id
            if (candidate / "plugin.json").is_file():
                return candidate
        return None

    def _find_installed_plugin_dir(self, plugin_id: str) -> Optional[Path]:
        """Return the on-disk directory for *plugin_id*, if present."""
        return self.find_installed_plugin_dir(plugin_id)

    async def _uninstall_without_instance(
        self,
        plugin_id: str,
    ) -> UnloadReport:
        """Clear disk provisions and the plugin dir when nothing is loaded."""
        from .provision import (
            declared_provision_dests,
            inventory_path,
            leftover_dests,
            recorded_tool_names,
            snapshot_created_dests,
            teardown_created_locations,
            teardown_paths,
        )

        report = UnloadReport(
            plugin_id=plugin_id,
            mode=UnloadMode.UNINSTALL,
        )
        source_path = self._find_installed_plugin_dir(plugin_id)
        has_inventory = inventory_path(plugin_id).is_file()
        if source_path is None and not has_inventory:
            raise KeyError(f"Plugin '{plugin_id}' is not installed")

        created = snapshot_created_dests(plugin_id)
        declared: list[str] = []
        candidate = False
        if not created and source_path is not None:
            try:
                _path, manifest = await asyncio.to_thread(
                    self._read_source_manifest,
                    source_path,
                )
                del _path
                declared = declared_provision_dests(
                    _manifest_as_dict(manifest),
                )
            except Exception:  # noqa: BLE001
                declared = []
            if declared:
                candidate = True
                report.errors.append(
                    "candidate: inventory missing; "
                    "using plugin.json declarations",
                )

        tool_names = recorded_tool_names(plugin_id)
        from ..utils.io_utils import run_sync_io
        from .provision import replay_persisted_provisions

        await run_sync_io(
            replay_persisted_provisions,
            plugin_id,
            source_path,
        )
        await self._drop_uninstalled_settings(plugin_id, tool_names)
        await run_sync_io(teardown_created_locations, plugin_id)
        if candidate:
            await run_sync_io(teardown_paths, declared)
        PluginApi.cleanup_sourced_skills(plugin_id)

        leftover = leftover_dests(created or declared)
        for dest in leftover:
            prefix = (
                "candidate leftover" if candidate else "inventory leftover"
            )
            report.errors.append(f"{prefix}: {dest}")
            report.clean = False

        if source_path is not None and await asyncio.to_thread(
            source_path.exists,
        ):
            await run_sync_io(
                safe_remove,
                source_path,
                purpose="uninstall plugin directory",
            )
        self.lifecycle.drop_instance(plugin_id)
        logger.info(
            "Uninstalled plugin '%s' without a live instance",
            plugin_id,
        )
        return report

    async def _drop_uninstalled_settings(
        self,
        plugin_id: str,
        tool_names: list[str] | None = None,
    ) -> None:
        """Clear persisted plugin settings and recorded tool configs."""
        from ..utils.io_utils import run_sync_io
        from .api import _remove_tool_config
        from .settings import drop_plugin_settings

        names = list(tool_names) if tool_names is not None else []

        def _apply() -> None:
            for name in names:
                _remove_tool_config(
                    name,
                    plugin_id=plugin_id,
                    owned_names=names,
                )
            drop_plugin_settings(plugin_id)

        await run_sync_io(_apply)

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

    async def reregister_unlocked(
        self,
        plugin_id: str,
        config: Optional[Dict] = None,
    ) -> None:
        """Call ``register()`` again on the already-imported plugin object."""
        record = self._loaded_plugins.get(plugin_id)
        if record is None or record.instance is None:
            raise RuntimeError(f"Plugin '{plugin_id}' is not loaded")
        await self._reregister_body(
            plugin_id,
            record.instance,
            config,
            _manifest_as_dict(record.manifest),
        )

    async def _reregister_body(
        self,
        plugin_id: str,
        plugin_def: Any,
        config: Optional[Dict],
        manifest_dict: Dict[str, Any],
    ) -> None:
        """Bind a fresh API and run ``register()``; do not dispose on error."""
        from .settings import runtime_config

        api = PluginApi(plugin_id, runtime_config(config), manifest_dict)
        api.set_registry(self.registry)
        instance = self.lifecycle.ensure_instance(plugin_id)
        instance.refuse_unquiescent_reregister()
        api.bind_instance(instance)
        self.registry.register_plugin_manifest(plugin_id, manifest_dict)
        instance.record_runtime(
            "plugin_manifest",
            lambda: self.registry.drop_plugin_manifest(plugin_id),
            kind="manifest",
        )
        if not hasattr(plugin_def, "register"):
            raise AttributeError(
                "Plugin must implement 'register(api)' method",
            )
        try:
            result = plugin_def.register(api)
            await await_with_budget(
                result,
                seconds=REGISTER_WALL_CLOCK_SECONDS,
                what="register()",
                plugin_id=plugin_id,
            )
        except BaseException:
            await self._dispose_then_undo_txn_disk(
                plugin_id,
                instance,
                use_teardown=True,
            )
            raise

    async def activate_plugin_unlocked(self, plugin_id: str) -> None:
        """Project, start, then commit. Raises on failure."""
        instance = self.lifecycle.get_instance(plugin_id)
        if instance is not None and instance.activated:
            record = self._loaded_plugins.get(plugin_id)
            if record is not None and record.status == "registered":
                record.status = "active"
            return
        from .api import snapshot_agent_tool_configs
        from .provision import snapshot_location_keys, snapshot_tool_inventory

        tools_before = snapshot_tool_inventory(plugin_id)
        agent_tools_before = snapshot_agent_tool_configs(tools_before)
        location_keys_before = snapshot_location_keys(plugin_id)
        committed: list[list[str] | None] = [None]
        cancelled = False
        cleanup_errors: list[str] = []
        try:
            await self._project_external_runtime(plugin_id)
            await self.run_plugin_startup_hooks(plugin_id)
            cleanup_errors = await self._commit_plugin_transaction(
                plugin_id,
                tools_before,
                committed=committed,
            )
        except BaseException as exc:
            if committed[0] is not None:
                cleanup_errors = committed[0]
                cancelled = isinstance(exc, asyncio.CancelledError)
                if not cancelled:
                    logger.warning(
                        "Activate already committed for '%s': %s",
                        plugin_id,
                        exc,
                    )
            else:
                from ..utils.io_utils import run_sync_io
                from .api import rollback_activate_install

                async def _rollback() -> None:
                    await run_sync_io(
                        rollback_activate_install,
                        plugin_id,
                        tools_before=tools_before,
                        agent_tools_before=agent_tools_before,
                        location_keys_before=location_keys_before,
                        created_dests=(
                            instance.created_dests()
                            if instance is not None
                            else []
                        ),
                        txn_escapes=(
                            instance.txn_escapes()
                            if instance is not None
                            else []
                        ),
                    )

                try:
                    await self._fail_after_startup(
                        plugin_id,
                        str(exc) or type(exc).__name__,
                        undo_disk=_rollback,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Activate rollback failed for plugin '%s'",
                        plugin_id,
                    )
                raise
        if instance is not None:
            instance.activated = True
            instance.clear_created_dests()
            instance.clear_txn_escapes()
            for item in cleanup_errors:
                instance.add_diagnostic(f"post-commit cleanup: {item}")
        record = self._loaded_plugins.get(plugin_id)
        if record is not None and record.status == "registered":
            record.status = "active"
        if cancelled:
            raise asyncio.CancelledError

    async def activate_all_loaded(self) -> None:
        """Activate every registered plugin that has not been activated yet."""
        for plugin_id, record in list(self._loaded_plugins.items()):
            if record.status not in {"registered", "active"}:
                continue
            instance = self.lifecycle.get_instance(plugin_id)
            if instance is not None and instance.activated:
                if record.status == "registered":
                    record.status = "active"
                continue
            try:
                await self.activate_plugin_unlocked(plugin_id)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Failed to activate plugin '%s': %s",
                    plugin_id,
                    exc,
                    exc_info=True,
                )

    async def _commit_plugin_transaction(
        self,
        plugin_id: str,
        tools_before: dict | None = None,
        committed: list | None = None,
    ) -> list[str]:
        from ..utils.io_utils import run_sync_io
        from .api import _remove_tool_config
        from .provision import (
            commit_migrations,
            drop_tool_rows,
            recorded_tool_names,
            tool_names_written_this_txn,
        )

        before = tools_before or {}
        box = committed if committed is not None else [None]

        def _commit() -> list[str]:
            from .updates import (
                STATUS_PREPARED,
                STATUS_UPDATING,
                mark_update_committed,
                update_marker_status,
            )

            written = tool_names_written_this_txn(plugin_id, before)
            errors: list[str] = []
            marked = False
            try:
                status = update_marker_status(plugin_id)
                if status in {STATUS_PREPARED, STATUS_UPDATING}:
                    mark_update_committed(plugin_id)
                    marked = True
                commit_migrations(plugin_id)
            except Exception as exc:
                if not marked:
                    raise
                errors.append(str(exc) or type(exc).__name__)
            box[0] = errors
            try:
                owned = recorded_tool_names(plugin_id)
                stale = [name for name in owned if name not in written]
                for name in stale:
                    _remove_tool_config(
                        name,
                        plugin_id,
                        owned_names=owned,
                    )
                drop_tool_rows(plugin_id, stale)
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc) or type(exc).__name__)
            return errors

        return await run_sync_io(_commit)

    async def _project_external_runtime(self, plugin_id: str) -> None:
        """Project providers and control commands for *plugin_id*."""
        providers = [
            (pid, reg)
            for pid, reg in self.registry.get_all_providers().items()
            if reg.plugin_id == plugin_id
        ]
        if providers:
            from ..providers.provider_manager import ProviderManager

            manager = ProviderManager.get_instance()
            for pid, reg in providers:
                await manager.register_plugin_provider_async(
                    provider_id=pid,
                    provider_class=reg.provider_class,
                    label=reg.label,
                    base_url=reg.base_url,
                    metadata=reg.metadata,
                )
        commands = [
            cmd
            for cmd in self.registry.get_control_commands()
            if cmd.plugin_id == plugin_id
        ]
        if not commands:
            return
        from ..runtime.commands.control import register_command
        from .workspace_projector import ProjectionError, live_channel_managers

        managers = live_channel_managers()
        for cmd_reg in commands:
            prefix = f"/{str(cmd_reg.handler.command_name).lstrip('/')}"
            try:
                register_command(cmd_reg.handler, owner=plugin_id)
                for manager in managers:
                    manager.register_control_command(
                        prefix,
                        priority_level=cmd_reg.priority_level,
                        owner=plugin_id,
                    )
            except ValueError as exc:
                raise ProjectionError(str(exc)) from exc

    async def run_plugin_startup_hooks(self, plugin_id: str) -> None:
        """Run startup hooks that currently belong to *plugin_id*.

        Exceptions propagate so ``update_config`` / reload can roll back.
        """
        for hook in self.registry.get_startup_hooks():
            if hook.plugin_id != plugin_id:
                continue
            await self._invoke_startup_hook(hook)

    async def run_startup_hooks_isolated(self, plugin_id: str) -> bool:
        """Run one plugin's startup hooks; failure → FAILED + ledger undo.

        Returns ``True`` when every hook succeeded.
        """
        for hook in self.registry.get_startup_hooks():
            if hook.plugin_id != plugin_id:
                continue
            try:
                await self._invoke_startup_hook(hook)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "✗ Failed to execute startup hook '%s' "
                    "from plugin '%s': %s",
                    hook.hook_name,
                    plugin_id,
                    exc,
                    exc_info=True,
                )
                await self._fail_after_startup(plugin_id, str(exc))
                return False
        return True

    async def run_all_startup_hooks(self) -> None:
        """Run every startup hook; one failure does not stop the others."""
        failed: set[str] = set()
        for hook in self.registry.get_startup_hooks():
            if hook.plugin_id in failed:
                continue
            logger.debug(
                "Executing startup hook '%s' from plugin '%s' "
                "(priority=%s)",
                hook.hook_name,
                hook.plugin_id,
                hook.priority,
            )
            try:
                await self._invoke_startup_hook(hook)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "✗ Failed to execute startup hook '%s' "
                    "from plugin '%s': %s",
                    hook.hook_name,
                    hook.plugin_id,
                    exc,
                    exc_info=True,
                )
                failed.add(hook.plugin_id)
                await self._fail_after_startup(hook.plugin_id, str(exc))
                continue
            logger.debug(
                "Completed startup hook '%s' from plugin '%s'",
                hook.hook_name,
                hook.plugin_id,
            )

    async def _invoke_startup_hook(self, hook: Any) -> None:
        result = hook.callback()
        await await_with_budget(
            result,
            seconds=REGISTER_WALL_CLOCK_SECONDS,
            what=f"startup hook '{hook.hook_name}'",
            plugin_id=hook.plugin_id,
        )

    async def _fail_after_startup(
        self,
        plugin_id: str,
        reason: str,
        *,
        undo_disk=None,
    ) -> None:
        """Mark FAILED, undo the runtime ledger, keep the loaded record."""
        instance = self.lifecycle.ensure_instance(plugin_id)
        instance.mark_failed(reason)
        try:
            report = await instance.dispose(UnloadMode.UNLOAD)
        except BaseException:
            instance.add_diagnostic("needs_restart")
            raise
        record = self._loaded_plugins.get(plugin_id)
        if not report.quiescent:
            instance.add_diagnostic("needs_restart")
            if record is not None:
                record.status = "failed"
                record.enabled = False
                record.diagnostics = list(instance.diagnostics)
            logger.error(
                "Plugin '%s' marked FAILED after startup "
                "(not quiescent): %s",
                plugin_id,
                reason,
            )
            return
        try:
            if undo_disk is not None:
                maybe = undo_disk()
                if inspect.isawaitable(maybe):
                    await maybe
            else:
                await self._undo_failed_txn_disk(plugin_id, instance)
            instance.clear_txn_escapes()
            instance.clear_created_dests()
        except Exception as undo_exc:  # noqa: BLE001
            instance.add_diagnostic(
                str(undo_exc) or type(undo_exc).__name__,
            )
        source = instance.source_path
        if source is None and record is not None:
            source = record.source_path
        self.lifecycle.drop_instance(plugin_id)
        failed = self.lifecycle.ensure_instance(plugin_id)
        failed.mark_failed(reason)
        if source is not None:
            failed.source_path = source
            self._cleanup_failed_load(
                plugin_id,
                f"plugin_{plugin_id.replace('-', '_')}",
                Path(source),
            )
        else:
            self.registry.unregister_plugin(plugin_id)
        if record is not None:
            record.status = "failed"
            record.enabled = False
            record.diagnostics = list(failed.diagnostics)
        logger.error(
            "Plugin '%s' marked FAILED after startup: %s",
            plugin_id,
            reason,
        )

    async def load_installed_unlocked(self, plugin_id: str) -> PluginRecord:
        """Load an on-disk plugin; caller must hold the lifecycle lock."""
        source_path = self._find_installed_plugin_dir(plugin_id)
        if source_path is None:
            raise KeyError(f"Plugin '{plugin_id}' is not installed")
        _path, manifest = await asyncio.to_thread(
            self._read_source_manifest,
            source_path,
        )
        del _path
        from ..config.utils import load_config
        from .settings import runtime_config

        raw = (load_config().plugins or {}).get(plugin_id)
        return await self._load_plugin_unlocked(
            manifest,
            source_path,
            runtime_config(raw),
            allow_install=False,
            activate=True,
        )


async def _invoke_after_unload(
    after_unload: Optional[Any],
    plugin_id: str,
) -> None:
    """Run an optional post-unload callback."""
    if after_unload is None:
        return
    maybe = after_unload(plugin_id)
    if inspect.isawaitable(maybe):
        await maybe


async def _recheck_created_locations(
    plugin_id: str,
    report: UnloadReport,
) -> None:
    """Uninstall step ⑦: teardown created dests, then ERROR if they remain."""
    from ..utils.io_utils import run_sync_io
    from .provision import (
        leftover_dests,
        snapshot_created_dests,
        teardown_created_locations,
    )

    created = snapshot_created_dests(plugin_id)
    await run_sync_io(teardown_created_locations, plugin_id)
    for dest in leftover_dests(created):
        report.errors.append(f"inventory leftover: {dest}")
        report.clean = False


def _manifest_as_dict(manifest: PluginManifest) -> Dict[str, Any]:
    """Project a manifest into the dict ``register()`` historically
    received."""
    if manifest.qwenpaw_version is not None:
        qv_dict = manifest.qwenpaw_version.model_dump()
    else:
        qv_dict = {
            "min": manifest.min_version,
            "max": manifest.max_version,
        }
    return {
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "description": manifest.description,
        "description_i18n": manifest.description_i18n,
        "author": manifest.author,
        "dependencies": manifest.dependencies,
        "qwenpaw_version": qv_dict,
        "meta": manifest.meta,
    }
