# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
# pylint: disable=use-implicit-booleaness-not-comparison
"""Unit tests for the crash-safe swap helpers that are platform neutral.

``tests/unit/backup/test_safe_swap.py`` covers the happy paths of the
three-phase protocol.  This file covers the failure and guard paths of
the module-level helpers: the restore-lock timeout resolver, the startup
target list, path de-duplication, stale-artifact recovery when the
filesystem refuses, the Zip Slip guard, the phase-2 rollback, the Windows
rename probe (driven through a patched ``os.name``) and the busy-path
narrowing helpers.

The ``msvcrt`` branches are never entered: they require a real Windows
byte-range lock, which does not exist on Linux.
"""

from __future__ import annotations

import errno
import io
import os
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.backup._utils import safe_swap as mod
from qwenpaw.backup._utils._mount_swap import (
    OLD_CONTENT_DIR_NAME,
    SwapPreparation,
)

_LOCK_ENV = "QWENPAW_RESTORE_LOCK_TIMEOUT_SECONDS"


# --------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------- #


def _zip(entries: dict[str, str]) -> zipfile.ZipFile:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    buffer.seek(0)
    return zipfile.ZipFile(buffer, "r")


def _snapshot(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _flock_module():
    """The module whose lock primitive ``mod`` uses on this OS."""
    if os.name == "nt":
        import msvcrt

        return msvcrt
    import fcntl

    return fcntl


def _lock_primitive_name() -> str:
    return "locking" if os.name == "nt" else "flock"


_POSIX_FLOCK = pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX-only: fcntl.flock does not exist on Windows",
)


class _FakeOs:
    """Proxy for the module-level ``os`` with an overridden ``name``.

    Patching ``mod.os.name`` directly mutates the real ``os`` module
    process-wide, which breaks ``pathlib`` (and therefore pytest's own
    failure reporting) for every other test in the run.
    """

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def __getattr__(self, item):
        return getattr(os, item)


def _set_platform(monkeypatch, name: str) -> None:
    monkeypatch.setattr(mod, "os", _FakeOs(name))


def _record_sleeps(monkeypatch) -> list[float]:
    """Replace ``time.sleep`` with a recorder and return the call log."""
    sleeps: list[float] = []

    def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(mod.time, "sleep", _fake_sleep)
    return sleeps


def _patch_rename(monkeypatch, failing_pairs):
    """Make ``Path.rename`` raise OSError for the listed path pairs."""
    real_rename = Path.rename
    normalized = {
        (os.fspath(source), os.fspath(target))
        for source, target in failing_pairs
    }

    def fake_rename(self, target):
        if (os.fspath(self), os.fspath(target)) in normalized:
            raise OSError(errno.EACCES, "rename blocked")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", fake_rename)
    return normalized


def _patch_rmtree(monkeypatch, failing_paths):
    """Make ``shutil.rmtree`` raise OSError for the listed paths."""
    real_rmtree = mod.shutil.rmtree
    failing = {os.fspath(item) for item in failing_paths}

    def fake_rmtree(path, *args, **kwargs):
        if os.fspath(path) in failing:
            raise OSError(errno.EACCES, "rmtree blocked")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(mod.shutil, "rmtree", fake_rmtree)


# --------------------------------------------------------------------- #
# _restore_lock_timeout_seconds / _raise_restore_lock_timeout
# --------------------------------------------------------------------- #


def test_lock_timeout_defaults_without_environment(monkeypatch) -> None:
    monkeypatch.delenv(_LOCK_ENV, raising=False)

    assert mod._restore_lock_timeout_seconds() == mod._LOCK_TIMEOUT_SECONDS


def test_lock_timeout_defaults_on_unparsable_value(monkeypatch) -> None:
    monkeypatch.setenv(_LOCK_ENV, "not-a-number")

    assert mod._restore_lock_timeout_seconds() == mod._LOCK_TIMEOUT_SECONDS


def test_lock_timeout_defaults_on_empty_value(monkeypatch) -> None:
    monkeypatch.setenv(_LOCK_ENV, "")

    assert mod._restore_lock_timeout_seconds() == mod._LOCK_TIMEOUT_SECONDS


