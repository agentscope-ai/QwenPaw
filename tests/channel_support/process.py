# -*- coding: utf-8 -*-
"""Test-free construction and observation of real isolated plugin workers."""

import asyncio
import hashlib
import json
from pathlib import Path
import platform
import os
import shutil
import sys
import sysconfig
import venv

import psutil

ROOT = Path(__file__).resolve().parents[2]


def digest(root):
    result = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            name, data = (
                path.relative_to(root).as_posix().encode(),
                path.read_bytes(),
            )
            result.update(len(name).to_bytes(8, "big"))
            result.update(name)
            result.update(len(data).to_bytes(8, "big"))
            result.update(data)
    return result.hexdigest()


async def eventually(predicate, timeout=5):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


def alive(pid):
    try:
        return (
            bool(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
        )
    except psutil.NoSuchProcess:
        return False


def launch(directory, *, mode="normal", **overrides):
    from qwenpaw.plugins.execution import PluginLaunchSpec

    code = directory / "component"
    code.mkdir()
    shutil.copyfile(Path(__file__).with_name("worker.py"), code / "worker.py")
    marker = directory / "marker"
    return (
        PluginLaunchSpec(
            **{
                "python_executable": sys.executable,
                "support_root": ROOT / "src",
                "code_root": code,
                "source_revision": digest(code),
                "plugin_id": "sample.component",
                "instance_id": directory.name,
                "generation": 1,
                "entrypoint": "worker:Worker",
                "config": {"marker": str(marker), "mode": mode},
                "startup_timeout": 2,
                "shutdown_timeout": 0.4,
                **overrides,
            },
        ),
        marker,
    )


def dependency_site(path):
    path.mkdir(parents=True)
    (path / "sample_shared_sdk.py").write_text("VALUE = 'offline-sdk'\n")
    info = path / "sample_shared_sdk-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: sample-shared-sdk\nVersion: 1.0\n",
    )
    return path


def runtime_layout(directory, monkeypatch):
    """Simulate a trusted frozen layout without rebuilding releases."""
    from packaging.tags import sys_tags
    from qwenpaw.__version__ import __version__

    root = directory / "Resources"
    support = root / "support"
    shutil.copytree(
        ROOT / "src/qwenpaw",
        support / "qwenpaw",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    runtime = root / "runtime"
    venv.EnvBuilder(with_pip=False, symlinks=False).create(runtime)
    executable = runtime / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    site_packages = runtime / (
        "Lib/site-packages"
        if os.name == "nt"
        else (
            f"lib/python{sys.version_info.major}.{sys.version_info.minor}/"
            "site-packages"
        )
    )
    (site_packages / "test-runtime.pth").write_text(
        sysconfig.get_path("purelib") + "\n",
    )
    site = dependency_site(root / "dependencies")
    index = support / "qwenpaw/official_channels/index.json"
    identity = {
        "version": list(sys.version_info[:2]),
        "implementation": sys.implementation.name,
        "cache_tag": sys.implementation.cache_tag,
        "sys_platform": sys.platform,
        "system": platform.system(),
        "machine": platform.machine(),
        "supported_tags": [str(tag) for tag in sys_tags()],
    }
    manifest = root / "runtime.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "host_version": __version__,
                "preset": "light",
                "python_executable": executable.relative_to(root).as_posix(),
                "support_root": "support",
                "dependency_paths": ["dependencies"],
                "python": identity,
                "python_runtime_release": "local-test-runtime",
                "host_wheel_sha256": "0" * 64,
                "official_index_sha256": hashlib.sha256(
                    index.read_bytes(),
                ).hexdigest(),
            },
        ),
    )
    for name, value in {
        "QWENPAW_TAURI_RESOURCE_DIR": root,
        "QWENPAW_CHANNEL_RUNTIME_MANIFEST": manifest,
        "QWENPAW_DESKTOP_PY_RUNTIME": executable.resolve(),
        "QWENPAW_CHANNEL_SUPPORT_ROOT": support,
        "QWENPAW_CHANNEL_DEPENDENCY_PATHS": json.dumps([str(site)]),
    }.items():
        monkeypatch.setenv(name, str(value))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    return support, site
