# -*- coding: utf-8 -*-
"""Dependency gate: boot check-only and host-package blacklist."""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import shlex
import sys
import tempfile
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version
from packaging.markers import default_environment
from packaging.requirements import Requirement
from . import wheel_additions

WheelAddition = wheel_additions.WheelAddition

logger = logging.getLogger(__name__)

# Known host packages that must not be pip-installed over a running process.
HOST_PACKAGE_NAMES: frozenset[str] = frozenset(
    {
        "httpx",
        "pydantic",
        "fastapi",
        "uvicorn",
        "starlette",
        "anyio",
        "openai",
        "agentscope",
        "reme-ai",
        "apscheduler",
    },
)

_IMPORT_NAME_OVERRIDES = {
    "pillow": "PIL",
    "pyyaml": "yaml",
    "beautifulsoup4": "bs4",
    "python-dateutil": "dateutil",
    "opencv-python": "cv2",
    "scikit-learn": "sklearn",
    "protobuf": "google.protobuf",
    "reme-ai": "reme",
}


@dataclass
class ParsedRequirements:
    """Installable requirements plus declarations this gate refuses."""

    requirements: list[Requirement] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)


@dataclass
class GateDecision:
    """Result of evaluating a plugin's requirements.txt."""

    allow_install: bool
    already_satisfied: bool
    missing: list[str] = field(default_factory=list)
    host_conflicts: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    require_restart: bool = False
    reason: str = ""
    reason_code: str = ""
    affected_instances: tuple[dict, ...] = ()


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def parse_requirement_lines(requirements_file: Path) -> list[Requirement]:
    """Parse installable requirement lines, skipping comments and flags."""
    return parse_requirements_file(requirements_file).requirements


def parse_requirements_file(requirements_file: Path) -> ParsedRequirements:
    """Parse requirements, recording unsupported declarations."""
    parsed = ParsedRequirements()
    if not requirements_file.is_file():
        return parsed
    for raw in requirements_file.read_text(encoding="utf-8").splitlines():
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-"):
            try:
                # Match pip's comment rules; '#' inside a URL is not a comment.
                args = shlex.split(re.split(r"\s+#", line, maxsplit=1)[0])
            except ValueError:
                args = []
            value = ""
            if len(args) == 2 and args[0] == "--index-url":
                value = args[1]
            elif len(args) == 1 and args[0].startswith("--index-url="):
                value = args[0].partition("=")[2]
            if value and not value.startswith("-"):
                continue
            parsed.unsupported.append(line)
            continue
        try:
            req = Requirement(line)
        except Exception:  # noqa: BLE001
            parsed.unsupported.append(line)
            continue
        if req.url or req.extras:
            parsed.unsupported.append(line)
            continue
        parsed.requirements.append(req)
    return parsed


def manifest_requirements(manifest: dict) -> list[str]:
    """Validate manifest entries using the same supported package syntax."""
    if not isinstance(manifest, dict):
        raise ValueError("plugin.json must contain an object")
    dependencies = manifest.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise ValueError("plugin.json dependencies must be a list of strings")
    result = []
    for declaration in dependencies:
        try:
            if not isinstance(declaration, str) or any(
                char in declaration for char in "\r\n"
            ):
                raise ValueError("Expected a single-line requirement")
            requirement = Requirement(declaration)
            if requirement.url or requirement.extras:
                raise ValueError("URLs and extras are unsupported")
        except ValueError as exc:
            raise ValueError(
                "plugin.json dependencies contains unsupported requirement "
                f"syntax: {declaration!r}",
            ) from exc
        result.append(str(requirement))
    return result