def test_lock_timeout_honours_environment(monkeypatch) -> None:
    monkeypatch.setenv(_LOCK_ENV, "42.5")

    assert mod._restore_lock_timeout_seconds() == 42.5


@pytest.mark.parametrize("raw", ["0", "-5", "0.25"])
def test_lock_timeout_is_clamped_to_one_second(raw, monkeypatch) -> None:
    monkeypatch.setenv(_LOCK_ENV, raw)

    assert mod._restore_lock_timeout_seconds() == 1.0


def test_raise_restore_lock_timeout_names_path_and_env(monkeypatch) -> None:
    monkeypatch.setenv(_LOCK_ENV, "7.5")

    with pytest.raises(TimeoutError) as excinfo:
        mod._raise_restore_lock_timeout(Path("/tmp/some.lock"))

    message = str(excinfo.value)
    assert "/tmp/some.lock" in message
    assert "7.5s" in message
    assert _LOCK_ENV in message
    assert "Another restore or startup cleanup may still be running" in (
        message
    )


# --------------------------------------------------------------------- #
# restore_process_lock / _acquire_file_lock / _release_file_lock
# --------------------------------------------------------------------- #


@_POSIX_FLOCK
def test_restore_process_lock_creates_and_releases_the_lock_file(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "working")

    import fcntl

    with mod.restore_process_lock():
        lock_file = tmp_path / "working" / ".qwenpaw_restore.lock"
        assert lock_file.exists()
        # Re-entering from another process handle must block, proving the
        # lock is really held for the duration of the body.
        with open(lock_file, "a+b") as probe:
            with pytest.raises(BlockingIOError):
                fcntl.flock(
                    probe.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )

    with open(lock_file, "a+b") as probe:
        fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(probe.fileno(), fcntl.LOCK_UN)


@_POSIX_FLOCK
def test_acquire_file_lock_retries_while_contended(
    tmp_path,
    monkeypatch,
) -> None:
    lock_path = tmp_path / "restore.lock"
    import fcntl

    real_flock = fcntl.flock
    attempts: list[int] = []

    def _contended_once(fd, operation):
        attempts.append(1)
        if len(attempts) == 1:
            raise BlockingIOError(errno.EWOULDBLOCK, "held by another")
        return real_flock(fd, operation)

    monkeypatch.setattr(fcntl, "flock", _contended_once)
    sleeps = _record_sleeps(monkeypatch)
    monkeypatch.setenv(_LOCK_ENV, "5")

    with open(lock_path, "a+b") as handle:
        mod._acquire_file_lock(handle, lock_path)
        acquire_attempts = len(attempts)

    # One contended attempt plus the successful retry.
    assert acquire_attempts == 2
    assert sleeps == [mod._LOCK_RETRY_INTERVAL_SECONDS]


@_POSIX_FLOCK
def test_acquire_file_lock_times_out_when_never_available(
    tmp_path,
    monkeypatch,
) -> None:
    lock_path = tmp_path / "restore.lock"
    import fcntl

    def _always_contended(fd, operation):
        raise BlockingIOError(errno.EWOULDBLOCK, "held by another")

    monkeypatch.setattr(fcntl, "flock", _always_contended)
    sleeps = _record_sleeps(monkeypatch)
    monkeypatch.setenv(_LOCK_ENV, "1")

    clock = iter([0.0, 0.4, 0.9, 5.0])
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(clock))

    with open(lock_path, "a+b") as handle:
        with pytest.raises(TimeoutError) as excinfo:
            mod._acquire_file_lock(handle, lock_path)

    assert str(lock_path) in str(excinfo.value)
    # deadline = 0.0 + 1.0; the loop ran while the clock read 0.4 and 0.9,
    # then the 5.0 check ended it without another attempt.
    assert sleeps == [mod._LOCK_RETRY_INTERVAL_SECONDS] * 2


