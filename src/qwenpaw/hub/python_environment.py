# -*- coding: utf-8 -*-
"""Per-runtime Python environments sharing a read-only framework install."""

from __future__ import annotations

import json
import os
import shutil
import sys
import sysconfig
import venv
from pathlib import Path

from ..plugins.install_lock import plugin_install_lock
from .models import RuntimeRecord


def environment_root(record: RuntimeRecord) -> Path:
    """Persist Python inside the user's runtime working directory."""
    return record.working_dir / ".venv"


def python_executable(record: RuntimeRecord) -> Path:
    """Preserve the venv symlink instead of resolving to the base Python."""
    root = environment_root(record)
    return (
        root / "Scripts/python.exe"
        if os.name == "nt"
        else (root / "bin/python")
    )


def ensure_python_environment(record: RuntimeRecord) -> Path:
    """Create once; never execute an existing user environment in the Hub."""
    root = environment_root(record)
    marker = root / ".qwenpaw-base.json"
    fingerprint = {
        "executable": sys.executable,
        "prefix": sys.prefix,
        "version": sys.version,
        "framework": str(Path(__file__).resolve().parents[1]),
    }
    lock = root.parent / ".python.lock"
    with plugin_install_lock(lock) as acquired:
        if not acquired:
            raise RuntimeError("Cannot lock runtime Python environment")
        if root.exists():
            try:
                previous = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                previous = None
            if previous == fingerprint and python_executable(record).is_file():
                return python_executable(record)
            raise RuntimeError(
                f"Runtime Python environment is incomplete or its base "
                f"changed. Stop the runtime, remove {root}, then start it "
                f"to reinstall plugin dependencies.",
            )
        try:
            venv.EnvBuilder(
                system_site_packages=False,
                with_pip=True,
                symlinks=os.name != "nt",
            ).create(root)
            # Append read-only base packages without executing host .pth
            # files, which may expose unrelated editable project paths.
            site = (
                root / "Lib/site-packages"
                if os.name == "nt"
                else root / f"lib/python{sys.version_info.major}."
                f"{sys.version_info.minor}/site-packages"
            )
            paths = dict.fromkeys(
                [
                    sysconfig.get_path("purelib"),
                    sysconfig.get_path("platlib"),
                    str(Path(__file__).resolve().parents[2]),
                ],
            )
            mail_source = (
                Path(__file__).resolve().parents[3]
                / "packages/qwenpawmail-mcp/src"
            )
            if mail_source.is_dir():
                paths[str(mail_source)] = None
            (site / "qwenpaw-base.pth").write_text(
                "\n".join(paths) + "\n",
                encoding="utf-8",
            )
            marker.write_text(json.dumps(fingerprint), encoding="utf-8")
        except BaseException:
            shutil.rmtree(root)
            raise
    return python_executable(record)


def apply_python_environment(
    record: RuntimeRecord,
    environment: dict[str, str],
) -> None:
    """Make shell commands and Python child processes use the same venv."""
    inherited_path = next(
        (value for key, value in environment.items() if key.upper() == "PATH"),
        "",
    )
    for key in list(environment):
        if key.upper() in {
            "PATH",
            "PYTHONPATH",
            "PYTHONHOME",
            "CONDA_PREFIX",
            "CONDA_DEFAULT_ENV",
            "BASH_ENV",
            "ENV",
        }:
            environment.pop(key)
    environment[
        "PATH"
    ] = f"{python_executable(record).parent}{os.pathsep}{inherited_path}"
    environment["VIRTUAL_ENV"] = str(environment_root(record))
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PIP_USER"] = "0"
    environment["PIP_CONFIG_FILE"] = os.devnull
