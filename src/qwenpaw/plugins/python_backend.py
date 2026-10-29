# -*- coding: utf-8 -*-
"""Legacy Python execution, with import custody across public registration."""

from __future__ import annotations

import csv
import importlib.util
import logging
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Callable

from .execution_backend import (
    DefinitionResult,
    PluginDescription,
    PreparedDependencyTargets,
)
from .lifecycle import PluginState, ReloadReport
from .module_isolation import (
    build_plugin_builtins,
    compile_plugin_import_closure,
    get_namespace_finder,
    probe_plugin_source,
    restore_plugin_import_state,
    snapshot_plugin_import_state,
    source_only_loader,
    strip_plugin_sys_path,
    sweep_bare_tree_modules,
    unregister_namespace,
)

logger = logging.getLogger(__name__)


class _EntryPointNotFoundError(FileNotFoundError):
    """Missing declared source, distinct from failures inside plugin code."""


def _norm_realpath(path):
    return os.path.normcase(os.path.realpath(str(path)))


def _relative_module_origins(origins, root):
    relative = set()
    for path in origins:
        try:
            relative.add(os.path.normcase(os.path.relpath(path, root)))
        except ValueError:
            # A different drive cannot belong to this root.
            continue
    return relative


def _files_for_loaded_origins(
    distribution,
    origins,
    *,
    metadata_path=None,
    record_reads=None,
):
    """Validate fresh RECORD rows, then stat only loaded-origin candidates."""
    from .execution.dependencies import _read_record

    record = _read_record(distribution, metadata_path, record_reads)
    if not record:
        return distribution.files
    candidates = []
    for row in csv.reader(record.splitlines()):
        if not 1 <= len(row) <= 3:
            raise ValueError("Invalid RECORD row")
        if len(row) == 3 and row[2]:
            int(row[2])
        path = row[0]
        # Keep anchor semantics for unusual paths without allocating a Path
        # for every unrelated, ordinary relative RECORD entry.
        if path.startswith("//") or "\\" in path or ":" in path:
            path = str(PurePosixPath(path))
        if os.path.normcase(os.path.normpath(path)) in origins:
            candidates.append(PurePosixPath(path))
    if sys.version_info < (3, 12):
        return candidates
    # Validate every row before checking candidates, and check all candidates
    # so a later matching-origin error cannot be hidden by an earlier match.
    return [
        path for path in candidates if distribution.locate_file(path).exists()
    ]


def _host_paths(cwd):
    """Detach path strings without resolving filesystem origins on the loop."""
    return tuple(
        os.path.join(cwd, path)
        for path in sys.path
        if isinstance(path, str) and path
    )


def _host_dependency_state():
    modules = sys.modules.copy()
    cwd = os.getcwd()
    paths = _host_paths(cwd)
    loaded = []
    for name, module in modules.items():
        if module is None:
            continue
        origin = module.__dict__.get("__file__")
        if isinstance(origin, str):
            loaded.append(
                (
                    name,
                    id(module),
                    os.path.join(cwd, origin),
                ),
            )
    return paths, tuple(loaded)