@_POSIX_FLOCK
def test_release_file_lock_unlocks_the_region(
    tmp_path,
    monkeypatch,
) -> None:
    lock_path = tmp_path / "restore.lock"
    import fcntl

    real_flock = fcntl.flock
    released: list[int] = []

    def _tracking(fd, operation):
        released.append(operation)
        return real_flock(fd, operation)

    monkeypatch.setattr(fcntl, "flock", _tracking)

    with open(lock_path, "a+b") as handle:
        real_flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        mod._release_file_lock(handle)

    assert released == [fcntl.LOCK_UN]


@_POSIX_FLOCK
def test_release_file_lock_propagates_oserror(
    tmp_path,
    monkeypatch,
) -> None:
    """Unlike fork_project._lock_file_release, this helper has no handler.

    The observable contract is therefore that an OS failure surfaces to
    the caller instead of being swallowed.
    """
    lock_path = tmp_path / "restore.lock"
    import fcntl

    def _boom(fd, operation):
        raise OSError(errno.EBADF, "bad file descriptor")

    monkeypatch.setattr(fcntl, "flock", _boom)

    with open(lock_path, "a+b") as handle:
        with pytest.raises(OSError, match="bad file descriptor"):
            mod._release_file_lock(handle)


# --------------------------------------------------------------------- #
# _dedupe_paths / _startup_restore_targets
# --------------------------------------------------------------------- #


def test_dedupe_paths_collapses_equivalent_paths(tmp_path) -> None:
    first = tmp_path / "a"
    nested = tmp_path / "a" / "inner"
    nested.mkdir(parents=True)
    via_dotdot = tmp_path / "a" / "inner" / ".."

    result = mod._dedupe_paths([first, nested, via_dotdot, first])

    assert result == [first, nested]


def test_dedupe_paths_falls_back_to_absolute_on_error(
    tmp_path,
    monkeypatch,
) -> None:
    first = tmp_path / "a"
    broken = tmp_path / "broken"

    def _exploding_resolve(self):
        if os.fspath(self) == os.fspath(broken):
            raise OSError(errno.ELOOP, "too many levels of symbolic links")
        return Path(os.path.realpath(os.fspath(self)))

    monkeypatch.setattr(Path, "resolve", _exploding_resolve)

    result = mod._dedupe_paths([first, broken, broken])

    assert result == [first, broken]


def test_startup_restore_targets_covers_skill_pool_and_workspaces(
    monkeypatch,
    tmp_path,
) -> None:
    profiles = {
        "a": SimpleNamespace(workspace_dir=str(tmp_path / "ws-a")),
        "b": SimpleNamespace(workspace_dir=str(tmp_path / "ws-b")),
        "dup": SimpleNamespace(workspace_dir=str(tmp_path / "ws-a")),
    }
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "working",
    )
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "config.json",
    )
    monkeypatch.setattr(
        "qwenpaw.config.load_config",
        lambda _path: SimpleNamespace(
            agents=SimpleNamespace(profiles=profiles),
        ),
    )

    targets = mod._startup_restore_targets()

    assert targets[0] == tmp_path / "working" / "skill_pool"
    assert targets[1:] == [tmp_path / "ws-a", tmp_path / "ws-b"]


def test_startup_restore_targets_expands_user_home(monkeypatch) -> None:
    monkeypatch.setenv("HOME", "/tmp/home-under-test")
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", Path("/tmp/working"))
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: Path("/tmp/config.json"),
    )
    monkeypatch.setattr(
        "qwenpaw.config.load_config",
        lambda _path: SimpleNamespace(
            agents=SimpleNamespace(
                profiles={
                    "a": SimpleNamespace(workspace_dir="~/agents/a"),
                },
            ),
        ),
    )

    targets = mod._startup_restore_targets()

    assert targets == [
        Path("/tmp/working/skill_pool"),
        Path("/tmp/home-under-test/agents/a"),
    ]


# --------------------------------------------------------------------- #
# _cleanup_stale_restore_artifacts_locked
# --------------------------------------------------------------------- #


def test_cleanup_keeps_old_artifact_when_recovery_rename_fails(
    tmp_path,
    monkeypatch,
) -> None:
    base = tmp_path / "secrets"
    old = tmp_path / "secrets.restore_old"
    old.mkdir()
    (old / "precious.txt").write_text("keep me", encoding="utf-8")
    stale = tmp_path / "secrets.restore_tmp"
    stale.mkdir()
    _patch_rename(monkeypatch, [(old, base)])

    mod._cleanup_stale_restore_artifacts_locked(base)

    # Abort without touching anything: keeping the data is the priority.
    assert _snapshot(old) == {"precious.txt": "keep me"}
    assert stale.exists()
    assert not base.exists()