@contextmanager
def combined_requirements(source: Path) -> Iterator[Path]:
    """Merge declarations without modifying a potentially read-only source."""
    requirements = source / "requirements.txt"
    manifest = source / "plugin.json"
    dependencies = (
        manifest_requirements(json.loads(manifest.read_text(encoding="utf-8")))
        if manifest.is_file()
        else []
    )
    if not dependencies:
        yield requirements
        return
    content = (
        requirements.read_text(encoding="utf-8")
        if requirements.is_file()
        else ""
    )
    with tempfile.TemporaryDirectory(
        prefix="qwenpaw-plugin-requirements-",
    ) as tmp:
        merged = Path(tmp) / "requirements.txt"
        merged.write_text(
            content + "\n" + "\n".join(dependencies) + "\n",
            encoding="utf-8",
        )
        yield merged


def _dist_key(req: Requirement) -> str:
    return req.name.lower().replace("_", "-")


def _import_name(req: Requirement) -> str:
    dist = _dist_key(req)
    return _IMPORT_NAME_OVERRIDES.get(dist, req.name.replace("-", "_"))


def requirement_applies(req: Requirement) -> bool:
    """False when a PEP 508 marker excludes the current environment."""
    if req.marker is None:
        return True
    try:
        return bool(req.marker.evaluate(default_environment()))
    except Exception:  # noqa: BLE001
        return True


def is_requirement_satisfied(req: Requirement) -> bool:
    """Return True if *req* is importable, in-spec, or not applicable."""
    if not requirement_applies(req):
        return True
    try:
        installed = _dist_version(req.name)
    except PackageNotFoundError:
        installed = None
    if installed is not None:
        if not req.specifier:
            return True
        try:
            return req.specifier.contains(installed)
        except Exception:  # noqa: BLE001
            return True
    import_name = _import_name(req)
    top = import_name.split(".", 1)[0]
    try:
        return importlib.util.find_spec(top) is not None
    except (ImportError, ValueError):
        return False


def hits_imported_host_package(req: Requirement) -> bool:
    """True when installing *req* would overwrite a host-owned package."""
    if not requirement_applies(req):
        return False
    dist = _dist_key(req)
    if _is_frozen():
        return dist in HOST_PACKAGE_NAMES
    if dist in HOST_PACKAGE_NAMES:
        top = _import_name(req).split(".", 1)[0]
        if top in sys.modules:
            return True
        try:
            _dist_version(req.name)
            return True
        except PackageNotFoundError:
            return False
    return False


class DependencyGate:
    """Front door for ``_ensure_dependencies_installed``."""

    def evaluate(
        self,
        requirements_file: Path,
        *,
        allow_install: bool,
        plugin_id: str,
    ) -> GateDecision:
        """Decide whether to install, fail, or require a backend restart.

        Args:
            requirements_file: Plugin ``requirements.txt``.
            allow_install: False on boot (check only). True for explicit
                install / update / repair.
            plugin_id: Plugin id (for messages).
        """
        parsed = parse_requirements_file(requirements_file)
        if parsed.unsupported:
            return GateDecision(
                allow_install=False,
                already_satisfied=False,
                unsupported=list(parsed.unsupported),
                reason=(
                    f"Plugin '{plugin_id}' uses unsupported requirement "
                    f"syntax: {', '.join(parsed.unsupported)}"
                ),
            )
        reqs = parsed.requirements
        missing = [
            str(req) for req in reqs if not is_requirement_satisfied(req)
        ]
        if not missing:
            return GateDecision(
                allow_install=False,
                already_satisfied=True,
                reason="already satisfied",
            )

        conflicts = [
            str(req)
            for req in reqs
            if not is_requirement_satisfied(req)
            and hits_imported_host_package(req)
        ]
        if conflicts:
            return GateDecision(
                allow_install=False,
                already_satisfied=False,
                missing=missing,
                host_conflicts=conflicts,
                require_restart=True,
                reason_code="DEPENDENCY_RESTART_REQUIRED",
                reason=(
                    f"Plugin '{plugin_id}' declares host packages that "
                    f"are already imported ({', '.join(conflicts)}). "
                    "Restart the backend to apply."
                ),
            )

        if not allow_install:
            return GateDecision(
                allow_install=False,
                already_satisfied=False,
                missing=missing,
                reason=(
                    f"Plugin '{plugin_id}' is missing dependencies: "
                    + ", ".join(missing)
                ),
            )

        return GateDecision(
            allow_install=True,
            already_satisfied=False,
            missing=missing,
            reason="install required",
        )


