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


@dataclass(frozen=True)
class _ReadAdmissionContext:
    description: PluginDescription
    source_digest: str
    paths: tuple[str, ...]
    executable: str
    runtime_identity: object = None


def _read_source_identity(description):
    """Fingerprint dependency declarations, without scanning plugin assets."""
    import hashlib

    from .architecture import PluginManifest
    from .dependency_gate import parse_requirements_file, manifest_requirements
    from .execution.dependencies import dependency_error
    import json

    manifest_path = description.source_path / "plugin.json"
    if (
        manifest_path.is_file()
        and PluginManifest.model_validate(
            json.loads(manifest_path.read_text(encoding="utf-8")),
        )
        != description.manifest
    ):
        raise dependency_error("DEPENDENCY_ORIGIN_INVALID")
    if description.requirements_path is not None:
        parsed = parse_requirements_file(description.requirements_path)
        current = tuple(
            dict.fromkeys(
                [str(item) for item in parsed.requirements]
                + parsed.unsupported
                + manifest_requirements(
                    description.manifest.model_dump(mode="json"),
                ),
            ),
        )
        if current != description.requirements:
            raise dependency_error("DEPENDENCY_ORIGIN_INVALID")
    digest = hashlib.sha256()
    digest.update(str(description.source_path.resolve()).encode())
    for name in ("plugin.json", "requirements.txt"):
        path = description.source_path / name
        digest.update(name.encode())
        content = path.read_bytes() if path.is_file() else b""
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


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
    key = ("host_paths", metadata_path)
    if (
        record_reads is None
        or metadata_path is None
        or key not in record_reads
    ):
        paths = []
        for row in csv.reader(record.splitlines()):
            if not 1 <= len(row) <= 3:
                raise ValueError("Invalid RECORD row")
            if len(row) == 3 and row[2]:
                int(row[2])
            path = row[0]
            # Retain unusual anchor semantics without a Path per ordinary row.
            if path.startswith("//") or "\\" in path or ":" in path:
                path = str(PurePosixPath(path))
            paths.append((os.path.normcase(os.path.normpath(path)), path))
        if record_reads is not None and metadata_path is not None:
            record_reads[key] = tuple(paths)
    else:
        paths = record_reads[key]
    candidates = [
        PurePosixPath(path) for name, path in paths if name in origins
    ]
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


def _observe_host_dependencies(
    code_root,
    paths,
    loaded_origins,
    *,
    inventory=None,
    _snapshot=None,
    _embedded_owners=None,
    _covered=None,
    _resolved=None,
    _module_owners=None,
):
    """Read metadata and RECORD ownership using only detached origins."""
    from importlib.metadata import PathDistribution
    from .execution.dependencies import (
        _provides_loaded_modules,
        observe_dependencies,
    )

    embedded_owners = dict(_embedded_owners or {})
    record_reads = (
        inventory.setdefault("records", {}) if inventory is not None else {}
    )
    snapshot = _snapshot or observe_dependencies(
        {
            "code_root": code_root,
            "_audit_sites": paths,
            "dependency_paths": (),
        },
        _embedded_owners=embedded_owners,
        _record_reads=record_reads,
        _inventory=inventory,
    )
    loaded = {name: Path(origin) for name, origin in loaded_origins}
    resolved = (
        _resolved
        if _resolved is not None
        else {
            path: Path(path).resolve()
            for path in dict.fromkeys(str(path) for path in loaded.values())
        }
    )
    relative_modules = {}
    imported = {}
    if _module_owners is not None:
        _module_owners.update(
            (name, {}) for name in _stdlib_modules(loaded_origins, resolved)
        )

    def retain(modules, package, row):
        if _module_owners is None:
            return
        for module in modules:
            owned = dict(row)
            embedded = owned.pop("loaded_modules", ())
            if module in embedded:
                owned["loaded_modules"] = (module,)
            _module_owners.setdefault(module, {})[package] = owned

    for name, row in snapshot.distributions.items():
        root = Path(row["metadata_path"]).parent
        distribution = PathDistribution(Path(row["metadata_path"]))
        if root not in relative_modules:
            indexed = relative_modules[root] = {}
            for module_name, path in loaded.items():
                for origin in _relative_module_origins(
                    (path, resolved[str(path)]),
                    root,
                ):
                    indexed.setdefault(origin, set()).add(module_name)
        indexed = relative_modules[root]
        files = _files_for_loaded_origins(
            distribution,
            indexed,
            metadata_path=row["metadata_path"],
            record_reads=record_reads,
        )
        if files is not None:
            owned = {
                os.path.normcase(os.path.normpath(item)) for item in files
            }
            matched_modules = {
                module_name
                for origin in owned.intersection(indexed)
                for module_name in indexed[origin]
            }
            if matched_modules:
                imported[name] = row
                if _covered is not None:
                    _covered.update(matched_modules)
                embedded_roots = [
                    Path(site).parent
                    for site, owner in embedded_owners.items()
                    if owner == row["metadata_path"]
                ]
                if embedded_roots:
                    modules = {
                        module_name
                        for module_name in matched_modules
                        if module_name.split(".", 1)[0] not in row["top_level"]
                        and any(
                            resolved[str(loaded[module_name])].is_relative_to(
                                site,
                            )
                            for site in embedded_roots
                        )
                    }
                    if modules:
                        imported[name] = {
                            **row,
                            "loaded_modules": tuple(sorted(modules)),
                        }
                retain(matched_modules, name, imported[name])
            continue
        # Legacy metadata without a file inventory needs top-level origin
        # evidence; RECORD ownership never uses this guess.
        legacy_modules = {
            module_name
            for module_name, path in loaded.items()
            if module_name.split(".", 1)[0] in row["top_level"]
            and (
                (
                    resolved[str(path)].parent == root
                    and resolved[str(path)].name.split(".", 1)[0]
                    == module_name.split(".", 1)[0]
                )
                or resolved[str(path)].is_relative_to(
                    root / module_name.split(".", 1)[0],
                )
            )
        }
        if legacy_modules:
            imported[name] = row
            retain(legacy_modules, name, row)
            if _covered is not None:
                _covered.update(legacy_modules)
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
        if _module_owners is not None:
            for module in embedded_modules:
                for name, row in imported.items():
                    if _provides_loaded_modules(
                        row,
                        {module},
                        record_reads=record_reads,
                    ):
                        retain({module}, name, row)
    return snapshot, imported