def test_cleanup_recovers_old_artifact_when_base_is_missing(tmp_path) -> None:
    base = tmp_path / "secrets"
    old = tmp_path / "secrets.restore_old"
    old.mkdir()
    (old / "recovered.txt").write_text("old", encoding="utf-8")

    mod._cleanup_stale_restore_artifacts_locked(base)

    assert _snapshot(base) == {"recovered.txt": "old"}
    assert not old.exists()


def test_cleanup_survives_failed_tmp_removal(tmp_path, monkeypatch) -> None:
    base = tmp_path / "secrets"
    base.mkdir()
    (base / "current.txt").write_text("live", encoding="utf-8")
    stale = tmp_path / "secrets.restore_tmp"
    stale.mkdir()
    (stale / "partial.txt").write_text("partial", encoding="utf-8")
    _patch_rmtree(monkeypatch, [stale])

    mod._cleanup_stale_restore_artifacts_locked(base)

    assert stale.exists()
    assert _snapshot(base) == {"current.txt": "live"}


def test_cleanup_survives_failed_old_removal(tmp_path, monkeypatch) -> None:
    base = tmp_path / "secrets"
    base.mkdir()
    old = tmp_path / "secrets.restore_old"
    old.mkdir()
    (old / "old.txt").write_text("old", encoding="utf-8")
    _patch_rmtree(monkeypatch, [old])

    mod._cleanup_stale_restore_artifacts_locked(base)

    assert old.exists()
    assert base.exists()


def test_cleanup_removes_both_stale_artifacts(tmp_path) -> None:
    base = tmp_path / "secrets"
    base.mkdir()
    stale_tmp = tmp_path / "secrets.restore_tmp"
    stale_tmp.mkdir()
    (stale_tmp / "partial.txt").write_text("partial", encoding="utf-8")
    stale_old = tmp_path / "secrets.restore_old"
    stale_old.mkdir()
    (stale_old / "old.txt").write_text("old", encoding="utf-8")

    mod._cleanup_stale_restore_artifacts_locked(base)

    assert not stale_tmp.exists()
    assert not stale_old.exists()
    assert base.exists()


def test_cleanup_stale_restore_artifacts_holds_the_per_path_lock(
    tmp_path,
    monkeypatch,
) -> None:
    base = tmp_path / "secrets"
    base.mkdir()
    held: list[bool] = []
    real_lock = mod._lock_for(base)

    def _locked_cleanup(_base_dir):
        held.append(real_lock.locked())

    monkeypatch.setattr(
        mod,
        "_cleanup_stale_restore_artifacts_locked",
        _locked_cleanup,
    )

    mod.cleanup_stale_restore_artifacts(base)

    assert held == [True]
    assert not real_lock.locked()


# --------------------------------------------------------------------- #
# _extract_zip_to
# --------------------------------------------------------------------- #


def test_extract_zip_to_skips_zip_slip_entries(tmp_path, caplog) -> None:
    base = tmp_path / "data"
    base.mkdir()
    staging = tmp_path / "staging"
    staging.mkdir()
    archive = _zip(
        {
            "legit.txt": "ok",
            "../escaped.txt": "outside",
        },
    )

    mod._extract_zip_to(archive, "", staging, base)

    assert _snapshot(staging) == {"legit.txt": "ok"}
    assert not (tmp_path / "escaped.txt").exists()
    assert any(
        "Skipping suspicious path in backup" in record.getMessage()
        for record in caplog.records
    )


def test_extract_zip_to_skips_dirs_and_other_prefixes(tmp_path) -> None:
    base = tmp_path / "data"
    base.mkdir()
    staging = tmp_path / "staging"
    staging.mkdir()
    archive = _zip(
        {
            "nested/": "",
            "nested/keep.txt": "kept",
            "other/drop.txt": "dropped",
        },
    )

    mod._extract_zip_to(archive, "nested/", staging, base)

    assert _snapshot(staging) == {"keep.txt": "kept"}


