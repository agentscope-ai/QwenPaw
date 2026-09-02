# -*- coding: utf-8 -*-
"""Regression tests for desktop packaging workflows."""

from pathlib import Path
import tomllib

from packaging.specifiers import SpecifierSet
from packaging.version import Version
import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_fork_desktop_build_uses_supported_python() -> None:
    """Both platform builders must bootstrap a project-supported Python."""
    project = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"),
    )
    supported = SpecifierSet(project["project"]["requires-python"])
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/fork-verify-desktop.yml").read_text(
            encoding="utf-8",
        ),
    )

    for job_name in ("tauri-macos", "tauri-windows"):
        setup_python = next(
            step
            for step in workflow["jobs"][job_name]["steps"]
            if step.get("uses", "").startswith("actions/setup-python@")
        )
        version = Version(str(setup_python["with"]["python-version"]))
        assert version in supported, (
            f"{job_name} bootstraps unsupported Python {version}; "
            f"project requires {supported}"
        )
