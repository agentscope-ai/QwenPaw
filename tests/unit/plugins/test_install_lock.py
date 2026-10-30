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
    def test_creates_lock_and_releases_after_the_block(self, lock_path):
        assert not lock_path.parent.exists()
        with lock_mod.plugin_install_lock(lock_path) as first:
            assert first is True
            assert lock_path.parent.is_dir()
            assert lock_path.is_file()

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

        def deny_write(*_args):
            pytest.fail("Acquiring a lock must not write into a peer's lock")

        monkeypatch.setattr(lock_mod.os, "write", deny_write)
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
    @pytest.mark.skipif(_WINDOWS, reason="requires POSIX search permissions")
    def test_search_only_ancestor_preserves_admission(self, tmp_path):
        from qwenpaw.plugins import dependency_maintenance as maintenance

        if os.geteuid() == 0:
            pytest.skip("root bypasses directory permissions")
        parent = tmp_path / "restricted"
        site = parent / "site-packages"
        site.mkdir(parents=True)
        package = site / "module.py"
        package.write_text("VALUE = 1")
        parent.chmod(0o111)
        try:
            assert package.read_text() == "VALUE = 1"
            try:
                list(parent.iterdir())
            except PermissionError:
                pass
            else:
                pytest.skip("filesystem does not enforce search-only access")
            assert maintenance.canonical(site) == site.resolve()
            maintenance.lease_environment([site])
            try:
                assert maintenance.live_readers([site])
                with pytest.raises(RuntimeError, match="BUSY"):
                    with maintenance.maintenance([site], "test", "token"):
                        pytest.fail("active reader admitted maintenance")
            finally:
                descriptor, lease = maintenance._READERS.pop(
                    str(site.resolve()),
                )
                os.close(descriptor)
                lease.unlink()
            assert not maintenance.live_readers([site])
            with maintenance.maintenance([site], "test", "token"):
                pass
            maintenance.clear_maintenance([site], "test")
        finally:
            parent.chmod(0o755)

    @pytest.mark.skipif(_WINDOWS, reason="POSIX passwd home selection")
    @pytest.mark.parametrize(
        "selection",
        ["passwd", "home", "explicit", "none"],
    )
    def test_state_root_selection_is_stable(
        self,
        tmp_path,
        monkeypatch,
        selection,
    ):
        import importlib.util
        import pwd
        from types import SimpleNamespace

        from qwenpaw.plugins import dependency_maintenance as maintenance

        spec = importlib.util.spec_from_file_location(
            "fresh_dependency_maintenance",
            maintenance.__file__,
        )
        fresh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fresh)
        home = tmp_path / "home"
        passwd_home = tmp_path / "passwd-home"
        override = tmp_path / "state"
        monkeypatch.delenv(fresh._STATE_ENV, raising=False)
        monkeypatch.delenv("HOME", raising=False)
        if selection != "none":
            monkeypatch.setenv("HOME", str(home))
        if selection == "explicit":
            monkeypatch.setenv(fresh._STATE_ENV, str(override))

        def account(_uid):
            if selection == "passwd":
                return SimpleNamespace(pw_dir=str(passwd_home))
            raise KeyError("uid not found")

        monkeypatch.setattr(pwd, "getpwuid", account)
        if selection == "none":
            with pytest.raises(
                RuntimeError,
                match="DEPENDENCY_STATE_ROOT_UNAVAILABLE",
            ):
                fresh.state_root()
            return
        expected = (
            override
            if selection == "explicit"
            else (passwd_home if selection == "passwd" else home)
            / ".qwenpaw"
            / "dependency-environments"
        )
        try:
            assert fresh.state_root() == expected.resolve()
            monkeypatch.setenv("HOME", str(tmp_path / "changed-home"))
            monkeypatch.setenv(
                fresh._STATE_ENV,
                str(tmp_path / "changed-state"),
            )
            monkeypatch.setenv(
                "QWENPAW_WORKING_DIR",
                str(tmp_path / "changed-work"),
            )
            assert fresh.state_root() == expected.resolve()
            site = tmp_path / "site"
            site.mkdir()
            fresh.lease_environment([site])
            assert fresh.live_readers([site])
            assert fresh._readers_dir(site).is_relative_to(expected.resolve())
        finally:
            fresh._close_readers()

    @pytest.mark.parametrize("alias_kind", ["symlink", "case", "distinct"])
    @pytest.mark.parametrize("owner", ["reader", "writer"])
    def test_site_aliases_share_one_cross_process_lock(
        self,
        tmp_path,
        alias_kind,
        owner,
    ):
        """Filesystem aliases share admission and independent sites do not."""
        import subprocess
        import sys

        from qwenpaw.plugins import dependency_maintenance as maintenance

        site = tmp_path / "CaseParent" / "CaseSite"
        site.mkdir(parents=True)
        alias = tmp_path / "caseparent" / "casesite"
        if alias_kind == "symlink":
            alias = tmp_path / "alias"
            alias.symlink_to(site, target_is_directory=True)
        elif alias_kind == "case":
            if not alias.exists() or not alias.samefile(site):
                pytest.skip("requires a case-insensitive filesystem")
        else:
            if alias.exists():
                pytest.skip("requires a case-sensitive filesystem")
            alias.mkdir(parents=True)
        same = alias_kind != "distinct"
        path = lock_mod.environment_install_lock_path(site)
        assert (path == lock_mod.environment_install_lock_path(alias)) == same
        script = """import sys
from pathlib import Path
from qwenpaw.plugins import dependency_maintenance as m
from qwenpaw.plugins.install_lock import (
    environment_install_lock_path, plugin_install_lock,
)
site = Path(sys.argv[1])
if sys.argv[2] == 'reader':
    m.lease_environment([site])
    print('held', flush=True)
    sys.stdin.readline()
else:
    with plugin_install_lock(environment_install_lock_path(site)):
        print('held', flush=True)
        sys.stdin.readline()
"""
        source_root = str(Path(lock_mod.__file__).resolve().parents[2])
        script = f"import sys\nsys.path.insert(0, {source_root!r})\n" + script
        with subprocess.Popen(
            [sys.executable, "-I", "-c", script, str(alias), owner],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as peer:
            try:
                assert peer.stdout.readline().strip() == "held"
                if owner == "reader":
                    assert bool(maintenance.live_readers([site])) == same
                operation = maintenance.maintenance([site], "test", "token")
                if same:
                    with pytest.raises(RuntimeError, match="BUSY"):
                        with operation:
                            (site / "sdk-mutated").touch()
                    assert not (site / "sdk-mutated").exists()
                else:
                    with operation:
                        pass
                    maintenance.clear_maintenance([site], "test")
            finally:
                peer.communicate("release\n", timeout=5)
        assert not maintenance.live_readers([site])
        with maintenance.maintenance([site], "test", "token"):
            pass
        maintenance.clear_maintenance([site], "test")
        before = lock_mod.environment_install_lock_path(site)
        (site / "package.py").write_text("updated")
        assert lock_mod.environment_install_lock_path(site) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "repair", "maintenance"])