def test_extract_zip_to_skips_reserved_internal_names(tmp_path) -> None:
    base = tmp_path / "data"
    base.mkdir()
    staging = tmp_path / "staging"
    staging.mkdir()
    archive = _zip({OLD_CONTENT_DIR_NAME + "/payload.txt": "old"})

    mod._extract_zip_to(archive, "", staging, base)

    assert _snapshot(staging) == {}


# --------------------------------------------------------------------- #
# _swap_directories
# --------------------------------------------------------------------- #


def test_swap_directories_requires_a_staging_directory(tmp_path) -> None:
    dst = tmp_path / "secrets"

    with pytest.raises(RuntimeError, match="without a valid staging"):
        mod._swap_directories(
            dst,
            tmp_path / "secrets.restore_tmp",
            tmp_path / "secrets.restore_old",
        )

    assert not dst.exists()


def test_swap_directories_rolls_back_when_commit_rename_fails(
    tmp_path,
    monkeypatch,
) -> None:
    # Phase 2 already moved the original away, so dst does not exist yet.
    dst = tmp_path / "secrets"
    staging = tmp_path / "secrets.restore_tmp"
    staging.mkdir()
    (staging / "new.txt").write_text("new", encoding="utf-8")
    old = tmp_path / "secrets.restore_old"
    old.mkdir()
    (old / "original.txt").write_text("original", encoding="utf-8")
    monkeypatch.setattr(
        mod,
        "prepare_destination_for_swap",
        lambda *_args: SwapPreparation.ORIGINAL_MOVED_TO_OLD,
    )
    _patch_rename(monkeypatch, [(staging, dst)])

    with pytest.raises(OSError):
        mod._swap_directories(dst, staging, old)

    # The rollback put the original data back so dst is never absent.
    assert _snapshot(dst) == {"original.txt": "original"}
    assert not old.exists()
    assert _snapshot(staging) == {"new.txt": "new"}


def test_swap_directories_reports_failed_rollback(
    tmp_path,
    monkeypatch,
) -> None:
    dst = tmp_path / "secrets"
    staging = tmp_path / "secrets.restore_tmp"
    staging.mkdir()
    old = tmp_path / "secrets.restore_old"
    old.mkdir()
    (old / "original.txt").write_text("original", encoding="utf-8")
    monkeypatch.setattr(
        mod,
        "prepare_destination_for_swap",
        lambda *_args: SwapPreparation.ORIGINAL_MOVED_TO_OLD,
    )
    _patch_rename(
        monkeypatch,
        [(staging, dst), (old, dst)],
    )

    with pytest.raises(OSError):
        mod._swap_directories(dst, staging, old)

    # The original data is still safe, just not back in place yet.
    assert _snapshot(old) == {"original.txt": "original"}
    assert not dst.exists()


def test_swap_directories_propagates_error_without_old_dir(
    tmp_path,
    monkeypatch,
) -> None:
    dst = tmp_path / "secrets"
    staging = tmp_path / "secrets.restore_tmp"
    staging.mkdir()
    old = tmp_path / "secrets.restore_old"
    monkeypatch.setattr(
        mod,
        "prepare_destination_for_swap",
        lambda *_args: SwapPreparation.ORIGINAL_MOVED_TO_OLD,
    )
    _patch_rename(monkeypatch, [(staging, dst)])

    with pytest.raises(OSError):
        mod._swap_directories(dst, staging, old)

    assert not dst.exists()


def test_swap_directories_returns_after_content_swap(
    tmp_path,
    monkeypatch,
) -> None:
    dst = tmp_path / "secrets"
    dst.mkdir()
    staging = tmp_path / "secrets.restore_tmp"
    staging.mkdir()
    old = tmp_path / "secrets.restore_old"
    renames: list[str] = []
    monkeypatch.setattr(
        mod,
        "prepare_destination_for_swap",
        lambda *_args: SwapPreparation.CONTENT_SWAP_COMPLETED,
    )
    real_rename = Path.rename

    def _tracking_rename(self, target):
        renames.append(f"{os.fspath(self)}->{os.fspath(target)}")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", _tracking_rename)

    mod._swap_directories(dst, staging, old)

    assert renames == []
    assert staging.exists()


