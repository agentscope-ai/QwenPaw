# -*- coding: utf-8 -*-
"""Actual-child dependency evidence, without importing candidate SDKs."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from importlib import metadata
from importlib.machinery import EXTENSION_SUFFIXES
from importlib.util import source_from_cache
import inspect
import os
from pathlib import Path
import re
import sys
import sysconfig
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

from packaging.markers import default_environment
from packaging.tags import sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version

from .errors import ProtocolValidationError


def dependency_error(reason: str = "DEPENDENCY_METADATA_INVALID"):
    """Return a safe error without package code or environment secrets."""
    return ProtocolValidationError(reason, reason_code=reason)


def valid_metadata_headers(message, required, optional=()) -> bool:
    """Singleton metadata must never be interpreted by first-header wins."""
    return all(
        len(message.get_all(name, [])) == 1 for name in required
    ) and all(len(message.get_all(name, [])) <= 1 for name in optional)


def canonical_environment_path(target: str | Path) -> Path:
    """One identity for publication, admission, lock and repair paths."""
    from ..dependency_maintenance import canonical

    return canonical(target)


def repair_marker(site: str | Path) -> Path:
    """Persistent evidence that an interrupted shared write needs repair."""
    from ..dependency_maintenance import repair_marker as shared_marker

    return shared_marker(site)


@dataclass(frozen=True)
class DependencySnapshot:
    """Bounded target metadata; candidate roots never supply distributions."""

    executable: str
    prefix: str
    sites: tuple[str, ...]
    marker_environment: Mapping[str, str]
    supported_tags: tuple[str, ...]
    distributions: Mapping[str, Mapping[str, Any]]
    dependency_sites: tuple[str, ...] | None = None

    def to_mapping(self) -> dict[str, Any]:
        """Encode independent JSON data for the private transport."""
        value = {
            "executable": self.executable,
            "prefix": self.prefix,
            "sites": list(self.sites),
            "marker_environment": dict(self.marker_environment),
            "supported_tags": list(self.supported_tags),
            "distributions": {
                key: {
                    **row,
                    "requires_dist": list(row["requires_dist"]),
                    "top_level": list(row["top_level"]),
                    **(
                        {"loaded_modules": list(row["loaded_modules"])}
                        if "loaded_modules" in row
                        else {}
                    ),
                }
                for key, row in self.distributions.items()
            },
        }
        if self.dependency_sites is not None:
            value["dependency_sites"] = list(self.dependency_sites)
        return value

    @classmethod
    # Closed metadata validation intentionally checks every untrusted field.
    # pylint: disable=too-many-branches
    def from_mapping(cls, value: object) -> DependencySnapshot:
        """Validate evidence fields, origins and installed versions."""
        fields = {
            "executable",
            "prefix",
            "sites",
            "marker_environment",
            "supported_tags",
            "distributions",
        }
        if not isinstance(value, Mapping) or set(value) not in (
            fields,
            fields | {"dependency_sites"},
        ):
            raise dependency_error()
        data = dict(value)
        for key in ("executable", "prefix"):
            if (
                not isinstance(data[key], str)
                or not Path(data[key]).is_absolute()
            ):
                raise dependency_error()
        for key in ("sites", "supported_tags"):
            if not isinstance(data[key], list) or any(
                not isinstance(item, str) or not item for item in data[key]
            ):
                raise dependency_error()
        if any(not Path(site).is_absolute() for site in data["sites"]):
            raise dependency_error()
        package_sites = data.get("dependency_sites")
        if "dependency_sites" in data and (
            not isinstance(package_sites, list)
            or any(
                not isinstance(site, str)
                or not Path(site).is_absolute()
                or str(Path(site).resolve())
                not in {str(Path(root).resolve()) for root in data["sites"]}
                for site in package_sites
            )
        ):
            raise dependency_error()
        environment = data["marker_environment"]
        if (
            not isinstance(environment, Mapping)
            or set(environment) != set(default_environment())
            or any(not isinstance(item, str) for item in environment.values())
        ):
            raise dependency_error()
        distributions = data["distributions"]
        if (
            not isinstance(distributions, Mapping)
            or len(distributions) > 10000
        ):
            raise dependency_error()
        copied = {}
        for name, row in distributions.items():
            if (
                not isinstance(name, str)
                or canonicalize_name(name) != name
                or not isinstance(row, Mapping)
                or set(row)
                not in (
                    {"version", "metadata_path", "requires_dist", "top_level"},
                    {
                        "version",
                        "metadata_path",
                        "requires_dist",
                        "top_level",
                        "loaded_modules",
                    },
                )
            ):
                raise dependency_error()
            try:
                Version(row["version"])
                origin = Path(row["metadata_path"])
            except (TypeError, ValueError):
                raise dependency_error() from None
            if (
                not origin.is_absolute()
                or str(origin.parent) not in data["sites"]
            ):
                raise dependency_error()
            for key in (
                "requires_dist",
                "top_level",
                *(["loaded_modules"] if "loaded_modules" in row else []),
            ):
                if not isinstance(row[key], (list, tuple)) or any(
                    not isinstance(item, str) for item in row[key]
                ):
                    raise dependency_error()
            copied[name] = {
                **row,
                "requires_dist": tuple(row["requires_dist"]),
                "top_level": tuple(row["top_level"]),
                **(
                    {"loaded_modules": tuple(row["loaded_modules"])}
                    if "loaded_modules" in row
                    else {}
                ),
            }
        return cls(
            data["executable"],
            data["prefix"],
            tuple(data["sites"]),
            dict(environment),
            tuple(data["supported_tags"]),
            copied,
            tuple(package_sites) if package_sites is not None else None,
        )

    @property
    def versions(self) -> dict[str, str]:
        """Observed versions for the existing shared hello validators."""
        return {
            name: row["version"] for name, row in self.distributions.items()
        }


def _dependency_protection_roots(resolved=None):
    """Resolve common protection inputs once per synchronous classification."""
    if resolved is None:
        resolved = {}

    def canonical_roots(paths):
        for path in paths:
            if path and str(path) not in resolved:
                resolved[str(path)] = canonical_environment_path(path)
        return {str(resolved[str(path)]) for path in paths if path}

    package_roots = canonical_roots(
        (
            sysconfig.get_path("purelib"),
            sysconfig.get_path("platlib"),
        ),
    )
    standard = canonical_roots(
        (
            sysconfig.get_path("stdlib"),
            sysconfig.get_path("platstdlib"),
            sysconfig.get_config_var("DESTSHARED"),
        ),
    )
    source = Path(__file__).resolve()
    support = canonical_roots((source.parents[3], source.parent))
    return package_roots, standard, support - package_roots


def _protected_dependency_target(target, roots):
    package_roots, standard, support = roots

    def contains(root):
        parts = Path(root).parts
        return target.parts[: len(parts)] == parts

    return any(contains(root) for root in support) or (
        any(contains(root) for root in standard)
        and not any(contains(root) for root in package_roots)
    )


def protected_dependency_target(path):
    """Protect local stdlib/support while preserving actual package sites."""
    return _protected_dependency_target(
        canonical_environment_path(path),
        _dependency_protection_roots(),
    )


def dependency_sites(sites, *, explicit=(), distributions=()):
    """Classify roots without granting explicit paths protected writes."""
    del explicit, distributions
    roots = None
    resolved = {}
    classified = {}
    for path in dict.fromkeys(str(path) for path in sites if path):
        if Path(path).is_dir():
            if roots is None:
                roots = _dependency_protection_roots(resolved)
            if str(path) not in resolved:
                resolved[str(path)] = canonical_environment_path(path)
            target = resolved[str(path)]
            if not _protected_dependency_target(target, roots):
                classified[str(target)] = None
    return tuple(classified)


def _read_record(distribution, metadata_path, records):
    """Reuse raw RECORD evidence only within the caller's synchronous read."""
    if records is None or metadata_path is None:
        return distribution.read_text("RECORD")
    if metadata_path not in records:
        records[metadata_path] = distribution.read_text("RECORD")
    return records[metadata_path]


