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

from .execution_backend import DefinitionResult, PluginDescription
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


def _files_for_loaded_origins(distribution, origins):
    """Validate fresh RECORD rows, then stat only loaded-origin candidates."""
    record = distribution.read_text("RECORD")
    if not record:
        return distribution.files
    candidates = []
    for row in csv.reader(record.splitlines()):
        if not 1 <= len(row) <= 3:
            raise ValueError("Invalid RECORD row")
        if len(row) == 3 and row[2]:
            int(row[2])
        path = PurePosixPath(row[0])
        if os.path.normcase(os.path.normpath(path)) in origins:
            candidates.append(path)
    if sys.version_info < (3, 12):
        return candidates
    # Validate every row before checking candidates, and check all candidates
    # so a later matching-origin error cannot be hidden by an earlier match.
    return [
        path for path in candidates if distribution.locate_file(path).exists()
    ]


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
    def dependency_targets(_description):
        """Host roots are admission hints for this host-importing backend."""
        from .execution.dependencies import dependency_sites

        return tuple(
            Path(path)
            for path in dependency_sites(path for path in sys.path if path)
        )

    @staticmethod
    def dependency_install_target(_description, snapshot):
        """Use one actual interpreter site, never overlay another provider."""
        targets = [
            Path(site)
            for site in snapshot.dependency_sites or ()
            if Path(site).name in {"site-packages", "dist-packages"}
            and Path(site).is_relative_to(snapshot.prefix)
        ]
        return targets[0] if len(targets) == 1 else None

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
        return await self.audit_dependencies(description)

    async def audit_dependencies(self, description):
        """Read this host's metadata without importing candidate modules."""
        from .execution.dependencies import observe_dependencies

        return observe_dependencies(
            {
                "code_root": str(description.source_path),
                "_audit_sites": tuple(path for path in sys.path if path),
                "dependency_paths": (),
            },
        )

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
    def observe_host_dependencies(description, usage, token):
        """Capture imported distribution origins at lifecycle boundaries."""
        from importlib.metadata import PathDistribution
        from .execution.dependencies import observe_dependencies

        try:
            snapshot = observe_dependencies(
                {
                    "code_root": str(description.source_path),
                    "_audit_sites": tuple(path for path in sys.path if path),
                    "dependency_paths": (),
                },
            )
            loaded = {
                name: Path(module.__dict__["__file__"]).absolute()
                for name, module in tuple(sys.modules.items())
                if module is not None
                and isinstance(module.__dict__.get("__file__"), str)
            }
            resolved = {path: path.resolve() for path in set(loaded.values())}
            origins = {*resolved, *resolved.values()}
            relative_origins = {}
            imported = {}
            for name, row in snapshot.distributions.items():
                root = Path(row["metadata_path"]).parent
                distribution = PathDistribution(Path(row["metadata_path"]))
                if root not in relative_origins:
                    relative_origins[root] = _relative_module_origins(
                        origins,
                        root,
                    )
                files = _files_for_loaded_origins(
                    distribution,
                    relative_origins[root],
                )
                if files is not None:
                    if any(
                        os.path.normcase(os.path.normpath(item))
                        in relative_origins[root]
                        for item in files
                    ):
                        imported[name] = row
                    continue
                # Legacy metadata without a file inventory needs top-level
                # origin evidence; RECORD ownership never uses this guess.
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
            usage.refine(token, snapshot)
            if imported:
                usage.observe_host(
                    token,
                    replace(snapshot, distributions=imported),
                )
        except Exception:  # Evidence failure must not invent a clean host.
            logger.debug("Host dependency evidence unavailable", exc_info=True)
            usage.observe_host(token, None)

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
