# -*- coding: utf-8 -*-
"""Dependency gate: boot check-only and host-package blacklist."""

from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version
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
}


@dataclass
class GateDecision:
    """Result of evaluating a plugin's requirements.txt."""

    allow_install: bool
    already_satisfied: bool
    missing: list[str] = field(default_factory=list)
    host_conflicts: list[str] = field(default_factory=list)
    require_restart: bool = False
    reason: str = ""


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def parse_requirement_lines(requirements_file: Path) -> list[Requirement]:
    """Parse installable requirement lines, skipping comments and flags."""
    if not requirements_file.is_file():
        return []
    parsed: list[Requirement] = []
    for raw in requirements_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        try:
            parsed.append(Requirement(line))
        except Exception:  # noqa: BLE001
            continue
    return parsed


def _dist_key(req: Requirement) -> str:
    return req.name.lower().replace("_", "-")


def _import_name(req: Requirement) -> str:
    dist = _dist_key(req)
    return _IMPORT_NAME_OVERRIDES.get(dist, req.name.replace("-", "_"))


def is_requirement_satisfied(req: Requirement) -> bool:
    """Return True if *req* is already importable / in-spec."""
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
    top = import_name.split(".")[0]
    try:
        return importlib.util.find_spec(top) is not None
    except (ImportError, ValueError):
        return False


def hits_imported_host_package(req: Requirement) -> bool:
    """True when installing *req* would overwrite a host-owned package."""
    dist = _dist_key(req)
    if _is_frozen():
        return dist in HOST_PACKAGE_NAMES
    if dist in HOST_PACKAGE_NAMES:
        top = _import_name(req).split(".")[0]
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
        reqs = parse_requirement_lines(requirements_file)
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
