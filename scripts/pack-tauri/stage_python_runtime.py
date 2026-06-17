#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage a standalone CPython runtime for the Tauri desktop bundle.

The Tauri backend is a PyInstaller-frozen executable, so ``sys.executable`` is
not a usable Python interpreter. To install third-party *plugin* dependencies
at runtime we ship a standalone CPython (python-build-standalone) whose
``X.Y``/architecture match the frozen interpreter, and drive ``pip install``
with it (see ``qwenpaw.plugins.loader``).

This script downloads the matching ``install_only`` build and extracts it to
``<dest>/python``. Run it with the SAME interpreter used for the PyInstaller
build so the bundled runtime version matches automatically.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

RELEASES_API = (
    "https://api.github.com/repos/astral-sh/"
    "python-build-standalone/releases/latest"
)


def _host_triple() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    arch = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
    }.get(machine)
    if arch is None:
        raise SystemExit(f"unsupported machine architecture: {machine!r}")
    if system == "Windows":
        return f"{arch}-pc-windows-msvc"
    if system == "Darwin":
        return f"{arch}-apple-darwin"
    if system == "Linux":
        return f"{arch}-unknown-linux-gnu"
    raise SystemExit(f"unsupported platform: {system!r}")


def _python_exe(dest: Path) -> Path:
    if platform.system() == "Windows":
        return dest / "python" / "python.exe"
    return dest / "python" / "bin" / "python3"


def _http_get(url: str) -> bytes:
    request = urllib.request.Request(url)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    request.add_header("User-Agent", "qwenpaw-build")
    with urllib.request.urlopen(request, timeout=120) as resp:
        return resp.read()


def _find_asset_url(xy: str, triple: str) -> str:
    data = json.loads(_http_get(RELEASES_API).decode("utf-8"))
    pattern = re.compile(
        rf"^cpython-{re.escape(xy)}\.\d+\+\d+-{re.escape(triple)}"
        r"-install_only\.tar\.gz$",
    )
    for asset in data.get("assets", []):
        if pattern.match(asset.get("name", "")):
            return asset["browser_download_url"]
    raise SystemExit(
        f"no python-build-standalone install_only asset for "
        f"Python {xy} / {triple} in the latest release",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        required=True,
        help="Target directory (a 'python' subdir is created inside it)",
    )
    parser.add_argument(
        "--python-version",
        default=f"{sys.version_info.major}.{sys.version_info.minor}",
        help="CPython X.Y to stage (default: this interpreter's version)",
    )
    args = parser.parse_args()

    xy = args.python_version
    triple = _host_triple()
    dest = Path(args.dest).resolve()
    marker = dest / ".python-runtime-version"

    already_staged = (
        _python_exe(dest).is_file()
        and marker.is_file()
        and marker.read_text(encoding="utf-8").strip() == f"{xy}-{triple}"
    )
    if already_staged:
        print(f"python-runtime already staged ({xy}-{triple}); skipping")
        return

    print(f"Staging standalone CPython {xy} for {triple}...")
    url = _find_asset_url(xy, triple)
    print(f"Downloading {url}")

    if dest.exists():
        import shutil

        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        suffix=".tar.gz",
        delete=False,
    ) as tmp:
        tmp.write(_http_get(url))
        archive = tmp.name
    try:
        with tarfile.open(archive, "r:gz") as tar:
            # ``filter="data"`` is only available on newer CPython patch
            # releases (3.12+, backported to 3.10.12/3.11.4). Fall back to a
            # plain extract on older interpreters; the archive comes from the
            # trusted python-build-standalone release.
            try:
                tar.extractall(dest, filter="data")
            except TypeError:
                tar.extractall(dest)
    finally:
        os.unlink(archive)

    exe = _python_exe(dest)
    if not exe.is_file():
        raise SystemExit(f"staging failed: interpreter missing at {exe}")
    marker.write_text(f"{xy}-{triple}", encoding="utf-8")
    print(f"Staged python-runtime at {dest / 'python'}")


if __name__ == "__main__":
    main()
