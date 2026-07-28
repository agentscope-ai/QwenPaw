# -*- coding: utf-8 -*-
"""Lightweight metadata inspection for shared ``pip --target`` sites."""

from __future__ import annotations

import contextlib
import csv
from dataclasses import dataclass
from email.parser import Parser
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Callable, Iterator, Literal
from uuid import uuid4

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


RequirementState = Literal[
    "satisfied",
    "missing",
    "version_mismatch",
    "runtime_conflict",
]

_VERIFY_RESULT_PREFIX = "QWENPAW_RUNTIME_VERIFY:"


class RuntimeLockUnavailable(RuntimeError):
    """Raised when a frozen Runtime write lock cannot be acquired."""


@dataclass(frozen=True)
class RuntimeDistribution:
    """One top-level distribution metadata entry in a target site."""

    canonical_name: str
    name: str
    version: str | None
    metadata_path: Path
    valid: bool
    requirements: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeSnapshot:
    """Top-level distribution metadata for one target site."""

    site_dir: Path
    distributions: dict[str, tuple[RuntimeDistribution, ...]]

    def entries(self, name: str) -> tuple[RuntimeDistribution, ...]:
        """Return metadata entries matching *name*."""
        return self.distributions.get(canonicalize_name(name), ())


def _metadata_file(path: Path) -> Path | None:
    if path.is_file() and path.name.endswith(".egg-info"):
        return path
    for name in ("METADATA", "PKG-INFO"):
        candidate = path / name
        if candidate.is_file():
            return candidate
    return None