def _record_entries(distribution, *, metadata_path=None, record_reads=None):
    """Validate RECORD once without allocating a Path for each file."""
    key = ("entries", metadata_path)
    record = _read_record(distribution, metadata_path, record_reads)
    if record_reads is not None and metadata_path is not None:
        if key not in record_reads:
            record_reads[key] = _parse_record_entries(record)
        return record_reads[key]
    return _parse_record_entries(record)


def _parse_record_entries(record):
    if not record:
        return None
    entries = []
    try:
        for row in csv.reader(record.splitlines(), strict=True):
            if not 1 <= len(row) <= 3 or not row[0]:
                return None
            if len(row) == 3 and row[2] and int(row[2]) < 0:
                return None
            entries.append(row[0])
    except (ValueError, csv.Error):
        return None
    return tuple(entries)


def _record_names(entries, *, allow_external=False):
    """Index bounded relative RECORD names without resolving unrelated files."""
    if entries is None:
        return None
    names = set()
    for item in entries:
        parts = item.replace("\\", "/").split("/")
        if item.startswith(("/", "\\")) or ":" in item or ".." in parts:
            if not allow_external:
                return None
            continue
        names.add(os.path.normcase(os.path.normpath(item)))
    return names


def _provides_loaded_modules(
    row,
    modules,
    *,
    record_reads=None,
    record_names=None,
):
    """Use RECORD overlap even when optional top-level hints are absent."""
    modules = tuple(modules)
    if not modules:
        return False
    origin = row["metadata_path"]
    if record_names is None or origin not in record_names:
        entries = _record_entries(
            metadata.Distribution.at(origin),
            metadata_path=origin,
            record_reads=record_reads,
        )
        names = _record_names(entries, allow_external=True)
        if record_names is not None:
            record_names[origin] = names
    else:
        names = record_names[origin]
    if names is None:
        return True
    module_paths = {
        os.path.normcase(module.replace(".", "/")).replace("\\", "/")
        for module in modules
    }
    module_ancestors = {
        "/".join(parts[:index])
        for module in module_paths
        for parts in (module.split("/"),)
        for index in range(1, len(parts))
    }
    for item in names:
        parts = item.replace("\\", "/").split("/")
        direct = "/".join((*parts[:-1], parts[-1].split(".", 1)[0]))
        if direct in module_paths:
            return True
        if parts[-1].endswith((".py", ".pyc", *EXTENSION_SUFFIXES)) and (
            direct in module_ancestors
            or (
                parts[-1].split(".", 1)[0] == "__init__"
                and "/".join(parts[:-1]) in module_ancestors
            )
        ):
            # A regular ancestor package (or module) blocks namespace traversal.
            return True
        for index in range(1, len(parts)):
            if "/".join(parts[:index]) in module_paths:
                return True
    return False


