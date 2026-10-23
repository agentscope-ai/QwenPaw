# -*- coding: utf-8 -*-
"""Lease cleanup uses real descriptors, locks and abruptly exiting children."""

import errno
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

SOURCE = (
    Path(__file__).resolve().parents[3]
    / "src/qwenpaw/plugins/dependency_maintenance.py"
)
CHILD = """
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location('lease_child', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.lease_environment([sys.argv[2]])
if sys.argv[3] == 'active':
    from pathlib import Path
    Path(sys.argv[4]).touch()
    sys.stdin.read(1)
os._exit(0)
"""


@pytest.fixture
def leases(tmp_path):
    spec = importlib.util.spec_from_file_location("lease_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    site = tmp_path / "site"
    site.mkdir()
    return module, site


@pytest.fixture
def opened(leases, monkeypatch):
    module, site = leases
    directory = module._readers_dir(site)
    real_open = os.open
    descriptors = []

    def track(path, *args, **kwargs):
        descriptor = real_open(path, *args, **kwargs)
        if Path(path).parent == directory:
            descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(os, "open", track)
    yield descriptors
    leaked = []
    for descriptor in descriptors:
        try:
            os.fstat(descriptor)
        except OSError as error:
            assert error.errno == errno.EBADF
        else:
            leaked.append(descriptor)
            os.close(descriptor)
    assert not leaked, f"Scanner leaked lease descriptors: {leaked}"


def residual(leases):
    module, site = leases
    result = subprocess.run(
        [sys.executable, "-I", "-c", CHILD, str(SOURCE), str(site), "exit"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    (path,) = module._readers_dir(site).glob("*.lease")
    return path


def windows_error(code):
    error = PermissionError(errno.EACCES, "Windows file error")
    error.winerror = code
    return error


def test_abrupt_exit_lease_is_closed_before_windows_delete(
    leases,
    opened,
    monkeypatch,
):
    module, site = leases
    path = residual(leases)
    real_unlink = Path.unlink

    def windows_unlink(target, *args, **kwargs):
        if target == path:
            for descriptor in opened:
                try:
                    os.fstat(descriptor)
                except OSError as error:
                    assert error.errno == errno.EBADF
                else:
                    raise windows_error(32)
        return real_unlink(target, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", windows_unlink)
    assert module.live_readers([site]) == []
    assert opened, "The scanner must inspect the real residual lease"
    assert not path.exists()


def test_real_active_child_blocks_maintenance_and_ignore_preserves_lease(
    leases,
    opened,
    tmp_path,
):
    module, site = leases
    ready = tmp_path / "ready"
    child = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-c",
            CHILD,
            str(SOURCE),
            str(site),
            "active",
            str(ready),
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and child.poll() is None:
            assert time.monotonic() < deadline, "Lease child did not start"
            time.sleep(0.01)
        assert ready.exists(), child.communicate(timeout=5)[1]
        (path,) = module._readers_dir(site).glob("*.lease")
        expected = [{"pid": child.pid, "site": str(site)}]
        assert module.live_readers([site]) == expected
        with pytest.raises(RuntimeError, match="DEPENDENCY_ENVIRONMENT_BUSY"):
            with module.maintenance([site], "blocked", "token"):
                pytest.fail("Maintenance admitted a real live consumer")
        assert not module.marker(site).exists()
        assert module.live_readers([site], ignore_pid=child.pid) == []
        assert path.exists()
        with module.maintenance(
            [site],
            "ignored",
            "token",
            ignore_pid=child.pid,
        ):
            assert path.exists()
        module.clear_maintenance([site], "ignored")
        assert module.live_readers([site]) == expected
        assert opened
    finally:
        if child.poll() is None:
            child.communicate("\n", timeout=5)
        assert child.returncode == 0


@pytest.mark.parametrize("boundary", ["open", "unlink"])
def test_concurrent_disappearance_is_harmless(
    leases,
    opened,
    monkeypatch,
    boundary,
):
    module, site = leases
    path = residual(leases)
    real_open, real_unlink = os.open, Path.unlink

    def vanished_open(target, *args, **kwargs):
        if Path(target) == path:
            real_unlink(path)
        return real_open(target, *args, **kwargs)

    def vanished_unlink(target, *args, **kwargs):
        if target == path:
            real_unlink(path)
        return real_unlink(target, *args, **kwargs)

    if boundary == "open":
        monkeypatch.setattr(os, "open", vanished_open)
    else:
        monkeypatch.setattr(Path, "unlink", vanished_unlink)
    assert module.live_readers([site]) == []
    assert not path.exists()


@pytest.mark.parametrize("code", [32, 33])
def test_stale_windows_sharing_violation_defers_cleanup(
    leases,
    opened,
    monkeypatch,
    code,
):
    module, site = leases
    path = residual(leases)
    real_unlink = Path.unlink

    def busy_unlink(target, *args, **kwargs):
        if target == path:
            raise windows_error(code)
        return real_unlink(target, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", busy_unlink)
        assert module.live_readers([site]) == []
        assert path.exists()
    assert module.live_readers([site]) == []
    assert not path.exists()
    assert opened


@pytest.mark.parametrize(
    "error",
    [
        PermissionError(errno.EACCES, "unrelated permission denial"),
        windows_error(5),
        OSError(errno.ENOSPC, "disk failure"),
    ],
)
def test_unrelated_delete_errors_surface(leases, opened, monkeypatch, error):
    module, site = leases
    path = residual(leases)
    real_unlink = Path.unlink

    def failed_unlink(target, *args, **kwargs):
        if target == path:
            raise error
        return real_unlink(target, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failed_unlink)
    with pytest.raises(type(error)) as raised:
        module.live_readers([site])
    assert raised.value is error
    assert path.exists()
    assert opened


def test_lock_probe_error_closes_descriptor(leases, opened, monkeypatch):
    module, site = leases
    path = residual(leases)
    error = OSError(errno.EIO, "lock probe failed")

    def failed_lock(_descriptor):
        raise error

    monkeypatch.setattr(module, "_try_lock", failed_lock)
    with pytest.raises(OSError) as raised:
        module.live_readers([site])
    assert raised.value is error
    assert path.exists()
    assert opened
