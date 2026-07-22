# -*- coding: utf-8 -*-
"""Windows sandbox shared utilities, base class, and unelevated sandbox.

This module serves as the canonical location for code shared across all
Windows sandbox implementations:

  - ``WindowsSandboxBase``: abstract base class for Windows sandboxes.
  - Shared ctypes structures, constants, SID/token/ACL helpers.
  - Pipe output decoding (OEM/ANSI/UTF-16LE).
  - Process helpers (shell command building, pipe I/O, Job Object).
  - ACL cleanup helpers (icacls-based removal with multi-strategy retry).

It also contains the ``WindowsUnelevatedSandbox`` implementation, which
uses a WRITE_RESTRICTED token without requiring administrator privileges.

Other Windows sandbox modules (``windows_appcontainer_sandbox.py`` and
``windows_elevated_sandbox.py``) import shared code from here.
"""

from __future__ import annotations

import asyncio
import atexit
import ctypes
import ctypes.wintypes
import hashlib
import json
import logging
import os
import random
import re
import struct
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import ExecutionResult, SandboxConfig

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Shared Constants
# ═══════════════════════════════════════════════════════════════════════════


class _WC:
    """Windows sandbox constants.

    Grouping all Win32 numeric/string constants into a single class so
    that consuming modules can ``from … import _WC`` instead of listing
    dozens of individual names.
    """

    # Violation detection regex (includes Chinese locale patterns)
    VIOLATION_RE = re.compile(
        r"Access is denied"
        r"|error 5\b"
        r"|0x80070005"
        r"|Permission denied"
        r"|拒绝访问"
        r"|权限不足"
        r"|系统无法执行"
        r"指定的程序",
        re.IGNORECASE | re.MULTILINE,
    )

    # CreateRestrictedToken flags
    DISABLE_MAX_PRIVILEGE = 0x01
    WRITE_RESTRICTED = 0x08

    # ACL / Security constants
    SE_FILE_OBJECT = 1
    DACL_SECURITY_INFORMATION = 0x00000004
    CONTAINER_INHERIT_ACE = 0x2
    OBJECT_INHERIT_ACE = 0x1
    GRANT_ACCESS = 1
    SET_ACCESS = 2
    DENY_ACCESS = 3
    TRUSTEE_IS_SID = 0
    TRUSTEE_IS_UNKNOWN = 0

    # File access masks
    FILE_GENERIC_READ = 0x00120089
    FILE_GENERIC_WRITE = 0x00120116
    FILE_GENERIC_EXECUTE = 0x001200A0
    FILE_WRITE_DATA = 0x00000002
    FILE_APPEND_DATA = 0x00000004
    FILE_WRITE_EA = 0x00000010
    FILE_WRITE_ATTRIBUTES = 0x00000100
    DELETE = 0x00010000
    FILE_DELETE_CHILD = 0x00000040
    GENERIC_ALL = 0x10000000
    GENERIC_WRITE = 0x40000000

    # Unelevated-specific write masks
    WRITE_ALLOW_MASK = (
        FILE_GENERIC_READ | FILE_GENERIC_WRITE | FILE_GENERIC_EXECUTE | DELETE
    )
    DENY_WRITE_MASK = (
        FILE_GENERIC_WRITE
        | FILE_WRITE_DATA
        | FILE_APPEND_DATA
        | FILE_WRITE_EA
        | FILE_WRITE_ATTRIBUTES
        | GENERIC_WRITE
        | DELETE
        | FILE_DELETE_CHILD
    )

    # Token information classes
    TokenGroups = 2
    TokenDefaultDacl = 6

    # SE_GROUP_LOGON_ID attribute
    SE_GROUP_LOGON_ID = 0xC0000000

    # Process creation flags
    CREATE_UNICODE_ENVIRONMENT = 0x00000400
    CREATE_NO_WINDOW = 0x08000000
    CREATE_SUSPENDED = 0x00000004
    STARTF_USESTDHANDLES = 0x00000100
    HANDLE_FLAG_INHERIT = 0x00000001

    # Job Object constants
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9

    # Wait constants
    WAIT_TIMEOUT = 0x00000102

    # Privilege constants
    SE_PRIVILEGE_ENABLED = 0x00000002
    SE_CHANGE_NOTIFY_NAME = "SeChangeNotifyPrivilege"

    # WinWorldSid type for Everyone SID
    WinWorldSid = 1

    # Shell executable name sets (for _build_shell_command_line)
    POWERSHELL_NAMES = {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}
    CMD_NAMES = {"cmd", "cmd.exe"}


# ═══════════════════════════════════════════════════════════════════════════
# Shared ctypes Structures
# ═══════════════════════════════════════════════════════════════════════════


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Sid", ctypes.c_void_p),
        ("Attributes", ctypes.wintypes.DWORD),
    ]


class _TRUSTEE_W(ctypes.Structure):
    _fields_ = [
        ("pMultipleTrustee", ctypes.c_void_p),
        ("MultipleTrusteeOperation", ctypes.c_uint32),
        ("TrusteeForm", ctypes.c_uint32),
        ("TrusteeType", ctypes.c_uint32),
        ("ptstrName", ctypes.c_void_p),
    ]


class _EXPLICIT_ACCESS_W(ctypes.Structure):
    _fields_ = [
        ("grfAccessPermissions", ctypes.c_uint32),
        ("grfAccessMode", ctypes.c_uint32),
        ("grfInheritance", ctypes.c_uint32),
        ("Trustee", _TRUSTEE_W),
    ]


class _TOKEN_DEFAULT_DACL(ctypes.Structure):
    _fields_ = [("DefaultDacl", ctypes.c_void_p)]


class _LUID(ctypes.Structure):
    _fields_ = [
        ("LowPart", ctypes.wintypes.DWORD),
        ("HighPart", ctypes.c_long),
    ]


class _LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Luid", _LUID),
        ("Attributes", ctypes.wintypes.DWORD),
    ]