def _owns_embedded_files(required, root, inventory):
    for item in required:
        relative = os.path.normcase(os.path.normpath(item.relative_to(root)))
        if relative in inventory:
            continue
        # Vendored RECORDs can retain build-machine caches omitted from the
        # enclosing wheel. Only an absent cache with jointly owned source is
        # dispensable; existing files and dangling symlinks remain evidence.
        if item.suffix != ".pyc":
            return False
        try:
            item.lstat()
        except FileNotFoundError:
            pass
        else:
            return False
        try:
            source = Path(source_from_cache(str(item)))
        except ValueError:
            return False
        if (
            source not in required
            or os.path.normcase(
                os.path.normpath(source.relative_to(root)),
            )
            not in inventory
        ):
            return False
    return True


def _installed_metadata(
    sites,
    *,
    embedded_sites=None,
    embedded_owners=None,
    record_reads=None,
    inventory=None,
):
    """Reuse unfiltered metadata only in a caller-owned observation."""
    key = ("metadata", tuple(str(site) for site in sites))
    if inventory is None or key not in inventory:
        embedded, owners = set(), {}
        result = _read_installed_metadata(
            sites,
            embedded_sites=embedded,
            embedded_owners=owners,
            record_reads=record_reads,
        )
        if inventory is not None:
            inventory[key] = (result, embedded, owners)
    else:
        result, embedded, owners = inventory[key]
    if embedded_sites is not None:
        embedded_sites.update(embedded)
    if embedded_owners is not None:
        embedded_owners.update(owners)
    rows, invalid, observed = result
    return (
        {name: dict(row) for name, row in rows.items()},
        dict(invalid),
        dict(observed),
    )