# --------------------------------------------------------------------- #
# extract_to_tmp / discard_tmp
# --------------------------------------------------------------------- #


def test_extract_to_tmp_replaces_an_existing_staging_dir(tmp_path) -> None:
    dst = tmp_path / "secrets"
    dst.mkdir()
    staging = tmp_path / "secrets.restore_tmp"
    staging.mkdir()
    (staging / "stale.txt").write_text("stale", encoding="utf-8")

    result = mod.extract_to_tmp(
        _zip({"fresh.txt": "fresh"}),
        "",
        dst,
    )

    assert result == staging
    assert _snapshot(staging) == {"fresh.txt": "fresh"}


def test_extract_to_tmp_applies_dir_mode(tmp_path) -> None:
    dst = tmp_path / "secrets"
    dst.mkdir()

    staging = mod.extract_to_tmp(_zip({"a.txt": "a"}), "", dst, dir_mode=0o700)

    if os.name != "nt":
        # Windows ignores the mode bits passed to mkdir.
        assert (staging.stat().st_mode & 0o777) == 0o700


def test_discard_tmp_removes_staging(tmp_path) -> None:
    dst = tmp_path / "secrets"
    dst.mkdir()
    staging = tmp_path / "secrets.restore_tmp"
    staging.mkdir()
    (staging / "a.txt").write_text("a", encoding="utf-8")

    mod.discard_tmp(dst)

    assert not staging.exists()
    assert dst.exists()


def test_discard_tmp_is_a_noop_without_staging(tmp_path) -> None:
    dst = tmp_path / "secrets"
    dst.mkdir()

    mod.discard_tmp(dst)

    assert dst.exists()


def test_discard_tmp_swallows_removal_errors(tmp_path, monkeypatch) -> None:
    dst = tmp_path / "secrets"
    dst.mkdir()
    staging = tmp_path / "secrets.restore_tmp"
    staging.mkdir()
    _patch_rmtree(monkeypatch, [staging])

    mod.discard_tmp(dst)

    assert staging.exists()


def test_commit_tmp_raises_without_staging(tmp_path) -> None:
    dst = tmp_path / "secrets"
    dst.mkdir()

    with pytest.raises(RuntimeError, match="without a valid staging"):
        mod.commit_tmp(dst)


# --------------------------------------------------------------------- #
# assert_directory_renamable / _unique_probe_path
# --------------------------------------------------------------------- #


def test_assert_directory_renamable_is_a_noop_off_windows(
    tmp_path,
    monkeypatch,
) -> None:
    target = tmp_path / "dst"
    target.mkdir()
    _set_platform(monkeypatch, "posix")

    mod.assert_directory_renamable(target)

    assert _snapshot(target) == {}
    assert not list(tmp_path.glob("*restore_probe*"))


def test_assert_directory_renamable_ignores_missing_and_files(
    tmp_path,
    monkeypatch,
) -> None:
    _set_platform(monkeypatch, "nt")
    regular = tmp_path / "file.txt"
    regular.write_text("x", encoding="utf-8")

    mod.assert_directory_renamable(tmp_path / "absent")
    mod.assert_directory_renamable(regular)

    assert regular.read_text(encoding="utf-8") == "x"


def test_assert_directory_renamable_probe_round_trip(
    tmp_path,
    monkeypatch,
) -> None:
    target = tmp_path / "dst"
    target.mkdir()
    (target / "a.txt").write_text("a", encoding="utf-8")
    _set_platform(monkeypatch, "nt")

    mod.assert_directory_renamable(target)

    assert _snapshot(target) == {"a.txt": "a"}
    assert not list(tmp_path.glob("*restore_probe*"))


