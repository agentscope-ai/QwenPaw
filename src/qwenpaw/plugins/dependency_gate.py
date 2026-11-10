# -*- coding: utf-8 -*-
"""Plugin-local dependency checks and coordinated shared writes."""

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
from importlib.metadata import requires as _dist_requires
from packaging.markers import default_environment
from packaging.requirements import Requirement
from . import wheel_additions

WheelAddition = wheel_additions.WheelAddition

logger = logging.getLogger(__name__)

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
    warnings: tuple[str, ...] = ()


def parse_requirements_file(requirements_file: Path) -> ParsedRequirements:
    """Parse requirements, recording unsupported declarations."""
    parsed = ParsedRequirements()
    if not requirements_file.is_file():
        return parsed
    for raw in requirements_file.read_text(encoding="utf-8-sig").splitlines():
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
        if req.url:
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
            if requirement.url:
                raise ValueError("Direct URLs are unsupported")
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
        manifest_requirements(
            json.loads(manifest.read_text(encoding="utf-8-sig")),
        )
        if manifest.is_file()
        else []
    )
    if not dependencies:
        yield requirements
        return
    content = (
        requirements.read_text(encoding="utf-8-sig")
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
        from .execution.dependencies import _dependency_closure

        class InstalledRequirements(dict):
            # Fetch only metadata reached through active requirements/extras.
            def get(self, name, default=None):
                if name not in self:
                    try:
                        self[name] = {
                            "version": _dist_version(name),
                            "requires_dist": tuple(_dist_requires(name) or ()),
                        }
                    except PackageNotFoundError:
                        self[name] = None
                return super().get(name, default)

        try:
            reqs = list(
                {
                    str(req): req
                    for _name, req in _dependency_closure(
                        [str(req) for req in parsed.requirements],
                        InstalledRequirements(),
                        default_environment(),
                        verify_sources=False,
                    )
                }.values(),
            )
        except ValueError as exc:
            return GateDecision(
                False,
                False,
                unsupported=[str(exc)],
                reason="Invalid dependency metadata",
                reason_code="DEPENDENCY_METADATA_INVALID",
            )
        # Markers were evaluated with their parent extras by the closure.
        for req in reqs:
            req.marker = None
        missing = [
            str(req) for req in reqs if not is_requirement_satisfied(req)
        ]
        if not missing:
            warnings = []
            for req in reqs:
                if not requirement_applies(req):
                    continue
                try:
                    _dist_version(req.name)
                except PackageNotFoundError:
                    warnings.append(
                        f"{req}: installed version unknown; attempting load",
                    )
            return GateDecision(
                allow_install=bool(warnings) and allow_install,
                already_satisfied=not warnings,
                warnings=tuple(warnings),
                reason=(
                    "already satisfied"
                    if not warnings
                    else "dependency version unknown"
                ),
            )

        if not allow_install:
            absent, warnings = [], []
            for value in missing:
                req = Requirement(value)
                try:
                    installed = _dist_version(req.name)
                except PackageNotFoundError:
                    absent.append(value)
                else:
                    warnings.append(
                        f"{req}: installed {installed}; attempting load",
                    )
            return GateDecision(
                allow_install=False,
                already_satisfied=False,
                missing=absent,
                warnings=tuple(warnings),
                reason=(
                    (
                        f"Plugin '{plugin_id}' is missing dependencies: "
                        + ", ".join(absent)
                    )
                    if absent
                    else "dependency version warning"
                ),
                reason_code="DEPENDENCY_UNSATISFIED" if absent else "",
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
    uses = tuple(uses)
    providers = [
        row.get("metadata_path")
        for use in uses
        if use.snapshot is not None
        for row in use.snapshot.distributions.values()
    ]
    providers += [
        fact.origin
        for use in uses
        for fact in getattr(use, "host_modules", ())
    ]
    unknown = any(
        use.origin == "host" and use.environment is None for use in uses
    )

    def retired_search_root(root):
        return (
            root not in sites
            and root != target
            and not unknown
            and not Path(root).exists()
            and not Path(root).is_symlink()
            and all(
                origin and not Path(origin).is_relative_to(root)
                for origin in providers
            )
        )

    roots = set()
    for use in uses:
        if use.read_admitted and use.environment is not None:
            visible = _canonical_dependency_roots(use.environment.sites)
            if (
                target in visible
                if target is not None
                else sites.intersection(visible)
            ):
                roots.update(
                    root for root in visible if not retired_search_root(root)
                )
        if (
            use.origin == "host"
            and use.snapshot is None
            and use.environment is not None
        ):
            roots.update(
                root
                for root in _canonical_dependency_roots(use.environment.sites)
                if not retired_search_root(root)
            )
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
        historical = _canonical_dependency_roots(
            (
                evidence.dependency_sites
                if evidence.dependency_sites is not None
                else dependency_sites(evidence.sites)
            ),
        )
        providers = [
            row.get("metadata_path") for row in evidence.distributions.values()
        ]
        for root in historical:
            try:
                Path(root).stat()
            except FileNotFoundError:
                # A retired search-only source is not a publication root.
                # Keep missing actual/provider roots subject to lock validation.
                if (
                    root not in sites
                    and root != target
                    and not Path(root).is_symlink()
                    and all(
                        origin and not Path(origin).is_relative_to(root)
                        for origin in providers
                    )
                ):
                    continue
            roots.add(root)
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
    from .execution.dependencies import (
        DependencyReadEvidence,
        DependencySnapshot,
    )
    from ..utils.io_utils import run_sync_io

    roots = await run_sync_io(_canonical_dependency_roots, targets)
    if isinstance(snapshot, (DependencySnapshot, DependencyReadEvidence)):
        roots |= await run_sync_io(
            _canonical_dependency_roots,
            snapshot.dependency_sites or (),
        )
    for _attempt in range(2):
        async with _shared_observation(roots):
            if validate is not None:
                validate()
            observed = await audit()
            if not isinstance(
                observed,
                (DependencySnapshot, DependencyReadEvidence),
            ):
                raise _unverified("admission environment unavailable")
            if validate is not None:
                validate()
            actual = await run_sync_io(
                _canonical_dependency_roots,
                observed.dependency_sites or (),
            )
            if not actual <= roots:
                roots |= actual
                continue
            _refine_admission(
                usage_registry,
                admission_token,
                observed,
                plugin_id,
                pending=True,
            )
            return observed
    raise _unverified("admission roots changed during inspection")


def evaluate_shared_dependencies(
    requirements_file,
    snapshot,
    *,
    plugin_id,
    uses=(),
    extra_requirements=(),
    installed_distributions=None,
    inventory=None,
    planned_records=None,
):
    """Check the requested closure; historical consumers are not install goals."""
    from .execution.dependencies import _dependency_closure, repair_marker
    from .dependency_maintenance import authorized

    parsed = (
        parse_requirements_file(requirements_file)
        if requirements_file is not None
        else ParsedRequirements()
    )
    missing, unsupported, conflicts = [], list(parsed.unsupported), []
    try:
        for name, requirement in _dependency_closure(
            [*(str(req) for req in parsed.requirements), *extra_requirements],
            snapshot.distributions,
            snapshot.marker_environment,
        ):
            row = snapshot.distributions.get(name)
            if row is None or not requirement.specifier.contains(
                row["version"],
                prereleases=True,
            ):
                missing.append(str(requirement))
    except (ValueError, TypeError, KeyError) as exc:
        unsupported.append(str(exc))

    # Additions may expose a public provider for a loaded embedded module.
    # Only the proposed changes matter; never compare an entire old snapshot.
    if installed_distributions is not None:
        from .execution.dependencies import (
            _provides_loaded_modules,
            host_module_affected,
        )

        record_reads = dict((inventory or {}).get("records", {}))
        record_reads.update(planned_records or {})
        changed = {
            name: row
            for name, row in snapshot.distributions.items()
            if installed_distributions.get(name) != row
        }
        for use in uses:
            if use.origin != "host":
                continue
            for name, row in changed.items():
                if host_module_affected(
                    row,
                    getattr(use, "host_modules", ()),
                    record_reads=record_reads,
                ):
                    conflicts.append(
                        f"host {use.plugin_id}: {name} changes or shadows loaded code",
                    )
            if use.snapshot is None:
                continue
            for name, row in changed.items():
                for owner, old in use.snapshot.distributions.items():
                    modules = old.get("loaded_modules", ())
                    if modules and (
                        owner == name
                        or _provides_loaded_modules(
                            row,
                            modules,
                            record_reads=record_reads,
                        )
                    ):
                        conflicts.append(
                            f"host {use.plugin_id}: {name} "
                            + (
                                "changes loaded code"
                                if owner == name
                                else "shadows a loaded embedded module"
                            ),
                        )
    dirty = any(
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
    return GateDecision(
        False,
        not code,
        sorted(set(missing)),
        sorted(set(conflicts)),
        sorted(set(unsupported)),
        bool(dirty or conflicts),
        (
            f"{code}: {plugin_id}: {', '.join(sorted(set(missing + conflicts + unsupported)))}"
            if code
            else "already satisfied"
        ),
        code,
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
    from .install_lock import observation_inputs

    before = usage_registry.snapshot(None, admission_token=admission_token)
    return await run_sync_io(
        evaluate_shared_dependencies,
        requirements_file,
        snapshot,
        uses=before.uses,
        inventory=observation_inputs(),
        **kwargs,
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
    wheel_tags=None,
    installer_python=None,
    installer_identity=None,
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
        from .execution.dependencies import DependencySnapshot

        observed = (await process.audit(spec)).snapshot
        if not isinstance(observed, DependencySnapshot):
            raise _unverified("complete write evidence required")
        _refine_admission(usage_registry, admission_token, observed, plugin_id)
        return observed

    planned_records = {}

    async def evaluate(observed, extra=()):
        return await _evaluate_shared_dependencies_async(
            requirements_file,
            observed,
            plugin_id=plugin_id,
            usage_registry=usage_registry,
            admission_token=admission_token,
            extra_requirements=extra,
            installed_distributions=snapshot.distributions,
            planned_records=planned_records,
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
    for _attempt in range(2):
        async with _shared_observation(
            observation_roots,
            timeout=lock_timeout,
        ):
            snapshot = await audit()
            actual = await run_sync_io(
                _canonical_dependency_roots,
                snapshot.dependency_sites or (),
            )
            if not actual <= observation_roots:
                observation_roots |= actual
                continue
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
                    in {
                        str(canonical(path))
                        for path in snapshot.dependency_sites
                    }
                    and str(target)
                    in {str(canonical(path)) for path in snapshot.sites}
                )

            if os.environ.get(
                "QWENPAW_RUNTIME_PROVISIONER",
            ) == "local" or not (await run_sync_io(valid_target)):
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
                from .execution.errors import ProtocolValidationError

                code = getattr(
                    exc,
                    "reason_code",
                    "DEPENDENCY_PLAN_UNVERIFIED",
                )
                logger.info(
                    "Dependency preparation failed: plugin=%s "
                    "stage=wheel-validation code=%s exception=%s errno=%s",
                    ascii(str(plugin_id))[1:-1][:160],
                    ascii(str(code))[1:-1][:160],
                    type(exc).__name__,
                    exc.errno if isinstance(exc, OSError) else None,
                )
                raise SharedDependencyError(
                    GateDecision(
                        False,
                        False,
                        reason=(
                            str(exc)
                            if isinstance(exc, ProtocolValidationError)
                            else code
                        ),
                        reason_code=code,
                        require_restart=code == "DEPENDENCY_RESTART_REQUIRED",
                    ),
                ) from exc
            for name, row in proposed.distributions.items():
                if name not in snapshot.distributions:
                    origin = Path(row["metadata_path"])
                    record = (origin.relative_to(target) / "RECORD").as_posix()
                    planned_records[str(origin)] = files[record].decode(
                        "utf-8",
                    )
            added = tuple(
                f"{name}=={row['version']}"
                for name, row in proposed.distributions.items()
                if name not in snapshot.distributions
            )
            # No await separates the final usage check from submitting publication.
            decision = await evaluate(proposed, added)
            if not decision.already_satisfied:
                raise SharedDependencyError(decision)
            parsed_recovery = await run_sync_io(
                parse_requirements_file,
                requirements_file,
            )
            return await _publish_additions(
                audit,
                evaluate,
                target,
                files,
                recovery={
                    "plugin_id": plugin_id,
                    "python_executable": spec.python_executable,
                    "support_root": str(spec.support_root),
                    "sites": list(snapshot.sites),
                    "requirements": [
                        *(str(req) for req in parsed_recovery.requirements),
                        *added,
                    ],
                    "providers": {
                        name: proposed.distributions[name]["metadata_path"]
                        for name in proposed.distributions
                        if name not in snapshot.distributions
                    },
                    "interpreter": installer_identity
                    or {
                        "executable": snapshot.executable,
                        "prefix": snapshot.prefix,
                        "supported_tags": list(snapshot.supported_tags),
                    },
                },
            )

    raise _unverified("publication roots changed during inspection")


async def _publish_additions(audit, evaluate, target, files, *, recovery=None):
    """Keep exclusion through exact-byte publication and child verification."""
    import asyncio
    from .execution.dependencies import repair_marker
    from .dependency_maintenance import _admission_gate, file_lock
    from .install_lock import async_lock, observation_write
    from ..utils.io_utils import run_sync_io
    from .dependency_recovery import begin_additions, record_phase

    record = None

    def mark(message):
        repair_marker(target).write_text(message, encoding="utf-8")

    def publish():
        nonlocal record
        if recovery is not None:
            record = begin_additions(target, files, recovery)
        else:
            mark("Shared dependency publication requires verification.\n")
        _write_additions(target, files)
        if record is not None:
            record_phase(record, "published")

    def failed(phase, exc, message):
        if record is None:
            if recovery is None:
                mark(message)
        else:
            record_phase(record, phase, exc)
        logger.warning(
            "Dependency publication failed: plugin=%s stage=%s exception=%s",
            (recovery or {}).get("plugin_id", "unknown"),
            phase,
            type(exc).__name__,
            exc_info=(type(exc), exc, exc.__traceback__),
        )

    admission = await run_sync_io(_admission_gate, target)
    async with async_lock(file_lock(admission, timeout=5)):
        try:
            with observation_write():
                await run_sync_io(publish)
        except asyncio.CancelledError as exc:
            await run_sync_io(
                failed,
                "write_cancelled",
                exc,
                "Cancelled dependency publication requires repair.\n",
            )
            raise
        except Exception as exc:
            await run_sync_io(
                failed,
                "write_failed",
                exc,
                "Shared dependency publication requires verification.\n",
            )
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
            if record is None:
                await run_sync_io(lambda: repair_marker(target).unlink())
            from .dependency_maintenance import capability_context

            plan = record[1]["plan"] if record is not None else None
            token = capability_context.set(
                plan["id"] + ":" + plan["capability"]
                if plan
                else capability_context.get(),
            )
            try:
                snapshot = await audit()
                decision = await evaluate(snapshot)
                if not decision.already_satisfied:
                    raise SharedDependencyError(decision)
                if record is not None:
                    await run_sync_io(record_phase, record, "verified")
                    await run_sync_io(lambda: repair_marker(target).unlink())
            finally:
                capability_context.reset(token)
        except BaseException as exc:
            await run_sync_io(
                failed,
                "verification_failed",
                exc,
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
