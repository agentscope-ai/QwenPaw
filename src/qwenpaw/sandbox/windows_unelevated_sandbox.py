# -*- coding: utf-8 -*-
"""Windows unelevated sandbox — WRITE_RESTRICTED token without admin privileges.

Uses the current user's token with CreateRestrictedToken(WRITE_RESTRICTED) and
a fabricated capability SID to gate write access. Only filesystem paths that
have an explicit allow-write ACE for the capability SID can be written to.

Key properties:
  - Does NOT require administrator privileges.
  - Write operations are restricted to workspace (and writable mounts).
  - Read/execute operations are unrestricted (WRITE_RESTRICTED only gates writes).
  - Network isolation is soft (environment variable proxy, not a firewall).
  - deny_paths are enforced via deny-write ACEs (deny-read NOT supported).

Requires Windows 10 1507+ and Python ctypes.
"""

from __future__ import annotations

import asyncio
import atexit
import ctypes
import ctypes.wintypes
import json
import logging
import os
import random
import struct
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import ExecutionResult, SandboxConfig
from .windows_sandbox import (
    _VIOLATION_RE,
    _decode_pipe_output,
    _get_python_install_dir,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

# CreateRestrictedToken flags
_DISABLE_MAX_PRIVILEGE = 0x01
_WRITE_RESTRICTED = 0x08  # Only write operations check restricting SIDs

# ACL / Security constants
_SE_FILE_OBJECT = 1
_DACL_SECURITY_INFORMATION = 0x00000004
_CONTAINER_INHERIT_ACE = 0x2
_OBJECT_INHERIT_ACE = 0x1
_GRANT_ACCESS = 1
_SET_ACCESS = 2
_DENY_ACCESS = 3
_TRUSTEE_IS_SID = 0
_TRUSTEE_IS_UNKNOWN = 0

# File access masks
_FILE_GENERIC_READ = 0x00120089
_FILE_GENERIC_WRITE = 0x00120116
_FILE_GENERIC_EXECUTE = 0x001200A0
_FILE_WRITE_DATA = 0x00000002
_FILE_APPEND_DATA = 0x00000004
_FILE_WRITE_EA = 0x00000010
_FILE_WRITE_ATTRIBUTES = 0x00000100
_DELETE = 0x00010000
_FILE_DELETE_CHILD = 0x00000040
_GENERIC_ALL = 0x10000000
_GENERIC_WRITE = 0x40000000

# Write-allow mask: RWX + Delete, NO FILE_DELETE_CHILD (prevents bypass of
# deny ACEs on child directories via parent delete).
_WRITE_ALLOW_MASK = (
    _FILE_GENERIC_READ | _FILE_GENERIC_WRITE | _FILE_GENERIC_EXECUTE | _DELETE
)

# Deny-write mask: comprehensive write denial
_DENY_WRITE_MASK = (
    _FILE_GENERIC_WRITE
    | _FILE_WRITE_DATA
    | _FILE_APPEND_DATA
    | _FILE_WRITE_EA
    | _FILE_WRITE_ATTRIBUTES
    | _GENERIC_WRITE
    | _DELETE
    | _FILE_DELETE_CHILD
)

# Token information classes
_TokenGroups = 2
_TokenDefaultDacl = 6

# SE_GROUP_LOGON_ID attribute
_SE_GROUP_LOGON_ID = 0xC0000000

# Process creation flags
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_CREATE_NO_WINDOW = 0x08000000
_CREATE_SUSPENDED = 0x00000004
_STARTF_USESTDHANDLES = 0x00000100
_HANDLE_FLAG_INHERIT = 0x00000001

# Job Object constants
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JobObjectExtendedLimitInformation = 9

# Wait constants
_WAIT_TIMEOUT = 0x00000102

# Privilege constants
_SE_PRIVILEGE_ENABLED = 0x00000002
_SE_CHANGE_NOTIFY_NAME = "SeChangeNotifyPrivilege"

# WinWorldSid type for Everyone SID
_WinWorldSid = 1


# ═══════════════════════════════════════════════════════════════════════════
# DLL Accessors (lazy init, same pattern as windows_restricted_sandbox)
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
# ctypes Structures
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
# SID Helpers
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
            f"ConvertStringSidToSidW failed for {sid_string}: "
            f"error={ctypes.get_last_error()}"
        )
    return psid