def _check_read_history(view, uses):
    from .dependency_gate import SharedDependencyError, GateDecision
    from .execution.dependencies import _provides_loaded_modules

    def refuse(code, detail):
        raise SharedDependencyError(
            GateDecision(
                False,
                False,
                reason=f"{code}: {detail}",
                reason_code=code,
                require_restart=code == "DEPENDENCY_RESTART_REQUIRED",
                unsupported=(
                    [detail] if code == "DEPENDENCY_PLAN_UNVERIFIED" else []
                ),
            ),
        )

    for use in uses:
        if use.origin != "host":
            continue
        if use.environment is None or use.snapshot is None:
            refuse("DEPENDENCY_PLAN_UNVERIFIED", "host history unavailable")
        if not set(use.environment.sites).intersection(view.dependency_sites):
            continue
        for name, old in use.snapshot.distributions.items():
            fresh = view.distributions.get(name)
            if (
                name in view.invalid
                or fresh is None
                or old["version"] != fresh["version"]
                or old["metadata_path"] != fresh["metadata_path"]
            ):
                refuse(
                    "DEPENDENCY_RESTART_REQUIRED",
                    "loaded dependency differs",
                )
            modules = old.get("loaded_modules", ())
            if modules and any(
                provider not in use.snapshot.distributions
                and _provides_loaded_modules(row, set(modules))
                for provider, row in view.distributions.items()
            ):
                refuse(
                    "DEPENDENCY_RESTART_REQUIRED",
                    "loaded embedded provider shadowed",
                )


