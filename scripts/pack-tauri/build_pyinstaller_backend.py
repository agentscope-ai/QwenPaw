#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the PyInstaller backend sidecar used by the Tauri desktop app."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _extract_version(repo_root: Path) -> str:
    version_file = repo_root / "src" / "qwenpaw" / "__version__.py"
    match = re.search(
        r'^__version__\s*=\s*"([^"]+)"',
        version_file.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if match is None:
        raise RuntimeError(f"Failed to extract version from {version_file}")
    return match.group(1)


def _run(args: list[str | os.PathLike[str]], **kwargs) -> None:
    display = " ".join(str(arg) for arg in args)
    print(f"+ {display}")
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def _which(name: str) -> str | None:
    return shutil.which(name)


def _venv_python(repo_root: Path) -> Path:
    if os.name == "nt":
        return repo_root / ".venv" / "Scripts" / "python.exe"
    return repo_root / ".venv" / "bin" / "python"


def _ensure_python(repo_root: Path) -> Path:
    python = _venv_python(repo_root)
    if python.exists():
        return python

    uv = _which("uv")
    if uv:
        print("Creating virtual environment with uv...")
        _run([uv, "venv", repo_root / ".venv"])
    else:
        print("Creating virtual environment with python -m venv...")
        _run([sys.executable, "-m", "venv", repo_root / ".venv"])

    if not python.exists():
        raise RuntimeError(f"Python not found after creating venv: {python}")
    return python


def _python_imports(python: Path, statement: str) -> bool:
    result = subprocess.run(
        [str(python), "-c", statement],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _install_packages(python: Path, packages: list[str]) -> None:
    uv = _which("uv")
    if uv:
        _run([uv, "pip", "install", "--python", python, *packages])
    else:
        _run([python, "-m", "pip", "install", *packages])


def _uninstall_package(python: Path, package: str) -> None:
    uv = _which("uv")
    if uv:
        args: list[str | os.PathLike[str]] = [
            uv,
            "pip",
            "uninstall",
            "--python",
            python,
            "-y",
            package,
        ]
    else:
        args = [python, "-m", "pip", "uninstall", "-y", package]

    subprocess.run(
        [str(arg) for arg in args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _copy_backend_bundle(repo_root: Path, backend_dir: Path) -> Path:
    dest = repo_root / "console" / "src-tauri" / "binaries" / "qwenpaw-backend"
    dest.mkdir(parents=True, exist_ok=True)

    for child in dest.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    for child in backend_dir.iterdir():
        target = dest / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)

    (dest / ".gitkeep").touch()
    executable = dest / (
        "qwenpaw-backend.exe" if os.name == "nt" else "qwenpaw-backend"
    )
    if executable.exists() and os.name != "nt":
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

    return dest


def _bundle_size_mb(path: Path) -> float:
    return sum(
        file.stat().st_size for file in path.rglob("*") if file.is_file()
    ) / (1024 * 1024)


def _dist_root(repo_root: Path) -> Path:
    dist_root = Path(os.environ.get("DIST", "dist"))
    if not dist_root.is_absolute():
        dist_root = repo_root / dist_root
    return dist_root


def _print_header(repo_root: Path, version: str) -> None:
    print("=========================================")
    print("QwenPaw PyInstaller Build")
    print("=========================================")
    print(f"Version: {version}")
    print(f"Repository: {repo_root}")
    print("")


def _prepare_python_env(repo_root: Path) -> Path:
    print("== Checking prerequisites ==")
    python = _ensure_python(repo_root)
    _run([python, "--version"])
    print("")

    print("== Installing PyInstaller ==")
    if not _python_imports(python, "import PyInstaller"):
        _install_packages(python, ["pyinstaller>=6.0.0"])
    print("PyInstaller installed")

    print("== Installing project dependencies ==")
    _install_packages(python, ["-e", ".[full]"])
    print("Project dependencies installed with full extras")

    if not _python_imports(python, "from acp import Agent"):
        print("Fixing agent-client-protocol namespace...")
        _uninstall_package(python, "acp")
        _install_packages(python, ["agent-client-protocol"])
    print("")
    return python


def _run_pyinstaller(python: Path, repo_root: Path, dist_root: Path) -> None:
    print("== Running PyInstaller ==")
    spec_file = repo_root / "scripts" / "pack-tauri" / "qwenpaw.spec"
    if not spec_file.exists():
        raise RuntimeError(f"Spec file not found at {spec_file}")

    _run(
        [
            python,
            "-m",
            "PyInstaller",
            spec_file,
            "--distpath",
            dist_root / "pyinstaller",
            "--workpath",
            dist_root / "pyinstaller-build",
            "--clean",
            "--noconfirm",
        ],
    )
    print("PyInstaller build complete")
    print("")


def _backend_paths(dist_root: Path) -> tuple[Path, Path]:
    backend_dir = dist_root / "pyinstaller" / "qwenpaw-backend"
    backend_exe = backend_dir / (
        "qwenpaw-backend.exe" if os.name == "nt" else "qwenpaw-backend"
    )
    return backend_dir, backend_exe


def _verify_backend_bundle(dist_root: Path) -> Path:
    backend_dir, backend_exe = _backend_paths(dist_root)
    if not backend_dir.is_dir():
        raise RuntimeError(
            f"Backend bundle directory not found at {backend_dir}",
        )
    if not backend_exe.is_file():
        raise RuntimeError(f"Backend executable not found at {backend_exe}")

    print(f"Backend bundle created: {backend_dir}")
    print(f"Bundle size: {_bundle_size_mb(backend_dir):.2f} MB")
    print("")
    return backend_dir


def _copy_to_tauri(repo_root: Path, backend_dir: Path) -> Path:
    print("== Copying to Tauri binaries directory ==")
    dest = _copy_backend_bundle(repo_root, backend_dir)
    print(f"Copied to: {dest}")
    print("")
    return dest


def _print_footer(backend_dir: Path, dest: Path) -> None:
    print("=========================================")
    print("PyInstaller Build Complete!")
    print("=========================================")
    print("Output:")
    print(f"  Bundle: {backend_dir}")
    print(f"  Tauri resource: {dest}")
    print("")


def main() -> None:
    repo_root = _repo_root()
    os.chdir(repo_root)
    version = _extract_version(repo_root)
    dist_root = _dist_root(repo_root)

    _print_header(repo_root, version)
    python = _prepare_python_env(repo_root)
    _run_pyinstaller(python, repo_root, dist_root)
    backend_dir = _verify_backend_bundle(dist_root)
    dest = _copy_to_tauri(repo_root, backend_dir)
    _print_footer(backend_dir, dest)


if __name__ == "__main__":
    main()