def _observe_host_dependencies(code_root, paths, loaded_origins):
    """Read metadata and RECORD ownership using only detached origins."""
    from importlib.metadata import PathDistribution
    from .execution.dependencies import (
        _provides_loaded_modules,
        observe_dependencies,
    )

    embedded_owners = {}
    record_reads = {}
    snapshot = observe_dependencies(
        {
            "code_root": code_root,
            "_audit_sites": paths,
            "dependency_paths": (),
        },
        _embedded_owners=embedded_owners,
        _record_reads=record_reads,
    )
    loaded = {name: Path(origin) for name, origin in loaded_origins}
    resolved = {path: path.resolve() for path in set(loaded.values())}
    origins = {*resolved, *resolved.values()}
    relative_origins = {}
    imported = {}
    for name, row in snapshot.distributions.items():
        root = Path(row["metadata_path"]).parent
        distribution = PathDistribution(Path(row["metadata_path"]))
        if root not in relative_origins:
            relative_origins[root] = _relative_module_origins(origins, root)
        files = _files_for_loaded_origins(
            distribution,
            relative_origins[root],
            metadata_path=row["metadata_path"],
            record_reads=record_reads,
        )
        if files is not None:
            owned = {
                os.path.normcase(os.path.normpath(item)) for item in files
            }
            if owned.intersection(relative_origins[root]):
                imported[name] = row
                embedded_roots = [
                    Path(site).parent
                    for site, owner in embedded_owners.items()
                    if owner == row["metadata_path"]
                ]
                if embedded_roots:
                    modules = {
                        module_name
                        for module_name, path in loaded.items()
                        if module_name.split(".", 1)[0] not in row["top_level"]
                        and any(
                            resolved[path].is_relative_to(site)
                            for site in embedded_roots
                        )
                        and owned.intersection(
                            _relative_module_origins(
                                (path, resolved[path]),
                                root,
                            ),
                        )
                    }
                    if modules:
                        imported[name] = {
                            **row,
                            "loaded_modules": tuple(sorted(modules)),
                        }
            continue
        # Legacy metadata without a file inventory needs top-level origin
        # evidence; RECORD ownership never uses this guess.
        if any(
            module_name.split(".", 1)[0] in row["top_level"]
            and (
                (
                    resolved[path].parent == root
                    and resolved[path].name.split(".", 1)[0]
                    == module_name.split(".", 1)[0]
                )
                or resolved[path].is_relative_to(
                    root / module_name.split(".", 1)[0],
                )
            )
            for module_name, path in loaded.items()
        ):
            imported[name] = row
    embedded_modules = {
        module
        for row in imported.values()
        for module in row.get("loaded_modules", ())
    }
    if embedded_modules:
        # Preserve the public-provider baseline too: existing coexistence is
        # stable, while later additions or replacement must require restart.
        for name, row in snapshot.distributions.items():
            if name not in imported and _provides_loaded_modules(
                row,
                embedded_modules,
                record_reads=record_reads,
            ):
                imported[name] = row
    return snapshot, imported


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


@dataclass(frozen=True)
class PythonServices:
    """Dependency and lifecycle operations needed by Python execution."""

    ensure_dependencies: Callable
    probe: Callable
    get_instance: Callable
    drop_instance: Callable
    unregister_plugin: Callable
    dependency_environment: Callable | None = None