class _TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [
        ("PrivilegeCount", ctypes.wintypes.DWORD),
        ("Privileges", _LUID_AND_ATTRIBUTES * 1),
    ]


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", ctypes.wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", ctypes.wintypes.BOOL),
    ]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.wintypes.DWORD),
        ("lpReserved", ctypes.c_wchar_p),
        ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p),
        ("dwX", ctypes.wintypes.DWORD),
        ("dwY", ctypes.wintypes.DWORD),
        ("dwXSize", ctypes.wintypes.DWORD),
        ("dwYSize", ctypes.wintypes.DWORD),
        ("dwXCountChars", ctypes.wintypes.DWORD),
        ("dwYCountChars", ctypes.wintypes.DWORD),
        ("dwFillAttribute", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("wShowWindow", ctypes.wintypes.WORD),
        ("cbReserved2", ctypes.wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", ctypes.wintypes.HANDLE),
        ("hStdOutput", ctypes.wintypes.HANDLE),
        ("hStdError", ctypes.wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", ctypes.wintypes.HANDLE),
        ("hThread", ctypes.wintypes.HANDLE),
        ("dwProcessId", ctypes.wintypes.DWORD),
        ("dwThreadId", ctypes.wintypes.DWORD),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.wintypes.DWORD),
        ("SchedulingClass", ctypes.wintypes.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Shared: Pipe Output Decoding
# ═══════════════════════════════════════════════════════════════════════════

_cached_oem_encoding: Optional[str] = None
_cached_ansi_encoding: Optional[str] = None


def _get_system_ansi_encoding() -> str:
    """Returns the Python codec name for the system ANSI code page (GetACP)."""
    global _cached_ansi_encoding
    if _cached_ansi_encoding is not None:
        return _cached_ansi_encoding
    try:
        acp = ctypes.windll.kernel32.GetACP()
        _cached_ansi_encoding = f"cp{acp}"
    except (AttributeError, OSError):
        _cached_ansi_encoding = "utf-8"
    return _cached_ansi_encoding


def _get_system_oem_encoding() -> str:
    """Returns the codec name for the system OEM code page."""
    global _cached_oem_encoding
    if _cached_oem_encoding is not None:
        return _cached_oem_encoding
    try:
        oem_cp = ctypes.windll.kernel32.GetOEMCP()
        _cached_oem_encoding = f"cp{oem_cp}"
    except (AttributeError, OSError):
        _cached_oem_encoding = _get_system_ansi_encoding()
    return _cached_oem_encoding


def _try_decode_utf16le(raw: bytes) -> Optional[str]:
    """Attempts to decode raw bytes as UTF-16LE via BOM or heuristic."""
    if len(raw) < 2:
        return None
    if raw[:2] == b"\xff\xfe":
        try:
            return raw.decode("utf-16-le")
        except (UnicodeDecodeError, ValueError):
            return None
    if len(raw) >= 4:
        sample = raw[: min(64, len(raw))]
        null_at_odd = sum(
            1 for i in range(1, len(sample), 2) if sample[i] == 0
        )
        total_odd = len(sample) // 2
        if total_odd > 0 and null_at_odd > total_odd * 0.25:
            try:
                return raw.decode("utf-16-le")
            except (UnicodeDecodeError, ValueError):
                pass
    return None


def _decode_pipe_output(raw: bytes) -> str:
    """Decodes raw pipe output using a multi-codec fallback strategy.

    Tries UTF-16LE (BOM + heuristic), system OEM code page, system ANSI
    code page, then UTF-8 with replacement characters.
    """
    if not raw:
        return ""
    result = _try_decode_utf16le(raw)
    if result is not None:
        return result
    for enc in (
        _get_system_oem_encoding(),
        _get_system_ansi_encoding(),
        "utf-8",
    ):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            pass
    return raw.decode("utf-8", errors="replace")


# ═══════════════════════════════════════════════════════════════════════════
# Shared: Platform Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _get_python_install_dir() -> Optional[str]:
    """Returns the Python installation root directory, or None."""
    import sys as _sys

    exe = _sys.executable
    if not exe or not os.path.isfile(exe):
        return None
    install_dir = os.path.dirname(os.path.abspath(exe))
    if os.path.basename(install_dir).lower() == "scripts":
        install_dir = os.path.dirname(install_dir)
    return install_dir


def _is_admin() -> bool:
    """Returns True if the current process has administrator privileges."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Module-local DLL Accessors
# ═══════════════════════════════════════════════════════════════════════════

_dll_kernel32: Optional[Any] = None
_dll_advapi32: Optional[Any] = None


def _get_kernel32():
    global _dll_kernel32
    if _dll_kernel32 is None:
        _dll_kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
        _dll_kernel32.LocalFree.argtypes = [ctypes.wintypes.HLOCAL]
        _dll_kernel32.LocalFree.restype = ctypes.wintypes.HLOCAL
        _dll_kernel32.GetCurrentProcess.argtypes = []
        _dll_kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
        _dll_kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
        _dll_kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
        _dll_kernel32.WaitForSingleObject.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
        ]
        _dll_kernel32.WaitForSingleObject.restype = ctypes.wintypes.DWORD
        _dll_kernel32.GetExitCodeProcess.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.POINTER(ctypes.wintypes.DWORD),
        ]
        _dll_kernel32.GetExitCodeProcess.restype = ctypes.wintypes.BOOL
        _dll_kernel32.ReadFile.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
            ctypes.POINTER(ctypes.wintypes.DWORD),
            ctypes.c_void_p,
        ]
        _dll_kernel32.ReadFile.restype = ctypes.wintypes.BOOL
        _dll_kernel32.CreatePipe.argtypes = [
            ctypes.POINTER(ctypes.wintypes.HANDLE),
            ctypes.POINTER(ctypes.wintypes.HANDLE),
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
        ]
        _dll_kernel32.CreatePipe.restype = ctypes.wintypes.BOOL
        _dll_kernel32.SetHandleInformation.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
        ]
        _dll_kernel32.SetHandleInformation.restype = ctypes.wintypes.BOOL
        _dll_kernel32.CreateJobObjectW.argtypes = [
            ctypes.c_void_p,
            ctypes.wintypes.LPCWSTR,
        ]
        _dll_kernel32.CreateJobObjectW.restype = ctypes.wintypes.HANDLE
        _dll_kernel32.AssignProcessToJobObject.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.HANDLE,
        ]
        _dll_kernel32.AssignProcessToJobObject.restype = ctypes.wintypes.BOOL
        _dll_kernel32.TerminateJobObject.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.c_uint,
        ]
        _dll_kernel32.TerminateJobObject.restype = ctypes.wintypes.BOOL
        _dll_kernel32.SetInformationJobObject.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
        ]
        _dll_kernel32.SetInformationJobObject.restype = ctypes.wintypes.BOOL
        _dll_kernel32.TerminateProcess.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.c_uint,
        ]
        _dll_kernel32.TerminateProcess.restype = ctypes.wintypes.BOOL
        _dll_kernel32.OpenProcess.argtypes = [
            ctypes.wintypes.DWORD,
            ctypes.wintypes.BOOL,
            ctypes.wintypes.DWORD,
        ]
        _dll_kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
    return _dll_kernel32


def _get_advapi32():
    global _dll_advapi32
    if _dll_advapi32 is None:
        _dll_advapi32 = ctypes.WinDLL("advapi32.dll", use_last_error=True)
        _dll_advapi32.OpenProcessToken.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.POINTER(ctypes.wintypes.HANDLE),
        ]
        _dll_advapi32.OpenProcessToken.restype = ctypes.wintypes.BOOL
        _dll_advapi32.GetTokenInformation.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
            ctypes.POINTER(ctypes.wintypes.DWORD),
        ]
        _dll_advapi32.GetTokenInformation.restype = ctypes.wintypes.BOOL
        _dll_advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
        _dll_advapi32.GetLengthSid.restype = ctypes.wintypes.DWORD
        _dll_advapi32.CopySid.argtypes = [
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        _dll_advapi32.CopySid.restype = ctypes.wintypes.BOOL
        _dll_advapi32.ConvertStringSidToSidW.argtypes = [
            ctypes.wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        _dll_advapi32.ConvertStringSidToSidW.restype = ctypes.wintypes.BOOL
        _dll_advapi32.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        _dll_advapi32.ConvertSidToStringSidW.restype = ctypes.wintypes.BOOL
        _dll_advapi32.CreateWellKnownSid.argtypes = [
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.wintypes.DWORD),
        ]
        _dll_advapi32.CreateWellKnownSid.restype = ctypes.wintypes.BOOL
        _dll_advapi32.CreateRestrictedToken.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.wintypes.HANDLE),
        ]
        _dll_advapi32.CreateRestrictedToken.restype = ctypes.wintypes.BOOL
        _dll_advapi32.SetTokenInformation.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
        ]
        _dll_advapi32.SetTokenInformation.restype = ctypes.wintypes.BOOL
        _dll_advapi32.LookupPrivilegeValueW.argtypes = [
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.LPCWSTR,
            ctypes.c_void_p,
        ]
        _dll_advapi32.LookupPrivilegeValueW.restype = ctypes.wintypes.BOOL
        _dll_advapi32.AdjustTokenPrivileges.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.BOOL,
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        _dll_advapi32.AdjustTokenPrivileges.restype = ctypes.wintypes.BOOL
        _dll_advapi32.GetNamedSecurityInfoW.argtypes = [
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        _dll_advapi32.GetNamedSecurityInfoW.restype = ctypes.wintypes.DWORD
        _dll_advapi32.SetNamedSecurityInfoW.argtypes = [
            ctypes.wintypes.LPWSTR,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        _dll_advapi32.SetNamedSecurityInfoW.restype = ctypes.wintypes.DWORD
        _dll_advapi32.SetEntriesInAclW.argtypes = [
            ctypes.wintypes.ULONG,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        _dll_advapi32.SetEntriesInAclW.restype = ctypes.wintypes.DWORD
        _dll_advapi32.CreateProcessAsUserW.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.LPWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.wintypes.BOOL,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.wintypes.LPCWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        _dll_advapi32.CreateProcessAsUserW.restype = ctypes.wintypes.BOOL
    return _dll_advapi32


# ═══════════════════════════════════════════════════════════════════════════
# Shared: SID Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _make_random_cap_sid_string() -> str:
    """Generate a random capability SID in the S-1-5-21-x-x-x-x domain."""
    return (
        f"S-1-5-21-{random.randint(0, 0xFFFFFFFF)}"
        f"-{random.randint(0, 0xFFFFFFFF)}"
        f"-{random.randint(0, 0xFFFFFFFF)}"
        f"-{random.randint(0, 0xFFFFFFFF)}"
    )


def _string_to_sid(sid_string: str) -> ctypes.c_void_p:
    """Convert a SID string to a PSID (must be freed with LocalFree)."""
    advapi32 = _get_advapi32()
    psid = ctypes.c_void_p()
    ok = advapi32.ConvertStringSidToSidW(
        ctypes.c_wchar_p(sid_string), ctypes.byref(psid)
    )
    if not ok:
        raise OSError(
            f"ConvertStringSidToSidW failed for '{sid_string}': "
            f"error={ctypes.get_last_error()}"
        )
    return psid


def _sid_to_string(psid: ctypes.c_void_p, advapi32: Any = None) -> str:
    """Convert a PSID pointer to its string representation."""
    if advapi32 is None:
        advapi32 = _get_advapi32()
    string_sid = ctypes.c_wchar_p()
    ret = advapi32.ConvertSidToStringSidW(psid, ctypes.byref(string_sid))
    if not ret:
        raise OSError(
            f"ConvertSidToStringSidW failed: error={ctypes.get_last_error()}"
        )
    try:
        sid_value = string_sid.value
        if sid_value is None:
            raise OSError("ConvertSidToStringSidW returned NULL")
        return sid_value
    finally:
        ctypes.windll.kernel32.LocalFree(string_sid)


def _create_well_known_sid(sid_type: int) -> bytes:
    """Create a well-known SID (e.g. Everyone = WinWorldSid = 1)."""
    advapi32 = _get_advapi32()
    size = ctypes.wintypes.DWORD(0)
    advapi32.CreateWellKnownSid(sid_type, None, None, ctypes.byref(size))
    if size.value == 0:
        size.value = 64
    buf = (ctypes.c_ubyte * size.value)()
    ok = advapi32.CreateWellKnownSid(sid_type, None, buf, ctypes.byref(size))
    if not ok:
        raise OSError(
            f"CreateWellKnownSid({sid_type}) failed: "
            f"error={ctypes.get_last_error()}"
        )
    return bytes(buf[: size.value])


def _copy_sid_from_ptr(sid_ptr_val: int) -> bytes:
    """Copy a SID from a raw pointer value to a bytes buffer."""
    advapi32 = _get_advapi32()
    psid = ctypes.c_void_p(sid_ptr_val)
    length = advapi32.GetLengthSid(psid)
    if length == 0:
        return b""
    buf = (ctypes.c_ubyte * length)()
    advapi32.CopySid(length, buf, psid)
    return bytes(buf)


def _get_logon_sid_bytes(h_token: ctypes.wintypes.HANDLE) -> bytes:
    """Extract the Logon SID from a token."""
    advapi32 = _get_advapi32()
    needed = ctypes.wintypes.DWORD(0)
    advapi32.GetTokenInformation(
        h_token, _WC.TokenGroups, None, 0, ctypes.byref(needed)
    )
    buf = (ctypes.c_ubyte * needed.value)()
    ok = advapi32.GetTokenInformation(
        h_token, _WC.TokenGroups, buf, needed.value, ctypes.byref(needed)
    )
    if not ok:
        raise OSError(
            f"GetTokenInformation(TokenGroups) failed: "
            f"error={ctypes.get_last_error()}"
        )

    raw = bytes(buf)
    group_count = struct.unpack_from("<I", raw, 0)[0]
    ptr_size = ctypes.sizeof(ctypes.c_void_p)
    sa_size = 16 if ptr_size == 8 else 8
    offset = (4 + ptr_size - 1) & ~(ptr_size - 1)

    for i in range(group_count):
        entry_offset = offset + i * sa_size
        if ptr_size == 8:
            sid_val = struct.unpack_from("<Q", raw, entry_offset)[0]
            attrs = struct.unpack_from("<I", raw, entry_offset + 8)[0]
        else:
            sid_val = struct.unpack_from("<I", raw, entry_offset)[0]
            attrs = struct.unpack_from("<I", raw, entry_offset + 4)[0]
        if (attrs & _WC.SE_GROUP_LOGON_ID) == _WC.SE_GROUP_LOGON_ID:
            result = _copy_sid_from_ptr(sid_val)
            if result:
                return result

    raise OSError("Logon SID not found in token groups")


# ═══════════════════════════════════════════════════════════════════════════
# Shared: Token Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _build_explicit_access(
    psid: ctypes.c_void_p,
    access_mask: int,
    access_mode: int,
    inheritance: int = 0,
) -> _EXPLICIT_ACCESS_W:
    """Build an EXPLICIT_ACCESS_W entry for a given SID."""
    entry = _EXPLICIT_ACCESS_W()
    entry.grfAccessPermissions = access_mask
    entry.grfAccessMode = access_mode
    entry.grfInheritance = inheritance
    entry.Trustee.pMultipleTrustee = None
    entry.Trustee.MultipleTrusteeOperation = 0
    entry.Trustee.TrusteeForm = _WC.TRUSTEE_IS_SID
    entry.Trustee.TrusteeType = _WC.TRUSTEE_IS_UNKNOWN
    entry.Trustee.ptstrName = psid
    return entry


def _set_default_dacl(
    h_token: ctypes.wintypes.HANDLE, sid_ptrs: List[ctypes.c_void_p]
) -> None:
    """Set the token's default DACL so child objects are accessible."""
    if not sid_ptrs:
        return
    advapi32 = _get_advapi32()
    kernel32 = _get_kernel32()

    entries = [
        _build_explicit_access(psid, _WC.GENERIC_ALL, _WC.GRANT_ACCESS)
        for psid in sid_ptrs
    ]
    arr = (_EXPLICIT_ACCESS_W * len(entries))(*entries)
    new_dacl = ctypes.c_void_p()
    rc = advapi32.SetEntriesInAclW(
        len(entries),
        ctypes.cast(arr, ctypes.c_void_p),
        None,
        ctypes.byref(new_dacl),
    )
    if rc != 0:
        logger.warning("SetEntriesInAclW for default DACL failed: rc=%d", rc)
        return

    info = _TOKEN_DEFAULT_DACL(DefaultDacl=new_dacl)
    advapi32.SetTokenInformation(
        h_token, _WC.TokenDefaultDacl, ctypes.byref(info), ctypes.sizeof(info)
    )
    if new_dacl:
        kernel32.LocalFree(new_dacl)


def _enable_privilege(h_token: ctypes.wintypes.HANDLE, name: str) -> bool:
    """Enable a privilege on a token. Returns True if successful."""
    advapi32 = _get_advapi32()
    luid = _LUID()
    if not advapi32.LookupPrivilegeValueW(
        None, ctypes.c_wchar_p(name), ctypes.byref(luid)
    ):
        return False
    tp = _TOKEN_PRIVILEGES()
    tp.PrivilegeCount = 1
    tp.Privileges[0].Luid = luid
    tp.Privileges[0].Attributes = _WC.SE_PRIVILEGE_ENABLED
    advapi32.AdjustTokenPrivileges(
        h_token, False, ctypes.byref(tp), 0, None, None
    )
    return ctypes.get_last_error() != 1300


# ═══════════════════════════════════════════════════════════════════════════
# Shared: Process Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _build_shell_command_line(
    cmd: str,
    shell_executable: Optional[str] = None,
) -> str:
    """Build the command line string for launching a command via a shell."""
    name = (
        os.path.basename(shell_executable).lower() if shell_executable else ""
    )
    if shell_executable and name in _WC.POWERSHELL_NAMES:
        ps_cmd = cmd.replace('"', '\\"')
        return (
            f"{shell_executable} -NoProfile -NonInteractive "
            f'-ExecutionPolicy Bypass -Command "{ps_cmd}"'
        )
    elif not shell_executable or name in _WC.CMD_NAMES:
        shell = shell_executable or "cmd.exe"
        return f'{shell} /c "{cmd}"'
    else:
        escaped = cmd.replace('"', '\\"')
        return f'{shell_executable} -c "{escaped}"'


def _make_env_block(env: Dict[str, str]) -> ctypes.Array:
    """Build a null-terminated Unicode environment block."""
    items = sorted(env.items(), key=lambda kv: kv[0].upper())
    env_str = "\x00".join(f"{k}={v}" for k, v in items) + "\x00\x00"
    return ctypes.create_unicode_buffer(env_str)


def _create_stdio_pipes(
    kernel32: Any = None,
) -> Tuple[
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
]:
    """Create inheritable stdout/stderr pipes for child process I/O.

    Returns (stdout_read, stdout_write, stderr_read, stderr_write).
    """
    if kernel32 is None:
        kernel32 = _get_kernel32()

    sa = _SECURITY_ATTRIBUTES(
        nLength=ctypes.sizeof(_SECURITY_ATTRIBUTES),
        lpSecurityDescriptor=None,
        bInheritHandle=True,
    )
    stdout_read = ctypes.wintypes.HANDLE()
    stdout_write = ctypes.wintypes.HANDLE()
    stderr_read = ctypes.wintypes.HANDLE()
    stderr_write = ctypes.wintypes.HANDLE()

    if not kernel32.CreatePipe(
        ctypes.byref(stdout_read),
        ctypes.byref(stdout_write),
        ctypes.byref(sa),
        0,
    ):
        raise OSError(
            f"CreatePipe(stdout) failed: error={ctypes.get_last_error()}"
        )
    if not kernel32.CreatePipe(
        ctypes.byref(stderr_read),
        ctypes.byref(stderr_write),
        ctypes.byref(sa),
        0,
    ):
        kernel32.CloseHandle(stdout_read)
        kernel32.CloseHandle(stdout_write)
        raise OSError(
            f"CreatePipe(stderr) failed: error={ctypes.get_last_error()}"
        )

    kernel32.SetHandleInformation(stdout_read, _WC.HANDLE_FLAG_INHERIT, 0)
    kernel32.SetHandleInformation(stderr_read, _WC.HANDLE_FLAG_INHERIT, 0)

    return stdout_read, stdout_write, stderr_read, stderr_write


def _read_pipe(handle: ctypes.wintypes.HANDLE, kernel32: Any = None) -> bytes:
    """Drain a pipe handle until EOF."""
    if kernel32 is None:
        kernel32 = _get_kernel32()
    _ERROR_BROKEN_PIPE = 109
    chunks: List[bytes] = []
    buf_size = 8192
    buf = (ctypes.c_ubyte * buf_size)()
    bytes_read = ctypes.wintypes.DWORD(0)

    while True:
        ok = kernel32.ReadFile(
            handle, buf, buf_size, ctypes.byref(bytes_read), None
        )
        if not ok:
            if bytes_read.value > 0:
                chunks.append(bytes(buf[: bytes_read.value]))
            break
        if bytes_read.value == 0:
            break
        chunks.append(bytes(buf[: bytes_read.value]))

    return b"".join(chunks)


def _create_job_object() -> Optional[ctypes.wintypes.HANDLE]:
    """Create a Job Object configured to kill all child processes on close."""
    kernel32 = _get_kernel32()
    h_job = kernel32.CreateJobObjectW(None, None)
    if not h_job:
        return None

    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = (
        _WC.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    )
    ok = kernel32.SetInformationJobObject(
        h_job,
        _WC.JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        kernel32.CloseHandle(h_job)
        return None
    return h_job


# ═══════════════════════════════════════════════════════════════════════════
# Shared: ACL / Cleanup Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _is_pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID is still running."""
    if pid <= 0:
        return False
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    try:
        kernel32 = _get_kernel32()
        handle = kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return False
        exit_code = ctypes.wintypes.DWORD(0)
        kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        kernel32.CloseHandle(handle)
        return exit_code.value == 259  # STILL_ACTIVE
    except OSError:
        return False


def _run_icacls_sync(args: List[str], timeout: float = 30.0) -> bool:
    """Run icacls synchronously. Returns True on success."""
    if timeout <= 0:
        return False
    try:
        result = subprocess.run(
            ["icacls"] + args,
            capture_output=True,
            timeout=int(max(1, timeout)),
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _verify_acl_removed_sync(
    path: str, sid: str, timeout: float = 180.0
) -> bool:
    """Verify that a SID no longer appears in the DACL of a path."""
    if not os.path.exists(path):
        return True
    if timeout <= 0:
        return False
    try:
        result = subprocess.run(
            ["icacls", path],
            capture_output=True,
            timeout=int(max(1, timeout)),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    output = result.stdout.decode("utf-8", errors="replace")
    if sid in output:
        return False
    if sid.upper() in output.upper():
        return False
    return True


def _remove_acl_with_verify_sync(
    path: str,
    sid: str,
    *,
    reset_only: bool = False,
    deadline: float = 0.0,
) -> bool:
    """Remove ACEs for a SID using multi-strategy retry with verification.

    Strategies:
      1. Basic /remove
      2. Recursive /remove /T /C
      3. Explicit /remove:g and /remove:d
      4. /inheritance:e then /remove again
      5. Break inheritance then /remove
      6. Non-recursive /reset then /remove

    Args:
        deadline: monotonic time deadline; 0.0 means no deadline.
        reset_only: skip strategies 1-5, use only reset+remove.
    """
    if not os.path.exists(path):
        return True

    def _budget_ok() -> bool:
        return deadline <= 0 or time.monotonic() < deadline

    def _budget_timeout() -> float:
        if deadline <= 0:
            return 30.0
        return min(30.0, max(1.0, deadline - time.monotonic()))

    strategies = [
        lambda: _run_icacls_sync(
            [path, "/remove", f"*{sid}"], timeout=_budget_timeout()
        ),
        lambda: _run_icacls_sync(
            [path, "/remove", f"*{sid}", "/T", "/C"], timeout=_budget_timeout()
        ),
        lambda: (
            _run_icacls_sync(
                [path, "/remove:g", f"*{sid}", "/T", "/C"],
                timeout=_budget_timeout(),
            ),
            _run_icacls_sync(
                [path, "/remove:d", f"*{sid}", "/T", "/C"],
                timeout=_budget_timeout(),
            ),
        ),
        lambda: (
            _run_icacls_sync(
                [path, "/inheritance:e"], timeout=_budget_timeout()
            ),
            _run_icacls_sync(
                [path, "/remove", f"*{sid}", "/T", "/C"],
                timeout=_budget_timeout(),
            ),
        ),
        lambda: (
            _run_icacls_sync(
                [path, "/inheritance:d"], timeout=_budget_timeout()
            ),
            _run_icacls_sync(
                [path, "/remove", f"*{sid}", "/T", "/C"],
                timeout=_budget_timeout(),
            ),
        ),
        lambda: (
            _run_icacls_sync([path, "/reset"], timeout=_budget_timeout()),
            _run_icacls_sync(
                [path, "/remove", f"*{sid}", "/T", "/C"],
                timeout=_budget_timeout(),
            ),
        ),
    ]

    if reset_only:
        strategies = [strategies[-1]]

    for attempt, strategy in enumerate(strategies, 1):
        if not _budget_ok():
            logger.warning(
                "ACL cleanup deadline reached; skipping remaining removal "
                "for %s",
                path,
            )
            return False

        strategy()

        if attempt > 1:
            if not _budget_ok():
                return False
            sleep_time = (
                min(1.0, max(0, deadline - time.monotonic()))
                if deadline > 0
                else 1.0
            )
            time.sleep(sleep_time)

        if _verify_acl_removed_sync(path, sid, timeout=_budget_timeout()):
            return True

    logger.warning(
        "ACL for SID %s could NOT be removed from %s after %d attempts",
        sid,
        path,
        len(strategies),
    )
    return False


# ═══════════════════════════════════════════════════════════════════════════
# WindowsSandboxBase (abstract base class for Windows sandboxes)
# ═══════════════════════════════════════════════════════════════════════════


class WindowsSandboxBase(ABC):
    """Abstract base class for Windows sandbox implementations.

    Provides common infrastructure shared by all Windows sandbox backends:
      - Config storage and ``config`` property.
      - Async context manager (``__aenter__``/``__aexit__``).
      - Process termination via Job Object or direct handle.
      - Sandbox violation detection.
      - Base environment building.
    """

    def __init__(self, config: SandboxConfig):
        self._config = config
        self._process_handle: Optional[ctypes.wintypes.HANDLE] = None
        self._job_handle: Optional[ctypes.wintypes.HANDLE] = None

    @property
    def config(self) -> SandboxConfig:
        return self._config

    @abstractmethod
    async def execute(
        self, cmd: str, cwd: Optional[str] = None
    ) -> ExecutionResult:
        """Execute a command inside the sandbox."""

    async def stop(self) -> None:
        """Terminate any running child process."""
        self._terminate_process()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()

    def _terminate_process(self) -> None:
        """Terminate running child via Job Object or process handle."""
        kernel32 = _get_kernel32()
        if self._job_handle:
            try:
                kernel32.TerminateJobObject(self._job_handle, 1)
            except OSError:
                pass
            self._job_handle = None
        if self._process_handle:
            try:
                kernel32.TerminateProcess(self._process_handle, 1)
            except OSError:
                pass
            self._process_handle = None

    def _detect_violation(
        self, exit_code: int, stdout: str, stderr: str
    ) -> Optional[str]:
        """Detect sandbox violations in process output."""
        if _WC.VIOLATION_RE.search(stderr):
            return stderr.strip()
        if exit_code != 0 and _WC.VIOLATION_RE.search(stdout):
            return stdout.strip()
        return None

    def _build_base_env(self) -> Dict[str, str]:
        """Build base child process environment.

        Inherits current environment, applies config env_vars, and ensures
        PYTHONHOME is set.
        """
        env = dict(os.environ)
        if self._config.env_vars:
            env.update(self._config.env_vars)
        python_dir = _get_python_install_dir()
        if python_dir:
            env.setdefault("PYTHONHOME", python_dir)
        return env


# ═══════════════════════════════════════════════════════════════════════════
# Unelevated-specific: ACL Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _add_write_allow_ace(path: str, cap_psid: ctypes.c_void_p) -> bool:
    """Add an inheritable write-allow ACE for cap_sid on a path."""
    return _set_path_ace(
        path, cap_psid, _WC.WRITE_ALLOW_MASK, _WC.SET_ACCESS, inherit=True
    )


def _add_deny_write_ace(path: str, cap_psid: ctypes.c_void_p) -> bool:
    """Add an inheritable deny-write ACE for cap_sid on a path."""
    return _set_path_ace(
        path, cap_psid, _WC.DENY_WRITE_MASK, _WC.DENY_ACCESS, inherit=True
    )


def _set_path_ace(
    path: str,
    psid: ctypes.c_void_p,
    access_mask: int,
    access_mode: int,
    inherit: bool = True,
) -> bool:
    """Set an ACE on a filesystem path."""
    advapi32 = _get_advapi32()
    kernel32 = _get_kernel32()

    p_sd = ctypes.c_void_p()
    p_dacl = ctypes.c_void_p()
    rc = advapi32.GetNamedSecurityInfoW(
        ctypes.c_wchar_p(path),
        _WC.SE_FILE_OBJECT,
        _WC.DACL_SECURITY_INFORMATION,
        None,
        None,
        ctypes.byref(p_dacl),
        None,
        ctypes.byref(p_sd),
    )
    if rc != 0:
        logger.warning("GetNamedSecurityInfoW(%s) failed: rc=%d", path, rc)
        return False

    ea = _build_explicit_access(
        psid,
        access_mask,
        access_mode,
        (_WC.CONTAINER_INHERIT_ACE | _WC.OBJECT_INHERIT_ACE) if inherit else 0,
    )

    new_dacl = ctypes.c_void_p()
    rc2 = advapi32.SetEntriesInAclW(
        1, ctypes.byref(ea), p_dacl, ctypes.byref(new_dacl)
    )
    if rc2 != 0:
        logger.warning("SetEntriesInAclW(%s) failed: rc=%d", path, rc2)
        if p_sd:
            kernel32.LocalFree(p_sd)
        return False

    rc3 = advapi32.SetNamedSecurityInfoW(
        ctypes.c_wchar_p(path),
        _WC.SE_FILE_OBJECT,
        _WC.DACL_SECURITY_INFORMATION,
        None,
        None,
        new_dacl,
        None,
    )
    if new_dacl:
        kernel32.LocalFree(new_dacl)
    if p_sd:
        kernel32.LocalFree(p_sd)

    if rc3 != 0:
        logger.warning("SetNamedSecurityInfoW(%s) failed: rc=%d", path, rc3)
        return False

    return True


def _remove_ace_sync(path: str, cap_sid_string: str) -> bool:
    """Remove all ACEs for cap_sid from a path using icacls."""
    try:
        result = subprocess.run(
            ["icacls", path, "/remove", f"*{cap_sid_string}"],
            capture_output=True,
            timeout=30,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Unelevated-specific: Token Creation
# ═══════════════════════════════════════════════════════════════════════════


def _create_restricted_token(
    h_base_token: ctypes.wintypes.HANDLE,
    cap_sid_string: str,
) -> Tuple[ctypes.wintypes.HANDLE, ctypes.c_void_p]:
    """Create a WRITE_RESTRICTED token with [cap_sid, logon_sid, Everyone].

    Returns (new_token_handle, cap_psid). The caller must free cap_psid
    with LocalFree after it is no longer needed for ACL operations.
    """
    advapi32 = _get_advapi32()
    kernel32 = _get_kernel32()

    logon_sid_bytes = _get_logon_sid_bytes(h_base_token)
    logon_buf = (ctypes.c_ubyte * len(logon_sid_bytes))(*logon_sid_bytes)
    logon_ptr = ctypes.cast(logon_buf, ctypes.c_void_p)

    everyone_bytes = _create_well_known_sid(_WC.WinWorldSid)
    everyone_buf = (ctypes.c_ubyte * len(everyone_bytes))(*everyone_bytes)
    everyone_ptr = ctypes.cast(everyone_buf, ctypes.c_void_p)

    cap_psid = _string_to_sid(cap_sid_string)

    entries = [
        _SID_AND_ATTRIBUTES(Sid=cap_psid, Attributes=0),
        _SID_AND_ATTRIBUTES(Sid=logon_ptr, Attributes=0),
        _SID_AND_ATTRIBUTES(Sid=everyone_ptr, Attributes=0),
    ]
    arr = (_SID_AND_ATTRIBUTES * len(entries))(*entries)

    flags = _WC.DISABLE_MAX_PRIVILEGE | _WC.WRITE_RESTRICTED
    new_token = ctypes.wintypes.HANDLE()
    ok = advapi32.CreateRestrictedToken(
        h_base_token,
        flags,
        0,
        None,
        0,
        None,
        len(entries),
        ctypes.cast(arr, ctypes.c_void_p),
        ctypes.byref(new_token),
    )
    if not ok:
        kernel32.LocalFree(cap_psid)
        raise OSError(
            f"CreateRestrictedToken failed: error={ctypes.get_last_error()}"
        )

    try:
        _set_default_dacl(new_token, [cap_psid, logon_ptr, everyone_ptr])
        if not _enable_privilege(new_token, _WC.SE_CHANGE_NOTIFY_NAME):
            logger.warning("Failed to enable SeChangeNotifyPrivilege on token")
    except Exception:
        kernel32.CloseHandle(new_token)
        kernel32.LocalFree(cap_psid)
        raise

    return new_token, cap_psid


# ═══════════════════════════════════════════════════════════════════════════
# Unelevated-specific: Process Creation
# ═══════════════════════════════════════════════════════════════════════════


def _create_process_as_user(
    h_token: ctypes.wintypes.HANDLE,
    cmd: str,
    cwd: str,
    env: Dict[str, str],
    shell_executable: Optional[str] = None,
) -> Tuple[
    int,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
    Optional[ctypes.wintypes.HANDLE],
]:
    """Create a process under the restricted token.

    Returns: (pid, process_handle, stdout_read, stderr_read, job_handle)
    """
    kernel32 = _get_kernel32()
    advapi32 = _get_advapi32()

    stdout_read, stdout_write, stderr_read, stderr_write = _create_stdio_pipes(
        kernel32
    )

    si = _STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.dwFlags = _WC.STARTF_USESTDHANDLES
    si.hStdInput = None
    si.hStdOutput = stdout_write
    si.hStdError = stderr_write
    si.lpDesktop = "WinSta0\\Default"

    env_block = _make_env_block(env)
    command_line = _build_shell_command_line(cmd, shell_executable)
    cl_buf = ctypes.create_unicode_buffer(command_line)

    pi = _PROCESS_INFORMATION()
    flags = (
        _WC.CREATE_UNICODE_ENVIRONMENT
        | _WC.CREATE_NO_WINDOW
        | _WC.CREATE_SUSPENDED
    )

    ok = advapi32.CreateProcessAsUserW(
        h_token,
        None,
        cl_buf,
        None,
        None,
        True,
        flags,
        ctypes.cast(env_block, ctypes.c_void_p),
        ctypes.c_wchar_p(cwd),
        ctypes.byref(si),
        ctypes.byref(pi),
    )
    err = ctypes.get_last_error() if not ok else 0

    kernel32.CloseHandle(stdout_write)
    kernel32.CloseHandle(stderr_write)

    if not ok:
        kernel32.CloseHandle(stdout_read)
        kernel32.CloseHandle(stderr_read)
        raise OSError(f"CreateProcessAsUserW failed: error={err}")

    h_job = _create_job_object()
    if h_job:
        kernel32.AssignProcessToJobObject(h_job, pi.hProcess)

    ctypes.windll.kernel32.ResumeThread(pi.hThread)
    kernel32.CloseHandle(pi.hThread)

    return (pi.dwProcessId, pi.hProcess, stdout_read, stderr_read, h_job)


# ═══════════════════════════════════════════════════════════════════════════
# Unelevated-specific: State Persistence
# ═══════════════════════════════════════════════════════════════════════════


def _state_file_path() -> Path:
    """Path to the unelevated sandbox state file."""
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    return home / ".qwenpaw" / "unelevated_sandbox_state.json"


def _save_state(
    cap_sid: str,
    acl_paths: List[str],
    deny_paths: List[str],
) -> None:
    """Persist sandbox state for cleanup on restart."""
    state_file = _state_file_path()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "cap_sid": cap_sid,
        "acl_paths": acl_paths,
        "deny_paths": deny_paths,
        "pid": os.getpid(),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    try:
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("Failed to save unelevated sandbox state: %s", e)


def _load_state() -> Optional[dict]:
    """Load persisted sandbox state."""
    state_file = _state_file_path()
    if not state_file.exists():
        return None
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _clear_state() -> None:
    """Remove the state file."""
    state_file = _state_file_path()
    try:
        state_file.unlink(missing_ok=True)
    except OSError:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# WindowsUnelevatedSandbox
# ═══════════════════════════════════════════════════════════════════════════


class WindowsUnelevatedSandbox(WindowsSandboxBase):
    """Windows sandbox using WRITE_RESTRICTED token without admin privileges.

    Write operations are gated by a fabricated capability SID: only filesystem
    paths with an explicit allow ACE for this SID can be written to by the
    sandboxed process. Read/execute access is unrestricted.

    Lifecycle:
        ``__aenter__``: Creates restricted token, applies workspace ACE.
        ``execute``: Launches command under restricted token.
        ``__aexit__`` / ``stop``: Kills process, removes ACEs, closes token.
    """

    def __init__(self, config: SandboxConfig):
        super().__init__(config)
        self._h_token: Optional[ctypes.wintypes.HANDLE] = None
        self._cap_psid: Optional[ctypes.c_void_p] = None
        self._cap_sid_string: Optional[str] = None
        self._acl_paths: List[str] = []
        self._deny_acl_paths: List[str] = []
        self._initialized = False

    async def __aenter__(self):
        await self._initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()

    async def _initialize(self) -> None:
        """Set up token and ACLs (runs once, lazily on first use)."""
        if self._initialized:
            return
        await asyncio.to_thread(self._initialize_sync)
        self._initialized = True

    def _initialize_sync(self) -> None:
        """Synchronous initialization: create token and apply ACLs."""
        kernel32 = _get_kernel32()
        advapi32 = _get_advapi32()

        workspace = self._config.workspace_dir
        os.makedirs(workspace, exist_ok=True)

        self._cap_sid_string = _make_random_cap_sid_string()
        logger.info(
            "Unelevated sandbox: cap_sid=%s workspace=%s",
            self._cap_sid_string,
            workspace,
        )

        h_base = ctypes.wintypes.HANDLE()
        ok = advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), 0x000F01FF, ctypes.byref(h_base)
        )
        if not ok:
            raise OSError(
                f"OpenProcessToken failed: error={ctypes.get_last_error()}"
            )

        try:
            self._h_token, self._cap_psid = _create_restricted_token(
                h_base, self._cap_sid_string
            )
        finally:
            kernel32.CloseHandle(h_base)

        if not _add_write_allow_ace(workspace, self._cap_psid):
            logger.error("Failed to set write ACE on workspace: %s", workspace)
        else:
            self._acl_paths.append(workspace)

        for mount in self._config.mounts:
            if os.path.exists(mount.path):
                mount_path = os.path.abspath(mount.path)
                if mount_path != os.path.abspath(workspace):
                    if _add_write_allow_ace(mount_path, self._cap_psid):
                        self._acl_paths.append(mount_path)
                    else:
                        logger.warning(
                            "Failed to set ACE on mount: %s", mount_path
                        )

        for deny_path in self._config.deny_paths:
            if os.path.exists(deny_path):
                if _add_deny_write_ace(deny_path, self._cap_psid):
                    self._deny_acl_paths.append(deny_path)
                else:
                    logger.warning("Failed to set deny ACE on: %s", deny_path)

        _save_state(
            self._cap_sid_string, self._acl_paths, self._deny_acl_paths
        )

    async def execute(
        self,
        cmd: str,
        cwd: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute a command inside the sandbox."""
        if not self._initialized:
            await self._initialize()

        effective_cwd = cwd or self._config.workspace_dir
        start = time.monotonic()

        try:
            env = self._build_base_env()

            # Network soft-block via proxy environment variables
            if not self._config.network_allow:
                env["HTTP_PROXY"] = "http://127.0.0.1:9"
                env["HTTPS_PROXY"] = "http://127.0.0.1:9"
                env["NO_PROXY"] = ""
                env["http_proxy"] = "http://127.0.0.1:9"
                env["https_proxy"] = "http://127.0.0.1:9"
                env["no_proxy"] = ""

            pid, h_proc, h_stdout, h_stderr, h_job = await asyncio.to_thread(
                _create_process_as_user,
                self._h_token,
                cmd,
                effective_cwd,
                env,
                self._config.shell_executable,
            )
            self._process_handle = h_proc
            self._job_handle = h_job

            exit_code, stdout, stderr, timed_out = await asyncio.to_thread(
                self._wait_and_read,
                h_proc,
                h_stdout,
                h_stderr,
                h_job,
            )

            duration_ms = int((time.monotonic() - start) * 1000)
            violation = self._detect_violation(exit_code, stdout, stderr)

            return ExecutionResult(
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                timed_out=timed_out,
                duration_ms=duration_ms,
                sandbox_violation=violation,
            )

        except OSError as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                timed_out=False,
                duration_ms=duration_ms,
            )
        finally:
            self._process_handle = None
            self._job_handle = None

    def _wait_and_read(
        self,
        h_proc: ctypes.wintypes.HANDLE,
        h_stdout: ctypes.wintypes.HANDLE,
        h_stderr: ctypes.wintypes.HANDLE,
        h_job: Optional[ctypes.wintypes.HANDLE],
    ) -> Tuple[int, str, str, bool]:
        """Wait for process and drain output pipes."""
        kernel32 = _get_kernel32()
        timeout_ms = self._config.timeout_seconds * 1000

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            f_stdout = pool.submit(_read_pipe, h_stdout)
            f_stderr = pool.submit(_read_pipe, h_stderr)

            wait_result = kernel32.WaitForSingleObject(h_proc, timeout_ms)
            timed_out = wait_result == _WC.WAIT_TIMEOUT

            if timed_out:
                if h_job:
                    kernel32.TerminateJobObject(h_job, 1)
                else:
                    kernel32.TerminateProcess(h_proc, 1)
                kernel32.WaitForSingleObject(h_proc, 5000)

            stdout_raw = f_stdout.result(timeout=10)
            stderr_raw = f_stderr.result(timeout=10)

        exit_code = ctypes.wintypes.DWORD()
        kernel32.GetExitCodeProcess(h_proc, ctypes.byref(exit_code))

        kernel32.CloseHandle(h_stdout)
        kernel32.CloseHandle(h_stderr)
        kernel32.CloseHandle(h_proc)
        if h_job:
            kernel32.CloseHandle(h_job)

        stdout = _decode_pipe_output(stdout_raw)
        stderr = _decode_pipe_output(stderr_raw)

        return (exit_code.value, stdout, stderr, timed_out)

    async def stop(self) -> None:
        """Terminate any running process and clean up resources."""
        kernel32 = _get_kernel32()

        self._terminate_process()

        if self._cap_sid_string:
            await asyncio.to_thread(self._cleanup_acls)

        if self._h_token:
            kernel32.CloseHandle(self._h_token)
            self._h_token = None

        if self._cap_psid:
            kernel32.LocalFree(self._cap_psid)
            self._cap_psid = None

        _clear_state()
        self._initialized = False

    def _cleanup_acls(self) -> None:
        """Remove all ACEs placed by this sandbox instance."""
        if not self._cap_sid_string:
            return

        all_paths = self._acl_paths + self._deny_acl_paths
        for path in all_paths:
            if os.path.exists(path):
                _remove_ace_sync(path, self._cap_sid_string)

        self._acl_paths.clear()
        self._deny_acl_paths.clear()


# ═══════════════════════════════════════════════════════════════════════════
# Module-level cleanup
# ═══════════════════════════════════════════════════════════════════════════


def shutdown_cleanup() -> None:
    """Best-effort cleanup of sandbox ACLs on process exit."""
    import sys

    if sys.platform != "win32":
        return

    state = _load_state()
    if not state:
        return

    cap_sid = state.get("cap_sid")
    if not cap_sid:
        return

    saved_pid = state.get("pid")
    if saved_pid and saved_pid != os.getpid():
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {saved_pid}", "/NH"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if str(saved_pid) in result.stdout.decode(
                "utf-8", errors="replace"
            ):
                return
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    all_paths = state.get("acl_paths", []) + state.get("deny_paths", [])
    for path in all_paths:
        if os.path.exists(path):
            _remove_ace_sync(path, cap_sid)

    _clear_state()
    logger.info("Unelevated sandbox cleanup: removed ACEs for %s", cap_sid)


atexit.register(shutdown_cleanup)