class _HeaderDistribution(metadata.PathDistribution):
    """Use the native metadata parser without its unused description body."""

    def read_text(self, filename):
        value = super().read_text(filename)
        if value and (
            boundary := re.search(r"\A(?:\r\n|\n|\r)|\n\r?\n|\r\r", value)
        ):
            # Keep the separator: empty headers with a body are still a
            # present METADATA file and must not fall through to PKG-INFO.
            return value[: boundary.end()]
        return value


def _read_installed_metadata(
    sites,
    *,
    embedded_sites=None,
    embedded_owners=None,
    record_reads=None,
):
    """Read metadata headers and invalid names without importing code."""
    # pylint: disable=protected-access
    from ..dependency_maintenance import authorized, check_admission

    for site in sites:
        check_admission(site)
    if any(
        repair_marker(site).exists() and not authorized(site) for site in sites
    ):
        raise dependency_error("DEPENDENCY_REPAIR_REQUIRED")
    rows, invalid, observed = {}, {}, {}
    candidates = {}
    unresolved_roots = set()
    canonical_sites = {str(canonical_environment_path(site)) for site in sites}
    # Resolve each metadata parent once per observation, never across installs.
    parents = {}
    for distribution in metadata.distributions(path=list(sites)):
        # importlib.metadata exposes the on-disk metadata origin here.
        origin = Path(
            distribution._path,
        ).resolve()
        parent = str(origin.parent)
        if parent not in parents:
            parents[parent] = str(canonical_environment_path(origin.parent))
        # Preserve the audited site's spelling in the serialized snapshot.
        origin = Path(parents[parent]) / origin.name
        installed_metadata = (
            _HeaderDistribution(distribution._path)
            if type(distribution) is metadata.PathDistribution
            else distribution
        ).metadata
        name = installed_metadata.get("Name")
        version = installed_metadata.get("Version")
        key = str(canonicalize_name(name or origin.name.split("-", 1)[0]))
        if not valid_metadata_headers(
            installed_metadata,
            ("Name", "Version"),
            ("Requires-Python",),
        ):
            unresolved_roots.add(origin.parent)
            for claimed in installed_metadata.get_all("Name", []) or (key,):
                invalid[
                    str(canonicalize_name(claimed))
                ] = "DEPENDENCY_METADATA_INVALID"
            continue
        try:
            if (
                not name
                or not version
                or parents[parent] not in canonical_sites
            ):
                raise ValueError("invalid metadata")
            Version(version)
        except ValueError:
            unresolved_roots.add(origin.parent)
            invalid[key] = "DEPENDENCY_METADATA_INVALID"
            continue
        if str(origin) in candidates:
            continue
        tops = set((distribution.read_text("top_level.txt") or "").split())
        if not tops:
            tops.add(key.replace("-", "_"))
        row = {
            "version": version,
            "metadata_path": str(origin),
            "requires_dist": tuple(
                installed_metadata.get_all("Requires-Dist", []),
            ),
            "top_level": tuple(sorted(tops)),
        }
        candidates[str(origin)] = (key, row, distribution)

    # A search root is not necessarily an independent installation. Retain
    # every candidate until explicit ancestor RECORD ownership is established.
    inventories = {}
    record_entries = {}

    def entries(origin, distribution):
        if origin not in record_entries:
            record_entries[origin] = _record_entries(
                distribution,
                metadata_path=origin,
                record_reads=record_reads,
            )
        return record_entries[origin]

    embedded = set()
    by_root = {}
    for origin, candidate in candidates.items():
        by_root.setdefault(Path(origin).parent, []).append((origin, candidate))
    ancestor_candidates = {
        root: [
            candidate
            for parent_root, group in by_root.items()
            if root != parent_root and root.is_relative_to(parent_root)
            for candidate in group
        ]
        for root in by_root
    }
    for origin, (key, _row, distribution) in candidates.items():
        path = Path(origin)
        ancestors = ancestor_candidates[path.parent]
        if not ancestors:
            continue
        owners = []
        possible = []
        for parent_origin, (_name, _row, parent) in ancestors:
            if parent_origin not in inventories:
                inventories[parent_origin] = _record_names(
                    entries(parent_origin, parent),
                    allow_external=True,
                )
            names = inventories[parent_origin]
            root = Path(parent_origin).parent
            marker = os.path.normcase(
                os.path.normpath(
                    str((path / "METADATA").relative_to(root)),
                ),
            )
            if names is not None and marker in names:
                possible.append((parent_origin, root, names))
        if possible:
            names = _record_names(entries(origin, distribution))
            required = (
                {
                    canonical_environment_path(path.parent / item)
                    for item in names
                }
                if names
                else set()
            )
            if path / "METADATA" in required and all(
                item.is_relative_to(path.parent) for item in required
            ):
                for parent_origin, root, inventory in possible:
                    if _owns_embedded_files(required, root, inventory):
                        owners.append(parent_origin)
        if len(owners) == 1:
            embedded.add(origin)
            if embedded_owners is not None:
                embedded_owners[origin] = owners[0]
        elif len(owners) > 1:
            invalid[key] = "DEPENDENCY_ENVIRONMENT_AMBIGUOUS"
    for origin, (key, row, distribution) in candidates.items():
        if origin in embedded:
            continue
        if key in rows:
            invalid[key] = "DEPENDENCY_ENVIRONMENT_AMBIGUOUS"
            continue
        rows[key] = row
        observed[key] = distribution
    if embedded_sites is not None:
        embedded_sites.update(
            str(root)
            for root, group in by_root.items()
            if root not in unresolved_roots
            and all(origin in embedded for origin, _candidate in group)
        )
    return rows, invalid, observed