def _inferred_name(path: Path) -> str | None:
    name = path.name
    for suffix in (".dist-info", ".egg-info"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    if "-" in name:
        name = name.rsplit("-", 1)[0]
    name = name.strip()
    return name or None


def _read_distribution(path: Path) -> RuntimeDistribution | None:
    inferred = _inferred_name(path)
    metadata_file = _metadata_file(path)
    name: str | None = None
    version: str | None = None
    requirements: tuple[str, ...] = ()
    if metadata_file is not None:
        try:
            metadata = Parser().parsestr(
                metadata_file.read_text(encoding="utf-8", errors="replace"),
            )
            name = metadata.get("Name")
            version = metadata.get("Version")
            requirements = tuple(metadata.get_all("Requires-Dist") or ())
        except OSError:
            pass
    resolved_name = (name or inferred or "").strip()
    if not resolved_name:
        return None
    resolved_version = version.strip() if version else None
    valid_version = False
    if resolved_version is not None:
        try:
            Version(resolved_version)
            valid_version = True
        except InvalidVersion:
            pass
    return RuntimeDistribution(
        canonical_name=canonicalize_name(resolved_name),
        name=resolved_name,
        version=resolved_version,
        metadata_path=path,
        valid=bool(name and resolved_version and valid_version),
        requirements=requirements,
    )


def build_runtime_snapshot(site_dir: Path) -> RuntimeSnapshot:
    """Inspect top-level distribution metadata without reading source trees."""
    site_dir = Path(site_dir)
    site_root = site_dir.resolve()
    grouped: dict[str, list[RuntimeDistribution]] = {}
    if site_dir.is_dir():
        for path in site_dir.iterdir():
            if not (
                path.name.endswith(".dist-info")
                or path.name.endswith(".egg-info")
            ):
                continue
            resolved = path.resolve()
            if resolved != site_root and site_root not in resolved.parents:
                continue
            distribution = _read_distribution(path)
            if distribution is None:
                continue
            grouped.setdefault(distribution.canonical_name, []).append(
                distribution,
            )
    return RuntimeSnapshot(
        site_dir=site_dir,
        distributions={
            name: tuple(
                sorted(items, key=lambda item: item.metadata_path.name),
            )
            for name, items in grouped.items()
        },
    )


def runtime_requirement_state(
    requirement: Requirement,
    snapshot: RuntimeSnapshot,
    *,
    fallback: Callable[[Requirement], bool] | None = None,
) -> RequirementState:
    """Resolve one requirement against a target Runtime and fallback env."""
    entries = snapshot.entries(requirement.name)
    if entries:
        if len(entries) != 1 or not entries[0].valid:
            return "runtime_conflict"
        version = entries[0].version
        try:
            parsed_version = Version(version or "")
        except InvalidVersion:
            return "runtime_conflict"
        if requirement.specifier and not requirement.specifier.contains(
            parsed_version,
        ):
            return "version_mismatch"
        return "satisfied"
    if fallback is not None and fallback(requirement):
        return "satisfied"
    return "missing"


@contextlib.contextmanager
def runtime_write_lock(
    site_dir: Path,
    *,
    timeout: float = 300.0,
    cancel_checker: Callable[[], bool] | None = None,
) -> Iterator[None]:
    """Hold the exclusive write lock for one frozen Runtime bucket."""
    from .plugins.install_lock import plugin_install_lock

    lock_path = Path(site_dir).parent / "runtime.lock"
    with plugin_install_lock(
        lock_path,
        timeout=timeout,
        cancel_checker=cancel_checker,
    ) as acquired:
        if not acquired:
            if cancel_checker is not None and cancel_checker():
                raise RuntimeLockUnavailable(
                    "Runtime installation was cancelled",
                )
            raise RuntimeLockUnavailable(
                "Timed out waiting for Runtime write lock",
            )
        yield


def _safe_relative_path(root: Path, value: str) -> Path:
    root = root.resolve()
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise RuntimeError(f"Runtime RECORD path escapes root: {value}")
    resolved = (root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise RuntimeError(f"Runtime RECORD path escapes root: {value}")
    return candidate


def _record_paths(
    distribution: RuntimeDistribution,
    site_dir: Path,
) -> set[Path] | None:
    metadata_path = distribution.metadata_path
    if not metadata_path.is_dir():
        return None
    record = metadata_path / "RECORD"
    if not record.is_file():
        return None
    paths: set[Path] = set()
    try:
        with record.open(newline="", encoding="utf-8") as handle:
            for row in csv.reader(handle):
                if not row:
                    continue
                relative = _safe_relative_path(site_dir, row[0])
                paths.add(relative)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise RuntimeError(
            f"Could not read RECORD for {distribution.name}",
        ) from exc
    return paths


def _relative_files(root: Path) -> set[Path]:
    if not root.is_dir():
        return set()
    result: set[Path] = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        _safe_relative_path(root, str(relative))
        result.add(relative)
    return result


def _same_file(left: Path, right: Path) -> bool:
    try:
        return (
            left.is_file()
            and right.is_file()
            and left.read_bytes() == right.read_bytes()
        )
    except OSError:
        return False


def _metadata_paths(
    distribution: RuntimeDistribution,
    site_dir: Path,
) -> set[Path]:
    metadata_path = distribution.metadata_path
    if metadata_path.is_file():
        return {metadata_path.relative_to(site_dir)}
    paths: set[Path] = set()
    for path in metadata_path.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(site_dir)
        _safe_relative_path(site_dir, str(relative))
        paths.add(relative)
    return paths


def _prune_empty_parents(site_dir: Path, paths: set[Path]) -> None:
    directories = {
        parent
        for relative in paths
        for parent in (site_dir / relative).parents
        if parent != site_dir and site_dir in parent.parents
    }
    for directory in sorted(
        directories,
        key=lambda value: len(value.parts),
        reverse=True,
    ):
        with contextlib.suppress(OSError):
            directory.rmdir()


class RuntimeTransaction:
    """Replace only distributions produced in one staging directory."""

    def __init__(self, site_dir: Path):
        self.site_dir = Path(site_dir)
        self.bucket_dir = self.site_dir.parent
        self.transaction_dir = self.bucket_dir / ".transactions" / uuid4().hex
        self.staging_dir = self.transaction_dir / "staging"
        self.backup_dir = self.transaction_dir / "backup"
        self.manifest_path = self.transaction_dir / "manifest.json"
        self._manifest: dict[str, object] = {}

    def create(self) -> Path:
        """Create a clean staging directory and return its path."""
        self.staging_dir.mkdir(parents=True, exist_ok=False)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        return self.staging_dir

    def reset_staging(self) -> Path:
        """Remove partial installer output and recreate staging."""
        shutil.rmtree(self.staging_dir, ignore_errors=True)
        self.staging_dir.mkdir(parents=True)
        return self.staging_dir

    def _write_manifest(self, state: str) -> None:
        self._manifest["state"] = state
        temporary = self.manifest_path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(self._manifest, indent=2, sort_keys=True))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.manifest_path)

    @staticmethod
    def _staged_versions(snapshot: RuntimeSnapshot) -> dict[str, str | None]:
        if not snapshot.distributions:
            raise RuntimeError("Staging did not contain distribution metadata")
        versions: dict[str, str | None] = {}
        for name, entries in snapshot.distributions.items():
            if len(entries) != 1 or not entries[0].valid:
                raise RuntimeError(
                    f"Staging contains invalid metadata for {name}",
                )
            versions[name] = entries[0].version
        return versions

    @staticmethod
    def _validate_constraints(
        staged_versions: dict[str, str | None],
        constraints: list[str],
    ) -> None:
        for raw in constraints:
            try:
                requirement = Requirement(raw)
            except InvalidRequirement:
                continue
            if (
                requirement.marker is not None
                and not requirement.marker.evaluate()
            ):
                continue
            version = staged_versions.get(canonicalize_name(requirement.name))
            if version is None or not requirement.specifier:
                continue
            if not requirement.specifier.contains(version):
                raise RuntimeError(
                    f"Runtime dependency conflict: {raw} does not allow "
                    f"{version}",
                )

    def _installed_ownership(
        self,
        replacement_names: set[str],
        current: RuntimeSnapshot,
    ) -> tuple[dict[Path, set[str]], set[Path]]:
        ownership: dict[Path, set[str]] = {}
        candidate_old_paths: set[Path] = set()
        for name, entries in current.distributions.items():
            for distribution in entries:
                record_paths = _record_paths(distribution, self.site_dir)
                paths = record_paths or set()
                if name in replacement_names:
                    paths.update(
                        _metadata_paths(distribution, self.site_dir),
                    )
                elif record_paths is None:
                    continue
                for path in paths:
                    ownership.setdefault(path, set()).add(name)
                    if name in replacement_names:
                        candidate_old_paths.add(path)
        return ownership, candidate_old_paths

    def _validate_staged_paths(
        self,
        staged_paths: set[Path],
        old_paths: set[Path],
        ownership: dict[Path, set[str]],
        replacement_names: set[str],
    ) -> None:
        for relative in staged_paths:
            _safe_relative_path(self.site_dir, str(relative))
            target = self.site_dir / relative
            staged = self.staging_dir / relative
            owners = ownership.get(relative, set()) - replacement_names
            if owners and target.exists() and not _same_file(target, staged):
                owner_list = ", ".join(sorted(owners))
                raise RuntimeError(
                    f"Runtime file conflict for {relative} "
                    f"(owned by {owner_list})",
                )
            if (
                target.exists()
                and not owners
                and relative not in old_paths
                and not _same_file(target, staged)
            ):
                raise RuntimeError(
                    f"Runtime unmanaged file conflict: {relative}",
                )

    def _prepare(
        self,
        constraints: list[str],
    ) -> tuple[set[str], set[Path], set[Path]]:
        staged = build_runtime_snapshot(self.staging_dir)
        staged_versions = self._staged_versions(staged)
        replacement_names = set(staged_versions)
        current = build_runtime_snapshot(self.site_dir)
        installed_constraints = [
            raw
            for name, entries in current.distributions.items()
            if name not in replacement_names
            for distribution in entries
            for raw in distribution.requirements
        ]
        self._validate_constraints(
            staged_versions,
            [*constraints, *installed_constraints],
        )
        ownership, candidate_old_paths = self._installed_ownership(
            replacement_names,
            current,
        )
        old_paths = {
            path
            for path in candidate_old_paths
            if ownership.get(path, set()) <= replacement_names
        }
        staged_paths = _relative_files(self.staging_dir)
        self._validate_staged_paths(
            staged_paths,
            old_paths,
            ownership,
            replacement_names,
        )
        new_paths = staged_paths | old_paths
        backup_paths = {
            path for path in new_paths if (self.site_dir / path).exists()
        }
        return replacement_names, backup_paths, staged_paths

    def commit(
        self,
        verify: Callable[[], None] | None = None,
        *,
        constraints: list[str] | None = None,
    ) -> None:
        """Commit staged distributions and roll back if verification fails."""
        replacement_names, backup_paths, staged_paths = self._prepare(
            constraints or [],
        )
        self._manifest = {
            "site_dir": str(self.site_dir),
            "replacement_names": sorted(replacement_names),
            "backup_paths": sorted(str(path) for path in backup_paths),
            "staged_paths": sorted(str(path) for path in staged_paths),
        }
        self._write_manifest("prepared")
        try:
            self._backup(backup_paths)
        except Exception:
            self.cleanup()
            raise
        try:
            self._write_manifest("committing")
            self._remove_old_files(backup_paths - staged_paths)
            self._copy_staging(staged_paths)
            if verify is not None:
                verify()
        except Exception:
            self.rollback()
            raise
        self._write_manifest("committed")
        self.cleanup()

    def _backup(self, paths: set[Path]) -> None:
        for relative in paths:
            source = self.site_dir / relative
            if not source.exists():
                continue
            destination = self.backup_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    def _remove_old_files(self, paths: set[Path]) -> None:
        for relative in paths:
            path = self.site_dir / relative
            if path.is_file() or path.is_symlink():
                path.unlink()
        _prune_empty_parents(self.site_dir, paths)

    def _copy_staging(self, paths: set[Path]) -> None:
        for relative in paths:
            source = self.staging_dir / relative
            destination = self.site_dir / relative
            if destination.exists() and _same_file(source, destination):
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    def rollback(self) -> None:
        """Restore the pre-transaction files when commit fails."""
        backup_paths = {
            _safe_relative_path(self.site_dir, str(value))
            for value in self._manifest.get("backup_paths", [])
        }
        staged_paths = {
            _safe_relative_path(self.site_dir, str(value))
            for value in self._manifest.get("staged_paths", [])
        }
        missing_backups = [
            relative
            for relative in backup_paths
            if not (self.backup_dir / relative).is_file()
        ]
        if missing_backups:
            missing = ", ".join(str(path) for path in missing_backups)
            raise RuntimeError(f"Runtime backup is incomplete: {missing}")
        for relative in sorted(backup_paths, key=str):
            source = self.backup_dir / relative
            destination = self.site_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(
                f".{destination.name}.{self.transaction_dir.name}.restore",
            )
            try:
                temporary.unlink(missing_ok=True)
                shutil.copy2(source, temporary)
                with temporary.open("rb") as handle:
                    os.fsync(handle.fileno())
                os.replace(temporary, destination)
            except Exception:
                with contextlib.suppress(OSError):
                    temporary.unlink()
                raise
        new_paths = staged_paths - backup_paths
        for relative in new_paths:
            path = self.site_dir / relative
            if path.is_file() or path.is_symlink():
                path.unlink()
        _prune_empty_parents(self.site_dir, new_paths)
        self.cleanup()

    def cleanup(self) -> None:
        """Remove temporary transaction data."""
        shutil.rmtree(self.transaction_dir, ignore_errors=True)

    def restore(self, manifest: dict[str, object]) -> None:
        """Restore one persisted committing transaction."""
        self._manifest = manifest
        self.rollback()


