# -*- coding: utf-8 -*-
"""Dependency gate: boot check-only and host-package blacklist."""

from __future__ import annotations

import importlib.util
import json
import logging
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
        line = raw.strip()
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