class SharedDependencyError(RuntimeError):
    """An actionable shared-environment refusal with affected consumers."""

    def __init__(self, decision: GateDecision):
        self.decision = decision
        self.reason_code = decision.reason_code
        super().__init__(decision.reason)


def _unverified(detail):
    return SharedDependencyError(
        GateDecision(
            False,
            False,
            unsupported=[detail],
            reason=f"DEPENDENCY_PLAN_UNVERIFIED: {detail}",
            reason_code="DEPENDENCY_PLAN_UNVERIFIED",
        ),
    )


def _refine_admission(usage, token, snapshot, plugin_id, *, pending=False):
    if token is not None:
        try:
            usage.refine(
                token,
                snapshot,
                plugin_id=plugin_id,
                pending=pending,
            )
        except ValueError as exc:
            raise _unverified("admission identity mismatch") from exc


def _canonical_dependency_roots(paths):
    from .install_lock import canonical_environment_path

    return {str(canonical_environment_path(path)) for path in paths}


def _host_observation_roots(uses, sites, install_target=None):
    from .execution.dependencies import dependency_sites

    sites = _canonical_dependency_roots(sites)
    target = (
        next(iter(_canonical_dependency_roots((install_target,))))
        if install_target is not None
        else None
    )
    roots = set()
    for use in uses:
        if use.origin != "host" or use.snapshot is None:
            continue
        evidence = use.snapshot
        visible = _canonical_dependency_roots(evidence.sites)
        if use.environment is not None and (
            target not in visible
            if target is not None
            else not sites.intersection(
                _canonical_dependency_roots(use.environment.sites),
            )
        ):
            continue
        roots.update(
            _canonical_dependency_roots(
                evidence.dependency_sites
                if evidence.dependency_sites is not None
                else dependency_sites(evidence.sites),
            ),
        )
    return roots


async def _usage_observation_roots(usage, token, sites, install_target=None):
    from ..utils.io_utils import run_sync_io

    uses = usage.snapshot(None, admission_token=token).uses
    return await run_sync_io(
        _host_observation_roots,
        uses,
        sites,
        install_target,
    )


@asynccontextmanager
async def _shared_observation(targets, *, timeout=300.0):
    from .install_lock import environment_observation, ObservationRootsChanged

    try:
        async with environment_observation(targets, timeout=timeout):
            yield
    except ObservationRootsChanged:
        raise
    except RuntimeError as exc:
        code = str(exc).partition(":")[0]
        if isinstance(exc, SharedDependencyError) or not code.startswith(
            "DEPENDENCY_",
        ):
            raise
        raise SharedDependencyError(
            GateDecision(
                False,
                False,
                reason=str(exc),
                reason_code=code,
                require_restart=code == "DEPENDENCY_REPAIR_REQUIRED",
            ),
        ) from exc


