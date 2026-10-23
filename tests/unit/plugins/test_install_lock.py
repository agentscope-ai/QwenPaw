# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Unit tests for the cross-process plugin install advisory lock.

The lock exists to stop two backend processes from running ``pip install``
into the same target at once (issue #5550: OOM plus corrupted ``.dist-info``
triggering a self-amplifying reinstall loop).

Probed on this platform: two fds in one process *do* contend on ``flock``
(the second raises ``EAGAIN``), so contention is testable without spawning.
"""

import errno
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from qwenpaw.plugins import install_lock as lock_mod

_WINDOWS = os.name == "nt"
_POSIX_FLOCK = pytest.mark.skipif(
    _WINDOWS,
    reason="POSIX-only: fcntl.flock does not exist on Windows",
)


@pytest.fixture()
def lock_path(tmp_path):
    return tmp_path / "locks" / "plugin-install.lock"


def _hold(path):
    """Take the OS lock on *path* from a second fd, as a peer would."""
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def _release(fd):
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def _flock_module():
    """The module whose lock primitive ``lock_mod`` uses on this OS."""
    if os.name == "nt":
        import msvcrt

        return msvcrt
    import fcntl

    return fcntl


def _lock_primitive_name() -> str:
    return "locking" if os.name == "nt" else "flock"


class TestAcquireRelease:
    def test_acquire_reraises_unexpected_os_error(self, monkeypatch, tmp_path):
        """EACCES/EAGAIN mean 'busy'; anything else must propagate."""
        path = tmp_path / "l.lock"
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)

        def boom(*_args):
            raise OSError(errno.EBADF, "bad fd")

        monkeypatch.setattr(_flock_module(), _lock_primitive_name(), boom)
        try:
            with pytest.raises(OSError) as excinfo:
                lock_mod._acquire_os_lock(fd)
            assert excinfo.value.errno == errno.EBADF
        finally:
            os.close(fd)

    def test_release_is_idempotent_on_a_free_fd(self, tmp_path):
        """Releasing a lock that is not held must not raise."""
        path = tmp_path / "l.lock"
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            lock_mod._release_os_lock(fd)
        finally:
            os.close(fd)

    def test_release_swallows_os_error(self, monkeypatch, tmp_path):
        path = tmp_path / "l.lock"
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)

        def boom(*_args):
            raise OSError(errno.EBADF, "bad fd")

        monkeypatch.setattr(_flock_module(), _lock_primitive_name(), boom)
        try:
            lock_mod._release_os_lock(fd)  # must not raise
        finally:
            os.close(fd)


class TestContextManager:
    def test_releases_after_the_block(self, lock_path):
        with lock_mod.plugin_install_lock(lock_path) as first:
            assert first is True

        # A second fd can take the lock only if the first was released.
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            assert lock_mod._acquire_os_lock(fd) is True
        finally:
            lock_mod._release_os_lock(fd)
            os.close(fd)

    def test_releases_even_when_the_body_raises(self, lock_path):
        with pytest.raises(RuntimeError):
            with lock_mod.plugin_install_lock(lock_path):
                raise RuntimeError("boom")

        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            assert lock_mod._acquire_os_lock(fd) is True
        finally:
            lock_mod._release_os_lock(fd)
            os.close(fd)

    def test_closes_its_descriptor(self, lock_path):
        with patch.object(lock_mod.os, "close", wraps=os.close) as close:
            with lock_mod.plugin_install_lock(lock_path) as acquired:
                assert acquired is True
        close.assert_called_once()
        with pytest.raises(OSError) as error:
            os.fstat(close.call_args.args[0])
        assert error.value.errno == errno.EBADF


class TestTimeoutFailsClosed:
    """No SDK-writing body may run without successful exclusion."""

    @pytest.mark.parametrize("timeout", [0.0, -5.0])
    def test_denied_lock_never_enters_writing_body(self, lock_path, timeout):
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        held = _hold(lock_path)
        written = lock_path.parent / "sdk-mutated"
        try:
            with pytest.raises(RuntimeError):
                with lock_mod.plugin_install_lock(lock_path, timeout=timeout):
                    written.touch()
        finally:
            _release(held)
        assert not written.exists()
        with lock_mod.plugin_install_lock(lock_path) as acquired:
            assert acquired is True

    def test_retries_until_the_peer_releases(self, lock_path, monkeypatch):
        """A short wait should succeed once the peer lets go."""
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        held = _hold(lock_path)
        monkeypatch.setattr(lock_mod, "_RETRY_INTERVAL_SECONDS", 0.01)
        try:
            # Release from a timer thread so the retry loop can observe it.
            import threading

            timer = threading.Timer(0.05, lambda: _release(held))
            timer.start()
            with lock_mod.plugin_install_lock(
                lock_path,
                timeout=5.0,
            ) as acquired:
                assert acquired is True
            timer.cancel()
            held = None
        finally:
            if held is not None:
                _release(held)


class TestDegradedPaths:
    @pytest.mark.parametrize("failure", ["mkdir", "open", "primitive"])
    def test_os_failure_never_enters_writing_body(
        self,
        monkeypatch,
        tmp_path,
        failure,
    ):
        target = tmp_path / "cannot-create" / "l.lock"
        written = tmp_path / "sdk-mutated"

        def deny(*_args, **_kwargs):
            raise OSError(errno.EACCES, "denied")

        if failure == "mkdir":
            monkeypatch.setattr(Path, "mkdir", deny)
        elif failure == "open":
            original_open = os.open

            def deny_lock(path, *args, **kwargs):
                if Path(path) == target:
                    return deny()
                return original_open(path, *args, **kwargs)

            monkeypatch.setattr(os, "open", deny_lock)
        else:
            monkeypatch.setattr(lock_mod, "_acquire_os_lock", deny)
        with pytest.raises(RuntimeError):
            with lock_mod.plugin_install_lock(target):
                written.touch()
        assert not written.exists()


class TestEnvironmentIdentity:
    def test_site_aliases_share_one_cross_process_lock(self, tmp_path):
        """Separate writers cannot evade exclusion through a site symlink."""
        import subprocess
        import sys

        assert hasattr(lock_mod, "environment_install_lock_path")
        site = tmp_path / "shared-site"
        site.mkdir()
        alias = tmp_path / "alias"
        alias.symlink_to(site, target_is_directory=True)
        path = lock_mod.environment_install_lock_path(site)
        assert path == lock_mod.environment_install_lock_path(alias)
        script = """import sys
from pathlib import Path
from qwenpaw.plugins.install_lock import (
    environment_install_lock_path,plugin_install_lock,
)
with plugin_install_lock(environment_install_lock_path(Path(sys.argv[1]))):
    print('held',flush=True)
    sys.stdin.readline()
"""
        source_root = str(Path(lock_mod.__file__).resolve().parents[2])
        script = f"import sys\nsys.path.insert(0, {source_root!r})\n" + script
        with subprocess.Popen(
            [sys.executable, "-I", "-c", script, str(alias)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as peer:
            try:
                assert peer.stdout.readline().strip() == "held"
                with pytest.raises(RuntimeError):
                    with lock_mod.plugin_install_lock(path, timeout=0):
                        (site / "sdk-mutated").touch()
                assert not (site / "sdk-mutated").exists()
            finally:
                peer.communicate("release\n", timeout=5)
        with lock_mod.plugin_install_lock(path) as acquired:
            assert acquired is True
