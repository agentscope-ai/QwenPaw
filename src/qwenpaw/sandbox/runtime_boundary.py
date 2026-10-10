# -*- coding: utf-8 -*-
"""Verify inherited process isolation using kernel state, not env flags."""

from __future__ import annotations

import ctypes
import functools
import os
from pathlib import Path
import re
import sys


def _mount_path(value: str) -> str:
    return re.sub(
        r"\\([0-7]{3})",
        lambda match: chr(int(match.group(1), 8)),
        value,
    )


def _linux_boundary(runtime_id: str) -> bool:
    """Check the private user namespace and the complete writable view."""
    mappings = (
        Path("/proc/self/uid_map").read_text(encoding="utf-8").splitlines()
    )
    if len(mappings) != 1 or mappings[0].split()[-1] != "1":
        return False
    status = Path("/proc/self/status").read_text(encoding="utf-8").splitlines()
    capabilities = next(line for line in status if line.startswith("CapEff:"))
    if int(capabilities.split()[1], 16):
        return False
    mounts = {}
    for line in (
        Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    ):
        fields, filesystem = line.split(" - ", 1)
        parts = fields.split()
        mounts[_mount_path(parts[4])] = (
            _mount_path(parts[3]),
            parts[5].split(","),
            filesystem.split()[0],
        )
    root = Path(mounts["/"][0])
    if root.name != "filesystem" or root.parent.name != runtime_id:
        return False
    expected = {
        "/": str(root),
        os.environ.get("QWENPAW_WORKING_DIR", ""): str(
            root.parent / "working",
        ),
        "/secrets": str(root.parent / "secrets"),
        "/backups": str(root.parent / "backups"),
    }
    if any(
        mounts.get(path, (None,))[0] != source
        for path, source in expected.items()
    ):
        return False
    for path, (source, options, filesystem) in mounts.items():
        if "ro" in options or expected.get(path) == source:
            continue
        if filesystem in {"tmpfs", "devtmpfs", "proc", "devpts"} and any(
            path == base or path.startswith(f"{base}/")
            for base in ("/tmp", "/dev", "/proc")
        ):
            continue
        return False
    return True


def _macos_boundary() -> bool:
    """Ask Seatbelt whether this process has an active sandbox profile."""
    library = ctypes.CDLL("/usr/lib/libsandbox.dylib")
    check = library.sandbox_check
    check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    check.restype = ctypes.c_int
    return check(os.getpid(), None, 0) == 1


def _windows_boundary() -> bool:
    """Inspect the process token for an AppContainer security boundary."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    security.OpenProcessToken.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    security.GetTokenInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    token = ctypes.c_void_p()
    if not security.OpenProcessToken(
        kernel.GetCurrentProcess(),
        0x0008,
        ctypes.byref(token),
    ):
        return False
    try:
        is_container = ctypes.c_ulong()
        returned = ctypes.c_ulong()
        # TokenIsAppContainer = 29; TOKEN_QUERY = 0x0008.
        success = security.GetTokenInformation(
            token,
            29,
            ctypes.byref(is_container),
            ctypes.sizeof(is_container),
            ctypes.byref(returned),
        )
        return bool(success and is_container.value)
    finally:
        kernel.CloseHandle(token)


@functools.lru_cache(maxsize=1)
def has_runtime_boundary(runtime_id: str) -> bool:
    """Fail closed if OS isolation cannot be established from kernel state."""
    try:
        if sys.platform == "linux":
            return _linux_boundary(runtime_id)
        if sys.platform == "darwin":
            return _macos_boundary()
        if sys.platform == "win32":
            return _windows_boundary()
    except (OSError, AttributeError, ValueError, KeyError, StopIteration):
        return False
    return False