def recover_runtime_transactions(site_dir: Path) -> None:
    """Recover or remove unfinished transactions for one Runtime site."""
    transactions = Path(site_dir).parent / ".transactions"
    if not transactions.is_dir():
        return
    for transaction_dir in transactions.iterdir():
        manifest_path = transaction_dir / "manifest.json"
        if not manifest_path.is_file():
            shutil.rmtree(transaction_dir, ignore_errors=True)
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            state = manifest.get("state")
            if state == "committed":
                shutil.rmtree(transaction_dir, ignore_errors=True)
                continue
            if state != "committing":
                shutil.rmtree(transaction_dir, ignore_errors=True)
                continue
            transaction = RuntimeTransaction(Path(site_dir))
            transaction.transaction_dir = transaction_dir
            transaction.staging_dir = transaction_dir / "staging"
            transaction.backup_dir = transaction_dir / "backup"
            transaction.manifest_path = manifest_path
            transaction.restore(manifest)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Could not recover Runtime transaction: {transaction_dir}",
            ) from exc


def recover_runtime_if_needed(
    site_dir: Path,
    *,
    timeout: float = 0.0,
) -> None:
    """Recover pending transactions unless an installer owns the Runtime."""
    transactions = Path(site_dir).parent / ".transactions"
    if not transactions.is_dir() or not any(transactions.iterdir()):
        return
    try:
        with runtime_write_lock(site_dir, timeout=timeout):
            recover_runtime_transactions(site_dir)
    except RuntimeLockUnavailable:
        return