class PythonBackend:
    """Import definitions; leave registration and transactions to Loader."""

    discover_disabled = False
    probe_before_activation = False

    def __init__(self, services: PythonServices):
        self.services = services

    def describe(self, source_path, manifest):
        from .dependency_gate import (
            manifest_requirements,
            parse_requirements_file,
        )

        requirements_path = Path(source_path) / "requirements.txt"
        parsed = parse_requirements_file(requirements_path)
        return PluginDescription(
            manifest,
            Path(source_path),
            requirements_path,
            manifest.entry.backend,
            requirements=tuple(
                dict.fromkeys(
                    [str(item) for item in parsed.requirements]
                    + parsed.unsupported
                    + manifest_requirements(manifest.model_dump(mode="json")),
                ),
            ),
        )

    @staticmethod
    async def prepare_dependency_targets(description):
        from .execution.dependencies import dependency_sites
        from ..utils.io_utils import run_sync_io

        cwd = os.getcwd()
        paths = _host_paths(cwd)

        def discover():
            code_root = Path(cwd, description.source_path).resolve()
            return dependency_sites(
                path
                for path in paths
                if not Path(path).resolve().is_relative_to(code_root)
            )

        targets = await run_sync_io(discover)

        def validate():
            if os.getcwd() != cwd or _host_paths(cwd) != paths:
                raise RuntimeError("DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED")

        prepared = PreparedDependencyTargets(
            tuple(Path(p) for p in targets),
            validate,
        )
        prepared.validate()
        return prepared

    def dependency_environment(self, _description, snapshot):
        from .dependency_context import DependencyEnvironmentContext

        factory = getattr(self.services, "dependency_environment", None)
        if factory is not None:
            return factory(snapshot)
        return DependencyEnvironmentContext.from_snapshot(snapshot)

    def dependency_install_target(self, description, snapshot):
        """Use one actual interpreter site, never overlay another provider."""
        return self.dependency_environment(
            description,
            snapshot,
        ).install_target

    async def prepare(
        self,
        description,
        *,
        allow_install,
        probe,
        wheels=(),
        owns_dependency_env=True,
    ):
        del wheels
        if owns_dependency_env:
            from .dependency_gate import SharedDependencyError

            try:
                decision = await self.services.ensure_dependencies(
                    description.source_path,
                    description.manifest.id,
                    allow_install=allow_install,
                )
            except SharedDependencyError as exc:
                if (
                    description.manifest.sdk is not None
                    and exc.decision.require_restart
                ):
                    from .errors import SDKRestartRequiredError

                    raise SDKRestartRequiredError(str(exc)) from exc
                raise
            if (
                decision.require_restart
                or decision.unsupported
                or (decision.missing and not decision.allow_install)
            ):
                if (
                    description.manifest.sdk is not None
                    and decision.require_restart
                ):
                    from .errors import SDKRestartRequiredError

                    raise SDKRestartRequiredError(decision.reason)
                raise SharedDependencyError(decision)
        if probe:
            entry = description.payload
            failed = await self.services.probe(
                description.manifest.id,
                description.source_path,
                description.source_path / entry if entry else None,
            )
            if failed is not None:
                raise RuntimeError("; ".join(failed.errors))
        return None

    async def audit_dependencies(
        self,
        description,
        *,
        context=None,
        validate=None,
    ):
        """Read this host's metadata without importing candidate modules."""
        from ..utils.io_utils import run_sync_io
        from .execution.dependencies import observe_dependencies
        from .install_lock import environment_observation

        factory = getattr(self.services, "dependency_environment", None)
        if context is None and factory is not None:
            context = await run_sync_io(factory)
        if validate is not None:
            validate()
        for _ in range(2):
            cwd = os.getcwd()
            paths = _host_paths(cwd)
            prepared = await self.prepare_dependency_targets(description)
            async with environment_observation(prepared.targets):
                prepared.validate()
                if os.getcwd() != cwd or _host_paths(cwd) != paths:
                    continue
                snapshot = await run_sync_io(
                    observe_dependencies,
                    {
                        "code_root": os.path.join(
                            cwd,
                            description.source_path,
                        ),
                        "_audit_sites": paths,
                        "dependency_paths": (),
                    },
                )
                if validate is not None:
                    validate()
                if (
                    context is not None
                    and context.runtime_identity is not None
                ):
                    from .channel_bootstrap import validate_runtime_identity

                    validate_runtime_identity(
                        snapshot,
                        context.runtime_identity,
                    )
                if _host_paths(os.getcwd()) == paths:
                    return snapshot
        raise RuntimeError("Host dependency paths changed during audit")

    async def load_definition(
        self,
        description,
        config,
        *,
        saved_definition=None,
    ):
        del config
        if saved_definition is not None:
            return DefinitionResult(saved_definition)
        manifest = description.manifest
        source = description.source_path
        backend = source / description.payload if description.payload else None
        frontend = (
            source / manifest.entry.frontend
            if manifest.entry.frontend
            else None
        )
        backend_exists, _ = self.validate_entry_points(
            manifest.id,
            backend,
            frontend,
        )
        if not backend_exists:
            return DefinitionResult(None)
        return DefinitionResult(
            self.import_definition(manifest.id, backend, source),
        )

    async def before_activate(self, description):
        """Python activation has no additional execution gate."""

    @staticmethod
    async def observe_host_dependencies(description, usage, token):
        """Capture imported distribution origins at lifecycle boundaries."""
        from ..utils.io_utils import run_async_to_completion, run_sync_io
        from .execution.dependencies import dependency_sites
        from .install_lock import environment_observation

        plugin_id = description.manifest.id

        def valid():
            return usage.has_declaration(token, plugin_id=plugin_id)

        def unknown():
            if valid():
                usage.observe_host(token, None)

        async def observe():
            if not valid():
                return
            try:
                for attempt in range(2):
                    paths, loaded = _host_dependency_state()
                    code_root = os.path.join(
                        os.getcwd(),
                        description.source_path,
                    )
                    roots = await run_sync_io(dependency_sites, paths)
                    async with environment_observation(roots):
                        if not valid():
                            return
                        try:
                            snapshot, imported = await run_sync_io(
                                _observe_host_dependencies,
                                code_root,
                                paths,
                                tuple(
                                    (name, origin)
                                    for name, _, origin in loaded
                                ),
                            )
                        except Exception:
                            logger.debug(
                                "Host dependency evidence unavailable",
                                exc_info=True,
                            )
                            unknown()
                            return
                        fresh = _host_dependency_state() == (paths, loaded)
                        covered = (
                            snapshot.dependency_sites is not None
                            and set(snapshot.dependency_sites) <= set(roots)
                        )
                        if fresh and covered:
                            if valid():
                                usage.refine(
                                    token,
                                    snapshot,
                                    plugin_id=plugin_id,
                                )
                                if imported:
                                    usage.observe_host(
                                        token,
                                        replace(
                                            snapshot,
                                            distributions=imported,
                                        ),
                                    )
                            return
                        if attempt == 1:
                            unknown()
            except Exception:
                logger.debug(
                    "Host dependency evidence unavailable",
                    exc_info=True,
                )
                unknown()

        await run_async_to_completion(observe())

    def validate_update(self, old, candidate, *, in_place):
        """Python sources support both in-place and directory updates."""

    def capture_restore_state(self, record):
        return snapshot_plugin_import_state(
            record.manifest.id,
            record.source_path,
        )

    def restore_state(self, state):
        if state is not None:
            restore_plugin_import_state(state)

    @contextmanager
    def registration_scope(self, description):
        """Keep import custody until public register and its cleanup finish."""
        plugin_id = description.manifest.id
        source = description.source_path
        module_name = f"plugin_{plugin_id.replace('-', '_')}"
        modules_before = dict(sys.modules)
        skip_cleanup = False
        try:
            yield
        except BaseException:
            instance = self.services.get_instance(plugin_id)
            if sys.modules.get(module_name) is modules_before.get(module_name):
                # Re-registering an existing definition owns no new import.
                # Its namespace must remain available for config rollback.
                skip_cleanup = True
            elif instance is not None and instance.state is PluginState.FAILED:
                skip_cleanup = True
            else:
                if (
                    instance is not None
                    and instance.state is PluginState.DISPOSED
                ):
                    self.services.drop_instance(plugin_id)
                self.services.unregister_plugin(plugin_id)
                self.cleanup_imports(plugin_id, source)
            raise
        finally:
            if not skip_cleanup:
                strip_plugin_sys_path(source)
                sweep_bare_tree_modules(source, modules_before)

    @staticmethod
    def cleanup_imports(plugin_id, source_path):
        module_name = f"plugin_{plugin_id.replace('-', '_')}"
        for name in list(sys.modules):
            if name == module_name or name.startswith(module_name + "."):
                sys.modules.pop(name, None)
        unregister_namespace(module_name)
        strip_plugin_sys_path(source_path)

    @staticmethod
    def validate_entry_points(
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
            raise _EntryPointNotFoundError(
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
            raise _EntryPointNotFoundError(
                f"Plugin '{plugin_id}' entry point files not found: "
                + ", ".join(missing),
            )

        return backend_exists, frontend_exists

    @staticmethod
    def import_definition(plugin_id, backend_entry_file, source_path):
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

        spec.loader = source_only_loader(spec.loader)
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

        return plugin_def
