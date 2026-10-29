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
import threading
import tempfile
from contextlib import AsyncExitStack, ExitStack, asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from packaging.requirements import Requirement

from ..utils.runtime_environment import CERTIFI_REQUIREMENT, require_pip

from .architecture import PluginManifest, PluginRecord, PluginType
from .execution_backend import (
    BackendBinding,
    BackendResolver,
    discovers_disabled,
    probes_before_activation,
    registration_scope,
)
from .dependency_context import _capture_runtime_selection
from .python_backend import (
    PythonBackend,
    PythonServices,
    _EntryPointNotFoundError,
)
from .python_backend import _probe_incoming as _probe_python_incoming
from .api import PluginApi
from .dependency_gate import (
    DependencyGate,
    GateDecision,
    combined_requirements,
    is_requirement_satisfied,
)
from .lifecycle import (
    PluginLifecycle,
    QuiescenceError,
    PluginState,
    ReloadReport,
    UnloadMode,
    UnloadReport,
    await_with_budget,
    REGISTER_WALL_CLOCK_SECONDS,
)
from .module_isolation import (
    refresh_import_caches,
    strip_plugin_sys_path,
    sweep_bare_tree_modules,
    unregister_namespace,
)
from .channel_adapter import (
    ChannelBackend,
    ChannelServices,
    describe_channel,
)
from .safe_fs import safe_remove, same_location
from .registry import PluginRegistry
from .ownership import RuntimeKey, RuntimeSourceBusyError, RuntimeStopReceipt

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


async def _probe_incoming(
    plugin_id: str,
    source_path: Path,
    entry_file: Path | None,
) -> ReloadReport | None:
    """Compatibility probe seam; execution lives in PythonBackend."""
    return await _probe_python_incoming(plugin_id, source_path, entry_file)


def _remove_dir(path: Path | None) -> None:
    if path is None:
        return
    raw = str(path).strip()
    if not raw:
        return
    safe_remove(path, purpose="remove plugin directory")


def _plugin_site_dir() -> Path:
    """Use the same managed dependency target as channel workers."""
    from .channel_bootstrap import plugin_runtime_site, runtime_manifest

    runtime = runtime_manifest() if _is_frozen() else None
    return plugin_runtime_site(_plugin_runtime_dir(), runtime)


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


@dataclass
class _DependencyAdmission:
    """Transaction custody until an exact declaration reaches a new ledger."""

    binding: BackendBinding
    token: object = None
    snapshot: object = None
    attached: bool = False
    released: bool = False


def _prepare_plugin_site_path(site_dir, path_snapshot):
    """Resolve the complete frozen path edit without touching global state."""
    try:
        target = _plugin_site_dir() if site_dir is None else site_dir
    except Exception:
        # Preserve the optional bootstrap path probe; the dependency gate
        # remains responsible for reporting invalid runtime policy.
        return None
    paths = list(path_snapshot)
    if (
        target.parent.name.startswith("bundle-")
        and target.parent.parent.parent == _plugin_runtime_dir()
    ):
        bucket = target.parent.parent.resolve()
        active = target.resolve()
        paths = []
        for entry in path_snapshot:
            path = Path(_norm_realpath(entry))
            managed = path == bucket / "site" or (
                path.name == "site"
                and path.parent.name.startswith("bundle-")
                and path.parent.parent == bucket
            )
            if not managed or path == active:
                paths.append(entry)
    site = str(target)
    if site not in paths:
        paths.insert(0, site)
    return site, paths


def _publish_plugin_site_path(prepared):
    if prepared is None:
        return
    site, paths = prepared
    sys.path[:] = paths
    os.environ["QWENPAW_PLUGIN_SITE"] = site
    refresh_import_caches()


async def _ensure_plugin_site_on_path_async(site_dir=None, *, validate=None):
    from ..utils.io_utils import run_sync_io

    if not _is_frozen():
        return
    paths = tuple(sys.path)
    site_environment = os.environ.get("QWENPAW_PLUGIN_SITE")
    prepared = await run_sync_io(_prepare_plugin_site_path, site_dir, paths)
    if (
        tuple(sys.path) != paths
        or os.environ.get("QWENPAW_PLUGIN_SITE") != site_environment
        or not _is_frozen()
    ):
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED")
    if validate is not None:
        validate()
    _publish_plugin_site_path(prepared)