def retains_installed_wheel_source(requirement, row, installed) -> bool:
    """Match a wheel reference to retained metadata without reading its URL."""
    if not requirement.url or installed is None or row != installed:
        return False
    try:
        url = urlsplit(requirement.url)
        if url.scheme not in {"file", "http", "https"}:
            return False
        name, version, _build, _tags = parse_wheel_filename(
            Path(unquote(url.path)).name,
        )
        return (
            str(name) == str(canonicalize_name(requirement.name))
            and Version(installed["version"]) == version
        )
    except (ValueError, TypeError, KeyError):
        return False


def _dependency_closure(requirements, rows, environment):
    """Traverse active metadata edges with their requested extras intact."""
    from packaging.requirements import Requirement

    pending = [(value, (), False) for value in requirements]
    visited = set()
    while pending:
        value, parent_extras, transitive = pending.pop()
        identity = (value, parent_extras, transitive)
        if identity in visited:
            continue
        visited.add(identity)
        requirement = Requirement(value)
        if requirement.marker and not any(
            requirement.marker.evaluate({**environment, "extra": extra})
            for extra in ("", *parent_extras)
        ):
            continue
        if requirement.extras and not transitive:
            raise dependency_error("DEPENDENCY_UNSATISFIED")
        name = str(canonicalize_name(requirement.name))
        row = rows.get(name)
        if requirement.url and (
            not transitive
            or not retains_installed_wheel_source(requirement, row, row)
        ):
            raise dependency_error("DEPENDENCY_UNSATISFIED")
        yield name, requirement
        if row is not None:
            extras = tuple(sorted(requirement.extras))
            pending.extend(
                (dependency, extras, True)
                for dependency in row["requires_dist"]
            )


def _inventory_sites(code_root, paths):
    """Resolve ordered search roots with this consumer's source exclusion."""
    root = Path(code_root).resolve()
    return tuple(
        dict.fromkeys(
            str(canonical_environment_path(path))
            for path in paths
            if path
            and Path(path).is_dir()
            and not Path(path).resolve().is_relative_to(root)
        ),
    )


