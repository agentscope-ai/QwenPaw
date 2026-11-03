# -*- coding: utf-8 -*-
"""Legacy Python execution, with import custody across public registration."""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, replace
from packaging.markers import default_environment

from pathlib import Path
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
from .dependency_requirements import (
    host_requirements,
    resolve_optional_dependencies,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ReadAdmissionContext:
    description: PluginDescription


def _read_source_identity(description):
    """Validate current declarations without hashing unused admission evidence."""
    from .architecture import PluginManifest
    from .dependency_gate import parse_requirements_file, manifest_requirements
    from .execution.dependencies import dependency_error
    import json

    manifest_path = description.source_path / "plugin.json"
    has_manifest = manifest_path.is_file()
    if (
        has_manifest
        and PluginManifest.model_validate(
            json.loads(manifest_path.read_text(encoding="utf-8")),
        )
        != description.manifest
    ):
        raise dependency_error("DEPENDENCY_ORIGIN_INVALID")
    # Metadata-only audit descriptions have no source declarations to compare.
    if description.requirements_path is not None or has_manifest:
        file_requirements = []
        if description.requirements_path is not None:
            parsed = parse_requirements_file(description.requirements_path)
            file_requirements = [
                str(item) for item in parsed.requirements
            ] + parsed.unsupported
        current = tuple(
            dict.fromkeys(
                file_requirements
                + manifest_requirements(
                    description.manifest.model_dump(mode="json"),
                )
                + list(
                    resolve_optional_dependencies(
                        description.manifest.optional_dependencies,
                        description.required_extras,
                    ),
                ),
            ),
        )
        if current != description.requirements:
            raise dependency_error("DEPENDENCY_ORIGIN_INVALID")


class _EntryPointNotFoundError(FileNotFoundError):
    """Missing declared source, distinct from failures inside plugin code."""


def _norm_realpath(path):
    return os.path.normcase(os.path.realpath(str(path)))


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
        locations = tuple(module.__dict__.get("__path__", ()))
        if not isinstance(origin, str) and locations:
            origin = locations[0]
        if isinstance(origin, str):
            loaded.append(
                (
                    name,
                    (module, locations),
                    os.path.join(cwd, origin),
                ),
            )
    return paths, tuple(loaded)


def _host_file_witness(origin, locations=()):
    values = []
    for value in dict.fromkeys((origin, *locations)):
        path = Path(value)
        while not path.exists() and path.parent != path:
            path = path.parent
        stat = path.stat()
        values.append(
            (
                str(path.resolve()),
                stat.st_dev,
                stat.st_ino,
                stat.st_size,
                stat.st_mtime_ns,
                stat.st_ctime_ns,
            ),
        )
    return tuple(values)


def _capture_host_module_facts(code_root, loaded, known):
    from .dependency_usage import HostModuleFact

    root = Path(code_root).resolve()
    if len(loaded) > 16384:
        raise ValueError("host module observation exceeds bound")
    pending, facts = [], []
    for name, identity, origin in loaded:
        locations = tuple(map(str, identity[1]))
        key = (name, id(identity[0]), origin, locations)
        if key in known:
            fact = known[key]
            if fact is not None and not Path(
                fact.file_witness[0][0],
            ).is_relative_to(root):
                facts.append(fact)
        else:
            pending.append((key, identity))
    origins = tuple((key[0], key[2]) for key, _identity in pending)
    resolved = {origin: Path(origin).resolve() for _name, origin in origins}
    standard = _stdlib_modules(origins, resolved)
    for key, identity in pending:
        name, module_id, origin, locations = key
        if name in standard:
            known[key] = None
            continue
        if resolved[origin].is_relative_to(root):
            continue
        fact = HostModuleFact(
            name,
            module_id,
            os.path.abspath(origin),
            locations,
            _host_file_witness(origin, locations),
            namespace=not isinstance(
                identity[0].__dict__.get("__file__"),
                str,
            ),
        )
        known[key] = fact
        facts.append(fact)
    return tuple(facts)


def _stdlib_modules(loaded_origins, resolved):
    """Recognize interpreter-owned sources, never merely standard names."""
    from .execution.dependencies import _dependency_protection_roots

    packages, standard, _ = _dependency_protection_roots()
    package_parts = tuple(Path(site).parts for site in packages)
    standard_parts = tuple(Path(site).parts for site in standard)
    trusted = set()
    for name, origin in loaded_origins:
        top = name.split(".", 1)[0]
        path = resolved[str(Path(origin))]
        parts = path.parts
        if path.drive:
            # Canonical roots normalize the anchor, not directory spelling.
            parts = (parts[0].lower(), *parts[1:])
        if (
            top not in sys.stdlib_module_names
            or {"site-packages", "dist-packages"}.intersection(parts)
            or any(parts[: len(site)] == site for site in package_parts)
        ):
            continue
        if any(
            len(parts) > len(site)
            and parts[: len(site)] == site
            and parts[len(site)].split(".", 1)[0] == top
            for site in standard_parts
        ):
            trusted.add(name)
    return trusted


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
            ParsedRequirements,
        )

        # A descriptor's legacy requirements file belongs to its worker.
        # Common Python registration has its own manifest dependencies.
        requirements_path = (
            None
            if manifest.entry.descriptor
            else Path(source_path) / "requirements.txt"
        )
        parsed = (
            parse_requirements_file(requirements_path)
            if requirements_path is not None
            else ParsedRequirements()
        )
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

    def describe_requirements(self, source_path, manifest, requires):
        """Select optional requirements without importing their consumers."""
        description = self.describe(source_path, manifest)
        optional = resolve_optional_dependencies(
            manifest.optional_dependencies,
            requires,
        )
        return replace(
            description,
            requirements=tuple(
                dict.fromkeys((*description.requirements, *optional)),
            ),
            required_extras=tuple(requires),
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

            additional = (
                host_requirements(description.manifest.model_dump(mode="json"))
                if allow_install
                and getattr(
                    description.manifest,
                    "optional_dependencies",
                    None,
                )
                else ()
            )
            requirements = (
                description.requirements
                if description.requirements_path is None
                else None
            )

            try:
                decision = await self.services.ensure_dependencies(
                    description.source_path,
                    description.manifest.id,
                    allow_install=allow_install,
                    requirements=requirements,
                    additional_requirements=additional,
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
            for warning in decision.warnings:
                logger.warning(
                    "Plugin '%s': %s",
                    description.manifest.id,
                    warning,
                )
                instance = getattr(
                    self.services,
                    "get_instance",
                    lambda _id: None,
                )(description.manifest.id)
                if instance is not None:
                    instance.add_diagnostic(warning)
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

    async def admit_existing(
        self,
        description,
        *,
        usage,
        token,
        snapshot=None,
    ):
        """Admit a candidate closure without producing full audit evidence."""
        from packaging.markers import default_environment
        from ..utils.io_utils import run_sync_io
        from .dependency_gate import (
            _shared_observation,
            SharedDependencyError,
            GateDecision,
        )
        from .dependency_usage import DependencyEnvironment
        from .execution.dependencies import (
            read_dependency_inventory,
        )

        del snapshot
        if not usage.has_declaration(token, plugin_id=description.manifest.id):
            raise ValueError("DEPENDENCY_DECLARATION_MISMATCH")
        prepared = await self.prepare_dependency_targets(description)
        cwd = os.getcwd()
        paths = _host_paths(cwd)
        factory = getattr(self.services, "dependency_environment", None)
        context = await run_sync_io(factory) if factory is not None else None
        async with _shared_observation(prepared.targets):
            prepared.validate()
            try:
                view, _ = await run_sync_io(
                    read_dependency_inventory,
                    description.source_path,
                    paths,
                    description.requirements,
                )
                await run_sync_io(_read_source_identity, description)
            except Exception as exc:
                code = getattr(
                    exc,
                    "reason_code",
                    "DEPENDENCY_PLAN_UNVERIFIED",
                )
                if isinstance(exc, SharedDependencyError):
                    raise
                raise SharedDependencyError(
                    GateDecision(
                        False,
                        False,
                        missing=(
                            [str(exc)]
                            if code == "DEPENDENCY_UNSATISFIED"
                            else []
                        ),
                        reason=f"{code}: {description.manifest.id}: {exc}",
                        reason_code=code,
                    ),
                ) from exc
            prepared.validate()
            for warning in view.warnings:
                logger.warning(
                    "Plugin '%s': %s",
                    description.manifest.id,
                    warning,
                )
                get_instance = getattr(self.services, "get_instance", None)
                instance = (
                    get_instance(description.manifest.id)
                    if get_instance
                    else None
                )
                if instance is not None:
                    instance.add_diagnostic(warning)
            environment = DependencyEnvironment(
                os.path.abspath(sys.executable),
                view.dependency_sites,
                dict(default_environment()),
            )
            if context is not None and context.runtime_identity is not None:
                identity = context.runtime_identity
                expected = {
                    "python_version": ".".join(map(str, identity["version"])),
                    "implementation_name": identity["implementation"],
                    "sys_platform": identity["sys_platform"],
                    "platform_system": identity["system"],
                    "platform_machine": identity["machine"],
                }
                if any(
                    environment.marker_environment.get(key) != value
                    for key, value in expected.items()
                ):
                    raise ValueError("CHANNEL_RUNTIME_IDENTITY_MISMATCH")
            usage.admit_read(
                token,
                environment,
                description=description,
                context=_ReadAdmissionContext(
                    description,
                ),
            )
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
        from .install_lock import environment_observation, observation_inputs

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
                        "_requirements": description.requirements,
                        "_reuse_ambiguous": True,
                    },
                    _inventory=observation_inputs(),
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
    async def reconcile_host_observations(usage):
        """Settle detached tails without replacing their first file witnesses."""
        from .dependency_usage import DependencyEnvironment
        from .install_lock import environment_observation

        for token, progress in usage.pending_host_observations():
            try:
                async with environment_observation(progress.roots):
                    valid = _host_paths(os.getcwd()) == progress.paths and all(
                        _host_file_witness(fact.origin, fact.locations)
                        == fact.file_witness
                        for fact in progress.facts
                    )
                    usage.finish_host_module_observation(
                        token,
                        progress,
                        (
                            DependencyEnvironment(
                                os.path.abspath(sys.executable),
                                progress.roots,
                                dict(default_environment()),
                            )
                            if valid
                            else None
                        ),
                    )
            except Exception:
                usage.finish_host_module_observation(token, progress, None)

    @staticmethod
    async def observe_host_dependencies(description, usage, token):
        """Capture append-only module facts; ownership is a write-time concern."""
        from ..utils.io_utils import run_async_to_completion, run_sync_io
        from .dependency_usage import DependencyEnvironment, HostModuleProgress
        from .execution.dependencies import dependency_sites
        from .install_lock import environment_observation

        declaration = usage.declaration(token)
        publish_unknown = usage.host_observer(
            token,
            plugin_id=description.manifest.id,
        )
        if declaration is None or publish_unknown is None:
            return
        known = getattr(usage, "_host_module_facts", None)
        if known is None:
            known = usage._host_module_facts = {}

        async def observe():
            await PythonBackend.reconcile_host_observations(usage)
            captured = _host_dependency_state()
            paths = captured[0]
            roots = await run_sync_io(dependency_sites, paths)
            environment = DependencyEnvironment(
                os.path.abspath(sys.executable),
                roots,
                dict(default_environment()),
            )
            try:
                async with environment_observation(roots):
                    for attempt in range(2):
                        facts = await run_sync_io(
                            _capture_host_module_facts,
                            description.source_path,
                            captured[1],
                            known,
                        )
                        usage.record_host_modules(
                            token,
                            facts,
                            environment,
                            declaration=declaration,
                        )
                        after = _host_dependency_state()
                        if after[0] != paths:
                            raise ValueError(
                                "host observation identity changed",
                            )
                        before = {
                            (name, id(identity[0]), origin, tuple(identity[1]))
                            for name, identity, origin in captured[1]
                        }
                        tail = tuple(
                            row
                            for row in after[1]
                            if (
                                row[0],
                                id(row[1][0]),
                                row[2],
                                tuple(row[1][1]),
                            )
                            not in before
                        )
                        if not tail:
                            return
                        captured = (paths, tail)
                    # The tail is detached before yielding. Its first file witness
                    # survives cancellation, removal and a subsequent disk upgrade.
                    facts = _capture_host_module_facts(
                        description.source_path,
                        tail,
                        known,
                    )
                    if facts:
                        usage.defer_host_observation(
                            token,
                            HostModuleProgress(paths, roots, facts),
                        )
            except Exception as error:
                logger.info(
                    "Host module observation plugin=%s reason=%s",
                    description.manifest.id,
                    error,
                )
                publish_unknown(None)

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
