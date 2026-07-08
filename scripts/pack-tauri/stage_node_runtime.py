#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage a Node.js runtime for the Tauri desktop bundle."""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_NODE_VERSION = "v22.20.0"
NODE_DIST_URL = "https://nodejs.org/dist"


def _target() -> tuple[str, str, str]:
    system = platform.system()
    machine = platform.machine().lower()
    arch = {
        "amd64": "x64",
        "x86_64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(machine)
    if arch is None:
        raise SystemExit(f"unsupported machine architecture: {machine!r}")
    if system == "Windows":
        return "win", arch, "zip"
    if system == "Darwin":
        return "darwin", arch, "tar.xz"
    if system == "Linux":
        return "linux", arch, "tar.xz"
    raise SystemExit(f"unsupported platform: {system!r}")


def _node_exe(dest: Path) -> Path:
    if platform.system() == "Windows":
        return dest / "node.exe"
    return dest / "bin" / "node"


def _npx_exe(dest: Path) -> Path:
    if platform.system() == "Windows":
        return dest / "npx.cmd"
    return dest / "bin" / "npx"


def _http_get(url: str) -> bytes:
    request = urllib.request.Request(url)
    request.add_header("User-Agent", "qwenpaw-build")
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def _extract(archive: Path, suffix: str, workdir: Path) -> Path:
    if suffix == "zip":
        with zipfile.ZipFile(archive) as zip_file:
            zip_file.extractall(workdir)
    else:
        with tarfile.open(archive, "r:xz") as tar:
            try:
                tar.extractall(workdir, filter="data")
            except TypeError:
                _validate_tar_members(tar, workdir)
                tar.extractall(workdir)

    roots = [
        path
        for path in workdir.iterdir()
        if path.is_dir() and path.name.startswith("node-")
    ]
    if len(roots) != 1:
        raise SystemExit("failed to locate extracted Node.js directory")
    return roots[0]


def _validate_tar_members(tar: tarfile.TarFile, workdir: Path) -> None:
    root = workdir.resolve()
    for member in tar.getmembers():
        target = (root / member.name).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise SystemExit(
                f"tar member escapes target: {member.name}",
            ) from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", required=True)
    parser.add_argument(
        "--node-version",
        default=os.environ.get("QWENPAW_NODE_VERSION", DEFAULT_NODE_VERSION),
    )
    args = parser.parse_args()

    version = args.node_version
    platform_name, arch, suffix = _target()
    target = f"{platform_name}-{arch}"
    dest = Path(args.dest).resolve()
    marker = dest / ".node-runtime-version"

    if (
        _node_exe(dest).is_file()
        and _npx_exe(dest).is_file()
        and marker.is_file()
        and marker.read_text(encoding="utf-8").strip() == f"{version}-{target}"
    ):
        print(f"node-runtime already staged ({version}-{target}); skipping")
        return

    archive_name = f"node-{version}-{target}.{suffix}"
    url = f"{NODE_DIST_URL}/{version}/{archive_name}"
    print(f"Staging Node.js {version} for {target}...")
    print(f"Downloading {url}")

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        archive = tmpdir / archive_name
        archive.write_bytes(_http_get(url))
        extracted = _extract(archive, suffix, tmpdir)

        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        for item in extracted.iterdir():
            shutil.move(str(item), dest / item.name)

    if not _node_exe(dest).is_file() or not _npx_exe(dest).is_file():
        raise SystemExit("staging failed: node or npx missing")
    marker.write_text(f"{version}-{target}", encoding="utf-8")
    print(f"Staged node-runtime at {dest}")


if __name__ == "__main__":
    main()