class PluginLoader:  # pylint: disable=too-many-public-methods
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
        self._recovery_blocked: dict[str, str] = {}
        self._recovery_errors: dict[str, str] = {}
        # In-process per-plugin serialization for load/unload/reinstall.
        # Distinct from the inter-process install-deps file lock.
        self._lifecycle_locks: Dict[str, asyncio.Lock] = {}
        self._lifecycle_locks_mu = threading.Lock()

        # Resolve mutable host service references only when invoked. Existing
        # embedders replace their registry and dependency gate after creation.
        def dependencies(*args, **kwargs):
            return self._ensure_dependencies_installed(*args, **kwargs)

        def channel_candidate(*args, **kwargs):
            return self._prepare_channel_candidate(*args, **kwargs)

        def unregister(plugin_id):
            return self.registry.unregister_plugin(plugin_id)

        def channel_registration(plugin_id):
            return next(
                (
                    row
                    for row in self.registry.get_channel_catalog().values()
                    if row.plugin_id == plugin_id
                    and row.description_record is not None
                ),
                None,
            )

        # pylint: disable=unnecessary-lambda
        self._python_backend = PythonBackend(
            PythonServices(
                ensure_dependencies=dependencies,
                probe=lambda *args: _probe_incoming(*args),
                get_instance=self.lifecycle.get_instance,
                drop_instance=self.lifecycle.drop_instance,
                unregister_plugin=unregister,
                dependency_environment=self._dependency_environment,
            ),
        )
        self._channel_backend = ChannelBackend(
            ChannelServices(
                runtime_settings=lambda: self.registry.channel_runtime,
                prepare_candidate=channel_candidate,
                own_preparation=self._own_preparation,
                stop_preparation=self._stop_preparation,
                release_preparation=self._finish_preparation,
                acquire_wheels=self._acquire_dependency_wheels,
                dependency_usage=lambda: self.registry.dependency_usage,
                workspaces=lambda: self.registry.projector.workspaces(),
                registration=channel_registration,
                record=self.get_loaded_plugin,
            ),
        )
        # pylint: enable=unnecessary-lambda
        self.backend_resolver = BackendResolver(self._python_backend)
        self.backend_resolver.register_descriptor(
            PluginType.CHANNEL,
            self._channel_backend,
        )

    @classmethod
    async def create(cls, plugin_dirs, *, channel_runtime=None):
        """Acquire process lifetime runtime custody before loop publication."""
        from ..utils.io_utils import run_sync_io
        from .dependency_maintenance import lease_environment

        validate = _capture_runtime_selection(
            lambda: channel_runtime,
            _is_frozen,
        )
        if channel_runtime is not None:
            await run_sync_io(
                lease_environment,
                tuple(channel_runtime.dependency_paths),
            )
        validate()
        loader = cls(plugin_dirs)
        if channel_runtime is not None:
            loader.registry.configure_channel_runtime(channel_runtime)
        return loader

    async def _publish_dependency_site(self, target, *, validate=None):
        if validate is None:
            validate = _capture_runtime_selection(
                lambda: self.registry.channel_runtime,
                _is_frozen,
            )
        validate()
        await _ensure_plugin_site_on_path_async(target, validate=validate)

    def _channel_runtime_for(self, manifest):
        return self._channel_backend.runtime_for(manifest)

    def _dependency_environment(self, snapshot=None):
        """Select host installation policy independently of plugin kind."""
        from .dependency_context import DependencyEnvironmentContext
        from .execution.environment import shared_dependency_paths

        if _is_frozen():
            from .channel_bootstrap import resolve_default_channel_runtime

            runtime = self.registry.channel_runtime
            if runtime is None:
                runtime = resolve_default_channel_runtime(provision=False)
            if (
                runtime.runtime_identity is None
                or runtime.dependency_install_target is None
            ):
                raise ValueError("CHANNEL_RUNTIME_MISSING")
            context = DependencyEnvironmentContext.from_runtime(runtime)
            return context
        if snapshot is not None:
            return DependencyEnvironmentContext.from_snapshot(snapshot)
        return DependencyEnvironmentContext(
            sys.executable,
            Path(__file__).resolve().parents[2],
            shared_dependency_paths(),
            None,
        )

    async def _binding_for_record(self, record):
        """Describe missing bindings off-loop; retain record writes here."""
        from ..utils.io_utils import run_sync_io

        if record.backend_binding is None:
            record.backend_binding = await run_sync_io(
                self.backend_resolver.resolve,
                record.source_path,
                record.manifest,
            )
        return record.backend_binding

    def _has_runtime_custody(self, plugin_id):
        return bool(
            self.registry.runtime_owners.leases(plugin_id),
        )

    def retains_preparation_source(self, root):
        """Keep upload staging while any retained inspection can use it."""
        root = Path(root).resolve()
        return any(
            lease.code_root.is_relative_to(root)
            or root.is_relative_to(lease.code_root)
            for lease in self.registry.runtime_owners.leases()
        )

    def _require_unowned_roots(self, *roots):
        """Refuse destructive changes beneath any retained source root."""
        if any(
            root is not None and self.retains_preparation_source(root)
            for root in roots
        ):
            raise RuntimeError("RUNTIME_SOURCE_STILL_OWNED; needs_restart")

    async def cleanup_preparation_source(self, root) -> bool:
        """Remove caller-owned staging, or retain it while its root is busy."""
        from ..utils.io_utils import run_sync_io

        try:
            with self.registry.runtime_owners.mutation(root):
                await run_sync_io(shutil.rmtree, root, True)
        except RuntimeSourceBusyError:
            return False
        return True

    def _require_recovered(self, plugin_id: str) -> None:
        """Do not import or commit a version whose boot recovery failed."""
        if plugin_id == "cloudpaw":
            from .legacy_cloudpaw import has_pending_uninstall

            if has_pending_uninstall(self):
                raise RuntimeError(
                    "CloudPaw uninstall is incomplete; retry uninstall",
                )
        if plugin_id in self._recovery_blocked:
            raise RuntimeError(
                f"Plugin '{plugin_id}' recovery failed; needs_restart: "
                f"{self._recovery_blocked[plugin_id]}",
            )

    def _add_recovery_diagnostics(self, plugin_id: str) -> None:
        error = self._recovery_errors.get(plugin_id)
        if error is None:
            return
        instance = self.lifecycle.get_instance(plugin_id)
        if instance is None:
            instance = self.lifecycle.ensure_instance(plugin_id)
        instance.add_diagnostic(f"Recovery failed: {error}")
        instance.add_diagnostic("needs_restart")
        record = self._loaded_plugins.get(plugin_id)
        if record is not None:
            record.diagnostics = list(instance.diagnostics)

    def _note_disk_recovery_failure(self, exc: BaseException) -> bool:
        """Block activation and commit until unfinished files are restored."""
        from .provision import MigrationRecoveryError

        if not isinstance(exc, MigrationRecoveryError):
            return False
        self._recovery_blocked.update(exc.result.blocked)
        self._recovery_errors.update(exc.result.failures)
        for plugin_id in exc.result.blocked:
            self._add_recovery_diagnostics(plugin_id)
        return True

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

    @asynccontextmanager
    async def execution_source(self, plugin_id):
        """Admit existing source custody without loading or preparing code."""
        from .execution.process import ProcessError

        lock = self._lifecycle_lock_for(plugin_id)
        hold_key = self._lifecycle_hold_key(plugin_id)
        if lock.locked() and (
            hold_key is None or _LIFECYCLE_HELD.get() != hold_key
        ):
            raise RuntimeSourceBusyError("RUNTIME_SOURCE_MUTATING")
        async with self.plugin_lifecycle(plugin_id):
            record = self.get_loaded_plugin(plugin_id)
            if record is None:
                raise ProcessError("PLUGIN_NOT_INSTALLED")
            enabled = (
                record.global_enabled
                if record.global_enabled is not None
                else record.enabled
            )
            if not enabled:
                raise ProcessError("PLUGIN_DISABLED")
            if plugin_id in self._recovery_blocked:
                raise ProcessError("SOURCE_UNAVAILABLE")
            yield record

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
        from .sdk_version import validate_sdk

        if isinstance(data, dict):
            validate_sdk(data.get("sdk"), data.get("id"))
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

    # Early decisions preserve boot/check-only and shared installation safety.
    # pylint: disable-next=too-many-return-statements
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
        from ..utils.io_utils import run_sync_io

        await self._publish_dependency_site(None)
        from .execution.dependencies import repair_marker
        from .dependency_maintenance import authorized

        from .execution.dependencies import dependency_sites
        from .install_lock import environment_observation

        host_paths = tuple(sys.path)
        roots = await run_sync_io(dependency_sites, host_paths)
        try:
            async with environment_observation(roots):
                dirty = await run_sync_io(
                    lambda: any(
                        repair_marker(path).exists() and not authorized(path)
                        for path in host_paths
                        if path and Path(path).is_dir()
                    ),
                )
        except RuntimeError as exc:
            if not str(exc).startswith("DEPENDENCY_REPAIR_REQUIRED"):
                raise
            dirty = True
        if dirty:
            return GateDecision(
                False,
                False,
                require_restart=True,
                reason="DEPENDENCY_REPAIR_REQUIRED",
                reason_code="DEPENDENCY_REPAIR_REQUIRED",
            )
        if not self.lifecycle.delegate.owns_dependency_env(plugin_id):
            return GateDecision(
                allow_install=False,
                already_satisfied=True,
                reason="dependency env not owned by this process",
            )
        cleanup = ExitStack()
        try:
            try:
                requirements_file = await run_sync_io(
                    cleanup.enter_context,
                    combined_requirements(source_path),
                )
            except ValueError as exc:
                return GateDecision(
                    allow_install=False,
                    already_satisfied=False,
                    unsupported=[str(exc)],
                    reason=str(exc),
                )
            return await self._ensure_requirements_installed(
                requirements_file,
                source_path,
                plugin_id,
                allow_install=allow_install,
            )
        finally:
            await run_sync_io(cleanup.close)

    async def _ensure_requirements_installed(
        self,
        requirements_file: Path,
        source_path: Path,
        plugin_id: str,
        *,
        allow_install: bool,
    ) -> GateDecision:
        from ..utils.io_utils import run_sync_io

        from .execution.dependencies import dependency_sites
        from .install_lock import environment_observation

        async def evaluate(install):
            roots = await run_sync_io(dependency_sites, tuple(sys.path))
            async with environment_observation(roots):
                return await run_sync_io(
                    DependencyGate().evaluate,
                    requirements_file,
                    allow_install=install,
                    plugin_id=plugin_id,
                )

        decision = await evaluate(allow_install)
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
        source = (
            {"source_path": source_path}
            if requirements_file.parent != source_path
            else {}
        )
        await self._prepare_python_dependencies(
            requirements_file,
            plugin_id,
            **source,
        )
        recheck = await evaluate(False)
        if recheck.already_satisfied:
            return recheck
        recheck.allow_install = False
        if not recheck.reason:
            recheck.reason = (
                f"Plugin '{plugin_id}' is still missing dependencies "
                f"after install: {', '.join(recheck.missing)}"
            )
        return recheck

    async def _prepare_channel_candidate(self, description, **kwargs):
        """Compatibility preparation seam for source transactions."""
        if not self.lifecycle.delegate.owns_dependency_env(
            description.plugin_id,
        ):
            kwargs.update(allow_install=False, wheels=())
        return await self._channel_backend.prepare_candidate(
            description,
            **kwargs,
        )

    def _own_preparation(
        self,
        plugin_id,
        process_type,
        code_root,
        *,
        instance_id,
        cleanup=None,
    ):
        """Reserve and bind custody before starting a preparation process."""
        owners = self.registry.runtime_owners
        lease = owners.reserve(
            plugin_id,
            RuntimeKey("preparation", plugin_id, "global"),
            code_root,
            instance_id=instance_id,
        )
        try:
            # Process constructors are synchronous and do not launch resources.
            process = process_type()
        except BaseException:
            owners.release(
                lease,
                RuntimeStopReceipt(True, "PROCESS_NOT_CONSTRUCTED"),
            )
            raise

        async def stop():
            result = await process.stop()
            if result.exited and not result.residual and cleanup is not None:
                from ..utils.io_utils import run_sync_io

                await run_sync_io(cleanup)
            return RuntimeStopReceipt(
                quiescent=result.exited and not result.residual,
                detail=(
                    ""
                    if result.exited and not result.residual
                    else "PROBE_CLEANUP_FAILED; needs_restart"
                ),
                exited=result.exited,
                returncode=result.returncode,
                forced=result.forced,
                residual=result.residual,
            )

        owners.attach(lease, stop, resource=process)
        instance = self.lifecycle.get_instance(plugin_id)
        if instance is not None:
            instance.record_runtime(
                f"preparation:{lease.instance_id}:{lease.generation}",
                teardown=lambda: self._finish_preparation(lease),
                kind="custody",
            )
        return process, lease

    async def _finish_preparation(self, lease):
        """Use current exact-lease stop evidence after preparation."""
        receipt = await self.registry.runtime_owners.stop(lease)
        if not receipt.stopped:
            raise QuiescenceError(
                f"{receipt.detail or 'PROBE_CLEANUP_FAILED'}; needs_restart",
                receipt=receipt,
            )

    async def _stop_preparation(self, plugin_id):
        """Retry retained preparation cleanup."""
        for lease in self.registry.runtime_owners.leases(plugin_id):
            if lease.key.kind == "preparation":
                await self._finish_preparation(lease)

    async def _stop_runtime_owners(self, plugin_id, mode):
        """Recover orphaned custody through the same attached stop adapters."""
        report = UnloadReport(plugin_id=plugin_id, mode=mode)
        for receipt in await self.registry.runtime_owners.stop_all(plugin_id):
            if not receipt.stopped:
                report.clean = report.quiescent = False
                report.needs_restart = True
                report.errors.append(receipt.detail or "RUNTIME_STILL_OWNED")
        if self.registry.runtime_owners.leases(plugin_id):
            report.clean = report.quiescent = False
            report.needs_restart = True
            if not report.errors:
                report.errors.append("RUNTIME_STILL_OWNED")
        return report

    def _install_requirements_locked(
        self,
        requirements_file: Path,
        plugin_id: str,
        *,
        source_path: Path | None = None,
    ) -> None:
        """Compatibility sync entry; safe preparation owns site exclusion."""
        asyncio.run(
            self._prepare_python_dependencies(
                requirements_file,
                plugin_id,
                source_path=source_path,
            ),
        )

    # Audit, source custody and cleanup form one shared dependency transaction.
    # pylint: disable-next=too-many-statements
    async def _prepare_python_dependencies(
        self,
        requirements_file: Path,
        plugin_id: str,
        *,
        source_path: Path | None = None,
    ):
        """Stage explicit legacy wheel installs through the shared gate."""
        from .dependency_gate import (
            SharedDependencyError,
            prepare_shared_dependencies,
        )
        from .execution import PluginLaunchSpec, PluginProcess
        from .execution.bootstrap import _hash_code_root
        from ..utils.io_utils import run_sync_io

        if os.environ.get("QWENPAW_RUNTIME_PROVISIONER") == "local":
            raise RuntimeError(
                "Shared runtime requires explicit administrator repair",
            )
        frozen = _is_frozen()
        validate_runtime_selection = _capture_runtime_selection(
            lambda: self.registry.channel_runtime,
            _is_frozen,
        )

        context = await run_sync_io(self._dependency_environment)
        validate_runtime_selection()
        target = context.install_target
        python = context.python_executable
        support = context.support_root
        paths = context.dependency_paths
        root = await run_sync_io(
            (source_path or requirements_file.parent).resolve,
        )
        if frozen:
            from .channel_bootstrap import (
                validate_runtime_identity,
            )
            from .install_lock import (
                async_lock,
                environment_install_lock_path,
                plugin_install_lock,
            )

            from .dependency_maintenance import canonical

            def validate_target():
                if target.is_symlink() or context.protected(target):
                    raise ValueError("CHANNEL_RUNTIME_TARGET_INVALID")
                return canonical(target)

            def prepare_target():
                validate_target()
                target.mkdir(parents=True, exist_ok=True)
                return validate_target()

            selected = await run_sync_io(prepare_target)
            async with async_lock(
                plugin_install_lock(
                    await run_sync_io(environment_install_lock_path, selected),
                ),
            ):
                if str(await run_sync_io(validate_target)) != str(
                    selected,
                ) or not await run_sync_io(selected.is_dir):
                    raise ValueError("CHANNEL_RUNTIME_TARGET_INVALID")
                target = selected

            def resolve_paths():
                return tuple(
                    Path(key)
                    for key in dict.fromkeys(
                        str(canonical(path)) for path in (*paths, target)
                    )
                )

            paths = await run_sync_io(resolve_paths)
            await self._publish_dependency_site(
                target,
                validate=validate_runtime_selection,
            )
        await self._stop_preparation(plugin_id)
        cleanup = ExitStack()
        try:
            if source_path is not None:

                def stage_requirements():
                    temporary = cleanup.enter_context(
                        tempfile.TemporaryDirectory(
                            prefix="qwenpaw-dependency-audit-",
                        ),
                    )
                    staged = Path(temporary) / "requirements.txt"
                    shutil.copyfile(requirements_file, staged)
                    return staged

                requirements_file = await run_sync_io(stage_requirements)
            audit_root = await run_sync_io(requirements_file.parent.resolve)
            process, lease = self._own_preparation(
                plugin_id,
                PluginProcess,
                root,
                instance_id="dependency:" + plugin_id,
                cleanup=cleanup.close,
            )
        except BaseException:
            await run_sync_io(cleanup.close)
            raise
        usage = self.registry.dependency_usage
        token = None
        identity_error = None
        try:
            from .dependency_gate import parse_requirements_file
            from .dependency_usage import DependencyDeclaration

            def inspect_requirements():
                return (
                    _hash_code_root(audit_root),
                    requirements_file.resolve(),
                    parse_requirements_file(requirements_file),
                )

            revision, requirements_path, requirements = await run_sync_io(
                inspect_requirements,
            )
            spec = PluginLaunchSpec(
                python_executable=python,
                support_root=support,
                code_root=audit_root,
                source_revision=revision,
                plugin_id=plugin_id,
                instance_id="dependency:" + plugin_id,
                generation=lease.generation,
                entrypoint="_dependency_audit:Driver",
                config={},
                requirements_path=requirements_path,
                dependency_paths=paths,
                startup_timeout=15,
            )
            token = usage.declare(
                DependencyDeclaration(
                    plugin_id,
                    spec.source_revision,
                    (
                        ()
                        if frozen
                        else (
                            tuple(
                                str(item) for item in requirements.requirements
                            )
                            + tuple(requirements.unsupported)
                        )
                    ),
                    None,
                ),
            )
            usage.bind(lease, token)

            def observe(snapshot):
                nonlocal identity_error
                if context.runtime_identity is not None:
                    try:
                        validate_runtime_identity(
                            snapshot,
                            context.runtime_identity,
                            python,
                        )
                    except ValueError as exc:
                        identity_error = exc
                        raise
                usage.observe(lease, snapshot)

            process.dependency_observer = observe
            from .install_lock import environment_observation

            # The configured sites have parent reader custody. Unknown native
            # interpreter sites remain subject to the child's cold audit.
            async with environment_observation(paths):
                snapshot = (await process.audit(spec)).snapshot
            observe(snapshot)
            wheel_tags = snapshot.supported_tags if frozen else None
            audit_process = process
            if frozen:
                from types import SimpleNamespace

                async def host_audit(_spec):
                    observed = await self._python_backend.audit_dependencies(
                        SimpleNamespace(source_path=root),
                        context=context,
                        validate=validate_runtime_selection,
                    )
                    return SimpleNamespace(snapshot=observed)

                # A worker proves installer identity. Ordinary plugin code
                # executes in this host, whose metadata also fences additions.
                audit_process = SimpleNamespace(audit=host_audit)
                snapshot = (await audit_process.audit(spec)).snapshot
            # A selected interpreter can expose package sites absent from the
            # host's sys.path (including an active user site). Retain its real
            # audited roots before the additive writer admits another audit.
            from .dependency_maintenance import lease_environment

            await run_sync_io(
                lease_environment,
                (target,) if frozen else snapshot.dependency_sites or (),
            )
            from .dependency_usage import current_admission_token

            if not frozen:
                context = await run_sync_io(
                    self._dependency_environment,
                    snapshot,
                )
                target = context.install_target
            validate_runtime_selection()
            try:
                await prepare_shared_dependencies(
                    audit_process,
                    spec,
                    plugin_id=plugin_id,
                    requirements_file=requirements_file,
                    usage_registry=usage,
                    admission_token=current_admission_token(
                        usage,
                        plugin_id,
                        root,
                    ),
                    install_target=target,
                    targets=snapshot.dependency_sites or (),
                )
            except SharedDependencyError as exc:
                if exc.decision.require_restart or exc.decision.unsupported:
                    raise
                if target is None:
                    raise RuntimeError(
                        "DEPENDENCY_ENVIRONMENT_AMBIGUOUS",
                    ) from exc
                await self._acquire_dependency_wheels(
                    audit_process,
                    spec,
                    snapshot,
                    target,
                    plugin_id,
                    requirements_file,
                    source_path=root,
                    wheel_tags=wheel_tags,
                    dependency_context=context if frozen else None,
                )
            if frozen:
                await self._publish_dependency_site(
                    target,
                    validate=validate_runtime_selection,
                )
            return GateDecision(False, True, reason="already satisfied")
        except Exception:
            if identity_error is not None:
                raise identity_error
            raise
        finally:
            try:
                observed = getattr(process, "dependency_snapshot", None)
                if token is not None and observed is not None:
                    usage.observe(lease, observed)
            finally:
                try:
                    await self._finish_preparation(lease)
                finally:
                    usage.withdraw(token)

    async def _acquire_dependency_wheels(
        self,
        process,
        spec,
        snapshot,
        target,
        plugin_id,
        requirements_file,
        *,
        source_path=None,
        wheel_tags=None,
        dependency_context=None,
    ):
        """Build/stage wheels; the shared gate owns actual package writes."""
        import hashlib
        from packaging.utils import parse_wheel_filename
        from .dependency_gate import (
            SharedDependencyError,
            WheelAddition,
            prepare_shared_dependencies,
        )

        from .dependency_usage import current_admission_token
        from ..utils.io_utils import run_sync_io

        async def run(command):
            return await run_sync_io(
                self._run_subprocess_with_streaming_log,
                command,
                timeout=300,
                plugin_id=plugin_id,
            )

        runtime = getattr(self.registry, "channel_runtime", None)
        if (
            dependency_context is None
            and getattr(runtime, "runtime_identity", None) is not None
        ):
            from .dependency_context import DependencyEnvironmentContext

            dependency_context = await run_sync_io(
                DependencyEnvironmentContext.from_runtime,
                runtime,
            )
        usage = self.registry.dependency_usage
        immutable = (
            await run_sync_io(dependency_context.immutable_providers)
            if dependency_context is not None
            else {}
        )
        if immutable:
            from .dependency_gate import parse_requirements_file
            from .execution.dependencies import _dependency_closure

            parsed = await run_sync_io(
                parse_requirements_file,
                requirements_file,
            )
            for name, requirement in _dependency_closure(
                [
                    *(str(item) for item in parsed.requirements),
                    CERTIFI_REQUIREMENT,
                ],
                {**immutable, **snapshot.distributions},
                snapshot.marker_environment,
            ):
                if name in immutable and (
                    name not in snapshot.distributions
                    or not requirement.specifier.contains(
                        immutable[name]["version"],
                        prereleases=True,
                    )
                ):
                    dependency_context.refuse_immutable_provider(
                        name,
                        immutable[name],
                    )
        cleanup = ExitStack()
        try:
            temporary = await run_sync_io(
                lambda: cleanup.enter_context(
                    tempfile.TemporaryDirectory(
                        prefix="qwenpaw-dependency-wheels-",
                    ),
                ),
            )
            staging = Path(temporary)
            constraints = staging / "constraints.txt"
            resolver = staging / "requirements.txt"

            def prepare_requirements():
                resolver.write_text(
                    requirements_file.read_text(encoding="utf-8")
                    + "\n"
                    + CERTIFI_REQUIREMENT
                    + "\n",
                    encoding="utf-8",
                )

            await run_sync_io(prepare_requirements)

            def constrain(observed):
                constraints.write_text(
                    "".join(
                        f"{name}=={row['version']}\n"
                        for name, row in observed.distributions.items()
                    )
                    + "".join(
                        f"{name}=={row['version']}\n"
                        for name, row in immutable.items()
                        if name not in observed.distributions
                        or row["version"]
                        != observed.distributions[name]["version"]
                    ),
                    encoding="utf-8",
                )

            if not await run_sync_io(
                require_pip,
                spec.python_executable,
                isolated=True,
            ):
                if _is_frozen() or (
                    dependency_context is not None
                    and dependency_context.runtime_identity is not None
                ):
                    raise RuntimeError(
                        "DEPENDENCY_INSTALLER_UNAVAILABLE: bundled pip is "
                        "missing; update QwenPaw Desktop.",
                    )
                # ensurepip uses bundled wheels, without upgrading installed
                # packages. Only a missing installer authorizes this retry.
                bootstrap = await run(
                    [spec.python_executable, "-I", "-m", "ensurepip"],
                )
                if not bootstrap.returncode:
                    snapshot = (await process.audit(spec)).snapshot
                if bootstrap.returncode or not await run_sync_io(
                    require_pip,
                    spec.python_executable,
                    isolated=True,
                ):
                    raise SharedDependencyError(
                        GateDecision(
                            False,
                            False,
                            reason="DEPENDENCY_INSTALLER_UNAVAILABLE",
                            reason_code="DEPENDENCY_INSTALLER_UNAVAILABLE",
                        ),
                    )
            await run_sync_io(constrain, snapshot)
            command = [
                spec.python_executable,
                "-I",
                "-B",
                "-m",
                "pip",
                "wheel",
                "--disable-pip-version-check",
                "--no-input",
                "--wheel-dir",
                str(staging),
                "--constraint",
                str(constraints),
                "-r",
                str(resolver),
            ]
            result = await run(command)
            if result.returncode:
                unpinned = command.copy()
                index = unpinned.index("--constraint")
                del unpinned[index : index + 2]
                control_cleanup = ExitStack()
                try:
                    control = await run_sync_io(
                        lambda: control_cleanup.enter_context(
                            tempfile.TemporaryDirectory(
                                prefix="qwenpaw-dependency-control-",
                            ),
                        ),
                    )
                    unpinned[unpinned.index("--wheel-dir") + 1] = control
                    resolved = await run(unpinned)
                finally:
                    await run_sync_io(control_cleanup.close)
                restart = resolved.returncode == 0
                code = (
                    "DEPENDENCY_RESTART_REQUIRED"
                    if restart
                    else "DEPENDENCY_PLAN_UNVERIFIED"
                )
                raise SharedDependencyError(
                    GateDecision(
                        False,
                        False,
                        require_restart=restart,
                        reason=(
                            f"{code}: complete wheels compatible with "
                            "installed versions required"
                        ),
                        reason_code=code,
                    ),
                )

            def collect_wheels():
                wheels = tuple(
                    WheelAddition(
                        path,
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                    for path in staging.glob("*.whl")
                    if str(parse_wheel_filename(path.name)[0])
                    not in snapshot.distributions
                )
                for item in wheels:
                    name = str(parse_wheel_filename(item.path.name)[0])
                    if name in immutable:
                        dependency_context.refuse_immutable_provider(
                            name,
                            immutable[name],
                        )
                return wheels

            wheels = await run_sync_io(collect_wheels)
            await prepare_shared_dependencies(
                process,
                spec,
                plugin_id=plugin_id,
                requirements_file=resolver,
                usage_registry=usage,
                admission_token=current_admission_token(
                    usage,
                    plugin_id,
                    source_path or spec.code_root,
                ),
                install_target=target,
                wheels=wheels,
                expected_snapshot=snapshot,
                wheel_tags=wheel_tags,
                installer_python=spec.python_executable,
                collision_sites=(
                    dependency_context.immutable_roots
                    if dependency_context
                    else ()
                ),
            )
        finally:
            await run_sync_io(cleanup.close)

    async def _load_backend_module(
        self,
        plugin_id,
        backend_entry_file,
        source_path,
        config,
        manifest,
    ):
        """Compatibility entry retaining import/register cleanup scope."""
        from ..utils.io_utils import run_sync_io

        description = await run_sync_io(
            self._python_backend.describe,
            source_path,
            manifest,
        )
        binding = BackendBinding(self._python_backend, description)
        async with self._dependency_registration(
            binding,
        ) as dependency_token:
            snapshot = await self.lifecycle.prepare_backend(
                binding,
                allow_install=False,
                probe=False,
            )
            await self._admit_dependencies(binding, dependency_token, snapshot)
            with registration_scope(binding):
                definition = self._python_backend.import_definition(
                    plugin_id,
                    backend_entry_file,
                    source_path,
                )
                await self._invoke_plugin_register(
                    plugin_id,
                    definition,
                    config,
                    _manifest_as_dict(manifest),
                    dependency_token=dependency_token,
                )
        return definition

    async def _invoke_plugin_register(
        self,
        plugin_id: str,
        plugin_def: Any,
        config: Optional[Dict],
        manifest_dict: Dict[str, Any],
        *,
        dependency_token=None,
    ) -> None:
        """Bind the current instance and run ``plugin_def.register``."""
        from .settings import runtime_config
        from qwenpaw.market import market_registry

        api = PluginApi(
            plugin_id,
            runtime_config(config),
            manifest_dict,
            dependency_token=dependency_token,
        )
        api.set_registry(self.registry)
        instance = self.lifecycle.ensure_instance(plugin_id)
        instance.refuse_unquiescent_reregister()
        api.bind_instance(instance, loader=self)
        if manifest_dict.get("sdk") is not None:
            from .sdk import PluginContext

            api = PluginContext(api)
            instance.sdk_context = api
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
        market_registry.begin_load(plugin_id)
        instance.accepts_provision_declarations = True
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
        finally:
            instance.accepts_provision_declarations = False
        market_registry.finish_load(plugin_id)

    async def _observe_host_dependencies(self, binding, token):
        observer = getattr(binding.backend, "observe_host_dependencies", None)
        if observer is not None:
            result = observer(
                binding.description,
                self.registry.dependency_usage,
                token,
            )
            if inspect.isawaitable(result):
                await result

    @asynccontextmanager
    async def _dependency_registration(
        self,
        binding,
        *,
        enabled=True,
        pending=True,
        admission=None,
        attach=True,
    ):
        """Own a declaration locally or transfer it to a runtime ledger."""
        if not enabled:
            yield None
            return
        description = binding.description
        usage = self.registry.dependency_usage
        from ..utils.io_utils import run_async_to_completion
        from .dependency_usage import admission_context
        from .install_lock import environment_coordinator

        admission = admission or _DependencyAdmission(binding)
        if admission.token is None:
            prepare = getattr(
                binding.backend,
                "prepare_dependency_targets",
                None,
            )
            prepared = (
                await prepare(description) if prepare is not None else None
            )
            async with environment_coordinator(
                prepared.targets if prepared else (),
            ):
                if prepared is not None:
                    prepared.validate()
                admission.token = usage.declare(
                    description.dependency_declaration(),
                    pending=pending,
                )
        elif (
            admission.released
            or admission.attached
            or admission.binding.backend is not binding.backend
            or admission.binding.description.dependency_declaration()
            != description.dependency_declaration()
            or not usage.has_declaration(
                admission.token,
                plugin_id=description.manifest.id,
            )
        ):
            raise RuntimeError("DEPENDENCY_ADMISSION_MISMATCH")
        token = admission.token
        context = admission_context.set(
            (usage, token, asyncio.current_task(), description),
        )

        async def observe():
            if not admission.released:
                await self._observe_host_dependencies(binding, token)

        async def withdraw():
            async def cleanup():
                if not admission.released:
                    if attach:
                        await observe()
                    usage.withdraw(token)
                    admission.released = True

            await run_async_to_completion(cleanup())

        try:
            if attach:
                self.lifecycle.ensure_instance(
                    description.manifest.id,
                ).record_runtime(
                    "dependency_declaration",
                    withdraw,
                )
                admission.attached = True
            yield token
            if attach:
                await observe()
        except BaseException:
            if attach:
                await withdraw()
            raise
        finally:
            try:
                if not attach and not admission.attached:
                    await withdraw()
            finally:
                admission_context.reset(context)

    async def _admit_dependencies(self, binding, token, snapshot):
        """Commit exact evidence before host definitions or business start."""
        if token is None:
            return None
        from .dependency_gate import admit_shared_dependencies

        audit = getattr(binding.backend, "audit_dependencies", None)
        if audit is None:
            raise RuntimeError(
                "DEPENDENCY_PLAN_UNVERIFIED: fresh audit unavailable",
            )

        prepared = None
        if snapshot is None:
            prepare = getattr(
                binding.backend,
                "prepare_dependency_targets",
                None,
            )
            if prepare is not None:
                prepared = await prepare(binding.description)
        return await admit_shared_dependencies(
            lambda: audit(binding.description),
            plugin_id=binding.description.manifest.id,
            requirements_file=None,
            usage_registry=self.registry.dependency_usage,
            admission_token=token,
            snapshot=snapshot,
            targets=prepared.targets if prepared is not None else (),
            validate=prepared.validate if prepared is not None else None,
        )

    async def _dispose_then_undo_txn_disk(
        self,
        plugin_id: str,
        instance,
        *,
        use_teardown: bool = False,
        undo_disk=None,
    ) -> UnloadReport | None:
        """Dispose first; only then undo this-txn create/migrate."""
        if instance is None:
            return None
        try:
            if use_teardown:
                report = await self.teardown_config_runtime(
                    plugin_id,
                    instance,
                )
            else:
                report = await instance.dispose(UnloadMode.UNLOAD)
        except BaseException:
            instance.add_diagnostic("needs_restart")
            raise
        if not report.quiescent:
            instance.add_diagnostic("needs_restart")
            return report
        try:
            if undo_disk is not None:
                maybe = undo_disk()
                if inspect.isawaitable(maybe):
                    await maybe
            else:
                await self._undo_failed_txn_disk(plugin_id, instance)
            instance.clear_txn_escapes()
            instance.clear_created_dests()
        except (Exception, asyncio.CancelledError) as undo_exc:  # noqa: BLE001
            report.clean = False
            if self._note_disk_recovery_failure(undo_exc):
                report.needs_restart = True
            report.errors.append(str(undo_exc) or type(undo_exc).__name__)
            instance.add_diagnostic(
                str(undo_exc) or type(undo_exc).__name__,
            )
            failed_descs = getattr(undo_exc, "failed_descs", None)
            if failed_descs is not None:
                instance.retain_txn_escapes(failed_descs)
            instance.state = PluginState.FAILED
            if isinstance(undo_exc, asyncio.CancelledError):
                instance.add_diagnostic("needs_restart")
                raise
        return report

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
        loop = asyncio.get_running_loop()

        def _undo() -> None:
            undo_this_txn_escapes(plugin_id, escapes, loop=loop)
            undo_created_locations(plugin_id, dests)
            recover_migrating_inventory(plugin_id, raise_on_blocked=True)

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
        reason = str(exc) or type(exc).__name__
        record = PluginRecord(
            manifest=manifest,
            source_path=source_path,
            enabled=False,
            diagnostics=[reason]
            + [item for item in live.diagnostics if item != reason],
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

        del module_name  # Kept for callers of this compatibility method.
        # 1. Registry (manifest, providers, hooks, middleware, routes, …)
        self.registry.unregister_plugin(plugin_id)

        self._python_backend.cleanup_imports(plugin_id, source_path)

    async def load_plugin(
        self,
        manifest: PluginManifest,
        source_path: Path,
        config: Optional[Dict] = None,
        *,
        allow_install: bool = False,
        activate: bool = True,
        backend_binding=None,
        prepared=False,
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
                backend_binding=backend_binding,
                prepared=prepared,
            )

    # pylint: disable=too-many-statements,too-many-return-statements
    # pylint: disable=too-many-branches
    async def _load_plugin_unlocked(
        self,
        manifest,
        source_path,
        config=None,
        *,
        allow_install=False,
        activate=False,
        generation=None,
        saved_plugin_def=None,
        allow_existing=True,
        backend_binding=None,
        prepared=False,
        dependency_admission=None,
    ) -> PluginRecord:
        """Load through a binding; retain public registration and ledger."""
        from ..utils.io_utils import run_sync_io

        plugin_id = manifest.id
        from .sdk_version import validate_sdk

        validate_sdk(manifest.sdk, manifest.id)
        if not self.lifecycle.delegate.owns_commit(plugin_id):
            raise RuntimeError(
                f"Plugin '{plugin_id}' commit is not owned by this process",
            )
        self._require_recovered(plugin_id)
        if plugin_id in self._loaded_plugins:
            if not allow_existing:
                raise RuntimeError(
                    f"Plugin '{plugin_id}' is still loaded; "
                    "refuse to restore over an existing record",
                )
            return self._loaded_plugins[plugin_id]
        binding = backend_binding or await run_sync_io(
            self.backend_resolver.resolve,
            source_path,
            manifest,
        )
        manifest = binding.description.manifest
        if activate:
            await binding.backend.before_activate(binding.description)
        previous_instance = self.lifecycle.get_instance(plugin_id)
        instance = self.lifecycle.ensure_instance(
            plugin_id,
            generation=generation,
        )
        instance.source_path = source_path
        self._add_recovery_diagnostics(plugin_id)
        from .settings import runtime_config, is_plugin_enabled

        if config is None:
            from ..config import load_config

            config = load_config().plugins.get(plugin_id, {})

        instance.config = runtime_config(config)
        if not is_plugin_enabled(config) and not discovers_disabled(binding):
            record = await self._inactive_record(binding, config)
            self._loaded_plugins[plugin_id] = record
            return record
        compatible, message = self._check_version_compatibility(manifest)
        if not compatible:
            record = self._record_failed_backend(
                manifest,
                source_path,
                RuntimeError(message),
            )
            record.backend_binding = binding
            return record
        definition_started = False
        try:
            static_discovery = not activate and discovers_disabled(binding)
            async with self._dependency_registration(
                binding,
                enabled=is_plugin_enabled(config),
                pending=not static_discovery,
                admission=dependency_admission,
            ) as dependency_token:
                snapshot = (
                    dependency_admission.snapshot
                    if dependency_admission is not None
                    else None
                )
                if dependency_admission is not None:
                    # A saved Python definition may outlive its mutable files.
                    # New definitions must still match preflight dependencies.
                    if saved_plugin_def is None:
                        fresh = await run_sync_io(
                            binding.backend.describe,
                            source_path,
                            manifest,
                        )
                        if (
                            fresh.dependency_declaration()
                            != binding.description.dependency_declaration()
                        ):
                            raise RuntimeError(
                                "DEPENDENCY_PLAN_UNVERIFIED: "
                                "admission source changed",
                            )
                if not prepared:
                    snapshot = await self.lifecycle.prepare_backend(
                        binding,
                        allow_install=allow_install,
                        probe=is_plugin_enabled(config)
                        and not static_discovery
                        and probes_before_activation(binding),
                    )
                if not static_discovery:
                    if dependency_admission is not None:
                        await self._observe_host_dependencies(
                            binding,
                            dependency_token,
                        )
                    await self._admit_dependencies(
                        binding,
                        dependency_token,
                        snapshot,
                    )
                definition_started = True
                with registration_scope(binding):
                    result = await binding.backend.load_definition(
                        binding.description,
                        config or {},
                        saved_definition=saved_plugin_def,
                    )
                    if result.definition is not None:
                        register = (
                            self._reregister_body
                            if saved_plugin_def is not None
                            else self._invoke_plugin_register
                        )
                        await register(
                            plugin_id,
                            result.definition,
                            config,
                            _manifest_as_dict(manifest),
                            dependency_token=dependency_token,
                        )
        except BaseException as exc:
            if isinstance(exc, _EntryPointNotFoundError):
                raise
            from .dependency_gate import SharedDependencyError
            from .errors import SDKRestartRequiredError

            if isinstance(exc, SDKRestartRequiredError) or (
                binding.backend is self._python_backend
                and not definition_started
                and not isinstance(exc, SharedDependencyError)
            ):
                reclaimed = False
                if (
                    instance is not previous_instance
                    and not instance.activated
                    and not self._has_runtime_custody(plugin_id)
                ):
                    report = await instance.dispose(UnloadMode.UNLOAD)
                    if report.clean and report.quiescent:
                        self.lifecycle.drop_instance(plugin_id)
                        reclaimed = True
                if not reclaimed:
                    record = self._record_failed_backend(
                        manifest,
                        source_path,
                        exc,
                    )
                    record.backend_binding = binding
                raise
            record = self._record_failed_backend(manifest, source_path, exc)
            record.backend_binding = binding
            if isinstance(exc, asyncio.CancelledError):
                raise
            return record
        record = PluginRecord(
            manifest=manifest,
            source_path=source_path,
            enabled=is_plugin_enabled(config),
            global_enabled=is_plugin_enabled(config),
            backend_binding=binding,
        )
        self._apply_definition_result(record, result)
        self._loaded_plugins[plugin_id] = record
        if activate and record.enabled:
            try:
                if not prepared and probes_before_activation(binding):
                    await self.lifecycle.preflight_backend(
                        binding,
                        allow_install=False,
                        probe=True,
                    )
                await self.activate_plugin_unlocked(plugin_id)
            except BaseException as exc:
                if (
                    instance.activated
                    or record.status == "active"
                    or isinstance(exc, asyncio.CancelledError)
                ):
                    raise
                instance.mark_failed(str(exc))
                record.status = "failed"
                record.enabled = False
                record.diagnostics = list(instance.diagnostics)
        return record

    async def _recover_startup_transactions(self) -> None:
        """Recover leftovers under each id's lock, never a live transaction."""
        from ..utils.io_utils import run_sync_io
        from .provision import (
            provision_ids_to_recover,
            recover_migrating_inventory,
        )
        from .updates import (
            interrupted_update_ids,
            recover_interrupted_updates,
        )

        try:
            ids = await run_sync_io(
                lambda: set(interrupted_update_ids())
                | set(provision_ids_to_recover()),
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Startup recovery scan failed; continuing plugin discovery",
            )
            return
        ids.update(self._recovery_blocked)
        for plugin_id in sorted(ids):
            async with self.plugin_lifecycle(plugin_id):
                if not self.lifecycle.delegate.owns_commit(plugin_id):
                    continue
                record = self._loaded_plugins.get(plugin_id)
                if record is not None and record.status in (
                    "registered",
                    "active",
                ):
                    continue
                instance = self.lifecycle.get_instance(plugin_id)
                if self._has_runtime_custody(plugin_id) or (
                    instance is not None and instance.has_runtime_ledger()
                ):
                    error = "Recovery has runtime resources; unload first"
                    self._recovery_blocked[plugin_id] = error
                    self._recovery_errors[plugin_id] = error
                    self._add_recovery_diagnostics(plugin_id)
                    continue

                blocked: dict[str, str] = {}
                errors: dict[str, str] = {}
                try:
                    updates = await run_sync_io(
                        recover_interrupted_updates,
                        plugin_id=plugin_id,
                    )
                    provisions = await run_sync_io(
                        recover_migrating_inventory,
                        plugin_id,
                    )
                    blocked.update(updates.blocked)
                    blocked.update(provisions.blocked)
                    errors.update(updates.failures)
                    errors.update(provisions.failures)
                except Exception as exc:  # noqa: BLE001
                    error = str(exc) or type(exc).__name__
                    blocked[plugin_id] = error
                    errors[plugin_id] = error
                    logger.exception(
                        "Startup recovery failed for '%s'",
                        plugin_id,
                    )
                if plugin_id in blocked:
                    self._recovery_blocked[plugin_id] = blocked[plugin_id]
                    manifest, path = next(
                        (
                            (manifest, path)
                            for manifest, path in await run_sync_io(
                                self.discover_plugins,
                            )
                            if manifest.id == plugin_id
                        ),
                        (
                            PluginManifest(id=plugin_id, version="unknown"),
                            (
                                self.plugin_dirs[0] / plugin_id
                                if self.plugin_dirs
                                else Path(plugin_id)
                            ),
                        ),
                    )
                    self._record_failed_backend(
                        manifest,
                        path,
                        RuntimeError(blocked[plugin_id]),
                    )
                elif self._recovery_blocked.pop(plugin_id, None) is not None:
                    self._loaded_plugins.pop(plugin_id, None)
                    self.lifecycle.drop_instance(plugin_id)
                self._recovery_errors.pop(plugin_id, None)
                self._recovery_errors.update(errors)
                if plugin_id in errors:
                    self._add_recovery_diagnostics(plugin_id)

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

        await self._recover_startup_transactions()
        discovered = await run_sync_io(self.discover_plugins)

        for manifest, plugin_dir in discovered:
            if types is not None and manifest.plugin_type not in types:
                continue
            from .settings import is_plugin_enabled

            async with self.plugin_lifecycle(manifest.id):
                if manifest.id in self._loaded_plugins:
                    continue
                config = configs.get(manifest.id) if configs else None
                try:
                    binding = await run_sync_io(
                        self.backend_resolver.resolve,
                        plugin_dir,
                        manifest,
                    )
                except Exception as exc:
                    self._record_failed_backend(manifest, plugin_dir, exc)
                    continue
                if not is_plugin_enabled(config) and not discovers_disabled(
                    binding,
                ):
                    logger.info(
                        "Skipping disabled plugin '%s'",
                        manifest.id,
                    )
                    continue

                try:
                    await self.load_plugin(
                        manifest,
                        plugin_dir,
                        config,
                        activate=activate,
                        backend_binding=binding,
                    )
                except Exception as e:
                    logger.error(f"Failed to load plugin '{manifest.id}': {e}")
        return self._loaded_plugins

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
        *,
        source_path: Path | None = None,
    ) -> None:
        """Explicit compatibility entry uses validated additive wheels only."""
        self._install_requirements_locked(
            requirements_file,
            plugin_id,
            source_path=source_path,
        )

    def _install_requirements_frozen(
        self,
        req: str,
        plugin_id: str,
        timeout: int,
    ) -> None:
        """Frozen callers use selected Python and the same safe writer."""
        del timeout
        self._install_requirements_locked(Path(req), plugin_id)

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
        before_unload: Optional[Any] = None,
        wheels=(),
        interrupt_tasks: bool = False,
    ) -> ReloadReport:
        """Reload one plugin while preventing new SDK invocations."""
        async with self.lifecycle.activity(plugin_id).mutation(
            interrupt_tasks=interrupt_tasks,
        ):
            return await self._reload_plugin_body(
                plugin_id,
                new_source=new_source,
                config=config,
                allow_install=allow_install,
                owns_dependency_env=owns_dependency_env,
                after_unload=after_unload,
                before_unload=before_unload,
                wheels=wheels,
            )

    async def _reload_plugin_body(self, plugin_id, **kwargs):
        """Keep temporary admissions owned through switch and recovery."""
        async with AsyncExitStack() as admissions:
            return await self._reload_plugin_transaction(
                plugin_id,
                admissions=admissions,
                **kwargs,
            )

    async def _reload_plugin_transaction(
        self,
        plugin_id: str,
        *,
        admissions,
        new_source: Optional[Path] = None,
        config: Optional[Dict] = None,
        allow_install: bool = False,
        owns_dependency_env: bool = True,
        after_unload: Optional[Any] = None,
        before_unload: Optional[Any] = None,
        wheels=(),
    ) -> ReloadReport:
        """Reload one plugin. Caller holds lifecycle and activity gates."""
        # pylint: disable=too-many-return-statements,too-many-branches
        from ..utils.io_utils import run_sync_io

        if not self.lifecycle.delegate.owns_commit(plugin_id):
            return ReloadReport(
                plugin_id=plugin_id,
                ok=False,
                unchanged=True,
                errors=["commit is not owned by this process"],
            )
        if plugin_id == "cloudpaw":
            from .legacy_cloudpaw import has_pending_uninstall

            if await run_sync_io(has_pending_uninstall, self):
                return ReloadReport(
                    plugin_id=plugin_id,
                    ok=False,
                    unchanged=True,
                    errors=[
                        "CloudPaw uninstall is incomplete; retry uninstall",
                    ],
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
        try:
            in_place = same_location(incoming, old_path)
            _, incoming_manifest = await run_sync_io(
                self._read_source_manifest,
                incoming,
            )
        except Exception as exc:
            return ReloadReport(
                plugin_id=plugin_id,
                ok=False,
                unchanged=True,
                errors=[f"incoming manifest invalid: {exc}"],
            )
        if incoming_manifest.id != plugin_id:
            return ReloadReport(
                plugin_id=plugin_id,
                ok=False,
                unchanged=True,
                errors=["Plugin identity changed"],
            )
        from .settings import is_plugin_enabled

        old_enabled = (
            record.global_enabled
            if record.global_enabled is not None
            else record.enabled
        )
        old_config = {**old_config, "enabled": old_enabled}
        config = {
            **(config if config is not None else old_config),
            "enabled": old_enabled,
        }
        # Unchanged old instances are expected custody, not failed preparation.
        old_runtime_leases = {
            lease
            for lease in self.registry.runtime_owners.leases(plugin_id)
            if inst is not None
            and inst.state is PluginState.ACTIVE
            and lease.key.kind != "preparation"
            and lease.code_root == old_path.resolve()
        }
        candidate_admission = None
        old_admission = None
        try:
            old_binding = await self._binding_for_record(record)
            candidate_binding = await run_sync_io(
                self.backend_resolver.resolve,
                incoming,
                incoming_manifest,
            )
            old_binding.validate_update(candidate_binding, in_place=in_place)
            if is_plugin_enabled(config):
                candidate_admission = _DependencyAdmission(candidate_binding)
                candidate_token = await admissions.enter_async_context(
                    self._dependency_registration(
                        candidate_binding,
                        admission=candidate_admission,
                        attach=False,
                    ),
                )
                await self._observe_host_dependencies(
                    candidate_binding,
                    candidate_token,
                )
                snapshot = await self.lifecycle.prepare_backend(
                    candidate_binding,
                    allow_install=allow_install,
                    probe=True,
                    wheels=wheels,
                    owns_dependency_env=owns_dependency_env,
                )
                candidate_admission.snapshot = await self._admit_dependencies(
                    candidate_binding,
                    candidate_token,
                    snapshot,
                )
                # Recovery owns separate evidence even if replacement cleanup
                # withdraws the candidate's exact declaration.
                old_admission = _DependencyAdmission(old_binding)
                old_token = await admissions.enter_async_context(
                    self._dependency_registration(
                        old_binding,
                        admission=old_admission,
                        attach=False,
                    ),
                )
                old_admission.snapshot = await self._admit_dependencies(
                    old_binding,
                    old_token,
                    candidate_admission.snapshot,
                )
        except Exception as exc:
            return ReloadReport(
                plugin_id=plugin_id,
                ok=False,
                unchanged=True,
                needs_restart=bool(
                    getattr(exc, "needs_restart", False)
                    or getattr(
                        getattr(exc, "decision", None),
                        "require_restart",
                        False,
                    ),
                )
                or any(
                    lease not in old_runtime_leases
                    for lease in self.registry.runtime_owners.leases(plugin_id)
                ),
                errors=[str(exc)],
                generation=old_generation,
            )
        # Callback rejection owns no replacement transaction to recover.
        await _invoke_after_unload(before_unload, plugin_id)
        old_restore_state = old_binding.backend.capture_restore_state(record)
        swapped: Path | None = None
        activated_new = False
        old_unloaded = False
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
                    errors=(
                        list(unload_report.errors)
                        or ["hosted resources did not go quiescent"]
                    )
                    + [
                        "New version was not enabled; "
                        "stopping the previous service was incomplete",
                    ],
                    generation=old_generation,
                )
            old_unloaded = True
            await _invoke_after_unload(after_unload, plugin_id)
            swapped = await self._swap_plugin_dir(
                plugin_id,
                old_path,
                incoming,
                preserve_marker_on_cancel=True,
            )
            target = old_path if swapped or in_place else incoming
            _, installed_manifest = await run_sync_io(
                self._read_source_manifest,
                target,
            )
            published_binding = await run_sync_io(
                candidate_binding.rebase,
                target,
                installed_manifest,
            )
            new_record = await self._load_plugin_unlocked(
                installed_manifest,
                target,
                config if config is not None else old_config,
                allow_install=allow_install,
                activate=True,
                generation=old_generation + 1,
                backend_binding=published_binding,
                prepared=True,
                dependency_admission=candidate_admission,
            )
            if new_record.status == "failed":
                raise RuntimeError(
                    (
                        new_record.diagnostics[0]
                        if new_record.diagnostics
                        else f"Plugin '{plugin_id}' failed to load"
                    ),
                )
            if not self._reload_already_committed(
                plugin_id,
                False,
                previous_instance=inst,
                generation=old_generation + 1,
            ):
                raise RuntimeError("New plugin instance did not activate")
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
                previous_instance=inst,
                generation=old_generation + 1,
            )
            restore: ReloadReport | None = None
            if not committed and not old_unloaded:
                if isinstance(exc, asyncio.CancelledError):
                    raise
                unchanged = (
                    self._loaded_plugins.get(plugin_id) is record
                    and self.lifecycle.get_instance(plugin_id) is inst
                    and record.status == "active"
                    and inst is not None
                    and inst.state is PluginState.ACTIVE
                    and inst.activated
                )
                return ReloadReport(
                    plugin_id=plugin_id,
                    ok=False,
                    unchanged=unchanged,
                    needs_restart=not unchanged,
                    errors=[
                        str(exc),
                        "New version was not enabled; "
                        + (
                            "previous service is still active"
                            if unchanged
                            else "stopping the previous service was incomplete"
                        ),
                    ],
                    generation=old_generation,
                )
            if not committed and (not occupied or old_path.exists()):
                restore = await self._rollback_reload(
                    plugin_id,
                    old_path,
                    old_config,
                    old_restore_state,
                    swapped,
                    incoming_manifest=record.manifest,
                    old_binding=old_binding,
                    owns_dependency_env=owns_dependency_env,
                    in_place=in_place,
                    saved_plugin_def=old_plugin_def,
                    generation=old_generation,
                    dependency_admission=old_admission,
                )
            if committed and not isinstance(exc, asyncio.CancelledError):
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
                errors.append(
                    "New version was not enabled; previous service "
                    + ("was restored" if restore.ok else "was not restored"),
                )
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
        *,
        previous_instance: Any,
        generation: int,
    ) -> bool:
        """Whether the new version is already the committed service."""
        if activated_new:
            return True
        instance = self.lifecycle.get_instance(plugin_id)
        current = self._loaded_plugins.get(plugin_id)
        return bool(
            instance is not None
            and instance is not previous_instance
            and instance.generation == generation
            and instance.state is PluginState.ACTIVE
            and instance.activated
            and current is not None
            and current.status == "active",
        )

    def _install_already_committed(self, plugin_id: str) -> bool:
        """Preserve a published install even when final cleanup fails."""
        instance = self.lifecycle.get_instance(plugin_id)
        current = self._loaded_plugins.get(plugin_id)
        if (instance is not None and instance.activated) or (
            current is not None and current.status == "active"
        ):
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
        from .updates import preserved_update_backup

        errors: list[str] = []
        try:
            await run_sync_io(mark_update_committed, plugin_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"mark committed failed: {exc}")
            return errors
        try:
            await run_sync_io(commit_prepared_migrations, plugin_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"commit prepared migrations failed: {exc}")
            return errors
        if swapped is not None:
            try:
                if (
                    await run_sync_io(preserved_update_backup, plugin_id)
                    is None
                ):
                    with self.registry.runtime_owners.mutation(swapped):
                        await run_sync_io(_remove_dir, swapped)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"committed backup cleanup failed: {exc}")
                return errors
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
        from .updates import (
            live_prepared_backup,
            marker_path,
            recover_one_update,
        )
        from .safe_fs import parse_optional_absolute

        backup = await run_sync_io(live_prepared_backup, plugin_id)
        if backup is None:
            return
        if self._has_runtime_custody(plugin_id):
            raise RuntimeError("CHANNEL_INSTANCE_STILL_OWNED; needs_restart")
        try:
            marker = await run_sync_io(
                lambda: json.loads(marker_path(plugin_id).read_text()),
            )
            if self._has_runtime_custody(plugin_id):
                raise RuntimeError(
                    "CHANNEL_INSTANCE_STILL_OWNED; needs_restart",
                )
            with self.registry.runtime_owners.mutation(
                backup,
                parse_optional_absolute(marker.get("target_path")),
                parse_optional_absolute(marker.get("staging_path")),
            ):
                await run_sync_io(recover_one_update, plugin_id)
        except (OSError, shutil.Error) as exc:
            raise RuntimeError(
                f"plugin directory is in use; restart required: {exc}",
            ) from exc
        if await run_sync_io(live_prepared_backup, plugin_id) is not None:
            raise RuntimeError(
                "plugin directory is in use; restart required",
            )

    async def _swap_plugin_dir(
        self,
        plugin_id: str,
        old_path: Path,
        incoming: Path,
        *,
        preserve_marker_on_cancel: bool = False,
        allow_incomplete_target: bool = False,
    ) -> Path | None:
        """Stage on the same volume, then short-swap. None if in-place."""
        if not self.lifecycle.delegate.owns_commit(plugin_id):
            return None
        if same_location(incoming, old_path):
            return None
        if self._has_runtime_custody(plugin_id):
            raise RuntimeError("RUNTIME_STILL_OWNED; needs_restart")
        from ..utils.io_utils import run_async_to_completion, run_sync_io
        from .updates import allocate_update_backup_path, write_updating_marker

        await self._recover_or_refuse_prepared_update(plugin_id)
        staging = old_path.with_name(old_path.name + f".{plugin_id}.staging")
        instance = self.lifecycle.get_instance(plugin_id)
        has_runtime = instance is not None and instance.has_runtime_ledger()

        def prepare():
            old_identity = None
            try:
                if (old_path / "plugin.json").is_symlink():
                    raise RuntimeError("refusing to replace a linked manifest")
                old_manifest = self._load_manifest(
                    resolved_plugin_manifest_path(old_path),
                )
            except (FileNotFoundError, ValueError) as exc:
                if not allow_incomplete_target:
                    raise
                if (
                    old_path.is_symlink()
                    or not old_path.is_dir()
                    or has_runtime
                ):
                    raise RuntimeError(
                        "incomplete plugin target is not quiescent",
                    ) from exc
                identity = old_path.lstat()
                old_identity = (identity.st_dev, identity.st_ino)
                old_manifest = None
            if old_manifest is not None and old_manifest.id != plugin_id:
                raise ValueError("existing plugin manifest has a different id")
            backup = allocate_update_backup_path(old_path, plugin_id)
            if old_identity is not None:
                backup = backup.with_name("." + backup.name)
            return old_manifest, old_identity, backup

        old_manifest, old_identity, backup = await run_sync_io(prepare)

        def _mark_phase(phase: str) -> None:
            write_updating_marker(
                plugin_id,
                backup_path=backup,
                target_path=old_path,
                staging_path=staging,
                phase=phase,
                old_version=old_manifest.version if old_manifest else None,
                preserve_backup=old_identity is not None,
                old_identity=old_identity,
            )

        def _swap() -> None:
            _mark_phase("staging")
            if staging.exists():
                safe_remove(staging, purpose="clear plugin staging")
            shutil.copytree(incoming, staging)
            if not (staging / "plugin.json").exists():
                raise RuntimeError("staged plugin is missing plugin.json")
            if backup.exists():
                raise RuntimeError(
                    f"refusing to clobber existing plugin backup: {backup}",
                )
            _mark_phase("swapping")
            shutil.move(str(old_path), str(backup))
            shutil.move(str(staging), str(old_path))

        try:
            with self.registry.runtime_owners.mutation(
                old_path,
                incoming,
                staging,
                backup,
            ):
                await run_sync_io(_swap)
        except asyncio.CancelledError:
            # The worker completed, but its backup was not returned. Restore
            # using the paths owned before awaiting it, then propagate cancel.
            try:
                await run_async_to_completion(
                    self._restore_failed_swap(
                        plugin_id,
                        old_path,
                        backup,
                        staging,
                        clear_marker_if_restored=not preserve_marker_on_cancel,
                    ),
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Cancelled swap recovery failed for plugin '%s'",
                    plugin_id,
                )
            raise
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
        from .updates import (
            clear_updating_marker,
            mark_update_restored,
            preserved_update_backup,
        )

        if self._has_runtime_custody(plugin_id):
            raise RuntimeError("RUNTIME_STILL_OWNED; needs_restart")

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
            if (
                not clear_marker_if_restored
                or preserved_update_backup(plugin_id) is not None
            ):
                mark_update_restored(plugin_id)

        try:
            with self.registry.runtime_owners.mutation(
                old_path,
                backup,
                staging,
            ):
                await run_sync_io(_restore)
                if clear_marker_if_restored and old_path.exists():
                    await run_sync_io(clear_updating_marker, plugin_id)
                    if backup.exists():
                        await run_sync_io(_remove_dir, backup)
        except Exception as exc:  # noqa: BLE001
            error = f"plugin directory recovery failed: {exc}"
            self._recovery_blocked[plugin_id] = error
            self._recovery_errors[plugin_id] = error
            self._add_recovery_diagnostics(plugin_id)
            self.lifecycle.ensure_instance(
                plugin_id,
            ).state = PluginState.FAILED
            logger.exception(
                "Could not restore plugin '%s' after a failed swap",
                plugin_id,
            )
            raise

    async def _rollback_reload(
        self,
        plugin_id: str,
        old_path: Path,
        old_config: Dict,
        snapshot: object | None,
        backup: Path | None,
        *,
        incoming_manifest: PluginManifest,
        in_place: bool = False,
        saved_plugin_def: Any = None,
        generation: int = 0,
        old_binding=None,
        owns_dependency_env=True,
        dependency_admission=None,
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
        if plugin_id in self._recovery_blocked:
            failed.errors.append(self._recovery_errors[plugin_id])
            return failed
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
        try:
            await run_sync_io(
                recover_migrating_inventory,
                plugin_id,
                raise_on_blocked=True,
            )
        except Exception as exc:  # noqa: BLE001
            self._note_disk_recovery_failure(exc)
            failed.errors.append(f"provision recovery failed: {exc}")
            return failed
        if self._has_runtime_custody(plugin_id):
            failed.errors.append("CHANNEL_INSTANCE_STILL_OWNED; needs_restart")
            return failed
        from .updates import live_prepared_backup

        backup = backup or await run_sync_io(live_prepared_backup, plugin_id)
        if self._has_runtime_custody(plugin_id):
            failed.errors.append("CHANNEL_INSTANCE_STILL_OWNED; needs_restart")
            return failed
        if backup is not None and backup.exists():
            try:
                await self._restore_failed_swap(
                    plugin_id,
                    old_path,
                    backup,
                    old_path.with_name(
                        old_path.name + f".{plugin_id}.staging",
                    ),
                    clear_marker_if_restored=False,
                )
            except Exception as exc:  # noqa: BLE001
                failed.errors.append(f"directory recovery failed: {exc}")
                return failed
        try:
            restoring_saved_definition = (
                in_place
                and saved_plugin_def is not None
                and dependency_admission is not None
                and old_binding is not None
                and old_binding.backend is self._python_backend
            )
            if restoring_saved_definition:
                restored_manifest = old_binding.description.manifest
            else:
                _, restored_manifest = await run_sync_io(
                    self._read_source_manifest,
                    old_path,
                )
            if old_binding is None:
                old_binding = await run_sync_io(
                    self.backend_resolver.resolve,
                    old_path,
                    incoming_manifest,
                )
            if in_place and old_binding.description.source_identity is None:
                # Mutable sources have no backup; the running old definition
                # and import snapshot retain their original manifest.
                restored_binding = old_binding
                restored_manifest = old_binding.description.manifest
            else:
                restored_binding = await run_sync_io(
                    old_binding.rebase,
                    old_path,
                    restored_manifest,
                )
            old_binding.backend.restore_state(snapshot)
            # Saved Python code uses its original admitted declaration. Its
            # mutable source can now describe the rejected candidate instead.
            if (
                old_config.get("enabled", True)
                and not restoring_saved_definition
            ):
                await self.lifecycle.preflight_backend(
                    restored_binding,
                    allow_install=False,
                    probe=probes_before_activation(restored_binding),
                    owns_dependency_env=owns_dependency_env,
                )
            record = await self._load_plugin_unlocked(
                restored_manifest,
                old_path,
                old_config,
                allow_install=False,
                activate=True,
                generation=generation,
                saved_plugin_def=saved_plugin_def if in_place else None,
                allow_existing=False,
                backend_binding=restored_binding,
                prepared=True,
                dependency_admission=dependency_admission,
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
            record.status not in {"active", "inactive"}
            or instance is None
            or (record.status == "active" and not instance.activated)
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

    async def seed_bundled_channel(self, source_path: Path, config=None):
        """Publish absent official source without dependency or SDK work."""
        from ..utils.io_utils import run_sync_io

        from .official_channel_catalog import official_channel_for_plugin
        from .settings import is_plugin_enabled

        source_path = Path(source_path).resolve()
        _, manifest = await run_sync_io(
            self._read_source_manifest,
            source_path,
        )
        description = await run_sync_io(
            describe_channel,
            source_path,
            manifest,
        )
        official = official_channel_for_plugin(manifest.id)
        if (
            official is None
            or description.descriptor.channel_key != official["channel_key"]
        ):
            raise ValueError("Unknown official channel owner")
        compatible, reason = self._check_version_compatibility(manifest)
        if not compatible:
            raise ValueError(reason)
        async with self.plugin_lifecycle(manifest.id):
            self._require_recovered(manifest.id)
            if self.find_installed_plugin_dir(manifest.id) is not None:
                raise ValueError("Official source already exists")
            # Reuse A first-copy/publication, never replacement.
            record = await self._load_plugin_from_path_unlocked(
                description.code_root,
                manifest,
                config,
                enabled=is_plugin_enabled(config),
                _bundled_seed=True,
            )
            if "channel_validation_pending" not in record.diagnostics:
                record.diagnostics.append("channel_validation_pending")
            return record

    def _install_paths(
        self,
        plugin_id: str,
        install_dir: Path | None,
    ) -> Tuple[Path, Path]:
        """Resolve and validate the installation target before side effects."""
        if install_dir is None:
            if not self.plugin_dirs:
                raise RuntimeError("No plugin directories configured")
            install_dir = self.plugin_dirs[0]
        base = Path(install_dir).resolve()
        target = (base / plugin_id).resolve()
        if target == base or not target.is_relative_to(base):
            raise ValueError(
                f"Plugin id '{plugin_id}' does not resolve to a safe child "
                f"of the plugin directory ({base}). Refusing to install.",
            )
        return base, target

    async def install_plugin_files(
        self,
        source_path: Path,
        *,
        force: bool = False,
    ) -> PluginRecord:
        """Install offline without registering or starting resources."""
        from ..utils.io_utils import run_sync_io

        source_path = await asyncio.to_thread(Path(source_path).resolve)
        _, manifest = await asyncio.to_thread(
            self._read_source_manifest,
            source_path,
        )
        async with self.plugin_lifecycle(manifest.id):
            self._require_recovered(manifest.id)
            if not self.lifecycle.delegate.owns_commit(manifest.id):
                raise RuntimeError(
                    f"Plugin '{manifest.id}' commit is not owned "
                    "by this process",
                )
            _, target = await asyncio.to_thread(
                self._install_paths,
                manifest.id,
                None,
            )
            if await asyncio.to_thread(target.exists) and not force:
                raise ValueError(
                    f"Plugin '{manifest.id}' already exists. "
                    "Use --force to reinstall.",
                )
            await self._recover_or_refuse_prepared_update(manifest.id)
            binding = await run_sync_io(
                self.backend_resolver.resolve,
                source_path,
                manifest,
            )
            if manifest.entry.backend:
                from .module_isolation import compile_plugin_import_closure

                entry = source_path / manifest.entry.backend
                await run_sync_io(
                    compile_plugin_import_closure,
                    entry,
                    [str(entry.parent), str(source_path)],
                )
            await self.lifecycle.preflight_backend(
                binding,
                allow_install=True,
                probe=False,
            )
            record = await self._load_plugin_from_path_unlocked(
                source_path,
                manifest,
                replace_files=force,
                enabled=False,
            )
            from .settings import clear_channel_tombstone

            await asyncio.to_thread(clear_channel_tombstone, manifest.id)
            return record

    async def load_plugin_from_path(
        self,
        source_path: Path,
        config: Optional[Dict] = None,
        install_dir: Optional[Path] = None,
        *,
        force: bool = False,
        wheels=(),
        interrupt_tasks: bool = False,
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
                report = await self.reload_plugin_unlocked(
                    plugin_id,
                    new_source=source_path,
                    interrupt_tasks=interrupt_tasks,
                    config=config,
                    allow_install=True,
                    owns_dependency_env=(
                        self.lifecycle.delegate.owns_dependency_env(
                            plugin_id,
                        )
                    ),
                    after_unload=after_force_unload,
                    before_unload=before_force_unload,
                    wheels=wheels,
                )
                if not report.ok:
                    detail = (
                        "; ".join(report.errors)
                        if report.errors
                        else f"Reload of '{plugin_id}' failed"
                    )
                    if manifest.sdk is not None and report.needs_restart:
                        from .errors import SDKRestartRequiredError

                        raise SDKRestartRequiredError(detail)
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
                from .settings import clear_channel_tombstone

                await asyncio.to_thread(clear_channel_tombstone, plugin_id)
                return record
            record = None
            from ..config import load_config
            from .settings import is_plugin_enabled, runtime_config

            saved = await asyncio.to_thread(load_config)
            settings = (saved.plugins or {}).get(plugin_id)
            enabled = is_plugin_enabled(settings)
            incoming = runtime_config(
                config if config is not None else settings,
            )
            try:
                record = await self._load_plugin_from_path_unlocked(
                    source_path,
                    manifest,
                    incoming,
                    install_dir,
                    replace_files=force,
                    pawport_owner=pawport_owner,
                    recover_incomplete=recover_incomplete,
                    enabled=enabled,
                    wheels=wheels,
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
                from .settings import clear_channel_tombstone

                await asyncio.to_thread(clear_channel_tombstone, plugin_id)
                return record
            except BaseException:
                already_committed = self._install_already_committed(plugin_id)
                if (
                    record is not None
                    and plugin_id in self._loaded_plugins
                    and not already_committed
                ):
                    await self._unload_plugin_unlocked(
                        plugin_id,
                        delete_files=False,
                    )
                if (
                    record is not None
                    and pawport_owner is not None
                    and not already_committed
                ):
                    await self._remove_incomplete_pawport_plugin(
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
        enabled: bool = True,
        wheels=(),
        _bundled_seed=False,
    ) -> PluginRecord:
        """Install+load from path; caller must hold lifecycle for id."""
        from ..utils.io_utils import run_sync_io

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

        candidate_binding = await run_sync_io(
            self.backend_resolver.resolve,
            source_path,
            manifest,
        )
        if not _bundled_seed:
            await candidate_binding.backend.before_activate(
                candidate_binding.description,
            )

        install_base, target_dir = await asyncio.to_thread(
            self._install_paths,
            plugin_id,
            install_dir,
        )

        from .updates import live_prepared_backup

        old_source = (
            await run_sync_io(live_prepared_backup, plugin_id) or target_dir
        )
        if not self.lifecycle.delegate.owns_commit(plugin_id):
            raise RuntimeError("PLUGIN_OPERATION_SUPERSEDED")
        if await asyncio.to_thread((old_source / "plugin.json").is_file):
            target_manifest_path = await asyncio.to_thread(
                resolved_plugin_manifest_path,
                old_source,
            )
            try:
                target_manifest = await asyncio.to_thread(
                    self._load_manifest,
                    target_manifest_path,
                )
            except ValueError:
                if candidate_binding.backend is not self._python_backend:
                    raise
                # Malformed Python remnants still follow the existing
                # no-force refusal or quiescent backup-preservation path.
            else:
                old_binding = await run_sync_io(
                    self.backend_resolver.resolve,
                    old_source,
                    target_manifest,
                )
                old_binding.validate_update(
                    candidate_binding,
                    in_place=same_location(source_path, target_dir),
                )

        await self._stop_preparation(plugin_id)
        if self._has_runtime_custody(plugin_id):
            raise RuntimeError("CHANNEL_INSTANCE_STILL_OWNED; needs_restart")
        if enabled and not _bundled_seed:
            await self.lifecycle.preflight_backend(
                candidate_binding,
                allow_install=True,
                probe=True,
                wheels=wheels,
            )

        self._require_unowned_roots(source_path, target_dir)
        # Copy files when source is not already the target (off the loop).
        # Identity, not string equality: a case-alias of the same
        # directory must not be deleted then copied onto itself.
        # An existing unique install uses the same swap as reload:
        # never rmtree the only copy, then copytree.
        swapped = None
        if not same_location(source_path, target_dir):

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

            def _first_install(stage_root: Path) -> None:
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
            with self.registry.runtime_owners.mutation(target_dir):
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
                    allow_incomplete_target=not (
                        install_base / plugin_id
                    ).is_symlink(),
                )
                if pawport_owner is not None:
                    with self.registry.runtime_owners.mutation(target_dir):
                        await run_sync_io(_write_pawport)
            else:
                with self.registry.runtime_owners.mutation(
                    source_path,
                    target_dir,
                ):
                    target_dir.parent.mkdir(parents=True, exist_ok=True)
                    stage_root = Path(
                        tempfile.mkdtemp(
                            prefix=f".{plugin_id}.install-",
                            dir=target_dir.parent,
                        ),
                    )
                    with self.registry.runtime_owners.mutation(stage_root):
                        await run_sync_io(_first_install, stage_root)
            logger.info(
                f"Copied plugin '{plugin_id}' to {target_dir}",
            )

        staging_hint = target_dir.with_name(
            target_dir.name + f".{plugin_id}.staging",
        )
        files_committed = False
        retained = None
        try:
            if swapped is not None:
                from .updates import preserved_update_backup

                retained = await asyncio.to_thread(
                    preserved_update_backup,
                    plugin_id,
                )
            # Re-read manifest from the installed location so that
            # source_path in the record points to the correct directory
            _installed_path, installed_manifest = await asyncio.to_thread(
                self._read_source_manifest,
                target_dir,
            )
            del _installed_path
            published_binding = await run_sync_io(
                candidate_binding.rebase,
                target_dir,
                installed_manifest,
            )
            if _bundled_seed:
                record = await self._load_plugin_unlocked(
                    installed_manifest,
                    target_dir,
                    config,
                    activate=False,
                    backend_binding=published_binding,
                    prepared=True,
                )
            elif enabled:
                record = await self.load_plugin(
                    installed_manifest,
                    target_dir,
                    config,
                    allow_install=True,
                    backend_binding=published_binding,
                    prepared=True,
                )
            else:
                record = await self._inactive_record(
                    published_binding,
                    config,
                )
            if record.status == "failed":
                reason = (
                    record.diagnostics[0]
                    if record.diagnostics
                    else f"Plugin '{plugin_id}' failed to load"
                )
                raise RuntimeError(reason)
            if swapped is not None:
                if retained is not None:
                    message = f"Existing files preserved at: {retained}"
                    record.diagnostics.append(message)
                    logger.warning("%s", message)
                files_committed = True
                cleanup_errors = await self._finish_committed_reload(
                    plugin_id,
                    swapped,
                )
                if cleanup_errors:
                    raise RuntimeError("; ".join(cleanup_errors))
            return record
        except BaseException:
            if files_committed:
                from .updates import marker_path, update_is_committed

                # A failed commit checkpoint still owns a prepared backup.
                # Preserve the new files only after durable commit or cleanup.
                files_committed = await asyncio.to_thread(
                    lambda: update_is_committed(plugin_id)
                    or not marker_path(plugin_id).is_file(),
                )
            instance = self.lifecycle.get_instance(plugin_id)
            current = self._loaded_plugins.get(plugin_id)
            committed = files_committed or self._install_already_committed(
                plugin_id,
            )
            live = instance is not None and instance.has_runtime_ledger()
            if (
                swapped is not None
                and not committed
                and (live or plugin_id in self._recovery_blocked)
            ):
                self.lifecycle.ensure_instance(plugin_id).add_diagnostic(
                    "needs_restart",
                )
            elif swapped is not None and not committed:
                try:
                    await self._restore_failed_swap(
                        plugin_id,
                        target_dir,
                        swapped,
                        staging_hint,
                        clear_marker_if_restored=True,
                    )
                    if (
                        retained is not None
                        and current is not None
                        and current.status == "failed"
                        and self._loaded_plugins.get(plugin_id) is current
                    ):
                        if (
                            instance is not None
                            and instance.state is PluginState.FAILED
                            and not instance.activated
                            and not instance.has_runtime_ledger()
                            and self.lifecycle.get_instance(plugin_id)
                            is instance
                        ):
                            self._loaded_plugins.pop(plugin_id)
                            self.lifecycle.drop_instance(plugin_id)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Failed to restore plugin '%s' after "
                        "unloaded force install",
                        plugin_id,
                    )
            if (
                swapped is None
                and pawport_owner is not None
                and not committed
                and not live
                and not self._has_runtime_custody(plugin_id)
            ):
                await self._remove_incomplete_pawport_plugin(
                    install_dir,
                    plugin_id,
                    pawport_owner,
                )
            raise

    async def _inactive_record(self, binding, config):
        """Describe disabled installs without importing or registering code."""
        record = PluginRecord(
            manifest=binding.description.manifest,
            source_path=binding.description.source_path,
            enabled=False,
            global_enabled=False,
            status="inactive",
            backend_binding=binding,
        )
        if discovers_disabled(binding):
            result = await binding.backend.load_definition(
                binding.description,
                {**(config or {}), "enabled": False},
            )
            self._apply_definition_result(record, result)
        return record

    async def _remove_incomplete_pawport_plugin(
        self,
        install_dir: Optional[Path],
        plugin_id: str,
        owner: dict[str, Any],
    ) -> None:
        base = Path(install_dir or self.plugin_dirs[0]).resolve()
        target = (base / plugin_id).resolve()
        from ..utils.io_utils import run_sync_io

        def remove():
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

        with self.registry.runtime_owners.mutation(target):
            await run_sync_io(remove)

    async def unload_plugin(
        self,
        plugin_id: str,
        delete_files: bool = False,
        *,
        mode: UnloadMode | None = None,
        interrupt_tasks: bool = False,
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
            interrupt_tasks=interrupt_tasks,
        )

    async def repair_dependencies(
        self,
        plugin_id: str,
        *,
        wheels=(),
    ) -> PluginRecord:
        """Explicit repair: gate + install + load a FAILED or disk plugin."""
        from ..utils.io_utils import run_sync_io

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
            if record is not None:
                previous_binding = await self._binding_for_record(record)
                # Repair explicitly inspects current disk contents, while the
                # retained source keeps its backend and custody until stopped.
                binding = BackendBinding(
                    previous_binding.backend,
                    await run_sync_io(
                        previous_binding.backend.describe,
                        source_path,
                        previous_binding.description.manifest.model_copy(
                            deep=True,
                        ),
                    ),
                )
            else:
                binding = await run_sync_io(
                    self.backend_resolver.resolve,
                    source_path,
                    manifest,
                )
            from .dependency_gate import SharedDependencyError

            try:
                await self.lifecycle.preflight_backend(
                    binding,
                    allow_install=True,
                    probe=True,
                    wheels=wheels,
                )
            except SharedDependencyError as exc:
                from .dependency_upgrade import stage_dependency_refusal

                await stage_dependency_refusal(
                    self,
                    source_path,
                    exc,
                    force=True,
                )
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
                repaired = PluginRecord(
                    manifest=manifest,
                    source_path=source_path,
                    enabled=False,
                    global_enabled=False,
                    status="inactive",
                    backend_binding=binding,
                )
                if discovers_disabled(binding):
                    result = await binding.backend.load_definition(
                        binding.description,
                        {**runtime_config(raw), "enabled": False},
                    )
                    self._apply_definition_result(repaired, result)
                repaired.diagnostics.append(
                    "dependencies installed; plugin remains disabled",
                )
                return repaired
            if saved_config is None:
                saved_config = runtime_config(raw)
            return await self._load_plugin_unlocked(
                manifest,
                source_path,
                saved_config,
                allow_install=False,
                activate=True,
                backend_binding=binding,
                prepared=True,
            )

    async def unload_plugin_with_mode(
        self,
        plugin_id: str,
        mode: UnloadMode,
        *,
        instance,
        delete_files: bool = False,
        interrupt_tasks: bool = False,
    ) -> UnloadReport:
        """Unlocked unload used by ``PluginLifecycle``.

        Caller must hold the per-plugin lifecycle lock.
        """
        return await self._unload_plugin_unlocked(
            plugin_id,
            delete_files,
            mode=mode,
            interrupt_tasks=interrupt_tasks,
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
        interrupt_tasks: bool = False,
    ) -> UnloadReport:
        """Unload a plugin and release a failed unload reservation."""
        from qwenpaw.memory import memory_registry
        from qwenpaw.market import market_registry

        async with self.lifecycle.activity(plugin_id).mutation(
            interrupt_tasks=interrupt_tasks or mode is UnloadMode.SHUTDOWN,
        ):
            market_registry.begin_unload(plugin_id)
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
            finally:
                market_registry.cancel_unload(plugin_id)

    async def _shutdown_runtime_owners(self, plugin_id, mode):
        """Drain generic projections before stopping their resources."""
        try:
            await self.registry.projector.revoke_plugin(plugin_id)
        except Exception as exc:
            return UnloadReport(
                plugin_id=plugin_id,
                mode=mode,
                clean=False,
                quiescent=False,
                needs_restart=True,
                errors=[str(exc)],
            )
        return await self._stop_runtime_owners(plugin_id, mode)

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
        if record is None and mode is UnloadMode.SHUTDOWN:
            return await self._shutdown_runtime_owners(plugin_id, mode)
        try:
            await self._stop_preparation(plugin_id)
        except Exception as exc:
            return UnloadReport(
                plugin_id=plugin_id,
                mode=mode,
                clean=False,
                quiescent=False,
                needs_restart=True,
                errors=[str(exc)],
            )
        record = self._loaded_plugins.get(plugin_id)
        if record is None:
            report = await self._stop_runtime_owners(plugin_id, mode)
            if not report.quiescent:
                return report
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

        cloudpaw_cleanup = None
        if plugin_id == "cloudpaw":
            from ..utils.io_utils import run_sync_io
            from .legacy_cloudpaw import (
                has_pending_stops,
                has_pending_uninstall,
                prepare_uninstall,
            )

            pending = await run_sync_io(has_pending_uninstall, self)
            if mode is UnloadMode.UNLOAD and pending:
                return UnloadReport(
                    plugin_id=plugin_id,
                    mode=mode,
                    clean=False,
                    quiescent=not has_pending_stops(self),
                    errors=[
                        "CloudPaw uninstall is incomplete; retry uninstall",
                    ],
                )
            if mode is UnloadMode.UNINSTALL or pending:
                try:
                    cloudpaw_cleanup = await prepare_uninstall(
                        self,
                        record.source_path,
                    )
                except Exception as exc:
                    return UnloadReport(
                        plugin_id=plugin_id,
                        mode=mode,
                        clean=False,
                        quiescent=False,
                        needs_restart=True,
                        errors=[f"CloudPaw agent shutdown: {exc}"],
                    )

        # Author hooks must run while they are still in the registry.
        # Ledger teardowns only drop the rows; they do not invoke them.
        report = UnloadReport(plugin_id=plugin_id, mode=mode)
        await self._run_shutdown_hooks(plugin_id, report)
        if mode is UnloadMode.SHUTDOWN:
            report.absorb(await instance.dispose(mode))
            if report.quiescent:
                report.absorb(await self._stop_runtime_owners(plugin_id, mode))
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
        before_install = None
        if mode is UnloadMode.UNINSTALL:
            from .provision import recorded_tool_names

            tool_names = recorded_tool_names(plugin_id)

            async def _cleanup_settings() -> None:
                stopped = await self._stop_runtime_owners(plugin_id, mode)
                report.absorb(stopped)
                if not stopped.quiescent:
                    raise QuiescenceError("; ".join(stopped.errors))
                if cloudpaw_cleanup is not None:
                    from .legacy_cloudpaw import cleanup, retire_agent_cleanup
                    from ..utils.io_utils import run_sync_io

                    await run_sync_io(cleanup, cloudpaw_cleanup)
                    await run_sync_io(retire_agent_cleanup, instance)
                await self._drop_uninstalled_settings(plugin_id, tool_names)

            before_install = _cleanup_settings
        disposal = (
            await instance.dispose(mode, before_install=before_install)
            if before_install is not None
            else await instance.dispose(mode)
        )
        report.absorb(disposal)
        if report.quiescent:
            report.absorb(await self._stop_runtime_owners(plugin_id, mode))
        if mode is UnloadMode.UNINSTALL and not report.clean:
            instance.state = PluginState.FAILED
            record.status = "failed"
            for error in report.errors:
                instance.add_diagnostic(error)
            record.diagnostics = list(instance.diagnostics)
            memory_registry.cancel_owner_unload(plugin_id)
            return report
        if report.quiescent and not was_committed:
            try:
                await self._undo_failed_txn_disk(plugin_id, instance)
                instance.clear_txn_escapes()
                instance.clear_created_dests()
            except (
                Exception,
                asyncio.CancelledError,
            ) as undo_exc:  # noqa: BLE001
                report.clean = False
                if self._note_disk_recovery_failure(undo_exc):
                    report.needs_restart = True
                report.errors.append(
                    str(undo_exc) or type(undo_exc).__name__,
                )
                failed_descs = getattr(undo_exc, "failed_descs", None)
                if failed_descs is not None:
                    instance.retain_txn_escapes(failed_descs)
                instance.add_diagnostic(str(undo_exc))
                instance.state = PluginState.FAILED
                record.status = "failed"
                record.diagnostics = list(instance.diagnostics)
                memory_registry.cancel_owner_unload(plugin_id)
                if isinstance(undo_exc, asyncio.CancelledError):
                    instance.add_diagnostic("needs_restart")
                    record.diagnostics = list(instance.diagnostics)
                    raise
                return report
        if self._has_runtime_custody(
            plugin_id,
        ) or self.retains_preparation_source(record.source_path):
            report.quiescent = False
            report.needs_restart = True
            report.errors.append("CHANNEL_INSTANCE_STILL_OWNED")
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

        # Slash commands were revoked by their ledger bindings above.
        # Keep tool ownership available for the remaining tool cleanup.
        self._cleanup_plugin_tools(plugin_id, record)

        # Clear all in-memory registry entries for this plugin
        self.registry.unregister_plugin(plugin_id)

        # Remove from the loaded-plugins dict
        del self._loaded_plugins[plugin_id]

        if mode is UnloadMode.UNINSTALL:
            await _recheck_created_locations(plugin_id, report)

        # Optionally delete files from disk (off the event loop).
        should_delete = delete_files or mode is UnloadMode.UNINSTALL
        if should_delete:
            source_path = record.source_path
            if await asyncio.to_thread(source_path.exists):
                from ..utils.io_utils import run_sync_io

                with self.registry.runtime_owners.mutation(source_path):
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

        if (
            mode is UnloadMode.UNINSTALL
            and cloudpaw_cleanup is not None
            and report.clean
        ):
            from .legacy_cloudpaw import finish_uninstall
            from ..utils.io_utils import run_sync_io

            await run_sync_io(finish_uninstall, self, cloudpaw_cleanup)

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
            # Tolerate malformed meta.tools (null / non-list).
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
        *,
        retire_successful: bool = False,
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
                if retire_successful:
                    self.registry.remove_shutdown_hook(hook)
            except Exception as exc:
                logger.error(
                    f"Error in shutdown hook '{hook.hook_name}' "
                    f"for plugin '{plugin_id}': {exc}",
                )
                report.errors.append(f"shutdown:{hook.hook_name}:{exc}")
                report.clean = False

    async def teardown_config_runtime(
        self,
        plugin_id: str,
        instance: Any,
    ) -> UnloadReport:
        """Flush author state before retiring a config generation's ledger."""
        report = UnloadReport(plugin_id=plugin_id, mode=UnloadMode.UNLOAD)
        instance.state = PluginState.UNLOADING
        instance.activated = False
        try:
            await self._run_shutdown_hooks(
                plugin_id,
                report,
                retire_successful=True,
            )
            if report.clean:
                report.absorb(await instance.teardown_runtime())
            else:
                report.quiescent = False
                report.needs_restart = True
        except BaseException as exc:
            report.clean = False
            report.quiescent = False
            report.needs_restart = True
            report.errors.append(str(exc) or type(exc).__name__)
            setattr(exc, "plugin_cleanup_report", report)
            raise
        finally:
            if not report.quiescent:
                instance.mark_failed("; ".join(report.errors))
                instance.add_diagnostic("needs_restart")
                record = self._loaded_plugins.get(plugin_id)
                if record is not None:
                    record.status = "failed"
                    record.diagnostics = list(instance.diagnostics)
        return report

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
        )

        report = UnloadReport(
            plugin_id=plugin_id,
            mode=UnloadMode.UNINSTALL,
        )
        source_path = self._find_installed_plugin_dir(plugin_id)
        if source_path is None:
            discovered = await asyncio.to_thread(self.discover_plugins)
            source_path = next(
                (
                    path
                    for manifest, path in discovered
                    if manifest.id == plugin_id
                ),
                None,
            )
        if self._has_runtime_custody(plugin_id) or (
            source_path is not None
            and self.retains_preparation_source(source_path)
        ):
            report.quiescent = False
            report.clean = False
            report.needs_restart = True
            report.errors.append("CHANNEL_INSTANCE_STILL_OWNED")
            return report
        has_inventory = inventory_path(plugin_id).is_file()
        from .legacy_cloudpaw import has_pending_cleanup

        if (
            source_path is None
            and not has_inventory
            and not (plugin_id == "cloudpaw" and has_pending_cleanup())
        ):
            raise KeyError(f"Plugin '{plugin_id}' is not installed")

        cloudpaw_cleanup = None
        if plugin_id == "cloudpaw":
            from .legacy_cloudpaw import prepare_uninstall

            try:
                cloudpaw_cleanup = await prepare_uninstall(self, source_path)
            except Exception as exc:
                report.clean = False
                report.quiescent = False
                report.needs_restart = True
                report.errors.append(f"CloudPaw agent shutdown: {exc}")
                return report

        created = snapshot_created_dests(plugin_id)
        declared: list[str] = []
        candidate = False
        # An inventory with no owned paths still records user ownership.
        if not has_inventory and source_path is not None:
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
                    "cannot confirm ownership of plugin.json declarations",
                )

        tool_names = recorded_tool_names(plugin_id)
        from ..utils.io_utils import run_sync_io
        from .provision import replay_persisted_provisions

        replay_errors = await run_sync_io(
            replay_persisted_provisions,
            plugin_id,
            source_path,
            **(
                {"skip_kinds": ("cloudpaw_agents",)}
                if cloudpaw_cleanup is not None
                else {}
            ),
        )
        if replay_errors:
            report.clean = False
            report.quiescent = False
            report.needs_restart = True
            report.errors.extend(replay_errors)
            return report
        try:
            if cloudpaw_cleanup is not None:
                from .legacy_cloudpaw import cleanup, retire_agent_cleanup

                await run_sync_io(cleanup, cloudpaw_cleanup)
                await run_sync_io(retire_agent_cleanup)
            await self._drop_uninstalled_settings(plugin_id, tool_names)
        except Exception as exc:  # noqa: BLE001
            report.clean = False
            report.errors.append(f"persisted config cleanup: {exc}")
            return report
        # Skill manifest cleanup needs ownership before the inventory is gone.
        await run_sync_io(PluginApi.cleanup_sourced_skills, plugin_id)
        await run_sync_io(teardown_created_locations, plugin_id)

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
            with self.registry.runtime_owners.mutation(source_path):
                await run_sync_io(
                    safe_remove,
                    source_path,
                    purpose="uninstall plugin directory",
                )
        self.lifecycle.drop_instance(plugin_id)
        if cloudpaw_cleanup is not None and report.clean:
            from .legacy_cloudpaw import finish_uninstall

            await run_sync_io(finish_uninstall, self, cloudpaw_cleanup)
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
            errors = []
            for name in names:
                try:
                    _remove_tool_config(
                        name,
                        plugin_id=plugin_id,
                        owned_names=names,
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append(str(exc))
            if errors:
                raise RuntimeError("; ".join(errors))
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

    def _apply_definition_result(self, record, result):
        """Apply execution state while preserving the user's enable intent."""
        if record.global_enabled is None:
            record.global_enabled = record.enabled
        record.instance = result.definition
        record.enabled = record.global_enabled and result.enabled
        record.status = (
            "inactive"
            if not record.enabled and result.status == "registered"
            else result.status
        )
        instance = self.lifecycle.get_instance(record.manifest.id)
        record.diagnostics = list(
            instance.diagnostics if instance is not None else (),
        ) + list(result.diagnostics)

    async def reregister_unlocked(
        self,
        plugin_id: str,
        config: Optional[Dict] = None,
        *,
        dependency_admission=None,
    ) -> None:
        """Call ``register()`` again on the already-imported plugin object."""
        self._require_recovered(plugin_id)
        record = self._loaded_plugins.get(plugin_id)
        if record is None or record.instance is None:
            raise RuntimeError(f"Plugin '{plugin_id}' is not loaded")
        binding = await self._binding_for_record(record)
        if record.global_enabled is None:
            record.global_enabled = record.enabled
        async with self._dependency_registration(
            binding,
            enabled=record.global_enabled,
            admission=dependency_admission,
        ) as dependency_token:
            if dependency_admission is None:
                snapshot = await self.lifecycle.prepare_backend(
                    binding,
                    allow_install=False,
                    probe=record.global_enabled
                    and probes_before_activation(binding),
                )
            else:
                snapshot = dependency_admission.snapshot
                await self._observe_host_dependencies(
                    binding,
                    dependency_token,
                )
            await self._admit_dependencies(binding, dependency_token, snapshot)
            with registration_scope(binding):
                result = await binding.backend.load_definition(
                    binding.description,
                    {**(config or {}), "enabled": record.global_enabled},
                    saved_definition=record.instance,
                )
                self._apply_definition_result(record, result)
                if result.definition is not None:
                    await self._reregister_body(
                        plugin_id,
                        result.definition,
                        config,
                        _manifest_as_dict(record.manifest),
                        dependency_token=dependency_token,
                    )

    async def _reregister_body(
        self,
        plugin_id: str,
        plugin_def: Any,
        config: Optional[Dict],
        manifest_dict: Dict[str, Any],
        *,
        dependency_token=None,
    ) -> None:
        """Bind a fresh API and run ``register()``; do not dispose on error."""
        from .settings import runtime_config
        from qwenpaw.market import market_registry

        api = PluginApi(
            plugin_id,
            runtime_config(config),
            manifest_dict,
            dependency_token=dependency_token,
        )
        api.set_registry(self.registry)
        instance = self.lifecycle.ensure_instance(plugin_id)
        instance.refuse_unquiescent_reregister()
        api.bind_instance(instance, loader=self)
        if manifest_dict.get("sdk") is not None:
            from .sdk import PluginContext

            api = PluginContext(api)
            instance.sdk_context = api
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
        market_registry.begin_load(plugin_id)
        instance.accepts_provision_declarations = True
        try:
            result = plugin_def.register(api)
            await await_with_budget(
                result,
                seconds=REGISTER_WALL_CLOCK_SECONDS,
                what="register()",
                plugin_id=plugin_id,
            )
        except BaseException as exc:
            cleanup_report = await self._dispose_then_undo_txn_disk(
                plugin_id,
                instance,
                use_teardown=True,
            )
            setattr(exc, "plugin_cleanup_report", cleanup_report)
            raise
        finally:
            instance.accepts_provision_declarations = False
        market_registry.finish_load(plugin_id)

    async def activate_plugin_unlocked(
        self,
        plugin_id: str,
        *,
        preserve_instance_on_failure: bool = False,
    ) -> None:
        """Project, start, then commit; config updates own failure recovery."""
        record = self._loaded_plugins.get(plugin_id)
        self._require_recovered(plugin_id)
        if record is not None:
            binding = await self._binding_for_record(record)
            await binding.backend.before_activate(binding.description)
            if not record.enabled:
                return
        instance = self.lifecycle.get_instance(plugin_id)
        if instance is not None and instance.activated:
            record = self._loaded_plugins.get(plugin_id)
            if record is not None and record.status == "registered":
                record.status = "active"
            return
        from .api import snapshot_agent_tool_configs
        from .provision import snapshot_location_keys, snapshot_tool_inventory

        from ..utils.io_utils import run_async_to_completion, run_sync_io

        def snapshot():
            tools = snapshot_tool_inventory(plugin_id)
            return (
                tools,
                snapshot_agent_tool_configs(tools),
                snapshot_location_keys(plugin_id),
            )

        tools_before = {}
        agent_tools_before = {}
        location_keys_before = set()
        snapshot_ready = False

        async def capture_snapshot() -> None:
            nonlocal tools_before, agent_tools_before, location_keys_before
            nonlocal snapshot_ready
            (
                tools_before,
                agent_tools_before,
                location_keys_before,
            ) = await run_sync_io(snapshot)
            if instance is not None:
                instance.activation_tool_configs = agent_tools_before
            snapshot_ready = True

        committed: list[list[str] | None] = [None]
        cancelled = False
        cleanup_errors: list[str] = []
        try:
            await run_async_to_completion(capture_snapshot())
            if instance is not None:
                for prepare in list(instance.pending_provisions):
                    await prepare()
                    instance.pending_provisions.remove(prepare)
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
                from .api import rollback_activate_install

                async def _rollback() -> None:
                    await run_sync_io(
                        rollback_activate_install,
                        plugin_id,
                        loop=asyncio.get_running_loop(),
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
                    if preserve_instance_on_failure:
                        # Undo this activation's writes after quiescence,
                        # without dropping the config transaction's instance
                        # or evicting its modules. The caller restores config.
                        cleanup_report = (
                            await self._dispose_then_undo_txn_disk(
                                plugin_id,
                                instance,
                                use_teardown=True,
                                undo_disk=(
                                    _rollback if snapshot_ready else None
                                ),
                            )
                        )
                        setattr(exc, "plugin_cleanup_report", cleanup_report)
                    else:
                        await self._fail_after_startup(
                            plugin_id,
                            str(exc) or type(exc).__name__,
                            undo_disk=_rollback if snapshot_ready else None,
                        )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Activate rollback failed for plugin '%s'",
                        plugin_id,
                    )
                raise
        if instance is not None:
            instance.activated = True
            instance.activation_tool_configs.clear()
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
        for plugin_id in list(self._loaded_plugins):
            try:
                async with self.plugin_lifecycle(plugin_id):
                    # Unload or reload may finish while we wait for the lock.
                    record = self._loaded_plugins.get(plugin_id)
                    instance = self.lifecycle.get_instance(plugin_id)
                    if (
                        record is None
                        or record.status not in {"registered", "active"}
                        or instance is None
                    ):
                        continue
                    if instance.activated:
                        if record.status == "registered":
                            record.status = "active"
                        continue
                    await self.lifecycle.activate(plugin_id)
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
        self._require_recovered(plugin_id)
        from ..utils.io_utils import run_sync_io
        from .api import _remove_tool_config
        from .provision import (
            PostCommitCleanupError,
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
            except PostCommitCleanupError as exc:
                errors.extend(exc.errors)
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
        from .workspace_projector import ProjectionError
        from ..app.channels.manager import live_channel_managers

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
        from .legacy_cloudpaw import (
            is_legacy_source,
            remember,
            restore_unload,
            snapshot,
        )
        from ..utils.io_utils import run_sync_io

        record = self._loaded_plugins.get(hook.plugin_id)
        source = record.source_path if record is not None else None
        legacy = hook.plugin_id == "cloudpaw" and is_legacy_source(source)
        before = await run_sync_io(snapshot) if legacy else None
        try:
            await self._invoke_startup_hook_body(hook)
        finally:
            if hook.plugin_id == "cloudpaw":
                patched = restore_unload(self)
                if (legacy or patched) and source is not None:
                    await run_sync_io(remember, source, before)

    async def _invoke_startup_hook_body(self, hook: Any) -> None:
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
        except (Exception, asyncio.CancelledError) as undo_exc:  # noqa: BLE001
            self._note_disk_recovery_failure(undo_exc)
            instance.add_diagnostic(
                str(undo_exc) or type(undo_exc).__name__,
            )
            failed_descs = getattr(undo_exc, "failed_descs", None)
            if failed_descs is not None:
                instance.retain_txn_escapes(failed_descs)
            # Runtime is stopped, but install-layer cleanup remains pending.
            # Keep its callable handles as well as the persistent references.
            instance.state = PluginState.FAILED
            if record is not None:
                record.status = "failed"
                record.enabled = False
                record.diagnostics = list(instance.diagnostics)
            if isinstance(undo_exc, asyncio.CancelledError):
                instance.add_diagnostic("needs_restart")
                if record is not None:
                    record.diagnostics = list(instance.diagnostics)
                raise
            return
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
    await run_sync_io(PluginApi.cleanup_sourced_skills, plugin_id)
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
        "sdk": manifest.sdk,
    }