async def admit_shared_dependencies(
    audit,
    *,
    plugin_id,
    requirements_file,
    usage_registry,
    admission_token=None,
    snapshot=None,
    targets=(),
    validate=None,
):
    """Audit and admit the exact consumer under environment exclusion."""
    from .execution.dependencies import DependencySnapshot
    from .install_lock import ObservationRootsChanged
    from ..utils.io_utils import run_sync_io

    keys = await run_sync_io(
        _canonical_dependency_roots,
        (
            snapshot.dependency_sites
            if isinstance(snapshot, DependencySnapshot)
            and snapshot.dependency_sites is not None
            else targets
        ),
    )
    # Release before reacquiring one changed root set; never re-enter prepare.
    for _attempt in range(2):
        host_roots = await _usage_observation_roots(
            usage_registry,
            admission_token,
            keys,
        )
        async with _shared_observation(keys | host_roots):
            if validate is not None:
                validate()
            try:
                observed = await audit()
            except ObservationRootsChanged as exc:
                keys = set(exc.targets)
                continue
            if validate is not None:
                validate()
            if (
                not isinstance(observed, DependencySnapshot)
                or observed.dependency_sites is None
            ):
                raise _unverified("admission evidence unavailable")
            actual = await run_sync_io(
                _canonical_dependency_roots,
                observed.dependency_sites,
            )
            if validate is not None:
                validate()
            if actual != keys and not (
                validate is not None and actual.issubset(keys)
            ):
                keys = actual
                continue
            _refine_admission(
                usage_registry,
                admission_token,
                observed,
                plugin_id,
            )
            try:
                decision = await _evaluate_shared_dependencies_async(
                    requirements_file,
                    observed,
                    plugin_id=plugin_id,
                    usage_registry=usage_registry,
                    admission_token=admission_token,
                )
            except ObservationRootsChanged:
                continue
            if validate is not None:
                validate()
            if not decision.already_satisfied:
                raise SharedDependencyError(decision)
            _refine_admission(
                usage_registry,
                admission_token,
                observed,
                plugin_id,
                pending=True,
            )
            return observed
    raise _unverified("admission roots changed")