def test_assert_directory_renamable_restores_after_failed_probe(
    tmp_path,
    monkeypatch,
) -> None:
    target = tmp_path / "dst"
    target.mkdir()
    (target / "a.txt").write_text("a", encoding="utf-8")
    _set_platform(monkeypatch, "nt")
    probe_holder: dict[str, Path] = {}
    real_probe = mod._unique_probe_path

    def _remember_probe(path):
        probe = real_probe(path)
        probe_holder["path"] = probe
        return probe

    monkeypatch.setattr(mod, "_unique_probe_path", _remember_probe)
    real_rename = Path.rename
    calls: list[tuple[str, str]] = []

    def _failing_second_rename(self, other):
        pair = (os.fspath(self), os.fspath(other))
        calls.append(pair)
        if len(calls) == 2:
            raise OSError(errno.EACCES, "handle still open")
        return real_rename(self, other)

    monkeypatch.setattr(Path, "rename", _failing_second_rename)

    with pytest.raises(OSError):
        mod.assert_directory_renamable(target)

    assert _snapshot(target) == {"a.txt": "a"}
    assert not probe_holder["path"].exists()


def test_assert_directory_renamable_logs_unrecoverable_probe(
    tmp_path,
    monkeypatch,
    caplog,
) -> None:
    target = tmp_path / "dst"
    target.mkdir()
    (target / "a.txt").write_text("a", encoding="utf-8")
    _set_platform(monkeypatch, "nt")
    probe_holder: dict[str, Path] = {}
    real_probe = mod._unique_probe_path

    def _remember_probe(path):
        probe = real_probe(path)
        probe_holder["path"] = probe
        return probe

    monkeypatch.setattr(mod, "_unique_probe_path", _remember_probe)
    real_rename = Path.rename
    calls: list[int] = []

    def _always_fail_after_first(self, other):
        calls.append(1)
        if len(calls) > 1:
            raise OSError(errno.EACCES, "handle still open")
        return real_rename(self, other)

    monkeypatch.setattr(Path, "rename", _always_fail_after_first)

    with caplog.at_level("ERROR"):
        with pytest.raises(OSError):
            mod.assert_directory_renamable(target)

    assert any(
        "Failed to restore" in record.getMessage() for record in caplog.records
    )
    assert _snapshot(probe_holder["path"]) == {"a.txt": "a"}


def test_unique_probe_path_returns_first_free_slot(tmp_path) -> None:
    target = tmp_path / "dst"

    probe = mod._unique_probe_path(target)

    assert probe.parent == tmp_path
    assert probe.name.startswith("dst.restore_probe_")
    assert str(os.getpid()) in probe.name
    assert str(threading.get_ident()) in probe.name
    assert not probe.exists()


def test_unique_probe_path_skips_taken_slots(tmp_path) -> None:
    target = tmp_path / "dst"
    first = mod._unique_probe_path(target)
    first.touch()
    second = mod._unique_probe_path(target)
    second.touch()

    probe = mod._unique_probe_path(target)

    assert probe.name == f"{first.name}_2"
    assert second.name == f"{first.name}_1"
    assert probe != first
    assert probe != second


def test_unique_probe_path_gives_up_after_100_slots(tmp_path) -> None:
    """Every candidate slot taken => no probe path can be reserved.

    The 100 slots are occupied for real instead of patching ``Path.exists``
    globally, which would also break tmp_path teardown and pytest's own
    failure reporting.
    """
    target = tmp_path / "dst"
    taken = []
    for _ in range(100):
        candidate = mod._unique_probe_path(target)
        candidate.touch()
        taken.append(candidate)

    assert len(set(taken)) == 100

    with pytest.raises(RuntimeError, match="restore probe path"):
        mod._unique_probe_path(target)


# --------------------------------------------------------------------- #
# find_busy_restore_paths / _find_busy_descendants
# --------------------------------------------------------------------- #


def test_find_busy_restore_paths_is_empty_off_windows(
    tmp_path,
    monkeypatch,
) -> None:
    target = tmp_path / "dst"
    target.mkdir()
    _set_platform(monkeypatch, "posix")

    assert mod.find_busy_restore_paths(target) == []


def test_find_busy_restore_paths_requires_a_directory(
    tmp_path,
    monkeypatch,
) -> None:
    _set_platform(monkeypatch, "nt")
    regular = tmp_path / "file.txt"
    regular.write_text("x", encoding="utf-8")

    assert mod.find_busy_restore_paths(tmp_path / "absent") == []
    assert mod.find_busy_restore_paths(regular) == []


