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
from contextlib import contextmanager
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


async def admit_shared_dependencies(
    audit,
    *,
    plugin_id,
    requirements_file,
    usage_registry,
    admission_token=None,
    snapshot=None,
    targets=(),
):
    """Audit and admit the exact consumer under environment exclusion."""
    from .execution.dependencies import DependencySnapshot
    from .install_lock import (
        canonical_environment_path as canonical,
        environment_coordinator,
    )

    keys = {
        canonical(path)
        for path in (
            snapshot.dependency_sites
            if isinstance(snapshot, DependencySnapshot)
            and snapshot.dependency_sites is not None
            else targets
        )
    }
    # Release before reacquiring one changed root set; never re-enter prepare.
    for _attempt in range(2):
        async with environment_coordinator(keys):
            observed = await audit()
            if (
                not isinstance(observed, DependencySnapshot)
                or observed.dependency_sites is None
            ):
                raise _unverified("admission evidence unavailable")
            actual = {canonical(path) for path in observed.dependency_sites}
            if actual != keys:
                keys = actual
                continue
            _refine_admission(
                usage_registry,
                admission_token,
                observed,
                plugin_id,
            )
            decision = evaluate_shared_dependencies(
                requirements_file,
                observed,
                plugin_id=plugin_id,
                uses=usage_registry.snapshot(
                    None,
                    admission_token=admission_token,
                ).uses,
            )
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
        repair_marker,
        retains_installed_wheel_source,
    )
    from .install_lock import canonical_environment_path as canonical

    parsed = (
        parse_requirements_file(requirements_file)
        if requirements_file is not None
        else ParsedRequirements()
    )
    missing, conflicts, unsupported = [], [], list(parsed.unsupported)
    affected = []
    target = canonical(install_target) if install_target is not None else None
    sites = {canonical(path) for path in snapshot.dependency_sites or ()}
    host_inventories = {}
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
            {canonical(path) for path in evidence.sites}
            if evidence is not None
            else (
                {canonical(path) for path in environment.sites}
                if environment is not None
                else None
            )
        )
        if environment is not None and (
            target not in (visible or set())
            if target is not None
            else not sites.intersection(
                canonical(path) for path in environment.sites
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
                    rows, invalid, _observed = _installed_metadata(roots)
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
                if fresh is None:
                    missing.append(f"{name}=={pin['version']}")
                elif fresh["version"] != pin["version"] or canonical(
                    fresh["metadata_path"],
                ) != canonical(pin["metadata_path"]):
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
            if canonical(Path(row["metadata_path"]).parent)
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
                or canonical(previous["metadata_path"])
                != canonical(row["metadata_path"])
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
):
    """Coordinate, audit, query current usage and publish safe additions."""
    from contextlib import AsyncExitStack
    from .install_lock import (
        async_lock,
        canonical_environment_path as canonical,
        environment_coordinator,
        environment_install_lock_path,
        plugin_install_lock,
    )
    from .wheel_additions import validate_additions
    from .execution.dependencies import protected_dependency_target

    target = canonical(install_target) if install_target is not None else None
    if target is not None and protected_dependency_target(target):
        raise _unverified("protected publication target")

    async def audit():
        observed = (await process.audit(spec)).snapshot
        _refine_admission(usage_registry, admission_token, observed, plugin_id)
        return observed

    def evaluate(observed, extra=()):
        return evaluate_shared_dependencies(
            requirements_file,
            observed,
            plugin_id=plugin_id,
            uses=usage_registry.snapshot(
                None,
                admission_token=admission_token,
            ).uses,
            install_target=target,
            extra_requirements=extra,
            installed_distributions=snapshot.distributions,
        )

    # A known destination waits before inspection so an in-flight marker is
    # not mistaken for inherited damage. Cold unknown inspection fails closed.
    preliminary = None if target is not None else await audit()
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
    async with environment_coordinator(keys), AsyncExitStack() as stack:
        if target is not None:
            try:
                await stack.enter_async_context(
                    async_lock(
                        plugin_install_lock(
                            environment_install_lock_path(target),
                            timeout=lock_timeout,
                        ),
                    ),
                )
            except RuntimeError as exc:
                code = str(exc).partition(":")[0]
                if not code.startswith("DEPENDENCY_"):
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
        if target is None and {
            canonical(path) for path in snapshot.dependency_sites or ()
        } != {canonical(path) for path in keys}:
            raise SharedDependencyError(
                GateDecision(
                    False,
                    False,
                    reason="DEPENDENCY_PLAN_UNVERIFIED: environment changed",
                    reason_code="DEPENDENCY_PLAN_UNVERIFIED",
                ),
            )
        decision = evaluate(snapshot)
        if decision.already_satisfied:
            return snapshot
        if (
            not wheels
            or target is None
            or decision.require_restart
            or decision.unsupported
        ):
            raise SharedDependencyError(decision)
        if (
            snapshot.dependency_sites is None
            or protected_dependency_target(target)
            or target
            not in {canonical(path) for path in snapshot.dependency_sites}
            or target not in {canonical(path) for path in snapshot.sites}
            or os.environ.get("QWENPAW_RUNTIME_PROVISIONER") == "local"
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
            files, proposed = validate_additions(
                tuple(wheels),
                snapshot,
                target,
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
        # This fresh query is the final no-await authorization before writing.
        decision = evaluate(proposed, added)
        if not decision.already_satisfied:
            raise SharedDependencyError(decision)
        return await _publish_additions(audit, evaluate, target, files)


async def _publish_additions(audit, evaluate, target, files):
    """Keep exclusion through exact-byte publication and child verification."""
    import asyncio
    from .execution.dependencies import repair_marker
    from .execution.process import _settle

    marker = repair_marker(target)
    marker.write_text(
        "Shared dependency publication requires verification.\n",
        encoding="utf-8",
    )
    writer = asyncio.create_task(
        asyncio.to_thread(_write_additions, target, files),
    )
    try:
        await asyncio.shield(writer)
    except asyncio.CancelledError:
        try:
            await _settle(writer)
        finally:
            marker.write_text(
                "Cancelled dependency publication requires repair.\n",
                encoding="utf-8",
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
    marker.unlink()
    try:
        snapshot = await audit()
        decision = evaluate(snapshot)
        if not decision.already_satisfied:
            raise SharedDependencyError(decision)
    except BaseException:
        marker.write_text(
            "Dependency verification failed; repair required.\n",
            encoding="utf-8",
        )
        raise
    return snapshot


def _write_additions(target: Path, files: dict[str, bytes]) -> None:
    """Publish the exact validated bytes while the site lock remains held."""
    for relative, content in files.items():
        path = target / relative
        if not path.resolve().is_relative_to(target) or path.is_symlink():
            raise RuntimeError("DEPENDENCY_REPAIR_REQUIRED")
        missing_parents = []
        parent = path.parent
        while not parent.exists():
            missing_parents.append(parent)
            parent = parent.parent
        for parent in reversed(missing_parents):
            parent.mkdir(mode=0o755, exist_ok=True)
        if not path.resolve().is_relative_to(target) or path.is_symlink():
            raise RuntimeError("DEPENDENCY_REPAIR_REQUIRED")
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
