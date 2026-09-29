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
    def test_acquire_succeeds_on_a_free_file(self, tmp_path):
        path = tmp_path / "l.lock"
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            assert lock_mod._acquire_os_lock(fd) is True
        finally:
            lock_mod._release_os_lock(fd)
            os.close(fd)

    def test_acquire_returns_false_when_contended(self, tmp_path):
        path = tmp_path / "l.lock"
        held = _hold(path)
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            assert lock_mod._acquire_os_lock(fd) is False
        finally:
            os.close(fd)
            _release(held)

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
    def test_creates_parent_dirs(self, lock_path):
        assert not lock_path.parent.exists()

        with lock_mod.plugin_install_lock(lock_path) as acquired:
            assert acquired is True
            assert lock_path.parent.is_dir()

    def test_yields_true_and_creates_lock_file(self, lock_path):
        with lock_mod.plugin_install_lock(lock_path) as acquired:
            assert acquired is True
            assert lock_path.is_file()

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


class TestTimeoutFallsOpen:
    """The body still runs unlocked: a stuck peer never blocks install."""

    def test_yields_false_when_the_lock_is_held_past_timeout(self, lock_path):
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        held = _hold(lock_path)
        try:
            with lock_mod.plugin_install_lock(
                lock_path,
                timeout=0.0,
            ) as acquired:
                assert acquired is False
        finally:
            _release(held)

    def test_body_runs_despite_timeout(self, lock_path):
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        held = _hold(lock_path)
        ran = []
        try:
            with lock_mod.plugin_install_lock(lock_path, timeout=0.0):
                ran.append(True)
        finally:
            _release(held)
        assert ran == [True]

    def test_timeout_does_not_leave_the_lock_held(self, lock_path):
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        held = _hold(lock_path)
        try:
            with lock_mod.plugin_install_lock(lock_path, timeout=0.0):
                pass
        finally:
            _release(held)

        # After the peer releases, the lock is free again (we never held it).
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            assert lock_mod._acquire_os_lock(fd) is True
        finally:
            lock_mod._release_os_lock(fd)
            os.close(fd)

    def test_negative_timeout_is_clamped_to_zero(self, lock_path):
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        held = _hold(lock_path)
        try:
            with lock_mod.plugin_install_lock(
                lock_path,
                timeout=-5.0,
            ) as acquired:
                assert acquired is False
        finally:
            _release(held)

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
    def test_unwritable_lock_dir_yields_false_but_still_runs(
        self,
        monkeypatch,
        tmp_path,
    ):
        target = tmp_path / "cannot-create" / "l.lock"

        real_mkdir = Path.mkdir

        def deny(self, *args, **kwargs):
            if "cannot-create" in str(self):
                raise OSError(errno.EACCES, "denied")
            return real_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", deny)
        ran = []
        with lock_mod.plugin_install_lock(target) as acquired:
            ran.append(acquired)

        assert ran == [False]

    def test_unopenable_lock_file_yields_false(self, monkeypatch, tmp_path):
        target = tmp_path / "l.lock"

        real_open = os.open

        def deny(*args, **kwargs):
            raise OSError(errno.EACCES, "denied")

        monkeypatch.setattr(os, "open", deny)
        with lock_mod.plugin_install_lock(target) as acquired:
            assert acquired is False
        monkeypatch.setattr(os, "open", real_open)

    def test_unexpected_lock_error_falls_open(self, monkeypatch, tmp_path):
        target = tmp_path / "l.lock"

        def boom(_fd):
            raise OSError(errno.EBADF, "bad fd")

        monkeypatch.setattr(lock_mod, "_acquire_os_lock", boom)
        with lock_mod.plugin_install_lock(target) as acquired:
            assert acquired is False

    def test_lock_file_path_is_coerced_from_str(self, tmp_path):
        target = str(tmp_path / "strlock" / "l.lock")
        with lock_mod.plugin_install_lock(target) as acquired:
            assert acquired is True
            assert Path(target).is_file()