def test_find_busy_restore_paths_is_empty_when_renamable(
    tmp_path,
    monkeypatch,
) -> None:
    target = tmp_path / "dst"
    target.mkdir()
    _set_platform(monkeypatch, "nt")

    assert mod.find_busy_restore_paths(target) == []


def test_find_busy_restore_paths_narrows_to_the_deepest_busy_child(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path / "workspace"
    busy = root / "browser"
    nested = busy / "user_data"
    free = root / "files"
    nested.mkdir(parents=True)
    free.mkdir(parents=True)
    _set_platform(monkeypatch, "nt")

    def fake_assert(path: Path) -> None:
        if path in {root, busy, nested}:
            raise PermissionError("locked")

    monkeypatch.setattr(mod, "assert_directory_renamable", fake_assert)

    assert mod.find_busy_restore_paths(root) == [nested]


def test_find_busy_restore_paths_stops_at_the_busy_ancestor(
    tmp_path,
    monkeypatch,
) -> None:
    """A renamable grandchild means the ancestor itself holds the handle."""
    root = tmp_path / "workspace"
    busy = root / "browser"
    nested = busy / "user_data"
    nested.mkdir(parents=True)
    _set_platform(monkeypatch, "nt")

    def fake_assert(path: Path) -> None:
        if path in {root, busy}:
            raise PermissionError("locked")

    monkeypatch.setattr(mod, "assert_directory_renamable", fake_assert)

    assert mod.find_busy_restore_paths(root) == [busy]


def test_find_busy_descendants_reports_root_when_listing_fails(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path / "dst"
    root.mkdir()

    def _boom(self):
        raise OSError(errno.EACCES, "cannot list")

    monkeypatch.setattr(Path, "iterdir", _boom)

    assert mod._find_busy_descendants(root) == [root]


def test_find_busy_descendants_skips_regular_files(tmp_path) -> None:
    root = tmp_path / "dst"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")

    assert mod._find_busy_descendants(root) == [root]


def test_find_busy_descendants_reports_child_that_cannot_be_stated(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path / "dst"
    child = root / "child"
    child.mkdir(parents=True)
    real_is_dir = Path.is_dir

    def _fake_is_dir(self):
        if os.fspath(self) == os.fspath(child):
            raise OSError(errno.EACCES, "cannot stat")
        return real_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", _fake_is_dir)

    assert mod._find_busy_descendants(root) == [child]


def test_find_busy_descendants_recurses_into_busy_child(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path / "dst"
    busy = root / "a"
    deep = busy / "b"
    deep.mkdir(parents=True)

    def fake_assert(path: Path) -> None:
        if path in {root, busy, deep}:
            raise PermissionError("locked")

    monkeypatch.setattr(mod, "assert_directory_renamable", fake_assert)

    assert mod._find_busy_descendants(root) == [deep]


def test_find_busy_descendants_collapses_to_busy_ancestor(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path / "dst"
    busy = root / "a"
    free = busy / "b"
    free.mkdir(parents=True)

    def fake_assert(path: Path) -> None:
        if path in {root, busy}:
            raise PermissionError("locked")

    monkeypatch.setattr(mod, "assert_directory_renamable", fake_assert)

    assert mod._find_busy_descendants(root) == [busy]


def test_find_busy_descendants_returns_root_when_no_child_is_busy(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path / "dst"
    child = root / "a"
    child.mkdir(parents=True)

    def fake_assert(path: Path) -> None:
        if path is root or os.fspath(path) == os.fspath(root):
            raise PermissionError("locked")

    monkeypatch.setattr(mod, "assert_directory_renamable", fake_assert)

    assert mod._find_busy_descendants(root) == [root]


def test_lock_for_returns_the_same_lock_per_destination(tmp_path) -> None:
    first = tmp_path / "dst"
    alias = tmp_path / "dst" / "inner" / ".."

    assert mod._lock_for(first) is mod._lock_for(alias)
    assert mod._lock_for(first) is not mod._lock_for(tmp_path / "other")
