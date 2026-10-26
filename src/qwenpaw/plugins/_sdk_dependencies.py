# -*- coding: utf-8 -*-
"""
SDK installs may add distributions, but never replace this process's code.
"""

import json
import re
import sys
import tempfile
from importlib.machinery import all_suffixes
from importlib.metadata import distributions
from pathlib import Path
from typing import Callable

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from .errors import SDKRestartRequiredError


def is_sdk_source(source: Path) -> bool:
    try:
        manifest = json.loads(
            (source / "plugin.json").read_text(encoding="utf-8"),
        )
    except (OSError, ValueError):
        return False
    return isinstance(manifest, dict) and manifest.get("sdk") is not None


def _public_module_loaded(package, files, loaded) -> bool:
    """A bundled copy imported under its public name is live host code."""
    root = Path(package.locate_file("")).resolve()
    paths = {Path(package.locate_file(path)).resolve() for path in files}
    for name, origin in loaded:
        if origin not in paths or not origin.is_relative_to(root):
            continue
        relative = origin.relative_to(root).as_posix()
        public = name.replace(".", "/")
        if any(
            relative in (public + suffix, public + "/__init__" + suffix)
            for suffix in all_suffixes()
        ):
            return True
    return False


def _installed_snapshot() -> dict[str, tuple[str, tuple[str, ...]]]:
    """Audit effective distributions, retaining their version and provenance.

    Some tools append bundled dependencies to sys.path. A later copy is only
    shadowed when another distribution's RECORD owns its metadata and it has
    not been imported under its public name. Ordinary duplicates stay audited.
    """
    snapshot = {}
    try:
        packages = [
            (package, package.files or ()) for package in distributions()
        ]
        bundled_metadata = {
            Path(package.locate_file(path)).resolve()
            for package, files in packages
            for path in files
            if len(path.parts) > 2
            and path.name == "METADATA"
            and path.parent.name.endswith(".dist-info")
        }
        loaded = None
        for package, files in packages:
            name = canonicalize_name(package.metadata["Name"], validate=True)
            version = str(Version(package.version))
            metadata = {
                Path(package.locate_file(path)).resolve()
                for path in files
                if len(path.parts) == 2
                and path.name == "METADATA"
                and path.parent.name.endswith(".dist-info")
            }
            source = str(Path(package.locate_file("")).resolve())
            source += ":" + (package.read_text("direct_url.json") or "")
            previous = snapshot.get(name)
            if previous and metadata & bundled_metadata:
                if loaded is None:
                    loaded = [
                        (name, Path(origin).resolve())
                        for name, module in tuple(sys.modules.items())
                        if (origin := getattr(module, "__file__", None))
                    ]
                if not _public_module_loaded(package, files, loaded):
                    continue
            if previous and previous[0] != version:
                raise ValueError(
                    f"Conflicting installed distributions for {name}: "
                    f"{previous[0]} at {previous[1]}; {version} at {source}",
                )
            sources = set(previous[1] if previous else ())
            sources.add(source)
            snapshot[name] = (version, tuple(sorted(sources)))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise SDKRestartRequiredError(
            "Cannot audit the installed dependency versions; restart with "
            "a repaired dependency environment before installing SDK plugins. "
            f"{exc}",
        ) from exc
    return snapshot


def _installed_versions() -> dict[str, str]:
    return {name: value[0] for name, value in _installed_snapshot().items()}


def loaded_sdk_conflicts(source: Path, missing: list[str]) -> list[str]:
    """Also protect not-yet-imported packages from concurrent first imports."""
    if not missing or not is_sdk_source(source):
        return []
    installed = _installed_versions()
    return [
        line
        for line in missing
        if canonicalize_name(Requirement(line).name) in installed
    ]


def _uv_additions(output: str) -> set[str]:
    """Read uv's dry-run plan, refusing unknown formats instead of guessing.

    Verified with uv 0.8.15: it prints ``Would install N packages``
    followed by `` + name==v``;
    removals use `` -``. The count and every operation must agree. This is not
    a resolver: any format/version change fails closed before a real install.
    """
    counts = re.findall(r"^Would install (\d+) packages?\s*$", output, re.M)
    rows = re.findall(r"^\s*([+~\-])\s+(.+)$", output, re.M)
    if (
        not counts
        and not rows
        and re.search(r"^Would make no changes\s*$", output, re.M)
    ):
        return set()
    if len(counts) != 1 or int(counts[0]) != len(rows):
        raise SDKRestartRequiredError(
            "Unrecognized uv dry-run dependency plan.",
        )
    names = set()
    for operation, declaration in rows:
        if operation != "+":
            raise SDKRestartRequiredError(
                "Dependency plan replaces installed code.",
            )
        # uv includes source provenance in parentheses, after name/version.
        match = re.fullmatch(
            r"([A-Za-z0-9_.-]+)==([^\s]+)(?: \(.+\))?",
            declaration,
        )
        if match is None:
            raise SDKRestartRequiredError(
                "Unrecognized uv dry-run package entry.",
            )
        names.add(canonicalize_name(match[1]))
    if len(names) != len(rows):
        raise SDKRestartRequiredError("Ambiguous uv dry-run dependency plan.")
    return names