def runtime_pythonpath(site_dir: Path, environment: dict[str, str]) -> None:
    """Prepend one target Runtime to a child Python environment."""
    value = str(site_dir)
    current = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        f"{value}{os.pathsep}{current}" if current else value
    )


def verify_runtime_requirements(
    python: str,
    site_dir: Path,
    requirements: list[str],
    import_names: dict[str, str],
    *,
    timeout: int = 60,
) -> None:
    """Verify versions and direct imports in a clean Python process."""
    normalized_import_names = {
        canonicalize_name(name): value for name, value in import_names.items()
    }
    applicable: list[Requirement] = []
    checks: list[dict[str, str | None]] = []
    for raw in requirements:
        try:
            requirement = Requirement(raw)
        except InvalidRequirement as exc:
            raise RuntimeError(f"Invalid Runtime requirement: {raw}") from exc
        if (
            requirement.marker is not None
            and not requirement.marker.evaluate()
        ):
            continue
        key = canonicalize_name(requirement.name)
        applicable.append(requirement)
        checks.append(
            {
                "key": key,
                "name": requirement.name,
                "import_name": normalized_import_names.get(key),
            },
        )
    payload = json.dumps(
        {
            "site_dir": str(site_dir),
            "checks": checks,
        },
    )
    script = """
import importlib
import importlib.metadata
import json
import re
import sys

payload = json.loads(sys.stdin.read())
site_dir = payload["site_dir"]
sys.path.insert(0, site_dir)

def canonicalize_name(value):
    return re.sub(r"[-_.]+", "-", value).lower()

versions = {}
for distribution in importlib.metadata.distributions(path=[site_dir]):
    name = distribution.metadata.get("Name")
    if name:
        versions.setdefault(canonicalize_name(name), []).append(
            distribution.version,
        )
results = {}
for check in payload["checks"]:
    key = check["key"]
    values = versions.get(key, [])
    if not values:
        try:
            values = [importlib.metadata.version(check["name"])]
        except importlib.metadata.PackageNotFoundError:
            values = []
    import_name = check.get("import_name")
    imported = False
    if import_name:
        importlib.import_module(import_name)
        imported = True
    results[key] = {"versions": values, "imported": imported}
print("QWENPAW_RUNTIME_VERIFY:" + json.dumps(results, sort_keys=True))
"""
    result = subprocess.run(
        [python, "-c", script],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env={
            **os.environ,
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        },
    )
    if result.returncode != 0:
        output = "\n".join(
            value for value in (result.stdout, result.stderr) if value
        )
        raise RuntimeError((output or "Runtime verification failed")[-4000:])
    result_line = next(
        (
            line[len(_VERIFY_RESULT_PREFIX) :]
            for line in reversed((result.stdout or "").splitlines())
            if line.startswith(_VERIFY_RESULT_PREFIX)
        ),
        None,
    )
    if result_line is None:
        raise RuntimeError("Runtime verification did not return metadata")
    try:
        verified = json.loads(result_line)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Runtime verification returned invalid data",
        ) from exc
    for requirement in applicable:
        key = canonicalize_name(requirement.name)
        entry = verified.get(key, {})
        values = entry.get("versions", [])
        if not values:
            if entry.get("imported"):
                continue
            raise RuntimeError(
                f"Missing Runtime metadata for {requirement.name}",
            )
        if len(values) != 1:
            raise RuntimeError(
                f"Invalid Runtime metadata for {requirement.name}",
            )
        try:
            installed = Version(values[0])
        except (InvalidVersion, TypeError) as exc:
            raise RuntimeError(
                f"Invalid Runtime version for {requirement.name}",
            ) from exc
        if requirement.specifier and not requirement.specifier.contains(
            installed,
        ):
            raise RuntimeError(
                f"Invalid Runtime version for {requirement.name}",
            )
