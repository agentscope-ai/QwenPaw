# -*- coding: utf-8 -*-
"""Dependency state helpers for desktop plugins.

The regular Desktop runtime installs plugin requirements into its packaged
Python environment.  Tauri/PyInstaller cannot safely do that at startup, so it
uses this module to keep per-plugin dependency targets in the user data dir.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Callable, Optional

TAURI_BACKEND_ENV = "QWENPAW_TAURI_BACKEND"
RUNTIME_PYTHON_ENV = "QWENPAW_RUNTIME_PYTHON"
RUNTIME_UV_ENV = "QWENPAW_RUNTIME_UV"

INSTALL_MANIFEST = "install.json"
SITE_PACKAGES_DIR = "site-packages"


@dataclass(frozen=True)
class DependencyInstaller:
    """Resolved command prefix for installing plugin requirements."""

    kind: str
    command_prefix: list[str]
    python: Optional[str] = None

    def build_install_command(
        self,
        requirements_file: Path,
        target_site: Path,
    ) -> list[str]:
        if self.kind == "uv":
            if not self.python:
                raise RuntimeError("uv installer requires a Python path")
            return [
                *self.command_prefix,
                "install",
                "--python",
                self.python,
                "--only-binary=:all:",
                "--target",
                str(target_site),
                "-r",
                str(requirements_file),
            ]
        return [
            *self.command_prefix,
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--only-binary=:all:",
            "--target",
            str(target_site),
            "-r",
            str(requirements_file),
        ]


@dataclass(frozen=True)
class PluginDependencyState:
    """Current dependency readiness for one plugin under this runtime."""

    plugin_id: str
    has_requirements: bool
    status: str
    runtime_id: str
    requirements_hash: Optional[str] = None
    deps_dir: Optional[Path] = None
    site_packages: Optional[Path] = None
    install_json: Optional[Path] = None
    repairable: bool = False
    reason: Optional[str] = None
    message: Optional[str] = None

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def api_fields(self, *, loaded: bool) -> dict:
        load_status = "loaded" if loaded else self.status
        if not self.has_requirements and not loaded:
            load_status = "unloaded"
        return {
            "load_status": load_status,
            "repairable": self.repairable,
            "repair_reason": self.reason,
            "runtime_id": self.runtime_id,
            "requirements_hash": self.requirements_hash,
        }


def is_tauri_backend() -> bool:
    return os.environ.get(TAURI_BACKEND_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def current_runtime_id() -> str:
    implementation = sys.implementation.name.lower()
    if implementation == "cpython":
        abi = f"cp{sys.version_info.major}{sys.version_info.minor}"
    else:
        abi = f"{implementation}{sys.version_info.major}{sys.version_info.minor}"

    if sys.platform == "darwin":
        os_name = "macos"
    elif sys.platform.startswith("win"):
        os_name = "windows"
    elif sys.platform.startswith("linux"):
        os_name = "linux"
    else:
        os_name = sys.platform.replace(" ", "_").lower()

    machine = platform.machine().lower() or "unknown"
    machine = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "aarch64": "arm64",
    }.get(machine, machine)
    return f"{abi}-{os_name}-{machine}"


def plugin_deps_root() -> Path:
    from ..constant import WORKING_DIR

    return WORKING_DIR / "plugin-deps"


def has_requirement_entries(requirements_file: Path) -> bool:
    if not requirements_file.exists():
        return False
    for line in requirements_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return True
    return False


def requirements_hash(requirements_file: Path) -> str:
    digest = hashlib.sha256()
    with open(requirements_file, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dependency_paths(
    plugin_id: str,
    runtime_id: str,
    req_hash: str,
) -> tuple[Path, Path, Path]:
    root = plugin_deps_root().resolve()
    deps_dir = (root / plugin_id / runtime_id / req_hash).resolve()
    if not deps_dir.is_relative_to(root):
        raise ValueError(
            f"Plugin id '{plugin_id}' resolves outside dependency store",
        )
    site_packages = deps_dir / SITE_PACKAGES_DIR
    install_json = deps_dir / INSTALL_MANIFEST
    return deps_dir, site_packages, install_json


def dependency_state(source_path: Path, plugin_id: str) -> PluginDependencyState:
    runtime_id = current_runtime_id()
    requirements_file = source_path / "requirements.txt"
    if not has_requirement_entries(requirements_file):
        return PluginDependencyState(
            plugin_id=plugin_id,
            has_requirements=False,
            status="ready",
            runtime_id=runtime_id,
            repairable=False,
        )

    req_hash = requirements_hash(requirements_file)
    deps_dir, site_packages, install_json = dependency_paths(
        plugin_id,
        runtime_id,
        req_hash,
    )
    installer = find_dependency_installer()
    base = {
        "plugin_id": plugin_id,
        "has_requirements": True,
        "runtime_id": runtime_id,
        "requirements_hash": req_hash,
        "deps_dir": deps_dir,
        "site_packages": site_packages,
        "install_json": install_json,
        "repairable": installer is not None,
    }

    if not install_json.exists():
        return PluginDependencyState(
            **base,
            status="needs_repair",
            reason="dependencies_not_prepared_for_current_desktop",
        )

    try:
        data = json.loads(install_json.read_text(encoding="utf-8"))
    except Exception:
        return PluginDependencyState(
            **base,
            status="needs_repair",
            reason="invalid_dependency_state",
        )

    expected = {
        "plugin_id": plugin_id,
        "runtime_id": runtime_id,
        "requirements_hash": req_hash,
        "status": "installed",
    }
    for key, value in expected.items():
        if data.get(key) != value:
            return PluginDependencyState(
                **base,
                status="needs_repair",
                reason=f"{key}_mismatch",
            )

    if not site_packages.is_dir():
        return PluginDependencyState(
            **base,
            status="needs_repair",
            reason="dependency_path_missing",
        )

    return PluginDependencyState(**base, status="ready")


def activate_dependency_path(state: PluginDependencyState) -> None:
    if not state.site_packages or not state.site_packages.is_dir():
        return
    site_path = str(state.site_packages)
    if site_path in sys.path:
        os.environ[dependency_env_key(state.plugin_id)] = site_path
        return
    sys.path.insert(0, site_path)
    os.environ[dependency_env_key(state.plugin_id)] = site_path


def dependency_env_key(plugin_id: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", plugin_id).strip("_").upper()
    return f"QWENPAW_PLUGIN_DEPS_{normalized or 'DEFAULT'}"


def install_dependencies(
    source_path: Path,
    plugin_id: str,
    run_subprocess: Callable[..., subprocess.CompletedProcess],
    timeout: int = 300,
) -> PluginDependencyState:
    requirements_file = source_path / "requirements.txt"
    if not has_requirement_entries(requirements_file):
        return dependency_state(source_path, plugin_id)

    installer = find_dependency_installer()
    if installer is None:
        raise RuntimeError(
            "Plugin dependency repair is unavailable because no plugin "
            "Python runtime or package manager was found. Bundle "
            "python-runtime with Tauri Desktop or set QWENPAW_RUNTIME_PYTHON "
            "and QWENPAW_RUNTIME_UV.",
        )

    runtime_id = current_runtime_id()
    req_hash = requirements_hash(requirements_file)
    deps_dir, site_packages, install_json = dependency_paths(
        plugin_id,
        runtime_id,
        req_hash,
    )
    parent = deps_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = parent / f".tmp-{req_hash[:12]}-{uuid.uuid4().hex}"
    tmp_site = tmp_dir / SITE_PACKAGES_DIR
    tmp_site.mkdir(parents=True, exist_ok=True)

    try:
        command = installer.build_install_command(requirements_file, tmp_site)
        result = run_subprocess(
            command,
            timeout=timeout,
            plugin_id=plugin_id,
        )
        if result.returncode != 0:
            output = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                "Plugin dependency repair failed"
                + (f": {output}" if output else ""),
            )

        manifest = {
            "plugin_id": plugin_id,
            "status": "installed",
            "runtime_id": runtime_id,
            "requirements_hash": req_hash,
            "installer": installer.kind,
            "deps_path": str(site_packages),
        }
        (tmp_dir / INSTALL_MANIFEST).write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        if deps_dir.exists():
            shutil.rmtree(deps_dir)
        shutil.move(str(tmp_dir), str(deps_dir))
    finally:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

    state = dependency_state(source_path, plugin_id)
    activate_dependency_path(state)
    return state


def remove_plugin_dependency_store(plugin_id: str) -> None:
    root = plugin_deps_root().resolve()
    target = (root / plugin_id).resolve()
    if target.exists() and target.is_relative_to(root):
        shutil.rmtree(target, ignore_errors=True)


def find_dependency_installer() -> Optional[DependencyInstaller]:
    python = _explicit_or_bundled_runtime_python()
    if python and (uv := _explicit_or_bundled_uv()):
        return DependencyInstaller(
            kind="uv",
            command_prefix=[str(uv), "pip"],
            python=str(python),
        )

    if python and not is_tauri_backend():
        return DependencyInstaller(
            kind="python",
            command_prefix=[str(python), "-m", "pip"],
            python=str(python),
        )

    if importlib.util.find_spec("pip") is not None:
        return DependencyInstaller(
            kind="python",
            command_prefix=[sys.executable, "-m", "pip"],
            python=sys.executable,
        )

    if uv := _find_uv():
        return DependencyInstaller(
            kind="uv",
            command_prefix=[uv, "pip"],
            python=sys.executable,
        )
    return None


def _explicit_or_bundled_runtime_python() -> Optional[Path]:
    explicit = os.environ.get(RUNTIME_PYTHON_ENV)
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return candidate

    exe_dir = Path(sys.executable).resolve().parent
    roots = [
        exe_dir,
        exe_dir.parent,
        exe_dir.parent.parent,
        exe_dir.parent.parent.parent,
    ]
    for root in roots:
        for rel in _runtime_python_relpaths():
            candidate = root / "python-runtime" / rel
            if candidate.is_file():
                return candidate
    return None


def _explicit_or_bundled_uv() -> Optional[Path]:
    explicit = os.environ.get(RUNTIME_UV_ENV)
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file():
            return candidate

    exe_dir = Path(sys.executable).resolve().parent
    roots = [
        exe_dir,
        exe_dir.parent,
        exe_dir.parent.parent,
        exe_dir.parent.parent.parent,
    ]
    for root in roots:
        candidate = root / "python-runtime" / _uv_executable_name()
        if candidate.is_file():
            return candidate
    return None


def _runtime_python_relpaths() -> tuple[Path, ...]:
    if sys.platform.startswith("win"):
        return (
            Path("python.exe"),
            Path("Scripts") / "python.exe",
        )
    return (
        Path("bin") / "python",
        Path("bin") / "python3",
        Path("bin") / "python3.10",
        Path("python"),
    )


def _uv_executable_name() -> str:
    return "uv.exe" if sys.platform.startswith("win") else "uv"


def _find_uv() -> Optional[str]:
    if found := shutil.which("uv"):
        return found

    home = Path.home()
    candidates = [
        home / ".local" / "bin" / "uv",
        home / ".cargo" / "bin" / "uv",
    ]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(
            Path(local_app_data) / "Programs" / "uv" / "uv.exe",
        )
    candidates.append(home / ".cargo" / "bin" / "uv.exe")

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None