def _create_well_known_sid(sid_type: int) -> bytes:
    """Create a well-known SID (e.g. Everyone = WinWorldSid = 1)."""
    advapi32 = _get_advapi32()
    size = ctypes.wintypes.DWORD(64)
    buf = (ctypes.c_ubyte * 64)()
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


# ═══════════════════════════════════════════════════════════════════════════
# Token Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _get_logon_sid_bytes(h_token: ctypes.wintypes.HANDLE) -> bytes:
    """Extract the Logon SID from a token."""
    advapi32 = _get_advapi32()
    needed = ctypes.wintypes.DWORD(0)
    advapi32.GetTokenInformation(
        h_token, _TokenGroups, None, 0, ctypes.byref(needed)
    )
    buf = (ctypes.c_ubyte * needed.value)()
    ok = advapi32.GetTokenInformation(
        h_token, _TokenGroups, buf, needed.value, ctypes.byref(needed)
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
        if (attrs & _SE_GROUP_LOGON_ID) == _SE_GROUP_LOGON_ID:
            result = _copy_sid_from_ptr(sid_val)
            if result:
                return result

    raise OSError("Logon SID not found in token groups")


def _set_default_dacl(
    h_token: ctypes.wintypes.HANDLE, sid_ptrs: List[ctypes.c_void_p]
) -> None:
    """Set the token's default DACL so child objects are accessible."""
    if not sid_ptrs:
        return
    advapi32 = _get_advapi32()
    kernel32 = _get_kernel32()

    entries = []
    for psid in sid_ptrs:
        ea = _EXPLICIT_ACCESS_W()
        ea.grfAccessPermissions = _GENERIC_ALL
        ea.grfAccessMode = _GRANT_ACCESS
        ea.grfInheritance = 0
        ea.Trustee.pMultipleTrustee = None
        ea.Trustee.MultipleTrusteeOperation = 0
        ea.Trustee.TrusteeForm = _TRUSTEE_IS_SID
        ea.Trustee.TrusteeType = _TRUSTEE_IS_UNKNOWN
        ea.Trustee.ptstrName = psid
        entries.append(ea)

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
        h_token, _TokenDefaultDacl, ctypes.byref(info), ctypes.sizeof(info)
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
    tp.Privileges[0].Attributes = _SE_PRIVILEGE_ENABLED
    advapi32.AdjustTokenPrivileges(
        h_token, False, ctypes.byref(tp), 0, None, None
    )
    # ERROR_NOT_ALL_ASSIGNED = 1300
    return ctypes.get_last_error() != 1300


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

    # Get logon SID from base token
    logon_sid_bytes = _get_logon_sid_bytes(h_base_token)
    logon_buf = (ctypes.c_ubyte * len(logon_sid_bytes))(*logon_sid_bytes)
    logon_ptr = ctypes.cast(logon_buf, ctypes.c_void_p)

    # Create Everyone SID
    everyone_bytes = _create_well_known_sid(_WinWorldSid)
    everyone_buf = (ctypes.c_ubyte * len(everyone_bytes))(*everyone_bytes)
    everyone_ptr = ctypes.cast(everyone_buf, ctypes.c_void_p)

    # Convert capability SID string to PSID
    cap_psid = _string_to_sid(cap_sid_string)

    # Build restricting SID list: [cap_sid, logon_sid, Everyone]
    # NOTE: No user_sid — this is the key difference from the elevated sandbox.
    # Without user_sid, writes are gated ONLY by cap_sid in the target DACL.
    entries = [
        _SID_AND_ATTRIBUTES(Sid=cap_psid, Attributes=0),
        _SID_AND_ATTRIBUTES(Sid=logon_ptr, Attributes=0),
        _SID_AND_ATTRIBUTES(Sid=everyone_ptr, Attributes=0),
    ]
    arr = (_SID_AND_ATTRIBUTES * len(entries))(*entries)

    flags = _DISABLE_MAX_PRIVILEGE | _WRITE_RESTRICTED
    new_token = ctypes.wintypes.HANDLE()
    ok = advapi32.CreateRestrictedToken(
        h_base_token,
        flags,
        0,
        None,  # DisableSidCount, SidsToDisable
        0,
        None,  # DeletePrivilegeCount, PrivilegesToDelete
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
        # Set default DACL: [cap_sid, logon_sid, Everyone] with GENERIC_ALL
        # This allows the sandbox process to create pipes, temp files, etc.
        _set_default_dacl(new_token, [cap_psid, logon_ptr, everyone_ptr])

        # Re-enable SeChangeNotifyPrivilege for path traversal
        if not _enable_privilege(new_token, _SE_CHANGE_NOTIFY_NAME):
            logger.warning("Failed to enable SeChangeNotifyPrivilege on token")
    except Exception:
        kernel32.CloseHandle(new_token)
        kernel32.LocalFree(cap_psid)
        raise

    return new_token, cap_psid


# ═══════════════════════════════════════════════════════════════════════════
# ACL Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _add_write_allow_ace(path: str, cap_psid: ctypes.c_void_p) -> bool:
    """Add an inheritable write-allow ACE for cap_sid on a path.

    Uses WRITE_ALLOW_MASK (RWX+Delete, no FILE_DELETE_CHILD).
    """
    return _set_path_ace(
        path, cap_psid, _WRITE_ALLOW_MASK, _SET_ACCESS, inherit=True
    )


def _add_deny_write_ace(path: str, cap_psid: ctypes.c_void_p) -> bool:
    """Add an inheritable deny-write ACE for cap_sid on a path.

    Uses DENY_WRITE_MASK to comprehensively block write operations.
    """
    return _set_path_ace(
        path, cap_psid, _DENY_WRITE_MASK, _DENY_ACCESS, inherit=True
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
        _SE_FILE_OBJECT,
        _DACL_SECURITY_INFORMATION,
        None,
        None,
        ctypes.byref(p_dacl),
        None,
        ctypes.byref(p_sd),
    )
    if rc != 0:
        logger.warning("GetNamedSecurityInfoW(%s) failed: rc=%d", path, rc)
        return False

    ea = _EXPLICIT_ACCESS_W()
    ea.grfAccessPermissions = access_mask
    ea.grfAccessMode = access_mode
    ea.grfInheritance = (
        (_CONTAINER_INHERIT_ACE | _OBJECT_INHERIT_ACE) if inherit else 0
    )
    ea.Trustee.pMultipleTrustee = None
    ea.Trustee.MultipleTrusteeOperation = 0
    ea.Trustee.TrusteeForm = _TRUSTEE_IS_SID
    ea.Trustee.TrusteeType = _TRUSTEE_IS_UNKNOWN
    ea.Trustee.ptstrName = psid

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
        _SE_FILE_OBJECT,
        _DACL_SECURITY_INFORMATION,
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
# Process Management
# ═══════════════════════════════════════════════════════════════════════════


def _make_env_block(env: Dict[str, str]) -> ctypes.Array:
    """Build a null-terminated Unicode environment block."""
    items = sorted(env.items(), key=lambda kv: kv[0].upper())
    env_str = "\x00".join(f"{k}={v}" for k, v in items) + "\x00\x00"
    return ctypes.create_unicode_buffer(env_str)


def _create_job_object() -> Optional[ctypes.wintypes.HANDLE]:
    """Create a Job Object configured to kill all child processes on close."""
    kernel32 = _get_kernel32()
    h_job = kernel32.CreateJobObjectW(None, None)
    if not h_job:
        return None

    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(
        h_job,
        _JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        kernel32.CloseHandle(h_job)
        return None
    return h_job


def _build_shell_command_line(
    cmd: str, shell_executable: Optional[str] = None
) -> str:
    """Build the full command line for process creation."""
    shell = shell_executable or "cmd.exe"
    shell_lower = shell.lower()

    if "powershell" in shell_lower or "pwsh" in shell_lower:
        # PowerShell: use -NoProfile -NonInteractive -Command
        return f'{shell} -NoProfile -NonInteractive -Command "{cmd}"'
    else:
        # cmd.exe (default)
        return f'cmd.exe /c "{cmd}"'


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

    # Create inheritable pipes for stdout and stderr
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
        raise OSError(f"CreatePipe(stdout) failed: {ctypes.get_last_error()}")
    if not kernel32.CreatePipe(
        ctypes.byref(stderr_read),
        ctypes.byref(stderr_write),
        ctypes.byref(sa),
        0,
    ):
        kernel32.CloseHandle(stdout_read)
        kernel32.CloseHandle(stdout_write)
        raise OSError(f"CreatePipe(stderr) failed: {ctypes.get_last_error()}")

    # Read ends must not be inherited
    kernel32.SetHandleInformation(stdout_read, _HANDLE_FLAG_INHERIT, 0)
    kernel32.SetHandleInformation(stderr_read, _HANDLE_FLAG_INHERIT, 0)

    # Build startup info
    si = _STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.dwFlags = _STARTF_USESTDHANDLES
    si.hStdInput = None
    si.hStdOutput = stdout_write
    si.hStdError = stderr_write
    si.lpDesktop = "WinSta0\\Default"

    # Build environment and command line
    env_block = _make_env_block(env)
    command_line = _build_shell_command_line(cmd, shell_executable)
    cl_buf = ctypes.create_unicode_buffer(command_line)

    pi = _PROCESS_INFORMATION()
    flags = _CREATE_UNICODE_ENVIRONMENT | _CREATE_NO_WINDOW | _CREATE_SUSPENDED

    ok = advapi32.CreateProcessAsUserW(
        h_token,
        None,  # lpApplicationName
        cl_buf,
        None,  # lpProcessAttributes
        None,  # lpThreadAttributes
        True,  # bInheritHandles
        flags,
        ctypes.cast(env_block, ctypes.c_void_p),
        ctypes.c_wchar_p(cwd),
        ctypes.byref(si),
        ctypes.byref(pi),
    )
    err = ctypes.get_last_error() if not ok else 0

    # Close write ends of pipes (parent doesn't need them)
    kernel32.CloseHandle(stdout_write)
    kernel32.CloseHandle(stderr_write)

    if not ok:
        kernel32.CloseHandle(stdout_read)
        kernel32.CloseHandle(stderr_read)
        raise OSError(f"CreateProcessAsUserW failed: error={err}")

    # Assign to job object for process tree management
    h_job = _create_job_object()
    if h_job:
        kernel32.AssignProcessToJobObject(h_job, pi.hProcess)

    # Resume the process (was created suspended for job assignment)
    ctypes.windll.kernel32.ResumeThread(pi.hThread)
    kernel32.CloseHandle(pi.hThread)

    return (pi.dwProcessId, pi.hProcess, stdout_read, stderr_read, h_job)


def _read_pipe(handle: ctypes.wintypes.HANDLE) -> bytes:
    """Drain a pipe handle until EOF."""
    kernel32 = _get_kernel32()
    chunks: List[bytes] = []
    buf = (ctypes.c_ubyte * 8192)()
    bytes_read = ctypes.wintypes.DWORD()

    while True:
        ok = kernel32.ReadFile(
            handle, buf, 8192, ctypes.byref(bytes_read), None
        )
        if not ok or bytes_read.value == 0:
            break
        chunks.append(bytes(buf[: bytes_read.value]))

    return b"".join(chunks)


# ═══════════════════════════════════════════════════════════════════════════
# State Persistence
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
# Public: WindowsUnelevatedSandbox
# ═══════════════════════════════════════════════════════════════════════════


class WindowsUnelevatedSandbox:
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
        self._config = config
        self._h_token: Optional[ctypes.wintypes.HANDLE] = None
        self._cap_psid: Optional[ctypes.c_void_p] = None
        self._cap_sid_string: Optional[str] = None
        self._process_handle: Optional[ctypes.wintypes.HANDLE] = None
        self._job_handle: Optional[ctypes.wintypes.HANDLE] = None
        self._acl_paths: List[str] = []
        self._deny_acl_paths: List[str] = []
        self._initialized = False

    @property
    def config(self) -> SandboxConfig:
        return self._config

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

        # Ensure workspace directory exists
        workspace = self._config.workspace_dir
        os.makedirs(workspace, exist_ok=True)

        # Generate capability SID
        self._cap_sid_string = _make_random_cap_sid_string()
        logger.info(
            "Unelevated sandbox: cap_sid=%s workspace=%s",
            self._cap_sid_string,
            workspace,
        )

        # Open current process token
        h_base = ctypes.wintypes.HANDLE()
        ok = advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), 0x000F01FF, ctypes.byref(h_base)
        )
        if not ok:
            raise OSError(
                f"OpenProcessToken failed: error={ctypes.get_last_error()}"
            )

        try:
            # Create restricted token
            self._h_token, self._cap_psid = _create_restricted_token(
                h_base, self._cap_sid_string
            )
        finally:
            kernel32.CloseHandle(h_base)

        # Apply write-allow ACE on workspace
        if not _add_write_allow_ace(workspace, self._cap_psid):
            logger.error("Failed to set write ACE on workspace: %s", workspace)
        else:
            self._acl_paths.append(workspace)

        # Apply ACEs on mounts.
        # Writable mounts: grant write ACE (same as workspace).
        # Read-only mounts: also grant write ACE to ensure the restricted
        # token can traverse and read the path (required when mount is under
        # a directory like %TEMP% whose DACL may not include Everyone/logon).
        # Write protection on read-only mounts can be enforced by adding
        # them to deny_paths if needed.
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

        # Apply deny-write ACEs on deny_paths (write-deny only; read remains open)
        for deny_path in self._config.deny_paths:
            if os.path.exists(deny_path):
                if _add_deny_write_ace(deny_path, self._cap_psid):
                    self._deny_acl_paths.append(deny_path)
                else:
                    logger.warning("Failed to set deny ACE on: %s", deny_path)

        # Persist state for cleanup
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
            # Build environment
            env = self._build_env()

            # Create process
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

            # Wait and read output
            exit_code, stdout, stderr, timed_out = await asyncio.to_thread(
                self._wait_and_read,
                h_proc,
                h_stdout,
                h_stderr,
                h_job,
            )

            duration_ms = int((time.monotonic() - start) * 1000)

            # Detect sandbox violations
            violation = None
            if exit_code != 0:
                if _VIOLATION_RE.search(stderr):
                    violation = "access denied"
                elif _VIOLATION_RE.search(stdout):
                    violation = "access denied"

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

    def _build_env(self) -> Dict[str, str]:
        """Build the child process environment."""
        env = dict(os.environ)

        # Apply configured env vars
        if self._config.env_vars:
            env.update(self._config.env_vars)

        # Network soft-block via proxy environment variables
        if not self._config.network_allow:
            env["HTTP_PROXY"] = "http://127.0.0.1:9"
            env["HTTPS_PROXY"] = "http://127.0.0.1:9"
            env["NO_PROXY"] = ""
            env["http_proxy"] = "http://127.0.0.1:9"
            env["https_proxy"] = "http://127.0.0.1:9"
            env["no_proxy"] = ""

        # Ensure Python can find its installation
        python_dir = _get_python_install_dir()
        if python_dir:
            env.setdefault("PYTHONHOME", python_dir)

        return env

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

        # Read pipes in threads to avoid deadlock
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            f_stdout = pool.submit(_read_pipe, h_stdout)
            f_stderr = pool.submit(_read_pipe, h_stderr)

            # Wait for process
            wait_result = kernel32.WaitForSingleObject(h_proc, timeout_ms)
            timed_out = wait_result == _WAIT_TIMEOUT

            if timed_out:
                # Kill process tree
                if h_job:
                    kernel32.TerminateJobObject(h_job, 1)
                else:
                    kernel32.TerminateProcess(h_proc, 1)
                # Give it a moment to terminate
                kernel32.WaitForSingleObject(h_proc, 5000)

            stdout_raw = f_stdout.result(timeout=10)
            stderr_raw = f_stderr.result(timeout=10)

        # Get exit code
        exit_code = ctypes.wintypes.DWORD()
        kernel32.GetExitCodeProcess(h_proc, ctypes.byref(exit_code))

        # Close handles
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

        # Kill running process
        if self._process_handle:
            try:
                if self._job_handle:
                    kernel32.TerminateJobObject(self._job_handle, 1)
                else:
                    kernel32.TerminateProcess(self._process_handle, 1)
            except OSError:
                pass

        # Remove ACLs
        if self._cap_sid_string:
            await asyncio.to_thread(self._cleanup_acls)

        # Close token handle
        if self._h_token:
            kernel32.CloseHandle(self._h_token)
            self._h_token = None

        # Free cap SID
        if self._cap_psid:
            kernel32.LocalFree(self._cap_psid)
            self._cap_psid = None

        # Clear persisted state
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
    """Best-effort cleanup of sandbox ACLs on process exit.

    Reads persisted state and removes capability SID ACEs from all paths
    that were modified. Safe to call multiple times and on non-Windows
    platforms (no-op).
    """
    import sys

    if sys.platform != "win32":
        return

    state = _load_state()
    if not state:
        return

    cap_sid = state.get("cap_sid")
    if not cap_sid:
        return

    # Only clean up our own state (check PID)
    saved_pid = state.get("pid")
    if saved_pid and saved_pid != os.getpid():
        # Check if the owning process is still alive
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
                # Owner is still alive, don't clean up
                return
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    all_paths = state.get("acl_paths", []) + state.get("deny_paths", [])
    for path in all_paths:
        if os.path.exists(path):
            _remove_ace_sync(path, cap_sid)

    _clear_state()
    logger.info("Unelevated sandbox cleanup: removed ACEs for %s", cap_sid)


# Register cleanup as atexit handler (safety net)
atexit.register(shutdown_cleanup)