# Each consumer retains its marker and origin context through closure checks.
# pylint: disable=too-many-statements,too-many-branches
def evaluate_shared_dependencies(
    requirements_file: Path,
    snapshot,
    *,
    plugin_id: str,
    uses=(),
    install_target: Path | None = None,
    extra_requirements=(),
    installed_distributions=None,
) -> GateDecision:
    """Validate each consumer in its own observed environment."""
    from packaging.utils import canonicalize_name
    from packaging.version import Version
    from .execution.dependencies import (
        _installed_metadata,
        _provides_loaded_modules,
        repair_marker,
        retains_installed_wheel_source,
    )
    from .install_lock import canonical_environment_path

    resolved = {}

    def canonical(path):
        key = str(path)
        if key not in resolved:
            resolved[key] = canonical_environment_path(path)
        return resolved[key]

    parsed = (
        parse_requirements_file(requirements_file)
        if requirements_file is not None
        else ParsedRequirements()
    )
    missing, conflicts, unsupported = [], [], list(parsed.unsupported)
    affected = []
    target = (
        str(canonical(install_target)) if install_target is not None else None
    )
    sites = {str(canonical(path)) for path in snapshot.dependency_sites or ()}
    host_inventories = {}
    record_reads, record_names, provider_matches = {}, {}, {}
    host_dirty = False
    extra_requirements = tuple(extra_requirements)
    additions = set()
    for value in extra_requirements:
        try:
            additions.add(str(canonicalize_name(Requirement(str(value)).name)))
        except ValueError:
            pass  # The normal requirement checker reports unsupported syntax.

    def check(values, inventory, markers, invalid=(), *, installed=None):
        pending = [(value, (), False) for value in values]
        visited = set()
        while pending:
            value, parent_extras, transitive = pending.pop()
            identity = (str(value), parent_extras, transitive)
            if identity in visited:
                continue
            visited.add(identity)
            try:
                requirement = Requirement(str(value))
                if requirement.marker:
                    if markers is None or not set(
                        default_environment(),
                    ) <= set(markers):
                        unsupported.append(
                            f"marker evidence unavailable: {value}",
                        )
                        continue
                    if not any(
                        requirement.marker.evaluate(
                            {**markers, "extra": extra},
                        )
                        for extra in ("", *parent_extras)
                    ):
                        continue
                if requirement.extras and not transitive:
                    unsupported.append(str(value))
                    continue
                name = str(canonicalize_name(requirement.name))
                if name in invalid:
                    unsupported.append(f"{invalid[name]}: {name}")
                    continue
                row = inventory.get(name)
                if requirement.url and (
                    not transitive
                    or not retains_installed_wheel_source(
                        requirement,
                        row,
                        (installed or {}).get(name),
                    )
                ):
                    unsupported.append(str(value))
                    continue
                if row is None:
                    missing.append(str(value))
                    continue
                if not requirement.specifier.contains(
                    Version(row["version"]),
                    prereleases=True,
                ):
                    missing.append(str(value))
                    conflicts.append(str(value))
                extras = tuple(sorted(requirement.extras))
                pending.extend(
                    (dependency, extras, True)
                    for dependency in row["requires_dist"]
                )
            except (ValueError, TypeError, KeyError):
                unsupported.append(str(value))

    check(
        [*parsed.requirements, *extra_requirements],
        snapshot.distributions,
        snapshot.marker_environment,
        installed=(
            snapshot.distributions
            if installed_distributions is None
            else installed_distributions
        ),
    )
    for use in uses:
        environment, evidence = use.environment, use.snapshot
        visible = (
            {str(canonical(path)) for path in evidence.sites}
            if evidence is not None
            else (
                {str(canonical(path)) for path in environment.sites}
                if environment is not None
                else None
            )
        )
        if environment is not None and (
            target not in (visible or set())
            if target is not None
            else not sites.intersection(
                str(canonical(path)) for path in environment.sites
            )
        ):
            continue
        affected.append(
            {
                "plugin_id": use.plugin_id,
                "instance_id": use.instance_id,
                "generation": use.generation,
                "origin": use.origin,
                "active": use.active,
            },
        )
        if environment is None:
            unsupported.append(
                f"{use.origin} {use.plugin_id}: "
                "environment evidence unavailable",
            )
            continue
        if use.origin == "host":
            if evidence is None:
                unsupported.append(
                    f"host {use.plugin_id}: import evidence unavailable",
                )
                continue
            values = [
                f"{name}=={row['version']}"
                for name, row in evidence.distributions.items()
            ]
            roots = tuple(
                dict.fromkeys(str(canonical(path)) for path in evidence.sites),
            )
            try:
                if roots not in host_inventories:
                    rows, invalid, _observed = _installed_metadata(
                        roots,
                        record_reads=record_reads,
                    )
                    del _observed
                    host_inventories[roots] = (rows, invalid)
                rows, invalid = host_inventories[roots]
            except Exception as exc:
                code = getattr(
                    exc,
                    "reason_code",
                    "DEPENDENCY_PLAN_UNVERIFIED",
                )
                host_dirty |= code == "DEPENDENCY_REPAIR_REQUIRED"
                unsupported.append(f"host {use.plugin_id}: {code}")
                continue
            inventory = {
                name: row for name, row in rows.items() if name not in invalid
            }
            for name, pin in evidence.distributions.items():
                fresh = inventory.get(name)
                if fresh is not None and pin.get("loaded_modules"):
                    embedded_tops = set(pin.get("loaded_modules", ()))
                    # Loaded embedded modules remain pinned to their owner.
                    # A newly visible public provider would resolve differently
                    # after restart, even when the owning wheel is unchanged.
                    for provider_name, provider in {
                        **inventory,
                        **{
                            key: row
                            for key, row in snapshot.distributions.items()
                            if str(
                                canonical(Path(row["metadata_path"]).parent),
                            )
                            in (
                                {target}
                                if target is not None
                                else visible or set()
                            )
                        },
                    }.items():
                        if provider_name in evidence.distributions:
                            continue
                        # Rows remain referenced by the inventories/snapshot;
                        # identity distinguishes all provider evidence sources.
                        key = (
                            provider_name,
                            id(provider),
                            frozenset(embedded_tops),
                        )
                        if key not in provider_matches:
                            provider_matches[key] = _provides_loaded_modules(
                                provider,
                                embedded_tops,
                                record_reads=record_reads,
                                record_names=record_names,
                            )
                        if provider_matches[key]:
                            conflicts.append(
                                f"host {use.plugin_id}: {provider_name} "
                                "shadows a loaded embedded module",
                            )
                if fresh is None:
                    missing.append(f"{name}=={pin['version']}")
                elif fresh["version"] != pin["version"] or (
                    fresh["metadata_path"] != pin["metadata_path"]
                    and str(canonical(fresh["metadata_path"]))
                    != str(canonical(pin["metadata_path"]))
                ):
                    conflicts.append(
                        f"host {use.plugin_id}: {name} origin/version differs",
                    )
        elif use.requirements is None:
            unsupported.append(
                f"{use.origin} {use.plugin_id}: requirements unavailable",
            )
            continue
        else:
            values = use.requirements
        if use.origin != "host":
            inventory = (
                dict(evidence.distributions) if evidence is not None else {}
            )
            invalid = ()
        installed = dict(inventory)
        relevant_rows = {
            name: row
            for name, row in snapshot.distributions.items()
            if str(canonical(Path(row["metadata_path"]).parent))
            in ({target} if target is not None else visible or set())
        }
        for name, row in relevant_rows.items():
            previous = inventory.get(name)
            if use.origin == "host" and (
                name in invalid or (previous is None and name not in additions)
            ):
                continue
            if previous is not None and (
                previous["version"] != row["version"]
                or (
                    previous["metadata_path"] != row["metadata_path"]
                    and str(canonical(previous["metadata_path"]))
                    != str(canonical(row["metadata_path"]))
                )
            ):
                conflicts.append(
                    f"{use.origin} {use.plugin_id}: "
                    f"{name} origin/version differs",
                )
            elif use.origin != "host" or previous is None:
                inventory[name] = row
        check(
            values,
            inventory,
            environment.marker_environment,
            invalid,
            installed=installed,
        )
    from .dependency_maintenance import authorized

    dirty = host_dirty or any(
        repair_marker(site).exists() and not authorized(site)
        for site in snapshot.sites
    )
    code = (
        "DEPENDENCY_REPAIR_REQUIRED"
        if dirty
        else (
            "DEPENDENCY_PLAN_UNVERIFIED"
            if unsupported
            else (
                "DEPENDENCY_RESTART_REQUIRED"
                if conflicts
                else "DEPENDENCY_UNSATISFIED"
                if missing
                else ""
            )
        )
    )
    detail = ", ".join(sorted(set(missing + conflicts + unsupported)))
    origins = ", ".join(
        sorted({f"{use['origin']} {use['plugin_id']}" for use in affected}),
    )
    reason = (
        "already satisfied"
        if not code
        else (
            f"{code}: {plugin_id}: {detail}. "
            f"Consumers: {origins or 'none known'}. "
            "Stop environment consumers before explicit repair and re-audit. "
            "Source rollback does not restore dependency packages."
        )
    )
    return GateDecision(
        False,
        not code,
        sorted(set(missing)),
        sorted(set(conflicts)),
        sorted(set(unsupported)),
        bool(conflicts or dirty),
        reason,
        code,
        tuple(affected),
    )