def _pip_plan(report: Path) -> dict:
    try:
        plan = json.loads(report.read_text(encoding="utf-8"))
        if plan["version"] != "1" or not isinstance(plan["install"], list):
            raise ValueError("Unknown pip report format")
        for item in plan["install"]:
            canonicalize_name(item["metadata"]["name"], validate=True)
        return plan
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise SDKRestartRequiredError(
            "Unrecognized pip dependency plan.",
        ) from exc


def _target_requirements(
    plan: dict | None,
    installed: dict[str, str],
) -> list[str]:
    """Install only missing, hash-bound artifacts from a complete pip plan.

    pip --target ignores installed packages. Its constrained plan still proves
    compatibility with the frozen host, but copying those host dependencies
    would shadow live code. Skip them and install the remaining exact artifacts
    without resolving a second time.
    """
    if plan is None:
        raise SDKRestartRequiredError(
            "The desktop dependency runtime needs pip to verify artifacts. "
            "Repair the bundled Python runtime.",
        )
    requirements = []
    seen = set()
    try:
        for item in plan["install"]:
            name = canonicalize_name(item["metadata"]["name"], validate=True)
            version = str(Version(item["metadata"]["version"]))
            if name in seen:
                raise ValueError(f"Duplicate planned distribution: {name}")
            seen.add(name)
            if name in installed:
                if item.get("is_direct") or Version(
                    installed[name],
                ) != Version(version):
                    raise ValueError(f"Dependency plan replaces {name}")
                continue
            download = item["download_info"]
            digest = download["archive_info"]["hashes"]["sha256"]
            url = download["url"]
            if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                raise ValueError(f"Missing artifact hash for {name}")
            if not isinstance(url, str) or any(c in url for c in "\r\n"):
                raise ValueError(f"Invalid artifact URL for {name}")
            separator = "&" if "#" in url else "#"
            requirements.append(f"{name} @ {url}{separator}sha256={digest}")
    except (KeyError, TypeError, ValueError) as exc:
        raise SDKRestartRequiredError(
            f"Cannot safely install the desktop dependency plan: {exc}",
        ) from exc
    return requirements


def install_sdk_requirements(
    requirements: Path,
    plugin_id: str,
    *,
    python: str,
    target: str | None,
    run: Callable,
    find_uv: Callable,
    timeout: int = 300,
) -> None:
    """Resolve read-only, then install with the same installed-version pins."""
    snapshot = _installed_snapshot()
    installed = {name: value[0] for name, value in snapshot.items()}
    with tempfile.TemporaryDirectory(
        prefix="qwenpaw-sdk-dependencies-",
    ) as temp:
        constraints = Path(temp) / "constraints.txt"
        constraints.write_text(
            "".join(
                f"{name}=={version}\n"
                for name, version in sorted(installed.items())
            ),
            encoding="utf-8",
        )
        report = Path(temp) / "plan.json"
        command = [
            python,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
        ]
        suffix = (["--target", target] if target else []) + [
            "-r",
            str(requirements),
        ]
        pins = ["--constraint", str(constraints)]
        dry = ["--dry-run", "--report", str(report)]

        def execute(args):
            return run(args, timeout=timeout, plugin_id=plugin_id)

        result = execute(command + suffix + pins + dry)
        using_uv = False
        if result.returncode and "No module named pip" in (
            result.stdout + result.stderr
        ):
            uv = find_uv()
            if uv is None:
                raise RuntimeError(
                    "Neither pip nor uv is available to resolve SDK "
                    "dependencies.",
                )
            command = [uv, "pip", "install", "--python", python]
            dry = ["--dry-run"]
            using_uv = True
            result = execute(command + suffix + pins + dry)
        if result.returncode:
            # Distinguish a version-pin conflict from an unavailable package or
            # network/resolver failure. Neither command changes installed code.
            unconstrained = execute(command + suffix + dry)
            if unconstrained.returncode == 0:
                raise SDKRestartRequiredError(
                    "SDK dependencies require replacing installed "
                    "distributions; "
                    "restart with the requested dependency environment.",
                )
            raise RuntimeError(
                f"Dependency resolution failed for '{plugin_id}': "
                f"{result.stdout}{result.stderr}",
            )
        plan = None
        if using_uv:
            additions = _uv_additions(result.stdout + "\n" + result.stderr)
        else:
            plan = _pip_plan(report)
            additions = {
                canonicalize_name(item["metadata"]["name"])
                for item in plan["install"]
            }
        if target:
            selected = _target_requirements(plan, installed)
            additions -= installed.keys()
            selected_file = Path(temp) / "additions.txt"
            selected_file.write_text(
                "\n".join(selected) + "\n",
                encoding="utf-8",
            )
            suffix = [
                "--target",
                target,
                "--no-deps",
                "--require-hashes",
                "-r",
                str(selected_file),
            ]
        elif additions & installed.keys():
            raise SDKRestartRequiredError(
                "Dependency plan reinstalls existing distributions (including "
                "same-version source changes); restart to apply.",
            )
        if _installed_snapshot() != snapshot:
            raise SDKRestartRequiredError(
                "The installed environment changed during dependency "
                "resolution; "
                "retry in a stable process.",
            )
        if additions:
            result = execute(command + suffix + pins)
            if result.returncode:
                raise RuntimeError(
                    f"Dependency installation failed for '{plugin_id}': "
                    f"{result.stdout}{result.stderr}",
                )
