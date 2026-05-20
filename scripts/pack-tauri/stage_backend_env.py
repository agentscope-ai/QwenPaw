#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage a conda-packed backend env for the Tauri desktop package.

Both Windows and macOS Tauri builds use the same resource layout:

    console/src-tauri/binaries/qwenpaw-backend/env/

The Rust shell starts the Python interpreter inside that env directly.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_CONDA_UNPACK_AFFECTED_PACKAGES = (
    "huggingface_hub",
    "discord.py",
)


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd or REPO_ROOT, check=True)


def _clean_resource_dir(resource_dir: Path) -> None:
    resource_dir.mkdir(parents=True, exist_ok=True)
    for child in resource_dir.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    (resource_dir / ".gitkeep").touch()


def _extract_archive(archive: Path, env_dir: Path) -> None:
    if env_dir.exists():
        shutil.rmtree(env_dir)
    env_dir.mkdir(parents=True)

    suffixes = "".join(archive.suffixes)
    if suffixes.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(env_dir)
        return

    if suffixes.endswith(".tar.gz") or suffixes.endswith(".tgz"):
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(env_dir)
        return

    raise ValueError(f"Unsupported backend env archive: {archive}")


def _python_executable(env_dir: Path) -> Path:
    if os.name == "nt":
        python = env_dir / "python.exe"
    else:
        python = env_dir / "bin" / "python"
    if not python.is_file():
        raise FileNotFoundError(f"Packaged Python not found: {python}")
    return python


def _conda_unpack(env_dir: Path) -> None:
    unpack = (
        env_dir / "Scripts" / "conda-unpack.exe"
        if os.name == "nt"
        else env_dir / "bin" / "conda-unpack"
    )
    if unpack.is_file():
        print(f"Running conda-unpack: {unpack}")
        _run([str(unpack)], cwd=env_dir)
    else:
        print(f"WARNING: conda-unpack not found at {unpack}, skipping")


def _repair_windows_conda_unpack(env_dir: Path, python: Path) -> None:
    if os.name != "nt":
        return

    wheels_cache = REPO_ROOT / ".cache" / "conda_unpack_wheels"
    if not wheels_cache.is_dir():
        print(f"WARNING: wheels cache missing: {wheels_cache}")
        return

    for package in WINDOWS_CONDA_UNPACK_AFFECTED_PACKAGES:
        print(f"Reinstalling {package} after conda-unpack")
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--force-reinstall",
                "--no-deps",
                "--find-links",
                str(wheels_cache),
                "--no-index",
                package,
            ],
            cwd=env_dir,
        )

    _run(
        [
            str(python),
            "-c",
            (
                "from huggingface_hub import file_download; "
                "import discord; "
                "print('Windows conda-unpack repair OK')"
            ),
        ],
        cwd=env_dir,
    )


def _precompile(env_dir: Path, python: Path) -> None:
    print("Pre-compiling Python bytecode")
    result = subprocess.run(
        [str(python), "-m", "compileall", "-q", "-j", "0", str(env_dir)],
        cwd=env_dir,
        check=False,
    )
    if result.returncode != 0:
        print(
            "WARNING: bytecode pre-compilation reported errors "
            f"(exit code {result.returncode}); continuing",
        )


def _smoke_test(env_dir: Path, python: Path) -> None:
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    path_parts: list[Path | str] = (
        [env_dir, env_dir / "Scripts"]
        if os.name == "nt"
        else [env_dir / "bin"]
    )
    existing_path = env.get("PATH")
    if existing_path:
        path_parts.append(existing_path)
    env["PATH"] = os.pathsep.join(str(path) for path in path_parts)
    subprocess.run(
        [
            str(python),
            "-c",
            (
                "import certifi, qwenpaw; "
                "print('Backend env smoke OK'); "
                "print(qwenpaw.__file__); "
                "print(certifi.where())"
            ),
        ],
        cwd=env_dir,
        env=env,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage a conda-packed backend env for Tauri.",
    )
    parser.add_argument("--archive", required=True, help="conda-pack archive")
    parser.add_argument(
        "--resource-dir",
        required=True,
        help="Tauri qwenpaw-backend resource directory",
    )
    parser.add_argument(
        "--precompile",
        action="store_true",
        help="Pre-compile Python bytecode before packaging",
    )
    args = parser.parse_args()

    archive = Path(args.archive).resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"Backend env archive not found: {archive}")

    resource_dir = Path(args.resource_dir).resolve()
    env_dir = resource_dir / "env"

    _clean_resource_dir(resource_dir)
    _extract_archive(archive, env_dir)
    python = _python_executable(env_dir)
    _conda_unpack(env_dir)
    _repair_windows_conda_unpack(env_dir, python)
    if args.precompile:
        _precompile(env_dir, python)
    _smoke_test(env_dir, python)

    print(f"Staged backend env: {env_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