# Inventory and relevant-closure rejection form one child-only audit.
# pylint: disable=too-many-branches,too-many-statements,protected-access
def observe_dependencies(
    packet: Mapping[str, Any],
    *,
    _embedded_owners=None,
    _record_reads=None,
    _inventory=None,
) -> DependencySnapshot:
    """Inspect this interpreter's paths before candidate imports execute."""
    if _record_reads is None and _inventory is not None:
        _record_reads = _inventory.setdefault("records", {})
    sites = _inventory_sites(packet["code_root"], packet["_audit_sites"])
    embedded_sites = set()
    rows, invalid, observed = _installed_metadata(
        sites,
        embedded_sites=embedded_sites,
        embedded_owners=_embedded_owners,
        record_reads=_record_reads,
        inventory=_inventory,
    )
    from .runtime import _requirements

    scanned = set()
    environment = default_environment()
    for name, _ in _dependency_closure(
        packet.get(
            "_requirements",
            _requirements(packet.get("requirements_path")),
        ),
        rows,
        environment,
    ):
        if name in invalid:
            raise dependency_error(invalid[name])
        if name in rows and name not in scanned:
            tops = set(rows[name]["top_level"])
            for path in observed[name].files or ():
                parts = str(path).replace("\\", "/").split("/")
                part = parts[0]
                # Scripts are not import providers; real package markers are.
                if (
                    len(parts) == 2
                    and part in {"bin", "Scripts"}
                    and not parts[1].casefold().startswith("__init__.")
                ):
                    continue
                if part not in {"", ".", ".."} and not part.endswith(
                    (".dist-info", ".egg-info"),
                ):
                    tops.add(part.split(".", 1)[0])
            rows[name]["top_level"] = tuple(sorted(tops))
            scanned.add(name)
    for name in invalid:
        rows.pop(name, None)
    return DependencySnapshot.from_mapping(
        {
            "executable": os.path.abspath(sys.executable),
            "prefix": sys.prefix,
            "sites": list(sites),
            "marker_environment": default_environment(),
            "supported_tags": [str(tag) for tag in sys_tags()],
            "distributions": rows,
            "dependency_sites": list(
                dependency_sites(
                    (site for site in sites if site not in embedded_sites),
                    explicit=packet.get("dependency_paths", ()),
                    distributions=rows.values(),
                ),
            ),
        },
    )


@dataclass(frozen=True)
class _ReadInventory:
    """Scoped metadata for a read decision, deliberately not audit evidence."""

    sites: tuple[str, ...]
    dependency_sites: tuple[str, ...]
    marker_environment: Mapping[str, str]
    distributions: Mapping[str, Mapping[str, Any]]
    invalid: Mapping[str, str]
    embedded_owners: Mapping[str, str]


def read_dependency_inventory(
    code_root,
    paths,
    requirements,
    *,
    inventory=None,
):
    """Check just the candidate closure and its actual imported providers."""
    root = Path(code_root).resolve()
    sites = _inventory_sites(root, paths)
    records = (
        inventory.setdefault("records", {}) if inventory is not None else {}
    )
    embedded = set()
    embedded_owners = {}
    rows, invalid, observed = _installed_metadata(
        sites,
        embedded_sites=embedded,
        embedded_owners=embedded_owners,
        record_reads=records,
        inventory=inventory,
    )
    environment = default_environment()
    relevant = set()
    for name, requirement in _dependency_closure(
        requirements,
        rows,
        environment,
    ):
        if name in invalid:
            raise dependency_error(invalid[name])
        row = rows.get(name)
        if row is None or not requirement.specifier.contains(
            Version(row["version"]),
            prereleases=True,
        ):
            raise ProtocolValidationError(
                requirement.name if requirement.url else str(requirement),
                reason_code="DEPENDENCY_UNSATISFIED",
            )
        relevant.add(name)
        # Derive import providers from the same installed RECORD as full audit.
        tops = set(row["top_level"])
        for item in observed[name].files or ():
            parts = str(item).replace("\\", "/").split("/")
            if (
                len(parts) == 2
                and parts[0] in {"bin", "Scripts"}
                and not parts[1].casefold().startswith("__init__.")
            ):
                continue
            if parts[0] not in {"", ".", ".."} and not parts[0].endswith(
                (".dist-info", ".egg-info"),
            ):
                tops.add(parts[0].split(".", 1)[0])
        row["top_level"] = tuple(sorted(tops))
    for name in invalid:
        rows.pop(name, None)
    view = _ReadInventory(
        sites,
        dependency_sites(site for site in sites if site not in embedded),
        environment,
        rows,
        invalid,
        embedded_owners,
    )
    check_import_origins(view, root, relevant)
    return view, relevant


def validate_driver(component: Any) -> None:
    """Check ordinary Driver calls without constructing or invoking it."""
    if not inspect.isclass(component):
        raise dependency_error("ENTRYPOINT_INVALID")
    try:
        inspect.signature(component).bind()
    except (TypeError, ValueError):
        raise dependency_error("ENTRYPOINT_INVALID") from None
    for name, arguments in (
        ("bind", (None, None)),
        ("start", (None, {})),
        ("stop", (None,)),
    ):
        method = getattr(component, name, None)
        if not callable(method):
            raise dependency_error("ENTRYPOINT_INVALID")
        try:
            inspect.signature(method).bind(*arguments)
        except (TypeError, ValueError):
            raise dependency_error("ENTRYPOINT_INVALID") from None
        if name in {"start", "stop"} and not inspect.iscoroutinefunction(
            method,
        ):
            raise dependency_error("ENTRYPOINT_INVALID")