async def _evaluate_shared_dependencies_async(
    requirements_file,
    snapshot,
    *,
    usage_registry,
    admission_token=None,
    **kwargs,
):
    """Read disk evidence against detached usage, then authorize on-loop."""
    from ..utils.io_utils import run_sync_io
    from .install_lock import environment_observation

    while True:
        before = usage_registry.snapshot(
            None,
            admission_token=admission_token,
        )
        roots = await run_sync_io(
            _host_observation_roots,
            before.uses,
            snapshot.dependency_sites or (),
            kwargs.get("install_target"),
        )
        async with environment_observation(roots):
            decision = await run_sync_io(
                evaluate_shared_dependencies,
                requirements_file,
                snapshot,
                uses=before.uses,
                **kwargs,
            )
        current = usage_registry.snapshot(
            None,
            admission_token=admission_token,
        )
        if current.revision == before.revision:
            return decision


async def prepare_shared_dependencies(
    process,
    spec,
    *,
    plugin_id: str,
    requirements_file: Path,
    usage_registry,
    admission_token=None,
    install_target: Path | None = None,
    wheels=(),
    lock_timeout: float = 300.0,
    expected_snapshot=None,
    wheel_tags=None,
    installer_python=None,
    collision_sites=(),
    targets=(),
):
    """Coordinate, audit, query current usage and publish safe additions."""
    from .install_lock import canonical_environment_path as canonical
    from .wheel_additions import validate_additions
    from .execution.dependencies import protected_dependency_target
    from ..utils.io_utils import run_sync_io

    def inspect_target():
        target = (
            canonical(install_target) if install_target is not None else None
        )
        if target is not None and protected_dependency_target(target):
            raise _unverified("protected publication target")
        return target

    target = await run_sync_io(inspect_target)

    async def audit():
        observed = (await process.audit(spec)).snapshot
        _refine_admission(usage_registry, admission_token, observed, plugin_id)
        return observed

    async def evaluate(observed, extra=()):
        return await _evaluate_shared_dependencies_async(
            requirements_file,
            observed,
            plugin_id=plugin_id,
            usage_registry=usage_registry,
            admission_token=admission_token,
            install_target=target,
            extra_requirements=extra,
            installed_distributions=snapshot.distributions,
        )

    # A known destination waits before inspection so an in-flight marker is
    # not mistaken for inherited damage. Cold unknown inspection fails closed.
    preliminary = None
    if target is None:
        async with _shared_observation(targets):
            preliminary = await audit()
    keys = (target,) if target is not None else preliminary.dependency_sites
    if keys is None:
        raise SharedDependencyError(
            GateDecision(
                False,
                False,
                unsupported=["environment evidence unavailable"],
                reason=(
                    "DEPENDENCY_PLAN_UNVERIFIED: "
                    "environment evidence unavailable"
                ),
                reason_code="DEPENDENCY_PLAN_UNVERIFIED",
            ),
        )
    keys = await run_sync_io(_canonical_dependency_roots, keys)
    observation_roots = await run_sync_io(
        _canonical_dependency_roots,
        (
            *keys,
            *targets,
            *(
                expected_snapshot.dependency_sites or ()
                if expected_snapshot is not None
                else ()
            ),
        ),
    )
    observation_roots |= await _usage_observation_roots(
        usage_registry,
        admission_token,
        keys,
        target,
    )
    async with _shared_observation(observation_roots, timeout=lock_timeout):
        snapshot = await audit()
        if expected_snapshot is not None and snapshot != expected_snapshot:
            raise SharedDependencyError(
                GateDecision(
                    False,
                    False,
                    require_restart=True,
                    reason=(
                        "DEPENDENCY_RESTART_REQUIRED: "
                        "environment changed during resolution"
                    ),
                    reason_code="DEPENDENCY_RESTART_REQUIRED",
                ),
            )
        if target is None and (
            await run_sync_io(
                _canonical_dependency_roots,
                snapshot.dependency_sites or (),
            )
            != keys
        ):
            raise SharedDependencyError(
                GateDecision(
                    False,
                    False,
                    reason="DEPENDENCY_PLAN_UNVERIFIED: environment changed",
                    reason_code="DEPENDENCY_PLAN_UNVERIFIED",
                ),
            )
        decision = await evaluate(snapshot)
        if decision.already_satisfied:
            return snapshot
        if (
            not wheels
            or target is None
            or decision.require_restart
            or decision.unsupported
        ):
            raise SharedDependencyError(decision)

        def valid_target():
            return (
                snapshot.dependency_sites is not None
                and not protected_dependency_target(target)
                and str(target)
                in {str(canonical(path)) for path in snapshot.dependency_sites}
                and str(target)
                in {str(canonical(path)) for path in snapshot.sites}
            )

        if os.environ.get("QWENPAW_RUNTIME_PROVISIONER") == "local" or not (
            await run_sync_io(valid_target)
        ):
            raise SharedDependencyError(
                GateDecision(
                    False,
                    False,
                    reason=(
                        "DEPENDENCY_PLAN_UNVERIFIED: "
                        "invalid publication target"
                    ),
                    reason_code="DEPENDENCY_PLAN_UNVERIFIED",
                ),
            )
        try:
            from dataclasses import replace

            files, proposed = await run_sync_io(
                validate_additions,
                tuple(wheels),
                replace(
                    snapshot,
                    supported_tags=wheel_tags or snapshot.supported_tags,
                    executable=installer_python or snapshot.executable,
                    sites=tuple(
                        dict.fromkeys(
                            (*snapshot.sites, *map(str, collision_sites)),
                        ),
                    ),
                ),
                target,
            )
            proposed = replace(
                proposed,
                supported_tags=snapshot.supported_tags,
                executable=snapshot.executable,
                sites=snapshot.sites,
            )
        except Exception as exc:
            code = getattr(exc, "reason_code", "DEPENDENCY_PLAN_UNVERIFIED")
            raise SharedDependencyError(
                GateDecision(
                    False,
                    False,
                    reason=code,
                    reason_code=code,
                    require_restart=code == "DEPENDENCY_RESTART_REQUIRED",
                ),
            ) from exc
        added = tuple(
            f"{name}=={row['version']}"
            for name, row in proposed.distributions.items()
            if name not in snapshot.distributions
        )
        # No await separates the final usage check from submitting publication.
        decision = await evaluate(proposed, added)
        if not decision.already_satisfied:
            raise SharedDependencyError(decision)
        return await _publish_additions(audit, evaluate, target, files)


