# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Regression tests for the Linux Landlock capability probe.

Containers do not mount securityfs, so ``/sys/kernel/security/lsm`` is
absent there even when the kernel LSM works.  Treating that as
"unsupported" made Code Mode ``run_code`` fail closed with "Sandbox is
enabled but unavailable".
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

import pytest

from qwenpaw.sandbox import SandboxMode
from qwenpaw.sandbox import config as sandbox_config
from qwenpaw.sandbox.config import _probe_linux_landlock

_LSM_PATH = "/sys/kernel/security/lsm"


class _FakeOS:
    """Stand-in for ``os`` so ``uname()`` works on non-POSIX hosts."""

    def __init__(self, release: str | None) -> None:
        self._release = release

    def uname(self):
        if self._release is None:
            raise AttributeError("uname")
        return SimpleNamespace(release=self._release)


def _patch_kernel(release: str | None):
    """Replace ``os`` inside the probe module with a fake exposing uname()."""
    return patch.object(sandbox_config, "os", _FakeOS(release))


def _patch_arch(machine: str):
    """Patch ``platform.machine()`` (imported lazily inside the probe)."""
    return patch("platform.machine", return_value=machine)


def _patch_libc(syscall_result: int, errno: int = 0):
    """Patch ``ctypes.CDLL`` so ``syscall()`` returns a fixed ABI version."""
    libc = MagicMock()
    libc.syscall.return_value = syscall_result
    return (
        patch("ctypes.CDLL", return_value=libc),
        patch("ctypes.util.find_library", return_value="libc.so.6"),
        patch("ctypes.get_errno", return_value=errno),
    )


def _run_probe(
    release: str,
    machine: str,
    syscall_result: int,
    errno: int = 0,
):
    """Invoke the probe with the given platform parameters patched."""
    cdll, find_library, get_errno = _patch_libc(syscall_result, errno)
    with (
        _patch_kernel(release),
        _patch_arch(machine),
        cdll,
        find_library,
        get_errno,
    ):
        return _probe_linux_landlock()


def _lsm_unreadable():
    """Make every attempt to read the LSM list raise OSError."""
    return patch(
        "qwenpaw.sandbox.config.open",
        side_effect=OSError(2, "No such file or directory"),
        create=True,
    )


def _lsm_contains(value: str):
    """Serve ``value`` as the contents of the LSM list."""
    return patch(
        "qwenpaw.sandbox.config.open",
        mock_open(read_data=value),
        create=True,
    )


class TestLandlockProbeWithoutSecurityfs:
    """Container case: the LSM file is absent, the kernel still supports it."""

    def test_unreadable_lsm_falls_through_to_syscall(self):
        """Regression: an absent securityfs must not mean 'unsupported'."""
        with _lsm_unreadable():
            cap = _run_probe("6.18.58.1-microsoft-standard-WSL2", "x86_64", 7)

        assert cap.supported is True
        assert cap.mode == SandboxMode.LANDLOCK
        assert cap.landlock_abi_version == 7

    def test_unreadable_lsm_logs_the_reason(self, caplog):
        """Operators need to see why the file was skipped."""
        with caplog.at_level("DEBUG", logger="qwenpaw.sandbox.config"):
            with _lsm_unreadable():
                _run_probe("6.5.0", "x86_64", 4)

        assert _LSM_PATH in caplog.text
        assert "syscall" in caplog.text

    def test_unreadable_lsm_and_syscall_unsupported_still_fails(self):
        """ENOSYS still wins: we never report a sandbox we cannot create."""
        with _lsm_unreadable():
            cap = _run_probe("6.5.0", "x86_64", -1, errno=38)

        assert cap.supported is False
        assert cap.mode == SandboxMode.NONE
        assert "errno=38" in cap.reason


class TestLandlockProbeWithReadableLsm:
    """A readable LSM list remains authoritative evidence either way."""

    def test_landlock_listed_and_syscall_ok(self):
        with _lsm_contains("capability,landlock,yama"):
            cap = _run_probe("6.5.0", "x86_64", 4)

        assert cap.supported is True
        assert cap.landlock_abi_version == 4

    def test_landlock_absent_from_list_is_not_over_permitted(self):
        """A readable list without landlock is a genuine 'no'."""
        with _lsm_contains("capability,yama"):
            cap = _run_probe("6.5.0", "x86_64", 4)

        assert cap.supported is False
        assert cap.mode == SandboxMode.NONE
        assert "Landlock not in LSM list" in cap.reason


class TestLandlockProbeEdgeCases:
    """Kernel gate and unknown architectures."""

    @pytest.mark.parametrize("release", ["5.10.0-generic", "4.19.0"])
    def test_kernel_too_old(self, release):
        with _lsm_contains("capability,landlock"):
            cap = _run_probe(release, "x86_64", 4)

        assert cap.supported is False
        assert "< 5.13" in cap.reason

    def test_unparsable_kernel_version(self):
        with _lsm_contains("capability,landlock"):
            with _patch_kernel("not-a-version"):
                cap = _probe_linux_landlock()

        assert cap.supported is False
        assert "Cannot parse kernel version" in cap.reason

    def test_uname_unavailable_is_not_a_crash(self):
        """Platforms without ``os.uname`` must degrade, not raise."""
        with _lsm_contains("capability,landlock"):
            with _patch_kernel(None):
                cap = _probe_linux_landlock()

        assert cap.supported is False
        assert "Cannot parse kernel version" in cap.reason

    def test_unknown_arch_without_lsm_is_not_guessed(self):
        """No syscall number and no LSM proof means we cannot verify."""
        with _lsm_unreadable():
            cap = _run_probe("6.5.0", "riscv64", 4)

        assert cap.supported is False
        assert cap.mode == SandboxMode.NONE
        assert "Cannot verify" in cap.reason

    def test_unknown_arch_with_lsm_still_trusted(self):
        with _lsm_contains("capability,landlock"):
            cap = _run_probe("6.5.0", "riscv64", 4)

        assert cap.supported is True
        assert cap.mode == SandboxMode.LANDLOCK
        assert "arch=riscv64" in cap.reason