def _observe_host_delta(
    code_root,
    paths,
    loaded_origins,
    baseline,
    *,
    inventory=None,
    _module_owners=None,
):
    """Resolve only changed modules; uncertain providers use the old observer."""
    from .execution.dependencies import read_dependency_inventory

    root = Path(code_root).resolve()
    resolved = {
        path: Path(path).resolve()
        for path in dict.fromkeys(
            str(Path(origin)) for _name, origin in loaded_origins
        )
    }
    loaded_origins = tuple(
        (name, origin)
        for name, origin in loaded_origins
        if not resolved[str(Path(origin))].is_relative_to(root)
    )
    if not loaded_origins:
        return replace(baseline, distributions={}), {}
    standard_modules = _stdlib_modules(loaded_origins, resolved)
    if _module_owners is not None:
        _module_owners.update((name, {}) for name in standard_modules)
    loaded_origins = tuple(
        (name, origin)
        for name, origin in loaded_origins
        if name not in standard_modules
    )
    if not loaded_origins:
        return replace(baseline, distributions={}), {}
    view, _ = read_dependency_inventory(
        code_root,
        paths,
        (),
        inventory=inventory,
    )
    rows = {}
    unresolved = set()
    required = set()
    by_root = {}
    for package, row in view.distributions.items():
        parent = Path(row["metadata_path"]).parent
        index = by_root.setdefault(str(parent), (parent, {}))[1]
        for top in row["top_level"]:
            index.setdefault(top, {})[package] = row
    dependency_roots = tuple(Path(site) for site in view.dependency_sites)
    for name, origin in loaded_origins:
        path = resolved[str(Path(origin))]
        if any(path.is_relative_to(site) for site in dependency_roots):
            required.add(name)
        matched = False
        for parent, index in by_root.values():
            if not path.is_relative_to(parent):
                continue
            first = path.relative_to(parent).parts[0].split(".", 1)[0]
            for top in {first, name.split(".", 1)[0]}:
                candidates = index.get(top, {})
                rows.update(candidates)
                matched = matched or bool(candidates)
        if not matched:
            unresolved.add(name)
    if unresolved:
        return _observe_host_dependencies(
            code_root,
            paths,
            loaded_origins,
            inventory=inventory,
            _resolved=resolved,
            _module_owners=_module_owners,
        )
    snapshot = replace(
        baseline,
        sites=view.sites,
        dependency_sites=view.dependency_sites,
        distributions=rows,
    )
    covered = set()
    observed, imported = _observe_host_dependencies(
        code_root,
        paths,
        loaded_origins,
        _snapshot=snapshot,
        inventory=inventory,
        _embedded_owners=view.embedded_owners,
        _covered=covered,
        _resolved=resolved,
        _module_owners=_module_owners,
    )
    if required - covered:
        return _observe_host_dependencies(
            code_root,
            paths,
            loaded_origins,
            inventory=inventory,
            _resolved=resolved,
            _module_owners=_module_owners,
        )
    return observed, imported


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
        from .execution.errors import ProtocolValidationError
        from .install_lock import observation_inputs

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
            for attempt in range(2):
                before = _host_dependency_state()
                before_usage = usage.snapshot()
                try:
                    view, _ = await run_sync_io(
                        read_dependency_inventory,
                        description.source_path,
                        paths,
                        description.requirements,
                        inventory=observation_inputs(),
                    )
                    digest = await run_sync_io(
                        _read_source_identity,
                        description,
                    )
                    await run_sync_io(
                        _check_read_history,
                        view,
                        before_usage.uses,
                    )
                except Exception as exc:
                    code = getattr(
                        exc,
                        "reason_code",
                        "DEPENDENCY_PLAN_UNVERIFIED",
                    )
                    if isinstance(exc, SharedDependencyError):
                        raise
                    missing = (
                        [str(exc)]
                        if isinstance(exc, ProtocolValidationError)
                        and code == "DEPENDENCY_UNSATISFIED"
                        and str(exc) != code
                        else []
                    )
                    raise SharedDependencyError(
                        GateDecision(
                            False,
                            False,
                            missing=missing,
                            reason=(
                                f"{code}: {description.manifest.id}"
                                + (
                                    f": {', '.join(missing)}"
                                    if missing
                                    else ""
                                )
                            ),
                            reason_code=code,
                            require_restart=code
                            == "DEPENDENCY_REPAIR_REQUIRED",
                        ),
                    ) from exc
                prepared.validate()
                if not set(view.dependency_sites) <= {
                    str(path) for path in prepared.targets
                }:
                    raise SharedDependencyError(
                        GateDecision(
                            False,
                            False,
                            reason="DEPENDENCY_PLAN_UNVERIFIED: admission roots changed",
                            reason_code="DEPENDENCY_PLAN_UNVERIFIED",
                        ),
                    )
                if (
                    before == _host_dependency_state()
                    and usage.snapshot().revision == before_usage.revision
                ):
                    break
                if attempt == 1:
                    raise SharedDependencyError(
                        GateDecision(
                            False,
                            False,
                            reason="DEPENDENCY_PLAN_UNVERIFIED: imports changed",
                            reason_code="DEPENDENCY_PLAN_UNVERIFIED",
                        ),
                    )
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
                    digest,
                    paths,
                    environment.executable,
                    context.runtime_identity if context is not None else None,
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
    async def observe_host_dependencies(description, usage, token):
        """Retain value-only import history; resolve changed sources only."""
        import weakref
        from ..utils.io_utils import run_async_to_completion, run_sync_io
        from .execution.dependencies import _inventory_sites, dependency_sites
        from .install_lock import environment_observation, observation_inputs

        plugin_id = description.manifest.id

        def valid():
            return usage.has_declaration(token, plugin_id=plugin_id)

        def unknown():
            if valid():
                usage.observe_host(token, None)

        def detached(loaded):
            return {
                name: (weakref.ref(identity[0]), identity[1], origin)
                for name, identity, origin in loaded
            }

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
                    key = (
                        await run_sync_io(
                            lambda: str(Path(code_root).resolve()),
                        ),
                        paths,
                    )
                    baselines = getattr(
                        usage,
                        "_host_observer_baselines",
                        None,
                    )
                    if baselines is None:
                        baselines = usage._host_observer_baselines = {}
                    previous = baselines.get(key)
                    current = detached(loaded)
                    roots = await run_sync_io(dependency_sites, paths)
                    async with environment_observation(roots):
                        if not valid():
                            return
                        sites = await run_sync_io(
                            _inventory_sites,
                            code_root,
                            paths,
                        )
                        # Changed roots invalidate current ownership while
                        # previous remains the append-only pin history.
                        baseline = (
                            previous
                            if previous is not None
                            and previous[1].sites == sites
                            else None
                        )
                        changed = tuple(
                            (name, origin)
                            for name, identity, origin in loaded
                            if baseline is None
                            or name not in baseline[0]
                            or baseline[0][name][0]() is not identity[0]
                            or baseline[0][name][1:] != (identity[1], origin)
                        )
                        evidence_key = (
                            os.path.abspath(sys.executable),
                            paths,
                            sites,
                        )
                        evidence = getattr(
                            usage,
                            "_host_module_evidence",
                            None,
                        )
                        if evidence is None:
                            evidence = usage._host_module_evidence = {}
                        shared = (
                            evidence.get(evidence_key)
                            if previous is None or baseline is not None
                            else None
                        )
                        reusable = shared[1] if shared is not None else {}
                        owners = {
                            name: rows
                            for name, (state, rows) in reusable.items()
                            if name in current
                            and state[0]() is current[name][0]()
                            and state[1:] == current[name][1:]
                        }
                        pending = tuple(
                            (name, origin)
                            for name, origin in changed
                            if name not in owners
                        )
                        if baseline is not None and not changed:
                            snapshot = baseline[1]
                            imported = snapshot.distributions
                        elif not pending and shared is not None:
                            snapshot = shared[0]
                            imported = {}
                        else:
                            try:
                                if baseline is None:
                                    snapshot, imported = await run_sync_io(
                                        _observe_host_dependencies,
                                        code_root,
                                        paths,
                                        pending,
                                        inventory=observation_inputs(),
                                        _module_owners=owners,
                                    )
                                else:
                                    snapshot, imported = await run_sync_io(
                                        _observe_host_delta,
                                        code_root,
                                        paths,
                                        pending,
                                        baseline[1],
                                        inventory=observation_inputs(),
                                        _module_owners=owners,
                                    )
                            except Exception:
                                logger.debug(
                                    "Host dependency evidence unavailable",
                                    exc_info=True,
                                )
                                unknown()
                                return
                        if (
                            _host_dependency_state() == (paths, loaded)
                            and snapshot.sites == sites
                            and snapshot.dependency_sites is not None
                            and set(snapshot.dependency_sites) <= set(roots)
                        ):
                            if not valid():
                                return
                            old = previous[1].distributions if previous else {}
                            for name, _origin in changed:
                                for package, row in owners.get(
                                    name,
                                    {},
                                ).items():
                                    existing = imported.get(package)
                                    if existing is not None:
                                        modules = set(
                                            existing.get("loaded_modules", ()),
                                        )
                                        modules.update(
                                            row.get("loaded_modules", ()),
                                        )
                                        if modules:
                                            row = {
                                                **row,
                                                "loaded_modules": tuple(
                                                    sorted(modules),
                                                ),
                                            }
                                    imported[package] = row
                            # Historical ownership is append-only, including
                            # imports removed from sys.modules during teardown.
                            history = replace(
                                snapshot,
                                distributions={**imported, **old},
                            )
                            baselines[key] = (current, history)
                            evidence[evidence_key] = (
                                replace(snapshot, distributions={}),
                                {
                                    name: (current[name], rows)
                                    for name, rows in owners.items()
                                    if name in current
                                },
                            )
                            if history.distributions:
                                usage.observe_host(token, history)
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