async def _publish_additions(audit, evaluate, target, files):
    """Keep exclusion through exact-byte publication and child verification."""
    import asyncio
    from .execution.dependencies import repair_marker
    from .dependency_maintenance import _admission_gate, file_lock
    from .install_lock import async_lock
    from ..utils.io_utils import run_sync_io

    def mark(message):
        repair_marker(target).write_text(message, encoding="utf-8")

    def publish():
        mark("Shared dependency publication requires verification.\n")
        _write_additions(target, files)

    admission = await run_sync_io(_admission_gate, target)
    async with async_lock(file_lock(admission, timeout=5)):
        try:
            await run_sync_io(publish)
        except asyncio.CancelledError:
            await run_sync_io(
                mark,
                "Cancelled dependency publication requires repair.\n",
            )
            raise
        except Exception as exc:
            raise SharedDependencyError(
                GateDecision(
                    False,
                    False,
                    reason="Dependency publication failed; repair is required.",
                    reason_code="DEPENDENCY_REPAIR_REQUIRED",
                    require_restart=True,
                ),
            ) from exc
        try:
            await run_sync_io(lambda: repair_marker(target).unlink())
            snapshot = await audit()
            decision = await evaluate(snapshot)
            if not decision.already_satisfied:
                raise SharedDependencyError(decision)
        except BaseException:
            await run_sync_io(
                mark,
                "Dependency verification failed; repair required.\n",
            )
            raise
        return snapshot


def _write_additions(target: Path, files: dict[str, bytes]) -> None:
    """Publish the exact validated bytes while the site lock remains held."""

    def validate_path(path):
        if not path.resolve().is_relative_to(target) or any(
            parent.is_symlink()
            for parent in (path, *path.parents)
            if parent.is_relative_to(target)
        ):
            raise RuntimeError("DEPENDENCY_REPAIR_REQUIRED")

    for relative, content in files.items():
        path = target / relative
        validate_path(path)
        missing_parents = []
        parent = path.parent
        while not parent.exists():
            missing_parents.append(parent)
            parent = parent.parent
        for parent in reversed(missing_parents):
            parent.mkdir(mode=0o755, exist_ok=True)
        validate_path(path)
        mode = (
            0o755
            if relative in getattr(files, "executable_paths", ())
            else 0o644
        )
        flags = (
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        )
        with os.fdopen(os.open(path, flags, mode), "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
