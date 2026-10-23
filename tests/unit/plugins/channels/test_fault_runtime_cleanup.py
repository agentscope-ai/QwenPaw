# -*- coding: utf-8 -*-
"""Temporary SDK sites release their own host lease before Windows removal."""

import os
import subprocess
import sys

import pytest

from qwenpaw.plugins import dependency_maintenance
from tests.fixtures.channel_plugins import g2_fault_runtime


def test_cleanup_closes_exact_host_lease_before_removing_runtime(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "runtime"
    site = root / "site-packages"
    site.mkdir(parents=True)
    other = tmp_path / "other-site"
    other.mkdir()
    monkeypatch.setattr(dependency_maintenance, "_READERS", {})
    dependency_maintenance.lease_environment((site, other))
    descriptor, lease_path = dependency_maintenance._READERS[
        dependency_maintenance.canonical(site)
    ]
    other_descriptor, _ = dependency_maintenance._READERS[
        dependency_maintenance.canonical(other)
    ]
    remove = g2_fault_runtime.shutil.rmtree

    def windows_style_remove(path):
        # Model WinError 32: deleting while the lease descriptor is open is
        # forbidden, even though POSIX permits unlinking an open file.
        with pytest.raises(OSError):
            os.fstat(descriptor)
        assert not lease_path.exists()
        os.fstat(other_descriptor)
        remove(path)

    monkeypatch.setattr(
        g2_fault_runtime.shutil,
        "rmtree",
        windows_style_remove,
    )
    try:
        g2_fault_runtime._cleanup_fault_runtime(root, site)
        assert not root.exists()
        assert set(dependency_maintenance._READERS) == {
            dependency_maintenance.canonical(other),
        }
    finally:
        dependency_maintenance._close_readers()


def test_cleanup_waits_for_child_holding_this_runtime_lease(tmp_path):
    root = tmp_path / "runtime"
    site = root / "site-packages"
    site.mkdir(parents=True)
    script = """
import importlib.util
import sys
import time
spec = importlib.util.spec_from_file_location("maintenance", sys.argv[1])
maintenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maintenance)
maintenance.lease_environment((sys.argv[2],))
print("leased", flush=True)
time.sleep(0.3)
"""
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            dependency_maintenance.__file__,
            str(site),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "leased"
        assert child.poll() is None
        g2_fault_runtime._cleanup_fault_runtime(root, site)
        assert child.wait(timeout=1) == 0
        assert not root.exists()
    finally:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=5)
        child.stdout.close()