async def test_reader_admission_waits_for_publication(tmp_path, outcome):
    """A live writer's temporary repair marker is not an abandoned write."""
    import asyncio
    import sys

    from qwenpaw.plugins import dependency_maintenance as maintenance

    site = tmp_path / "site"
    site.mkdir()
    source = str(Path(lock_mod.__file__).resolve().parents[2])
    script = (
        f"import sys\nsys.path.insert(0, {source!r})\n"
        + """
from pathlib import Path
from qwenpaw.plugins import dependency_maintenance as m
site = Path(sys.argv[1])
original = m._try_lock
attempts = 0
def observed(fd):
    global attempts
    acquired = original(fd)
    if not acquired and attempts < 2:
        attempts += 1
        print('blocked', flush=True)
        sys.stdin.readline()
    return acquired
m._try_lock = observed
try:
    m.lease_environment([site])
    print('admitted', flush=True)
    sys.stdin.readline()
except RuntimeError as exc:
    print(str(exc).split(':')[0], flush=True)
finally:
    m._close_readers()
"""
    )
    peer = None
    repair = maintenance.repair_marker(site)
    barrier = maintenance.marker(site)

    async def line():
        return (
            (await asyncio.wait_for(peer.stdout.readline(), 5))
            .decode()
            .strip()
        )

    async def resume():
        peer.stdin.write(b"continue\n")
        await peer.stdin.drain()

    try:
        with (
            lock_mod.plugin_install_lock(
                lock_mod.environment_install_lock_path(site),
            ),
            maintenance.file_lock(maintenance._admission_gate(site)),
        ):
            if outcome != "maintenance":
                repair.write_text("publication pending")
            peer = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                "-c",
                script,
                str(site),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={
                    **os.environ,
                    "QWENPAW_DEPENDENCY_STATE_DIR": str(
                        maintenance.state_root(),
                    ),
                },
            )
            assert await line() == "blocked"
            if outcome == "maintenance":
                barrier.write_text("{}")
            await resume()
            expected = (
                "DEPENDENCY_MAINTENANCE_REQUIRED"
                if outcome == "maintenance"
                else "blocked"
            )
            assert await line() == expected
            assert not maintenance.live_readers([site])
            if outcome == "success":
                repair.unlink()
        if outcome != "maintenance":
            await resume()
            expected = (
                "admitted"
                if outcome == "success"
                else "DEPENDENCY_REPAIR_REQUIRED"
            )
            assert await line() == expected
            readers = maintenance.live_readers([site])
            assert [row["pid"] for row in readers] == (
                [peer.pid] if outcome == "success" else []
            )
            if outcome == "success":
                await resume()
        _stdout, stderr = await asyncio.wait_for(peer.communicate(), 5)
        assert peer.returncode == 0, stderr.decode()
        assert not maintenance.live_readers([site])
    finally:
        if peer is not None and peer.returncode is None:
            peer.kill()
            await peer.wait()
        repair.unlink(missing_ok=True)
        barrier.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_async_lock_cancellation_waits_for_real_acquisition(lock_path):
    """A cancelled waiter cannot leave a late acquired descriptor locked."""
    import asyncio
    import threading
    from contextlib import contextmanager

    lock_path.parent.mkdir(parents=True)
    peer = _hold(lock_path)
    started = threading.Event()
    claims = []
    task = None

    @contextmanager
    def acquire():
        started.set()
        with lock_mod.plugin_install_lock(lock_path, timeout=5) as acquired:
            yield acquired

    async def waiter():
        async with lock_mod.async_lock(
            acquire(),
            on_acquired=lambda value: claims.append(
                (value, asyncio.current_task()),
            ),
        ):
            pytest.fail("cancelled waiter entered its body")

    try:
        task = asyncio.create_task(waiter())
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        _release(peer)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert claims == [(True, task)]
    competitor = _hold(lock_path)
    _release(competitor)