def _owned_import_paths(row, tops):
    """Read RECORD ownership from an already selected metadata origin."""
    distribution = metadata.Distribution.at(row["metadata_path"])
    if distribution.version != row["version"]:
        raise dependency_error("DEPENDENCY_ORIGIN_INVALID")
    files = distribution.files
    root = Path(row["metadata_path"]).parent
    owned = set()
    provided = set(row["top_level"]).intersection(tops)
    for item in files or ():
        relative = Path(str(item))
        if relative.is_absolute() or ".." in relative.parts:
            continue
        top = relative.parts[0].split(".", 1)[0]
        if top in tops:
            provided.add(top)
            # Metadata root is canonical and RECORD is relative/traversal-free.
            # Index lexical ownership without stat/realpath for every installed
            # file; actual imported locations are resolved and fenced below.
            owned.add(root / relative)
    directories = {
        parent
        for path in owned
        for parent in path.parents
        if parent.is_relative_to(root)
    }
    return root, provided, owned, directories, files is not None


def check_import_origins(snapshot, code_root, relevant) -> None:
    """Fence imported SDK modules and namespace portions to metadata owners."""
    rows = [snapshot.distributions[name] for name in relevant]
    tops = {top for row in rows for top in row["top_level"]}
    modules = {
        name: module
        for name, module in tuple(sys.modules.items())
        if name.split(".", 1)[0] in tops and module is not None
    }
    resolved = {}
    for module in modules.values():
        locations = list(getattr(module, "__path__", ()))
        origin = getattr(module, "__file__", None)
        if origin:
            locations.append(origin)
        for location in locations:
            if location not in resolved:
                resolved[location] = Path(location).resolve()
            if resolved[location].is_relative_to(code_root):
                raise dependency_error("DEPENDENCY_ORIGIN_INVALID")
    # Restrict RECORD reads to observed providers for relevant namespaces.
    # Relevant transitive providers have their top-level names read at audit.
    providers = [
        row
        for row in snapshot.distributions.values()
        if set(row["top_level"]).intersection(tops)
    ]
    owners = [_owned_import_paths(row, tops) for row in providers]
    for name, module in modules.items():
        module_name = getattr(module, "__name__", name)
        # requests.packages aliases the actual urllib3 module objects. Resolve
        # such aliases only through an already imported, identical module.
        identity_name = (
            module_name if sys.modules.get(module_name) is module else name
        )
        top = identity_name.split(".", 1)[0]
        locations = list(getattr(module, "__path__", ()))
        origin = getattr(module, "__file__", None)
        if origin:
            locations.append(origin)
        for location in locations:
            path = resolved[location]
            directory = location in getattr(module, "__path__", ())
            accepted = False
            for root, provided, owned, directories, has_record in owners:
                if top not in provided or not path.is_relative_to(root):
                    continue
                if has_record:
                    accepted = path in (directories if directory else owned)
                else:
                    # Older distributions may omit RECORD; their selected site
                    # still fences plain modules and package search portions.
                    accepted = path == root / (
                        top + ".py"
                    ) or path.is_relative_to(root / top)
                if accepted:
                    break
            if not accepted:
                raise dependency_error("DEPENDENCY_ORIGIN_INVALID")


def require_dependencies(
    snapshot: DependencySnapshot,
    packet: Mapping[str, Any],
) -> set[str]:
    """Require the closure and return its canonical distribution names."""
    from .runtime import _requirements

    relevant = set()
    for name, requirement in _dependency_closure(
        packet.get(
            "_requirements",
            _requirements(packet.get("requirements_path")),
        ),
        snapshot.distributions,
        snapshot.marker_environment,
    ):
        row = snapshot.distributions.get(name)
        if row is None or not requirement.specifier.contains(
            Version(row["version"]),
            prereleases=True,
        ):
            raise dependency_error("DEPENDENCY_UNSATISFIED")
        relevant.add(name)
    return relevant