@pytest.mark.asyncio
async def test_async_lock_release_is_schedulable_and_exclusive(lock_path):
    """Release completion stays protected while the loop can make progress."""
    import asyncio
    import threading

    entered_exit = threading.Event()
    finish_exit = threading.Event()
    underlying = lock_mod.plugin_install_lock(lock_path)
    exits = []

    class SlowRelease:
        def __enter__(self):
            return underlying.__enter__()

        def __exit__(self, *error):
            exits.append(error)
            entered_exit.set()
            assert finish_exit.wait(3)
            return underlying.__exit__(*error)

    async def owner():
        async with lock_mod.async_lock(SlowRelease()):
            with pytest.raises(OSError):
                _hold(lock_path)

    task = asyncio.create_task(owner())
    try:
        assert await asyncio.to_thread(entered_exit.wait, 2)
        assert not task.done()
        with pytest.raises(OSError):
            _hold(lock_path)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        finish_exit.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert len(exits) == 1
    competitor = _hold(lock_path)
    _release(competitor)


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_case", ["normal", "cancel", 32, 33])
async def test_observation_child_custody_is_temporary(
    tmp_path,
    monkeypatch,
    exit_case,
):
    """Inspection children start under held gates without permanent readers."""
    import asyncio
    import sys

    from qwenpaw.plugins import dependency_maintenance as maintenance
    from .timing import WAIT_TIMEOUT

    site = tmp_path / "inspection-site"
    site.mkdir()
    other = tmp_path / "other-inspection-site"
    other.mkdir()
    sites = [site, other]
    script = """
import importlib.util
import sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('maintenance', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.lease_environment([Path(sys.argv[2])], parent_pid=int(sys.argv[3]) or None)
sys.stdout.buffer.write(b'READY\\n')
sys.stdout.buffer.flush()
sys.stdin.readline()
m._close_readers()
"""
    ready, release = asyncio.Event(), asyncio.Event()

    async def observe():
        peer = None
        async with lock_mod.environment_observation(sites):
            with pytest.raises(lock_mod.InstallLockError):
                with lock_mod.plugin_install_lock(
                    lock_mod.environment_install_lock_path(site),
                    timeout=0,
                ):
                    pytest.fail("observation admitted a competing writer")
            # The parent custody is scoped, never inserted into lifetime leases.
            assert str(site.resolve()) not in maintenance._READERS
            assert [
                row["pid"] for row in maintenance.live_readers([site])
            ] == [
                os.getpid(),
            ]
            try:
                peer = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-I",
                    "-c",
                    script,
                    maintenance.__file__,
                    str(site),
                    # Independent CLI startup needs no inspection-parent proof.
                    str(0 if exit_case == "normal" else os.getpid()),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env={
                        **os.environ,
                        "QWENPAW_DEPENDENCY_STATE_DIR": str(
                            maintenance.state_root(),
                        ),
                    },
                )
                assert (
                    await asyncio.wait_for(
                        peer.stdout.readline(),
                        WAIT_TIMEOUT,
                    )
                    == b"READY\n"
                )
                assert sorted(
                    row["pid"] for row in maintenance.live_readers([site])
                ) == sorted([os.getpid(), peer.pid])
                peer.stdin.write(b"RELEASE\n")
                await peer.stdin.drain()
                _, error = await asyncio.wait_for(
                    peer.communicate(),
                    WAIT_TIMEOUT,
                )
                assert peer.returncode == 0, error
                assert [
                    row["pid"] for row in maintenance.live_readers([site])
                ] == [
                    os.getpid(),
                ]
                ready.set()
                await release.wait()
            finally:
                if peer is not None and peer.returncode is None:
                    peer.kill()
                    await peer.communicate()

    pending = asyncio.create_task(observe())
    ready_wait = asyncio.create_task(ready.wait())
    shared_paths = set()
    try:
        done, _ = await asyncio.wait_for(
            asyncio.wait(
                {pending, ready_wait},
                return_when=asyncio.FIRST_COMPLETED,
            ),
            WAIT_TIMEOUT,
        )
        if pending in done:
            await pending
        assert ready.is_set()
        if isinstance(exit_case, int):
            unlink = Path.unlink

            def sharing_conflict(path, *args, **kwargs):
                if path.suffix == ".lease" and path not in shared_paths:
                    shared_paths.add(path)
                    error = OSError("scanner still has stale lease open")
                    error.winerror = exit_case
                    raise error
                return unlink(path, *args, **kwargs)

            monkeypatch.setattr(Path, "unlink", sharing_conflict)
        if exit_case == "cancel":
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(pending, WAIT_TIMEOUT)
        else:
            release.set()
            await asyncio.wait_for(pending, WAIT_TIMEOUT)
    finally:
        ready_wait.cancel()
        await asyncio.gather(ready_wait, return_exceptions=True)
        release.set()
        if not pending.done():
            await asyncio.wait_for(pending, WAIT_TIMEOUT)
    if isinstance(exit_case, int):
        assert shared_paths  # Cleanup encountered the simulated Windows race.
        assert list(maintenance._readers_dir(site).glob("*.lease"))
    # Closed descriptors are already non-live; the scanner reaps stale paths.
    assert not maintenance.live_readers(sites)
    for root in sites:
        assert not list(maintenance._readers_dir(root).glob("*.lease"))
        assert str(root.resolve()) not in maintenance._READERS


@_POSIX_FLOCK
def test_scoped_reader_custody_across_process_exit(tmp_path, monkeypatch):
    """Scoped readers exclude host maintenance until normal or abrupt exit."""
    import subprocess
    import sys

    from qwenpaw.plugins import dependency_maintenance as maintenance

    site = tmp_path / "site"
    site.mkdir()
    state = tmp_path / "state"
    monkeypatch.setattr(maintenance, "_STATE_ROOT", state)
    monkeypatch.setattr(maintenance, "_READER_SCOPE", "")
    monkeypatch.setenv("QWENPAW_DEPENDENCY_STATE_DIR", str(state))
    scope = "a" * 64
    directory = maintenance.prepare_reader_scope([site], scope)[0]
    script = """
import os
import sys
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location("maintenance", sys.argv[2])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
site = Path(sys.argv[1])
scope = m.reader_scope()
os.environ['QWENPAW_DEPENDENCY_READER_SCOPE'] = 'b' * 64
assert m.reader_scope() == scope
with m.file_lock(m._gate(site)):
    with m.observation_readers([site]):
        assert any(row['pid'] == os.getpid() for row in m.live_readers([site]))
m.lease_environment([site])
print('held', flush=True)
sys.stdin.readline()
"""
    env = dict(os.environ, QWENPAW_DEPENDENCY_READER_SCOPE=scope)
    for crash in (False, True):
        with subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-c",
                script,
                str(site),
                maintenance.__file__,
            ],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as peer:
            try:
                assert peer.stdout.readline().strip() == "held"
                assert [
                    row["pid"] for row in maintenance.live_readers([site])
                ] == [peer.pid]
                assert list(directory.glob("*.lease"))
                with pytest.raises(RuntimeError, match="BUSY"):
                    with maintenance.maintenance([site], "test", "token"):
                        pytest.fail("scoped reader admitted maintenance")
            finally:
                if crash:
                    peer.kill()
                _, stderr = peer.communicate("release\n", timeout=5)
            assert peer.returncode == (-9 if crash else 0), stderr
        if not crash:
            assert not list(directory.glob("*.lease"))
        assert not maintenance.live_readers([site])
        assert not list(directory.glob("*.lease"))
        with maintenance.maintenance([site], "test", "token"):
            pass
        maintenance.clear_maintenance([site], "test")

    # A malformed namespace entry must fail promptly rather than block on FIFO.
    invalid = directory / "invalid.lease"
    os.mkfifo(invalid)
    try:
        with pytest.raises(RuntimeError, match="LEASE_INVALID"):
            maintenance.live_readers([site])
    finally:
        invalid.unlink()
