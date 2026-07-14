# -*- coding: utf-8 -*-
"""Windows restricted-token sandbox implementation (allow_read_all=True).

Uses dedicated local user accounts with CreateRestrictedToken in
WRITE_RESTRICTED mode and WFP firewall rules for native process isolation.
Only write operations check the restricting SID list; read/execute access
uses normal DACL evaluation, so no per-directory read ACEs are needed.

Requires Windows 10 1507+, administrator privileges, and Python ctypes.
"""

import asyncio
import atexit
import base64
import ctypes
import ctypes.wintypes
import hashlib
import json
import logging
import os
import random
import struct
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import ExecutionResult, SandboxConfig
from .windows_sandbox import (
    _VIOLATION_RE,
    _decode_pipe_output,
    _get_python_install_dir,
    _is_admin,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

# Sandbox user group
SANDBOX_USERS_GROUP = "QwenpawUsers"

# CreateRestrictedToken flags
_DISABLE_MAX_PRIVILEGE = 0x01
_LUA_TOKEN = 0x04
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

# Token information classes
_TokenGroups = 2
_TokenUser = 1
_TokenDefaultDacl = 6

# SE_GROUP_LOGON_ID attribute
_SE_GROUP_LOGON_ID = 0xC0000000

# Process creation flags
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_CREATE_NO_WINDOW = 0x08000000
_CREATE_SUSPENDED = 0x00000004
_STARTF_USESTDHANDLES = 0x00000100
_HANDLE_FLAG_INHERIT = 0x00000001

# CreateProcessWithTokenW logon flags
_LOGON_WITH_PROFILE = 0x00000001

# Job Object constants
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JobObjectExtendedLimitInformation = 9

# Wait constants
_WAIT_TIMEOUT = 0x00000102

# Privilege constants
_SE_PRIVILEGE_ENABLED = 0x00000002
_SE_CHANGE_NOTIFY_NAME = "SeChangeNotifyPrivilege"

# LogonUser constants
_LOGON32_LOGON_BATCH = 4
_LOGON32_PROVIDER_DEFAULT = 0

# NetUser constants
_USER_PRIV_USER = 1
_UF_SCRIPT = 0x0001
_UF_DONT_EXPIRE_PASSWD = 0x10000
_NERR_Success = 0
_ERROR_ALIAS_EXISTS = 1379


# ═══════════════════════════════════════════════════════════════════════════
# Cached DLL accessors
# ═══════════════════════════════════════════════════════════════════════════

_dll_kernel32: Optional[Any] = None
_dll_advapi32: Optional[Any] = None
_dll_netapi32: Optional[Any] = None
_dll_user32: Optional[Any] = None
_dll_userenv: Optional[Any] = None


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
        _dll_kernel32.CreateFileW.argtypes = [
            ctypes.wintypes.LPCWSTR,  # lpFileName
            ctypes.wintypes.DWORD,  # dwDesiredAccess
            ctypes.wintypes.DWORD,  # dwShareMode
            ctypes.c_void_p,  # lpSecurityAttributes
            ctypes.wintypes.DWORD,  # dwCreationDisposition
            ctypes.wintypes.DWORD,  # dwFlagsAndAttributes
            ctypes.wintypes.HANDLE,  # hTemplateFile
        ]
        _dll_kernel32.CreateFileW.restype = ctypes.wintypes.HANDLE
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
        _dll_kernel32.OpenProcess.argtypes = [
            ctypes.wintypes.DWORD,  # dwDesiredAccess
            ctypes.wintypes.BOOL,  # bInheritHandle
            ctypes.wintypes.DWORD,  # dwProcessId
        ]
        _dll_kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
        _dll_kernel32.TerminateProcess.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.c_uint,
        ]
        _dll_kernel32.TerminateProcess.restype = ctypes.wintypes.BOOL
        _dll_kernel32.CreateJobObjectW.argtypes = [
            ctypes.c_void_p,  # lpJobAttributes
            ctypes.wintypes.LPCWSTR,  # lpName
        ]
        _dll_kernel32.CreateJobObjectW.restype = ctypes.wintypes.HANDLE
        _dll_kernel32.AssignProcessToJobObject.argtypes = [
            ctypes.wintypes.HANDLE,  # hJob
            ctypes.wintypes.HANDLE,  # hProcess
        ]
        _dll_kernel32.AssignProcessToJobObject.restype = ctypes.wintypes.BOOL
        _dll_kernel32.TerminateJobObject.argtypes = [
            ctypes.wintypes.HANDLE,  # hJob
            ctypes.c_uint,  # uExitCode
        ]
        _dll_kernel32.TerminateJobObject.restype = ctypes.wintypes.BOOL
        _dll_kernel32.SetInformationJobObject.argtypes = [
            ctypes.wintypes.HANDLE,  # hJob
            ctypes.c_int,  # JobObjectInformationClass
            ctypes.c_void_p,  # lpJobObjectInformation
            ctypes.wintypes.DWORD,  # cbJobObjectInformationLength
        ]
        _dll_kernel32.SetInformationJobObject.restype = ctypes.wintypes.BOOL
        _dll_kernel32.GetCurrentThreadId.argtypes = []
        _dll_kernel32.GetCurrentThreadId.restype = ctypes.wintypes.DWORD
        # CreatePipe / SetHandleInformation are used via the default ctypes
        # signatures; they accept varargs comfortably for our usage.
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
            ctypes.wintypes.LPCWSTR,  # pObjectName
            ctypes.wintypes.DWORD,  # ObjectType
            ctypes.wintypes.DWORD,  # SecurityInfo
            ctypes.POINTER(ctypes.c_void_p),  # ppsidOwner (out, nullable)
            ctypes.POINTER(ctypes.c_void_p),  # ppsidGroup (out, nullable)
            ctypes.POINTER(ctypes.c_void_p),  # ppDacl (out, nullable)
            ctypes.POINTER(ctypes.c_void_p),  # ppSacl (out, nullable)
            ctypes.POINTER(ctypes.c_void_p),  # ppSecurityDescriptor (out)
        ]
        _dll_advapi32.GetNamedSecurityInfoW.restype = ctypes.wintypes.DWORD
        _dll_advapi32.SetNamedSecurityInfoW.argtypes = [
            ctypes.wintypes.LPWSTR,  # pObjectName
            ctypes.wintypes.DWORD,  # ObjectType
            ctypes.wintypes.DWORD,  # SecurityInfo
            ctypes.c_void_p,  # psidOwner
            ctypes.c_void_p,  # psidGroup
            ctypes.c_void_p,  # pDacl
            ctypes.c_void_p,  # pSacl
        ]
        _dll_advapi32.SetNamedSecurityInfoW.restype = ctypes.wintypes.DWORD
        _dll_advapi32.SetEntriesInAclW.argtypes = [
            ctypes.wintypes.ULONG,  # cCountOfExplicitEntries
            ctypes.c_void_p,  # pListOfExplicitEntries
            ctypes.c_void_p,  # OldAcl
            ctypes.POINTER(ctypes.c_void_p),  # NewAcl (PACL*, out)
        ]
        _dll_advapi32.SetEntriesInAclW.restype = ctypes.wintypes.DWORD
        _dll_advapi32.ConvertStringSidToSidW.argtypes = [
            ctypes.wintypes.LPCWSTR,  # StringSid
            ctypes.POINTER(ctypes.c_void_p),  # Sid (PSID*, out)
        ]
        _dll_advapi32.ConvertStringSidToSidW.restype = ctypes.wintypes.BOOL
        _dll_advapi32.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,  # Sid (PSID)
            ctypes.POINTER(ctypes.c_wchar_p),  # StringSid (LPWSTR*, out)
        ]
        _dll_advapi32.ConvertSidToStringSidW.restype = ctypes.wintypes.BOOL
        _dll_advapi32.CreateWellKnownSid.argtypes = [
            ctypes.wintypes.DWORD,  # WellKnownSidType
            ctypes.c_void_p,  # DomainSid
            ctypes.c_void_p,  # Sid
            ctypes.POINTER(ctypes.wintypes.DWORD),  # cbSid
        ]
        _dll_advapi32.CreateWellKnownSid.restype = ctypes.wintypes.BOOL
        _dll_advapi32.CreateRestrictedToken.argtypes = [
            ctypes.wintypes.HANDLE,  # ExistingTokenHandle
            ctypes.wintypes.DWORD,  # Flags
            ctypes.wintypes.DWORD,  # DisableSidCount
            ctypes.c_void_p,  # SidsToDisable
            ctypes.wintypes.DWORD,  # DeletePrivilegeCount
            ctypes.c_void_p,  # PrivilegesToDelete
            ctypes.wintypes.DWORD,  # RestrictedSidCount
            ctypes.c_void_p,  # SidsToRestrict
            ctypes.POINTER(ctypes.wintypes.HANDLE),  # NewTokenHandle
        ]
        _dll_advapi32.CreateRestrictedToken.restype = ctypes.wintypes.BOOL
        _dll_advapi32.SetTokenInformation.argtypes = [
            ctypes.wintypes.HANDLE,  # TokenHandle
            ctypes.wintypes.DWORD,  # TokenInformationClass
            ctypes.c_void_p,  # TokenInformation
            ctypes.wintypes.DWORD,  # TokenInformationLength
        ]
        _dll_advapi32.SetTokenInformation.restype = ctypes.wintypes.BOOL
        _dll_advapi32.GetTokenInformation.argtypes = [
            ctypes.wintypes.HANDLE,  # TokenHandle
            ctypes.wintypes.DWORD,  # TokenInformationClass
            ctypes.c_void_p,  # TokenInformation
            ctypes.wintypes.DWORD,  # TokenInformationLength
            ctypes.POINTER(ctypes.wintypes.DWORD),  # ReturnLength
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
        _dll_advapi32.LogonUserW.argtypes = [
            ctypes.wintypes.LPCWSTR,  # lpszUsername
            ctypes.wintypes.LPCWSTR,  # lpszDomain
            ctypes.wintypes.LPCWSTR,  # lpszPassword
            ctypes.wintypes.DWORD,  # dwLogonType
            ctypes.wintypes.DWORD,  # dwLogonProvider
            ctypes.POINTER(ctypes.wintypes.HANDLE),  # phToken
        ]
        _dll_advapi32.LogonUserW.restype = ctypes.wintypes.BOOL
        _dll_advapi32.LookupAccountNameW.argtypes = [
            ctypes.wintypes.LPCWSTR,  # lpSystemName
            ctypes.wintypes.LPCWSTR,  # lpAccountName
            ctypes.c_void_p,  # Sid
            ctypes.POINTER(ctypes.wintypes.DWORD),  # cbSid
            ctypes.wintypes.LPWSTR,  # ReferencedDomainName
            ctypes.POINTER(ctypes.wintypes.DWORD),  # cchReferencedDomainName
            ctypes.POINTER(ctypes.wintypes.DWORD),  # peUse
        ]
        _dll_advapi32.LookupAccountNameW.restype = ctypes.wintypes.BOOL
        _dll_advapi32.CreateProcessAsUserW.argtypes = [
            ctypes.wintypes.HANDLE,  # hToken
            ctypes.wintypes.LPCWSTR,  # lpApplicationName
            ctypes.wintypes.LPWSTR,  # lpCommandLine
            ctypes.c_void_p,  # lpProcessAttributes
            ctypes.c_void_p,  # lpThreadAttributes
            ctypes.wintypes.BOOL,  # bInheritHandles
            ctypes.wintypes.DWORD,  # dwCreationFlags
            ctypes.c_void_p,  # lpEnvironment
            ctypes.wintypes.LPCWSTR,  # lpCurrentDirectory
            ctypes.c_void_p,  # lpStartupInfo
            ctypes.c_void_p,  # lpProcessInformation
        ]
        _dll_advapi32.CreateProcessAsUserW.restype = ctypes.wintypes.BOOL
        _dll_advapi32.CreateProcessWithTokenW.argtypes = [
            ctypes.wintypes.HANDLE,  # hToken
            ctypes.wintypes.DWORD,  # dwLogonFlags
            ctypes.wintypes.LPCWSTR,  # lpApplicationName
            ctypes.wintypes.LPWSTR,  # lpCommandLine
            ctypes.wintypes.DWORD,  # dwCreationFlags
            ctypes.c_void_p,  # lpEnvironment
            ctypes.wintypes.LPCWSTR,  # lpCurrentDirectory
            ctypes.c_void_p,  # lpStartupInfo
            ctypes.c_void_p,  # lpProcessInformation
        ]
        _dll_advapi32.CreateProcessWithTokenW.restype = ctypes.wintypes.BOOL
        _dll_advapi32.GetSecurityInfo.argtypes = [
            ctypes.wintypes.HANDLE,  # handle
            ctypes.wintypes.DWORD,  # ObjectType
            ctypes.wintypes.DWORD,  # SecurityInfo
            ctypes.POINTER(ctypes.c_void_p),  # ppsidOwner
            ctypes.POINTER(ctypes.c_void_p),  # ppsidGroup
            ctypes.POINTER(ctypes.c_void_p),  # ppDacl
            ctypes.POINTER(ctypes.c_void_p),  # ppSacl
            ctypes.POINTER(ctypes.c_void_p),  # ppSecurityDescriptor
        ]
        _dll_advapi32.GetSecurityInfo.restype = ctypes.wintypes.DWORD
        _dll_advapi32.SetSecurityInfo.argtypes = [
            ctypes.wintypes.HANDLE,  # handle
            ctypes.wintypes.DWORD,  # ObjectType
            ctypes.wintypes.DWORD,  # SecurityInfo
            ctypes.c_void_p,  # psidOwner
            ctypes.c_void_p,  # psidGroup
            ctypes.c_void_p,  # pDacl
            ctypes.c_void_p,  # pSacl
        ]
        _dll_advapi32.SetSecurityInfo.restype = ctypes.wintypes.DWORD
        _dll_advapi32.GetSecurityDescriptorDacl.argtypes = [
            ctypes.c_void_p,  # pSecurityDescriptor
            ctypes.POINTER(ctypes.wintypes.BOOL),  # lpbDaclPresent
            ctypes.POINTER(ctypes.c_void_p),  # pDacl (PACL*)
            ctypes.POINTER(ctypes.wintypes.BOOL),  # lpbDaclDefaulted
        ]
        _dll_advapi32.GetSecurityDescriptorDacl.restype = ctypes.wintypes.BOOL
        _dll_advapi32.InitializeSecurityDescriptor.argtypes = [
            ctypes.c_void_p,  # pSecurityDescriptor
            ctypes.wintypes.DWORD,  # dwRevision
        ]
        _dll_advapi32.InitializeSecurityDescriptor.restype = (
            ctypes.wintypes.BOOL
        )
        _dll_advapi32.SetSecurityDescriptorDacl.argtypes = [
            ctypes.c_void_p,  # pSecurityDescriptor
            ctypes.wintypes.BOOL,  # bDaclPresent
            ctypes.c_void_p,  # pDacl
            ctypes.wintypes.BOOL,  # bDaclDefaulted
        ]
        _dll_advapi32.SetSecurityDescriptorDacl.restype = ctypes.wintypes.BOOL
    return _dll_advapi32


def _get_netapi32():
    global _dll_netapi32
    if _dll_netapi32 is None:
        _dll_netapi32 = ctypes.WinDLL("netapi32.dll", use_last_error=True)
    return _dll_netapi32


def _get_user32():
    global _dll_user32
    if _dll_user32 is None:
        _dll_user32 = ctypes.WinDLL("user32.dll", use_last_error=True)
        _dll_user32.GetProcessWindowStation.argtypes = []
        _dll_user32.GetProcessWindowStation.restype = ctypes.wintypes.HANDLE
        _dll_user32.GetThreadDesktop.argtypes = [ctypes.wintypes.DWORD]
        _dll_user32.GetThreadDesktop.restype = ctypes.wintypes.HANDLE
        _dll_user32.GetUserObjectSecurity.argtypes = [
            ctypes.wintypes.HANDLE,  # hObj
            ctypes.POINTER(ctypes.wintypes.DWORD),  # pSIRequested
            ctypes.c_void_p,  # pSD
            ctypes.wintypes.DWORD,  # nLength
            ctypes.POINTER(ctypes.wintypes.DWORD),  # lpnLengthNeeded
        ]
        _dll_user32.GetUserObjectSecurity.restype = ctypes.wintypes.BOOL
        _dll_user32.SetUserObjectSecurity.argtypes = [
            ctypes.wintypes.HANDLE,  # hObj
            ctypes.POINTER(ctypes.wintypes.DWORD),  # pSIRequested
            ctypes.c_void_p,  # pSD
        ]
        _dll_user32.SetUserObjectSecurity.restype = ctypes.wintypes.BOOL
    return _dll_user32


def _get_userenv():
    global _dll_userenv
    if _dll_userenv is None:
        _dll_userenv = ctypes.WinDLL("userenv.dll", use_last_error=True)
        _dll_userenv.CreateProfile.argtypes = [
            ctypes.wintypes.LPCWSTR,  # pszUserSid
            ctypes.wintypes.LPCWSTR,  # pszUserName
            ctypes.c_wchar_p,  # pszProfilePath (out buffer)
            ctypes.wintypes.DWORD,  # cchProfilePath
        ]
        _dll_userenv.CreateProfile.restype = ctypes.wintypes.LONG  # HRESULT
        _dll_userenv.GetUserProfileDirectoryW.argtypes = [
            ctypes.wintypes.HANDLE,  # hToken
            ctypes.c_wchar_p,  # lpProfileDir (out buffer)
            ctypes.POINTER(ctypes.wintypes.DWORD),  # lpcchSize (in/out)
        ]
        _dll_userenv.GetUserProfileDirectoryW.restype = ctypes.wintypes.BOOL
    return _dll_userenv


# ═══════════════════════════════════════════════════════════════════════════
# SID utilities
# ═══════════════════════════════════════════════════════════════════════════


def _make_random_cap_sid_string() -> str:
    """Generates a random capability SID in the S-1-5-21-* namespace."""
    a = random.randint(0, 0xFFFFFFFF)
    b = random.randint(0, 0xFFFFFFFF)
    c = random.randint(0, 0xFFFFFFFF)
    d = random.randint(0, 0xFFFFFFFF)
    return f"S-1-5-21-{a}-{b}-{c}-{d}"


def _string_to_sid(sid_string: str) -> ctypes.c_void_p:
    """Converts a SID string to a PSID pointer.

    Caller must free with LocalFree.
    """
    advapi32 = _get_advapi32()
    psid = ctypes.c_void_p()
    ret = advapi32.ConvertStringSidToSidW(
        ctypes.c_wchar_p(sid_string),
        ctypes.byref(psid),
    )
    if not ret:
        raise OSError(
            f"ConvertStringSidToSidW failed for '{sid_string}': "
            f"error={ctypes.get_last_error()}",
        )
    return psid


def _sid_to_string(psid: ctypes.c_void_p) -> str:
    """Converts a PSID pointer to its string representation."""
    advapi32 = _get_advapi32()
    string_sid = ctypes.c_wchar_p()
    ret = advapi32.ConvertSidToStringSidW(psid, ctypes.byref(string_sid))
    if not ret:
        raise OSError(
            f"ConvertSidToStringSidW failed: error={ctypes.get_last_error()}",
        )
    try:
        sid_value = string_sid.value
        if sid_value is None:
            raise OSError("ConvertSidToStringSidW returned NULL")
        return sid_value
    finally:
        _get_kernel32().LocalFree(string_sid)


def _create_well_known_sid(sid_type: int) -> bytes:
    """Creates a well-known SID (e.g. Everyone = WinWorldSid = 1)."""
    advapi32 = _get_advapi32()
    size = ctypes.c_uint32(0)
    advapi32.CreateWellKnownSid(sid_type, None, None, ctypes.byref(size))
    buf = (ctypes.c_ubyte * size.value)()
    ok = advapi32.CreateWellKnownSid(sid_type, None, buf, ctypes.byref(size))
    if not ok:
        raise OSError(
            f"CreateWellKnownSid failed: error={ctypes.get_last_error()}",
        )
    return bytes(buf)


def _lookup_account_sid(
    account_name: str,
) -> Optional[Tuple[ctypes.Array, int]]:
    """Resolves an account name to a SID buffer via LookupAccountNameW.

    Returns (sid_buf, sid_size) or None if the account is not found.
    The returned sid_buf can be cast to ctypes.c_void_p for use as a PSID.
    """
    advapi32 = _get_advapi32()
    sid_size = ctypes.wintypes.DWORD(0)
    domain_size = ctypes.wintypes.DWORD(0)
    sid_use = ctypes.wintypes.DWORD(0)
    advapi32.LookupAccountNameW(
        None,
        ctypes.c_wchar_p(account_name),
        None,
        ctypes.byref(sid_size),
        None,
        ctypes.byref(domain_size),
        ctypes.byref(sid_use),
    )
    if sid_size.value == 0:
        return None
    sid_buf = (ctypes.c_ubyte * sid_size.value)()
    domain_buf = ctypes.create_unicode_buffer(domain_size.value)
    ok = advapi32.LookupAccountNameW(
        None,
        ctypes.c_wchar_p(account_name),
        sid_buf,
        ctypes.byref(sid_size),
        domain_buf,
        ctypes.byref(domain_size),
        ctypes.byref(sid_use),
    )
    if not ok:
        return None
    return sid_buf, sid_size.value


# ═══════════════════════════════════════════════════════════════════════════
# Sandbox user provisioning
# ═══════════════════════════════════════════════════════════════════════════


def _random_password(length: int = 24) -> str:
    """Generates a random password for the sandbox user account."""
    chars = (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        "0123456789!@#$%^&*()-_=+"
    )
    return "".join(random.choice(chars) for _ in range(length))


class _DATA_BLOB(ctypes.Structure):
    """Win32 DATA_BLOB structure for DPAPI calls."""

    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.c_void_p),
    ]


def _local_free(ptr: int) -> None:
    """Calls kernel32.LocalFree with correct pointer type for 64-bit."""
    ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(ptr))


def _dpapi_encrypt(plaintext: str) -> str:
    """Encrypts a string using DPAPI (current user scope).

    Returns a base64-encoded ciphertext string. Only the same Windows
    user account that encrypted the data can decrypt it.
    """
    data = plaintext.encode("utf-8")
    blob_in = _DATA_BLOB(
        cbData=len(data),
        pbData=ctypes.cast(
            (ctypes.c_byte * len(data))(*data),
            ctypes.c_void_p,
        ),
    )
    blob_out = _DATA_BLOB()

    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        None,  # description
        None,  # optional entropy
        None,  # reserved
        None,  # prompt struct
        0,  # flags
        ctypes.byref(blob_out),
    ):
        raise OSError(
            f"CryptProtectData failed: error={ctypes.get_last_error()}",
        )

    try:
        enc_bytes = (ctypes.c_byte * blob_out.cbData).from_address(
            blob_out.pbData,
        )
        return base64.b64encode(bytes(enc_bytes)).decode("ascii")
    finally:
        _local_free(blob_out.pbData)


def _dpapi_decrypt(ciphertext_b64: str) -> str:
    """Decrypts a DPAPI-protected base64-encoded string.

    Returns the original plaintext. Raises OSError if decryption fails
    (e.g. different user account or corrupted data).
    """
    data = base64.b64decode(ciphertext_b64)
    blob_in = _DATA_BLOB(
        cbData=len(data),
        pbData=ctypes.cast(
            (ctypes.c_byte * len(data))(*data),
            ctypes.c_void_p,
        ),
    )
    blob_out = _DATA_BLOB()

    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,  # description out
        None,  # optional entropy
        None,  # reserved
        None,  # prompt struct
        0,  # flags
        ctypes.byref(blob_out),
    ):
        raise OSError(
            f"CryptUnprotectData failed: error={ctypes.get_last_error()}",
        )

    try:
        dec_bytes = (ctypes.c_byte * blob_out.cbData).from_address(
            blob_out.pbData,
        )
        return bytes(dec_bytes).decode("utf-8")
    finally:
        _local_free(blob_out.pbData)


class _USER_INFO_1(ctypes.Structure):
    _fields_ = [
        ("usri1_name", ctypes.c_wchar_p),
        ("usri1_password", ctypes.c_wchar_p),
        ("usri1_password_age", ctypes.wintypes.DWORD),
        ("usri1_priv", ctypes.wintypes.DWORD),
        ("usri1_home_dir", ctypes.c_wchar_p),
        ("usri1_comment", ctypes.c_wchar_p),
        ("usri1_flags", ctypes.wintypes.DWORD),
        ("usri1_script_path", ctypes.c_wchar_p),
    ]


class _USER_INFO_1003(ctypes.Structure):
    _fields_ = [
        ("usri1003_password", ctypes.c_wchar_p),
    ]


class _LOCALGROUP_INFO_1(ctypes.Structure):
    _fields_ = [
        ("lgrpi1_name", ctypes.c_wchar_p),
        ("lgrpi1_comment", ctypes.c_wchar_p),
    ]


class _LOCALGROUP_MEMBERS_INFO_3(ctypes.Structure):
    _fields_ = [
        ("lgrmi3_domainandname", ctypes.c_wchar_p),
    ]


def _ensure_local_group(name: str, comment: str) -> bool:
    """Creates a local group if it doesn't already exist."""
    netapi32 = _get_netapi32()
    info = _LOCALGROUP_INFO_1(lgrpi1_name=name, lgrpi1_comment=comment)
    parm_err = ctypes.c_uint32(0)
    status = netapi32.NetLocalGroupAdd(
        None,
        1,
        ctypes.byref(info),
        ctypes.byref(parm_err),
    )
    if status in (_NERR_Success, _ERROR_ALIAS_EXISTS, 2223):
        return True
    logger.warning("NetLocalGroupAdd failed for %s: code %d", name, status)
    return False


def _ensure_local_user(username: str, password: str) -> bool:
    """Creates a local user account or updates its password if it exists."""
    netapi32 = _get_netapi32()
    info = _USER_INFO_1(
        usri1_name=username,
        usri1_password=password,
        usri1_password_age=0,
        usri1_priv=_USER_PRIV_USER,
        usri1_home_dir=None,
        usri1_comment=None,
        usri1_flags=_UF_SCRIPT | _UF_DONT_EXPIRE_PASSWD,
        usri1_script_path=None,
    )
    status = netapi32.NetUserAdd(None, 1, ctypes.byref(info), None)
    if status == _NERR_Success:
        return True

    # User may already exist — update password
    pw_info = _USER_INFO_1003(usri1003_password=password)
    upd = netapi32.NetUserSetInfo(
        None,
        ctypes.c_wchar_p(username),
        1003,
        ctypes.byref(pw_info),
        None,
    )
    if upd != _NERR_Success:
        logger.warning(
            "Failed to create/update user %s: create=%d, update=%d",
            username,
            status,
            upd,
        )
        return False
    return True


def _ensure_group_member(group_name: str, username: str) -> None:
    """Adds a user to a local group (silently ignores if already a member)."""
    netapi32 = _get_netapi32()
    member = _LOCALGROUP_MEMBERS_INFO_3(lgrmi3_domainandname=username)
    netapi32.NetLocalGroupAddMembers(
        None,
        ctypes.c_wchar_p(group_name),
        3,
        ctypes.byref(member),
        1,
    )


class _LSA_OBJECT_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.c_ulong),
        ("RootDirectory", ctypes.wintypes.HANDLE),
        ("ObjectName", ctypes.c_void_p),
        ("Attributes", ctypes.c_ulong),
        ("SecurityDescriptor", ctypes.c_void_p),
        ("SecurityQualityOfService", ctypes.c_void_p),
    ]


class _LSA_UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.c_ushort),
        ("MaximumLength", ctypes.c_ushort),
        ("Buffer", ctypes.c_wchar_p),
    ]


def _grant_batch_logon_right(username: str) -> None:
    """Grants SeBatchLogonRight to the specified user via LSA policy.

    Required for ``LogonUserW`` with ``LOGON32_LOGON_BATCH`` to succeed.
    """
    advapi32 = _get_advapi32()

    result = _lookup_account_sid(username)
    if result is None:
        raise OSError(
            f"LookupAccountNameW failed for '{username}': "
            f"error={ctypes.get_last_error()}",
        )
    sid_buf, _ = result
    psid = ctypes.cast(sid_buf, ctypes.c_void_p)

    # Open LSA policy
    obj_attrs = _LSA_OBJECT_ATTRIBUTES()
    obj_attrs.Length = ctypes.sizeof(_LSA_OBJECT_ATTRIBUTES)
    policy_handle = ctypes.wintypes.HANDLE()
    _POLICY_LOOKUP_NAMES = 0x00000800
    _POLICY_CREATE_ACCOUNT = 0x00000010
    status = advapi32.LsaOpenPolicy(
        None,
        ctypes.byref(obj_attrs),
        _POLICY_LOOKUP_NAMES | _POLICY_CREATE_ACCOUNT,
        ctypes.byref(policy_handle),
    )
    if status != 0:
        raise OSError(
            f"LsaOpenPolicy failed: NTSTATUS=0x{status & 0xFFFFFFFF:08X}",
        )

    try:
        priv_name = "SeBatchLogonRight"
        priv_str = _LSA_UNICODE_STRING()
        priv_str.Buffer = priv_name
        priv_str.Length = len(priv_name) * 2
        priv_str.MaximumLength = (len(priv_name) + 1) * 2

        status = advapi32.LsaAddAccountRights(
            policy_handle,
            psid,
            ctypes.byref(priv_str),
            1,
        )
        if status != 0:
            raise OSError(
                f"LsaAddAccountRights failed for '{username}': "
                f"NTSTATUS=0x{status & 0xFFFFFFFF:08X}",
            )
    finally:
        advapi32.LsaClose(policy_handle)


def _provision_sandbox_user(username: str, password: str) -> bool:
    """Provisions a sandbox user account and adds it to the sandbox group."""
    _ensure_local_group(
        SANDBOX_USERS_GROUP,
        "QwenPaw sandbox internal group (managed)",
    )
    if not _ensure_local_user(username, password):
        return False
    _ensure_group_member(SANDBOX_USERS_GROUP, username)
    _grant_batch_logon_right(username)
    return True


# ═══════════════════════════════════════════════════════════════════════════
# LogonUser (authenticate as sandbox user)
# ═══════════════════════════════════════════════════════════════════════════


def _logon_user(username: str, password: str) -> ctypes.wintypes.HANDLE:
    """Logs on as the specified user and returns the token handle.

    Uses ``LOGON32_LOGON_BATCH`` which is appropriate for non-interactive
    service processes and does not require the "Log on locally" user right.
    """
    advapi32 = _get_advapi32()
    h_token = ctypes.wintypes.HANDLE()
    ok = advapi32.LogonUserW(
        ctypes.c_wchar_p(username),
        ctypes.c_wchar_p("."),  # local machine
        ctypes.c_wchar_p(password),
        _LOGON32_LOGON_BATCH,
        _LOGON32_PROVIDER_DEFAULT,
        ctypes.byref(h_token),
    )
    if not ok:
        raise OSError(
            f"LogonUserW failed for '{username}': "
            f"error={ctypes.get_last_error()}",
        )
    return h_token


def _create_user_profile(user_sid_string: str, username: str) -> Optional[str]:
    """Creates a user profile via userenv.dll CreateProfile.

    Returns the profile directory path, or None on failure.
    This properly registers the profile in the Windows profile list
    registry (HKLM\\...\\ProfileList) so that LOGON_WITH_PROFILE will
    not create a suffixed directory.
    """
    userenv = _get_userenv()
    buf = ctypes.create_unicode_buffer(260)
    hr = userenv.CreateProfile(
        ctypes.c_wchar_p(user_sid_string),
        ctypes.c_wchar_p(username),
        buf,
        ctypes.wintypes.DWORD(260),
    )
    if hr == 0:  # S_OK
        profile_path = buf.value
        logger.debug("CreateProfile succeeded: %s", profile_path)
        return profile_path
    elif hr == -2147024713:  # 0x800700B7 - ERROR_ALREADY_EXISTS as HRESULT
        logger.debug(
            "CreateProfile: profile already exists for %s (HRESULT=0x%08X)",
            username,
            hr & 0xFFFFFFFF,
        )
        return None
    else:
        logger.warning(
            "CreateProfile failed for %s (HRESULT=0x%08X)",
            username,
            hr & 0xFFFFFFFF,
        )
        return None


def _get_profile_directory(h_token: ctypes.wintypes.HANDLE) -> Optional[str]:
    """Gets the profile directory for a token using GetUserProfileDirectoryW.

    Returns the profile path or None if it cannot be determined.
    """
    userenv = _get_userenv()
    size = ctypes.wintypes.DWORD(0)
    # First call to get the required buffer size.
    userenv.GetUserProfileDirectoryW(h_token, None, ctypes.byref(size))
    if size.value == 0:
        return None
    buf = ctypes.create_unicode_buffer(size.value)
    ok = userenv.GetUserProfileDirectoryW(h_token, buf, ctypes.byref(size))
    if ok:
        return buf.value
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Token creation
# ═══════════════════════════════════════════════════════════════════════════


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Sid", ctypes.c_void_p),
        ("Attributes", ctypes.wintypes.DWORD),
    ]


def _get_token_info_raw(
    h_token: ctypes.wintypes.HANDLE,
    info_class: int,
    label: str,
) -> ctypes.Array:
    """Two-pass GetTokenInformation: returns the raw buffer."""
    advapi32 = _get_advapi32()
    needed = ctypes.c_uint32(0)
    advapi32.GetTokenInformation(
        h_token,
        info_class,
        None,
        0,
        ctypes.byref(needed),
    )
    if needed.value == 0:
        raise OSError(f"GetTokenInformation({label}) size query returned 0")
    buf = (ctypes.c_ubyte * needed.value)()
    ok = advapi32.GetTokenInformation(
        h_token,
        info_class,
        buf,
        needed.value,
        ctypes.byref(needed),
    )
    if not ok:
        raise OSError(
            f"GetTokenInformation({label}) failed: "
            f"error={ctypes.get_last_error()}",
        )
    return buf


def _copy_sid_from_ptr(sid_ptr_val: int) -> bytes:
    """Copies a SID from a raw pointer value into a bytes object."""
    advapi32 = _get_advapi32()
    psid = ctypes.c_void_p(sid_ptr_val)
    sid_len = advapi32.GetLengthSid(psid)
    if sid_len == 0:
        return b""
    sid_buf = (ctypes.c_ubyte * sid_len)()
    advapi32.CopySid(sid_len, sid_buf, psid)
    return bytes(sid_buf)


def _get_logon_sid_bytes(h_token: ctypes.wintypes.HANDLE) -> bytes:
    """Extracts the logon SID bytes from a token."""
    buf = _get_token_info_raw(h_token, _TokenGroups, "TokenGroups")

    # Parse TOKEN_GROUPS
    group_count = struct.unpack_from("<I", bytes(buf), 0)[0]
    ptr_size = ctypes.sizeof(ctypes.c_void_p)
    sa_size = 16 if ptr_size == 8 else 8
    offset = (4 + ptr_size - 1) & ~(ptr_size - 1)

    for i in range(group_count):
        entry_offset = offset + i * sa_size
        if ptr_size == 8:
            sid_ptr_val = struct.unpack_from("<Q", bytes(buf), entry_offset)[0]
            attrs = struct.unpack_from("<I", bytes(buf), entry_offset + 8)[0]
        else:
            sid_ptr_val = struct.unpack_from("<I", bytes(buf), entry_offset)[0]
            attrs = struct.unpack_from("<I", bytes(buf), entry_offset + 4)[0]

        if (attrs & _SE_GROUP_LOGON_ID) == _SE_GROUP_LOGON_ID:
            sid_bytes = _copy_sid_from_ptr(sid_ptr_val)
            if sid_bytes:
                return sid_bytes

    raise OSError("Logon SID not found in token groups")


def _get_user_sid_bytes(h_token: ctypes.wintypes.HANDLE) -> bytes:
    """Extracts the user SID bytes from a token."""
    buf = _get_token_info_raw(h_token, _TokenUser, "TokenUser")

    ptr_size = ctypes.sizeof(ctypes.c_void_p)
    if ptr_size == 8:
        sid_ptr_val = struct.unpack_from("<Q", bytes(buf), 0)[0]
    else:
        sid_ptr_val = struct.unpack_from("<I", bytes(buf), 0)[0]

    sid_bytes = _copy_sid_from_ptr(sid_ptr_val)
    if not sid_bytes:
        raise OSError("GetLengthSid(TokenUser) failed")
    return sid_bytes


def _create_restricted_token(
    h_base_token: ctypes.wintypes.HANDLE,
    cap_sid_strings: List[str],
) -> ctypes.wintypes.HANDLE:
    """Creates a WRITE_RESTRICTED token with capability SIDs.

    In WRITE_RESTRICTED mode only WRITE access checks the restricting SID
    list; read/execute access uses normal DACL evaluation, so reads work
    automatically without per-path read ACEs. Write checks require a matching
    restricting SID in the target object's DACL.

    The restricting SID list includes:
      [capabilities..., user_sid, logon_sid, Everyone]
    """
    advapi32 = _get_advapi32()
    kernel32 = _get_kernel32()

    logon_sid_bytes = _get_logon_sid_bytes(h_base_token)
    user_sid_bytes = _get_user_sid_bytes(h_base_token)

    # Build restricting SID list
    sid_buffers: List[Any] = []
    entries: List[_SID_AND_ATTRIBUTES] = []
    cap_psids: List[ctypes.c_void_p] = []

    # 1. Capability SIDs
    for sid_str in cap_sid_strings:
        psid = _string_to_sid(sid_str)
        cap_psids.append(psid)
        entries.append(_SID_AND_ATTRIBUTES(Sid=psid, Attributes=0))

    # 2. User SID (sandbox user's SID — gates write checks for the user)
    user_buf = (ctypes.c_ubyte * len(user_sid_bytes))(*user_sid_bytes)
    sid_buffers.append(user_buf)
    user_ptr = ctypes.cast(user_buf, ctypes.c_void_p)
    entries.append(_SID_AND_ATTRIBUTES(Sid=user_ptr, Attributes=0))

    # 3. Logon SID
    logon_buf = (ctypes.c_ubyte * len(logon_sid_bytes))(*logon_sid_bytes)
    sid_buffers.append(logon_buf)
    logon_ptr = ctypes.cast(logon_buf, ctypes.c_void_p)
    entries.append(_SID_AND_ATTRIBUTES(Sid=logon_ptr, Attributes=0))

    # 4. Everyone SID — must be present so write checks are gated by the
    #    restricting SIDs in WRITE_RESTRICTED mode.
    _WinWorldSid = 1
    everyone_bytes = _create_well_known_sid(_WinWorldSid)
    everyone_buf = (ctypes.c_ubyte * len(everyone_bytes))(*everyone_bytes)
    sid_buffers.append(everyone_buf)
    everyone_ptr = ctypes.cast(everyone_buf, ctypes.c_void_p)
    entries.append(_SID_AND_ATTRIBUTES(Sid=everyone_ptr, Attributes=0))

    array_type = _SID_AND_ATTRIBUTES * len(entries)
    restricting_sids = array_type(*entries)
    flags = _DISABLE_MAX_PRIVILEGE | _LUA_TOKEN | _WRITE_RESTRICTED
    new_token = ctypes.wintypes.HANDLE()
    ok = advapi32.CreateRestrictedToken(
        h_base_token,
        flags,
        0,
        None,  # DisableSidCount, SidsToDisable
        0,
        None,  # DeletePrivilegeCount, PrivilegesToDelete
        len(entries),
        ctypes.cast(restricting_sids, ctypes.POINTER(_SID_AND_ATTRIBUTES)),
        ctypes.byref(new_token),
    )
    if not ok:
        for psid in cap_psids:
            kernel32.LocalFree(psid)
        raise OSError(
            f"CreateRestrictedToken failed: error={ctypes.get_last_error()}",
        )

    # Set default DACL and enable traversal privilege. If either fails,
    # close the newly created token to avoid handle leaks.
    try:
        # Set default DACL (logon + capabilities — allows pipe/IPC creation)
        dacl_sids = [logon_ptr] + cap_psids
        _set_default_dacl(new_token, dacl_sids)

        # Enable SeChangeNotifyPrivilege (path traversal)
        _enable_privilege(new_token, _SE_CHANGE_NOTIFY_NAME)
    except Exception:
        kernel32.CloseHandle(new_token)
        raise
    finally:
        # Free capability SIDs regardless of success/failure
        for psid in cap_psids:
            kernel32.LocalFree(psid)

    return new_token


# ═══════════════════════════════════════════════════════════════════════════
# Token helper functions
# ═══════════════════════════════════════════════════════════════════════════


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


def _build_explicit_access(
    psid: ctypes.c_void_p,
    access_mask: int,
    access_mode: int,
    inheritance: int = 0,
) -> _EXPLICIT_ACCESS_W:
    entry = _EXPLICIT_ACCESS_W()
    entry.grfAccessPermissions = access_mask
    entry.grfAccessMode = access_mode
    entry.grfInheritance = inheritance
    entry.Trustee.pMultipleTrustee = None
    entry.Trustee.MultipleTrusteeOperation = 0
    entry.Trustee.TrusteeForm = _TRUSTEE_IS_SID
    entry.Trustee.TrusteeType = _TRUSTEE_IS_UNKNOWN
    entry.Trustee.ptstrName = psid
    return entry


class _TOKEN_DEFAULT_DACL(ctypes.Structure):
    _fields_ = [("DefaultDacl", ctypes.c_void_p)]


class _TOKEN_PRIVILEGES(ctypes.Structure):
    class _LUID(ctypes.Structure):
        _fields_ = [
            ("LowPart", ctypes.wintypes.DWORD),
            ("HighPart", ctypes.c_long),
        ]

    class _LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("Luid_LowPart", ctypes.wintypes.DWORD),
            ("Luid_HighPart", ctypes.c_long),
            ("Attributes", ctypes.wintypes.DWORD),
        ]

    _fields_ = [
        ("PrivilegeCount", ctypes.wintypes.DWORD),
        ("Privileges", _LUID_AND_ATTRIBUTES * 1),
    ]


def _set_default_dacl(
    h_token: ctypes.wintypes.HANDLE,
    sids: List[ctypes.c_void_p],
) -> None:
    """Sets a permissive default DACL for pipe/IPC creation."""
    advapi32 = _get_advapi32()
    kernel32 = _get_kernel32()
    if not sids:
        return

    built = [
        _build_explicit_access(sid, _GENERIC_ALL, _GRANT_ACCESS)
        for sid in sids
    ]
    entries = (_EXPLICIT_ACCESS_W * len(sids))(*built)

    p_new_dacl = ctypes.c_void_p()
    res = advapi32.SetEntriesInAclW(
        len(sids),
        ctypes.cast(entries, ctypes.c_void_p),
        None,
        ctypes.byref(p_new_dacl),
    )
    if res != 0:
        logger.warning("SetEntriesInAclW for default DACL failed: %d", res)
        return

    info = _TOKEN_DEFAULT_DACL(DefaultDacl=p_new_dacl)
    advapi32.SetTokenInformation(
        h_token,
        _TokenDefaultDacl,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if p_new_dacl:
        kernel32.LocalFree(p_new_dacl)


def _enable_privilege(h_token: ctypes.wintypes.HANDLE, name: str) -> bool:
    """Enables a single privilege on a token. Returns True if successful."""
    advapi32 = _get_advapi32()
    luid = _TOKEN_PRIVILEGES._LUID()  # pylint: disable=protected-access
    ok = advapi32.LookupPrivilegeValueW(
        None,
        ctypes.c_wchar_p(name),
        ctypes.byref(luid),
    )
    if not ok:
        logger.debug(
            "LookupPrivilegeValueW failed for %s: %d",
            name,
            ctypes.get_last_error(),
        )
        return False
    tp = _TOKEN_PRIVILEGES()
    tp.PrivilegeCount = 1
    tp.Privileges[0].Luid_LowPart = luid.LowPart
    tp.Privileges[0].Luid_HighPart = luid.HighPart
    tp.Privileges[0].Attributes = _SE_PRIVILEGE_ENABLED
    ok = advapi32.AdjustTokenPrivileges(
        h_token,
        False,
        ctypes.byref(tp),
        0,
        None,
        None,
    )
    # AdjustTokenPrivileges returns TRUE even on partial failure; must check
    # GetLastError for ERROR_NOT_ALL_ASSIGNED (1300).
    err = ctypes.get_last_error()
    if not ok or err == 1300:
        logger.debug("AdjustTokenPrivileges failed for %s: err=%d", name, err)
        return False
    return True


# ═══════════════════════════════════════════════════════════════════════════
# ACL management via Win32 API
# ═══════════════════════════════════════════════════════════════════════════


_privileges_enabled = False


def _ensure_privileges() -> None:
    """Enables all required privileges on the current process token.

    Combines ACL privileges (SeRestore/SeBackup/SeTakeOwnership),
    process-creation privileges (SeImpersonate for CreateProcessWithTokenW,
    SeAssignPrimaryToken/SeIncreaseQuota as fallback for
    CreateProcessAsUserW).
    Idempotent — runs once per process lifetime.
    """
    global _privileges_enabled
    if _privileges_enabled:
        return

    advapi32 = _get_advapi32()
    kernel32 = _get_kernel32()

    _TOKEN_ADJUST_PRIVILEGES = 0x0020
    _TOKEN_QUERY = 0x0008
    h_process_token = ctypes.wintypes.HANDLE()
    ok = advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        _TOKEN_ADJUST_PRIVILEGES | _TOKEN_QUERY,
        ctypes.byref(h_process_token),
    )
    if not ok:
        return

    try:
        for priv_name in (
            "SeRestorePrivilege",
            "SeBackupPrivilege",
            "SeTakeOwnershipPrivilege",
            "SeImpersonatePrivilege",
            "SeAssignPrimaryTokenPrivilege",
            "SeIncreaseQuotaPrivilege",
        ):
            if not _enable_privilege(h_process_token, priv_name):
                logger.debug("Could not enable %s", priv_name)
        _privileges_enabled = True
    finally:
        kernel32.CloseHandle(h_process_token)


def _set_path_ace(
    path: str,
    psid: ctypes.c_void_p,
    access_mask: int,
    access_mode: int,
) -> bool:
    """Sets a single ACE on a filesystem path's DACL.

    Common implementation for all ACL operations (allow-read, allow-full,
    deny-all). The ACE is set with inheritable flags and
    ``SetNamedSecurityInfoW`` propagates it to all existing child objects.
    """
    _ensure_privileges()
    advapi32 = _get_advapi32()
    kernel32 = _get_kernel32()

    p_sd = ctypes.c_void_p()
    p_dacl = ctypes.c_void_p()
    code = advapi32.GetNamedSecurityInfoW(
        ctypes.c_wchar_p(path),
        _SE_FILE_OBJECT,
        _DACL_SECURITY_INFORMATION,
        None,
        None,
        ctypes.byref(p_dacl),
        None,
        ctypes.byref(p_sd),
    )
    if code != 0:
        logger.warning("GetNamedSecurityInfoW failed for %s: %d", path, code)
        return False

    entry = _build_explicit_access(
        psid,
        access_mask,
        access_mode,
        _CONTAINER_INHERIT_ACE | _OBJECT_INHERIT_ACE,
    )

    p_new_dacl = ctypes.c_void_p()
    code2 = advapi32.SetEntriesInAclW(
        1,
        ctypes.byref(entry),
        p_dacl,
        ctypes.byref(p_new_dacl),
    )
    if code2 != 0:
        if p_sd:
            kernel32.LocalFree(p_sd)
        logger.warning("SetEntriesInAclW failed for %s: %d", path, code2)
        return False

    code3 = advapi32.SetNamedSecurityInfoW(
        ctypes.c_wchar_p(path),
        _SE_FILE_OBJECT,
        _DACL_SECURITY_INFORMATION,
        None,
        None,
        p_new_dacl,
        None,
    )

    ok = code3 == 0

    if p_new_dacl:
        kernel32.LocalFree(p_new_dacl)
    if p_sd:
        kernel32.LocalFree(p_sd)

    if not ok:
        logger.warning("SetNamedSecurityInfoW failed for %s: %d", path, code3)

    return ok


# ── Access mask constants for ACE helpers ──

_ACL_READ_EXECUTE = _FILE_GENERIC_READ | _FILE_GENERIC_EXECUTE

_ACL_FULL_ACCESS = (
    _FILE_GENERIC_READ
    | _FILE_GENERIC_WRITE
    | _FILE_GENERIC_EXECUTE
    | _DELETE
    | _FILE_DELETE_CHILD
)

_ACL_DENY_ALL = _ACL_FULL_ACCESS | _GENERIC_ALL


# ── Public ACE helpers (thin wrappers) ──


def _add_allow_ace(path: str, psid: ctypes.c_void_p) -> bool:
    """Grants full read+write+execute+delete access."""
    return _set_path_ace(path, psid, _ACL_FULL_ACCESS, _SET_ACCESS)


def _add_allow_read_ace(path: str, psid: ctypes.c_void_p) -> bool:
    """Grants read+execute (no write) access."""
    return _set_path_ace(path, psid, _ACL_READ_EXECUTE, _SET_ACCESS)


def _add_deny_all_ace(path: str, psid: ctypes.c_void_p) -> bool:
    """Denies all access (read+write+execute+delete)."""
    return _set_path_ace(path, psid, _ACL_DENY_ALL, _DENY_ACCESS)


def _allow_null_device(psid: ctypes.c_void_p) -> None:
    """Grants RX to the null device (NUL) for the given SID."""
    kernel32 = _get_kernel32()
    advapi32 = _get_advapi32()

    desired = 0x00020000 | 0x00040000  # READ_CONTROL | WRITE_DAC
    h = kernel32.CreateFileW(
        ctypes.c_wchar_p(r"\\.\NUL"),
        desired,
        0x00000001 | 0x00000002,
        None,
        3,
        0x00000080,
        0,
    )
    if not h or h == ctypes.c_void_p(-1).value:
        return

    _SE_KERNEL_OBJECT = 6
    p_sd = ctypes.c_void_p()
    p_dacl = ctypes.c_void_p()
    code = advapi32.GetSecurityInfo(
        h,
        _SE_KERNEL_OBJECT,
        _DACL_SECURITY_INFORMATION,
        None,
        None,
        ctypes.byref(p_dacl),
        None,
        ctypes.byref(p_sd),
    )
    if code == 0:
        entry = _build_explicit_access(
            psid,
            _FILE_GENERIC_READ | _FILE_GENERIC_WRITE | _FILE_GENERIC_EXECUTE,
            _SET_ACCESS,
        )

        p_new_dacl = ctypes.c_void_p()
        code2 = advapi32.SetEntriesInAclW(
            1,
            ctypes.byref(entry),
            p_dacl,
            ctypes.byref(p_new_dacl),
        )
        if code2 == 0:
            advapi32.SetSecurityInfo(
                h,
                _SE_KERNEL_OBJECT,
                _DACL_SECURITY_INFORMATION,
                None,
                None,
                p_new_dacl,
                None,
            )
            if p_new_dacl:
                kernel32.LocalFree(p_new_dacl)

    if p_sd:
        kernel32.LocalFree(p_sd)
    kernel32.CloseHandle(h)


# ── One-time Python directory ACL grant (group-based) ──

_python_dir_acl_granted: bool = False


def _ensure_python_dir_group_acl() -> None:
    """Grants RX to the QwenpawUsers group on the Python install directory.

    This is a ONE-TIME operation per process lifetime.  Once the group has
    RX access, ALL sandbox users (who are members of that group) can read
    the Python interpreter and stdlib without per-sandbox ACL operations.

    The first call is expensive (~68s for large conda envs) because
    ``SetNamedSecurityInfoW`` propagates the inheritable ACE to all children.
    Subsequent sandbox creations skip this entirely (0ms).

    The grant persists on disk until manually removed, so even across
    process restarts the cost is only paid once per machine.
    """
    global _python_dir_acl_granted
    if _python_dir_acl_granted:
        return

    python_dir = _get_python_install_dir()
    if not python_dir or not os.path.isdir(python_dir):
        _python_dir_acl_granted = True
        return

    # Resolve the group SID via LookupAccountNameW
    result = _lookup_account_sid(SANDBOX_USERS_GROUP)
    if result is None:
        # Group doesn't exist yet — will be created during provisioning.
        # Mark as granted so we don't retry on every sandbox creation;
        # the per-user fallback in _apply_all_acls will handle it.
        logger.debug(
            "_ensure_python_dir_group_acl: group %s not found, skipping",
            SANDBOX_USERS_GROUP,
        )
        _python_dir_acl_granted = True
        return

    sid_buf, _ = result
    group_psid = ctypes.cast(sid_buf, ctypes.c_void_p)

    # Check if the group already has an ACE on the Python dir by attempting
    # a quick test — try to see if we already granted access in a prior run.
    # We use a marker file approach: if a hidden marker exists in the Python
    # dir, skip the expensive ACL operation.
    marker_path = os.path.join(python_dir, ".qwenpaw_acl_granted")
    if os.path.exists(marker_path):
        logger.debug(
            "_ensure_python_dir_group_acl: marker exists, skipping ACL set",
        )
        _python_dir_acl_granted = True
        return

    logger.info(
        "Granting RX to %s on Python dir: %s (one-time, may be slow)",
        SANDBOX_USERS_GROUP,
        python_dir,
    )
    result = _add_allow_read_ace(python_dir, group_psid)
    if result:
        # Write marker so we don't repeat on next process start.
        try:
            with open(marker_path, "w", encoding="utf-8") as f:
                f.write(SANDBOX_USERS_GROUP)
        except OSError:
            pass  # non-critical

    _python_dir_acl_granted = True


def _remove_python_dir_acl_marker() -> None:
    """Removes the .qwenpaw_acl_granted marker and resets the flag.

    Targets the Python install directory's marker file.

    Called during shutdown_cleanup so that the next sandbox creation will
    re-grant the ACL to the (re-created) QwenpawUsers group. Without this,
    after a full cleanup removes the group and its ACL, the stale marker
    would cause _ensure_python_dir_group_acl() to skip the grant on the
    next run — leaving the sandbox user unable to access Python.
    """
    global _python_dir_acl_granted

    python_dir = _get_python_install_dir()
    if not python_dir:
        _python_dir_acl_granted = False
        return

    marker_path = os.path.join(python_dir, ".qwenpaw_acl_granted")
    if os.path.exists(marker_path):
        try:
            os.remove(marker_path)
            logger.debug("Removed ACL marker: %s", marker_path)
        except OSError as e:
            logger.warning(
                "Failed to remove ACL marker %s: %s",
                marker_path,
                e,
            )

    _python_dir_acl_granted = False


@dataclass
class _AclEntry:
    """Record of a single ACL operation applied to the filesystem."""

    path: str
    access_mode: str  # "allow_read" | "allow_full" | "deny_all"
    sid_type: str  # "cap" | "user"


def _apply_all_acls(  # pylint: disable=too-many-branches
    config: SandboxConfig,
    cap_sid_string: str,
    user_sid_string: str,
) -> List[_AclEntry]:
    """Applies filesystem ACLs for WRITE_RESTRICTED mode and returns a record.

    Only write operations are gated by the restricting SIDs; reads use normal
    DACL evaluation. For writes to succeed BOTH the normal DACL check AND the
    restricting SID check must pass, so we grant:
      - Full access ACE for the cap SID on writable paths (restricting-SID
        check on writes)
      - Full access ACE for the user SID on writable paths (normal DACL check)
      - Read ACE for the user SID on read-only paths (normal DACL check)
      - Deny-all ACE for the user SID on deny_paths
    """
    kernel32 = _get_kernel32()
    psid = _string_to_sid(cap_sid_string)
    entries: List[_AclEntry] = []

    def _grant_workspace_and_mounts(
        sid: ctypes.c_void_p,
        sid_label: str,
    ) -> None:
        _add_allow_ace(config.workspace_dir, sid)
        entries.append(
            _AclEntry(config.workspace_dir, "allow_full", sid_label),
        )
        for mount in config.mounts:
            if os.path.exists(mount.path):
                if mount.writable:
                    _add_allow_ace(mount.path, sid)
                    entries.append(
                        _AclEntry(mount.path, "allow_full", sid_label),
                    )
                else:
                    _add_allow_read_ace(mount.path, sid)
                    entries.append(
                        _AclEntry(mount.path, "allow_read", sid_label),
                    )

    try:
        _grant_workspace_and_mounts(psid, "cap")

        _ensure_python_dir_group_acl()
        python_dir = _get_python_install_dir()
        if python_dir and os.path.isdir(python_dir):
            entries.append(_AclEntry(python_dir, "allow_read", "group"))

        user_psid = _string_to_sid(user_sid_string)
        try:
            _grant_workspace_and_mounts(user_psid, "user")

            for deny_path in config.deny_paths:
                expanded = os.path.expanduser(deny_path)
                if os.path.exists(expanded):
                    _add_deny_all_ace(expanded, user_psid)
                    entries.append(_AclEntry(expanded, "deny_all", "user"))
        finally:
            kernel32.LocalFree(user_psid)

        _allow_null_device(psid)
    finally:
        kernel32.LocalFree(psid)

    return entries


# ═══════════════════════════════════════════════════════════════════════════
# WFP network filtering
# ═══════════════════════════════════════════════════════════════════════════


def _install_wfp_block_filters(username: str, user_sid: str) -> bool:
    """Installs firewall rules to block all network for a user.

    Uses ``New-NetFirewallRule`` (PowerShell cmdlet) which supports the
    ``-LocalUser`` parameter with SDDL format.  ``netsh advfirewall``
    does not support ``localuser`` on all Windows editions/locales.

    Installs both outbound and inbound block rules. Runs on the host side
    (as administrator), not inside the sandbox.
    """

    rule_name_out = f"QwenPaw_Block_{username}_Out"
    rule_name_in = f"QwenPaw_Block_{username}_In"

    # SDDL string identifying the sandbox user.
    sddl_user = f"D:(A;;CC;;;{user_sid})"

    # Build a single PowerShell script that:
    #   1. Removes any existing rules (silently ignores errors)
    #   2. Creates outbound + inbound block rules for the user
    ps_script = (
        f"Remove-NetFirewallRule -DisplayName '{rule_name_out}' "
        f"-ErrorAction SilentlyContinue; "
        f"Remove-NetFirewallRule -DisplayName '{rule_name_in}' "
        f"-ErrorAction SilentlyContinue; "
        f"New-NetFirewallRule -DisplayName '{rule_name_out}' "
        f"-Direction Outbound -Action Block "
        f"-LocalUser '{sddl_user}' -Enabled True; "
        f"New-NetFirewallRule -DisplayName '{rule_name_in}' "
        f"-Direction Inbound -Action Block "
        f"-LocalUser '{sddl_user}' -Enabled True"
    )

    result = _run_powershell(ps_script)
    if result.returncode != 0:
        stdout_msg = result.stdout.decode("utf-8", errors="replace").strip()
        stderr_msg = result.stderr.decode("utf-8", errors="replace").strip()
        logger.warning(
            "Failed to install firewall block rules for %s (SID=%s): "
            "rc=%d stdout=%r stderr=%r",
            username,
            user_sid,
            result.returncode,
            stdout_msg,
            stderr_msg,
        )
        return False
    return True


# ═══════════════════════════════════════════════════════════════════════════
# WindowStation / Desktop DACL grants
# ═══════════════════════════════════════════════════════════════════════════


def _grant_winsta_desktop_access(user_sid_string: str) -> None:
    """Grants the sandbox user access to WinSta0 and the Default desktop.

    Without these grants, processes launched with ``CreateProcessWithTokenW``
    crash with ``STATUS_DLL_INIT_FAILED`` (0xC0000142) because DLL init code
    in ``user32.dll`` / ``kernel32.dll`` tries to open the desktop and
    WindowStation during ``DLL_PROCESS_ATTACH``. Even pure console apps go
    through this path on Windows.

    The grants are:
      - WindowStation: WINSTA_ALL_ACCESS (read/write attrs, enumerate desktops,
        access clipboard, etc.)
      - Desktop: GENERIC_ALL (read/write objects, create windows, etc.)

    These are applied to the current process's WindowStation and thread's
    Desktop, which is ``WinSta0\\Default`` for interactive services.

    This function is idempotent — calling it multiple times for the same SID
    is harmless (the ACE is merged with existing DACLs).
    """
    user32 = _get_user32()
    kernel32 = _get_kernel32()

    psid = _string_to_sid(user_sid_string)
    try:
        _grant_object_access(
            user32.GetProcessWindowStation(),
            psid,
            "WindowStation",
        )

        h_desktop = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
        _grant_object_access(h_desktop, psid, "Desktop")
    finally:
        kernel32.LocalFree(psid)


def _grant_object_access(  # pylint: disable=too-many-return-statements
    h_obj: ctypes.wintypes.HANDLE,
    psid: ctypes.c_void_p,
    label: str,
) -> None:
    """Adds a GENERIC_ALL allow ACE for psid on a User Object.

    Targets WindowStation or Desktop by reading the existing DACL and
    merging a new entry via GetUserObjectSecurity/SetUserObjectSecurity.
    """
    user32 = _get_user32()
    advapi32 = _get_advapi32()
    kernel32 = _get_kernel32()

    if not h_obj:
        logger.debug("_grant_object_access(%s): NULL handle", label)
        return

    si_flags = ctypes.wintypes.DWORD(_DACL_SECURITY_INFORMATION)

    # Query existing SD size
    needed = ctypes.wintypes.DWORD(0)
    user32.GetUserObjectSecurity(
        h_obj,
        ctypes.byref(si_flags),
        None,
        0,
        ctypes.byref(needed),
    )
    if needed.value == 0:
        logger.debug(
            "_grant_object_access(%s): size query returned 0, err=%d",
            label,
            ctypes.get_last_error(),
        )
        return

    # Read existing SD
    sd_buf = (ctypes.c_ubyte * needed.value)()
    ok = user32.GetUserObjectSecurity(
        h_obj,
        ctypes.byref(si_flags),
        sd_buf,
        needed.value,
        ctypes.byref(needed),
    )
    if not ok:
        logger.debug(
            "_grant_object_access(%s): GetUserObjectSecurity failed, err=%d",
            label,
            ctypes.get_last_error(),
        )
        return

    # Extract DACL from the SD
    _dacl_present = ctypes.wintypes.BOOL()
    _p_dacl = ctypes.c_void_p()
    _dacl_defaulted = ctypes.wintypes.BOOL()
    ok = advapi32.GetSecurityDescriptorDacl(
        ctypes.cast(sd_buf, ctypes.c_void_p),
        ctypes.byref(_dacl_present),
        ctypes.byref(_p_dacl),
        ctypes.byref(_dacl_defaulted),
    )
    if not ok:
        logger.debug(
            "_grant_object_access(%s): GetSecurityDescriptorDacl failed",
            label,
        )
        return

    old_dacl = _p_dacl if _dacl_present.value else None

    entry = _build_explicit_access(
        psid,
        _GENERIC_ALL,
        _GRANT_ACCESS,
        _CONTAINER_INHERIT_ACE | _OBJECT_INHERIT_ACE,
    )

    p_new_dacl = ctypes.c_void_p()
    code = advapi32.SetEntriesInAclW(
        1,
        ctypes.byref(entry),
        old_dacl,
        ctypes.byref(p_new_dacl),
    )
    if code != 0:
        logger.debug(
            "_grant_object_access(%s): SetEntriesInAclW failed: %d",
            label,
            code,
        )
        return

    # Build a new SD with the merged DACL
    # InitializeSecurityDescriptor + SetSecurityDescriptorDacl
    _SECURITY_DESCRIPTOR_REVISION = 1
    # SECURITY_DESCRIPTOR is 20 bytes on 32-bit, 40 bytes on 64-bit
    sd_size = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 20
    new_sd = (ctypes.c_ubyte * sd_size)()
    ok = advapi32.InitializeSecurityDescriptor(
        ctypes.cast(new_sd, ctypes.c_void_p),
        _SECURITY_DESCRIPTOR_REVISION,
    )
    if not ok:
        kernel32.LocalFree(p_new_dacl)
        logger.debug(
            "_grant_object_access(%s): InitializeSecurityDescriptor failed",
            label,
        )
        return

    ok = advapi32.SetSecurityDescriptorDacl(
        ctypes.cast(new_sd, ctypes.c_void_p),
        True,  # DaclPresent
        p_new_dacl,
        False,  # DaclDefaulted
    )
    if not ok:
        kernel32.LocalFree(p_new_dacl)
        logger.debug(
            "_grant_object_access(%s): SetSecurityDescriptorDacl failed",
            label,
        )
        return

    # Apply the new SD
    ok = user32.SetUserObjectSecurity(
        h_obj,
        ctypes.byref(si_flags),
        ctypes.cast(new_sd, ctypes.c_void_p),
    )
    if not ok:
        logger.debug(
            "_grant_object_access(%s): SetUserObjectSecurity failed, err=%d",
            label,
            ctypes.get_last_error(),
        )

    kernel32.LocalFree(p_new_dacl)


# ═══════════════════════════════════════════════════════════════════════════
# Process launch structures
# ═══════════════════════════════════════════════════════════════════════════


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


def _create_job_object() -> Optional[ctypes.wintypes.HANDLE]:
    """Creates a Job Object with KILL_ON_JOB_CLOSE limit.

    All processes assigned to this Job Object will be terminated when the
    Job Object handle is closed or when TerminateJobObject is called.
    """
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


# ═══════════════════════════════════════════════════════════════════════════
# Process spawn with restricted token
# ═══════════════════════════════════════════════════════════════════════════


def _make_env_block(env: Dict[str, str]) -> ctypes.Array:
    """Builds a Unicode environment block sorted case-insensitively."""
    items = sorted(env.items(), key=lambda kv: kv[0].upper())
    env_str = "\x00".join(f"{k}={v}" for k, v in items) + "\x00\x00"
    return ctypes.create_unicode_buffer(env_str)


def _create_stdio_pipes(
    kernel32: Any,
) -> Tuple[
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
]:
    """Creates inheritable stdout/stderr pipes."""

    class _SA(ctypes.Structure):
        _fields_ = [
            ("nLength", ctypes.wintypes.DWORD),
            ("lpSecurityDescriptor", ctypes.c_void_p),
            ("bInheritHandle", ctypes.wintypes.BOOL),
        ]

    sa = _SA(
        nLength=ctypes.sizeof(_SA()),
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
            f"CreatePipe(stdout) failed: error={ctypes.get_last_error()}",
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
            f"CreatePipe(stderr) failed: error={ctypes.get_last_error()}",
        )

    # Make read ends non-inheritable
    kernel32.SetHandleInformation(stdout_read, _HANDLE_FLAG_INHERIT, 0)
    kernel32.SetHandleInformation(stderr_read, _HANDLE_FLAG_INHERIT, 0)

    return stdout_read, stdout_write, stderr_read, stderr_write


_POWERSHELL_NAMES = {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}
_CMD_NAMES = {"cmd", "cmd.exe"}


def _build_shell_command_line(
    cmd: str,
    shell_executable: Optional[str] = None,
) -> str:
    """Builds the command line string for launching a command via a shell.

    Supports three modes:
      - PowerShell (powershell.exe / pwsh.exe): uses -NoProfile -NonInteractive
        -ExecutionPolicy Bypass -Command "..."
      - cmd.exe (default): uses cmd.exe /c "..."
      - Other executables: uses <executable> -c "..." (POSIX-style)

    The sandbox itself is the security boundary, not execution policy or shell
    restrictions.
    """
    name = (
        os.path.basename(shell_executable).lower() if shell_executable else ""
    )
    if shell_executable and name in _POWERSHELL_NAMES:
        ps_cmd = cmd.replace('"', '\\"')
        return (
            f"{shell_executable} -NoProfile -NonInteractive "
            f'-ExecutionPolicy Bypass -Command "{ps_cmd}"'
        )
    elif not shell_executable or name in _CMD_NAMES:
        shell = shell_executable or "cmd.exe"
        return f'{shell} /c "{cmd}"'
    else:
        # POSIX-like shell on Windows (e.g. Git Bash, MSYS2)
        escaped = cmd.replace('"', '\\"')
        return f'{shell_executable} -c "{escaped}"'


def _create_process_with_token(
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
    """Launches a process with the restricted token.

    Tries ``CreateProcessWithTokenW`` first (requires only
    ``SeImpersonatePrivilege``, which elevated administrators have).
    Falls back to ``CreateProcessAsUserW`` (requires
    ``SeAssignPrimaryTokenPrivilege``, typically only SYSTEM).

    Returns (pid, process_handle, stdout_read, stderr_read, job_handle).
    The job_handle (if not None) owns the entire process tree — calling
    ``TerminateJobObject`` on it kills all child processes.
    """
    kernel32 = _get_kernel32()
    advapi32 = _get_advapi32()

    stdout_read, stdout_write, stderr_read, stderr_write = _create_stdio_pipes(
        kernel32,
    )

    si = _STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.dwFlags = _STARTF_USESTDHANDLES
    si.hStdInput = None
    si.hStdOutput = stdout_write
    si.hStdError = stderr_write
    si.lpDesktop = "WinSta0\\Default"

    env_block = _make_env_block(env)
    pi = _PROCESS_INFORMATION()
    creation_flags = _CREATE_UNICODE_ENVIRONMENT | _CREATE_NO_WINDOW

    _ensure_privileges()
    shell_cmd = _build_shell_command_line(cmd, shell_executable)
    cmd_line = ctypes.create_unicode_buffer(shell_cmd)

    # Try CreateProcessWithTokenW first — only needs SeImpersonatePrivilege.
    # Use LOGON_WITH_PROFILE to load the user's registry hive (HKCU).
    # Without profile loading, many executables (git, powershell, whoami)
    # crash with STATUS_DLL_INIT_FAILED (0xC0000142) because DLL init code
    # expects a valid HKCU and user profile paths.
    # Profile creation is slow on first use but cached afterwards.
    success = advapi32.CreateProcessWithTokenW(
        h_token,
        _LOGON_WITH_PROFILE,
        None,
        cmd_line,
        creation_flags,
        ctypes.cast(env_block, ctypes.c_void_p),
        ctypes.c_wchar_p(cwd),
        ctypes.byref(si),
        ctypes.byref(pi),
    )

    if not success:
        # Fallback to CreateProcessAsUserW (SeAssignPrimaryTokenPrivilege).
        err_with_token = ctypes.get_last_error()
        logger.debug(
            "CreateProcessWithTokenW failed (error=%d), "
            "falling back to CreateProcessAsUserW",
            err_with_token,
        )
        # Recreate cmd_line buffer (may have been modified by first call).
        cmd_line = ctypes.create_unicode_buffer(shell_cmd)
        pi = _PROCESS_INFORMATION()
        success = advapi32.CreateProcessAsUserW(
            h_token,
            None,
            cmd_line,
            None,
            None,
            True,
            creation_flags,
            ctypes.cast(env_block, ctypes.c_void_p),
            ctypes.c_wchar_p(cwd),
            ctypes.byref(si),
            ctypes.byref(pi),
        )

    kernel32.CloseHandle(stdout_write)
    kernel32.CloseHandle(stderr_write)

    if not success:
        err = ctypes.get_last_error()
        kernel32.CloseHandle(stdout_read)
        kernel32.CloseHandle(stderr_read)
        raise OSError(
            f"CreateProcess failed: error={err} "
            f"(CreateProcessWithTokenW also failed: {err_with_token})",
        )

    kernel32.CloseHandle(pi.hThread)

    # Assign the process to a Job Object so the entire process tree can be
    # terminated via TerminateJobObject (kills cmd.exe + all child processes).
    h_job = _create_job_object()
    if h_job:
        if not kernel32.AssignProcessToJobObject(h_job, pi.hProcess):
            logger.debug(
                "AssignProcessToJobObject failed: error=%d",
                ctypes.get_last_error(),
            )
            kernel32.CloseHandle(h_job)
            h_job = None

    return (pi.dwProcessId, pi.hProcess, stdout_read, stderr_read, h_job)


# ═══════════════════════════════════════════════════════════════════════════
# Pipe reading and process waiting
# ═══════════════════════════════════════════════════════════════════════════


def _read_pipe(handle: ctypes.wintypes.HANDLE, kernel32: Any) -> bytes:
    """Reads all data from a pipe handle until EOF."""
    chunks: List[bytes] = []
    buf_size = 8192
    buf = (ctypes.c_ubyte * buf_size)()
    bytes_read = ctypes.c_uint32()

    while True:
        ok = kernel32.ReadFile(
            handle,
            buf,
            buf_size,
            ctypes.byref(bytes_read),
            None,
        )
        if not ok:
            if bytes_read.value > 0:
                chunks.append(bytes(buf[: bytes_read.value]))
            break
        if bytes_read.value == 0:
            break
        chunks.append(bytes(buf[: bytes_read.value]))

    return b"".join(chunks)


async def _wait_and_read_process(
    process_handle: ctypes.wintypes.HANDLE,
    stdout_handle: ctypes.wintypes.HANDLE,
    stderr_handle: ctypes.wintypes.HANDLE,
    timeout_seconds: int,
    job_handle: Optional[ctypes.wintypes.HANDLE] = None,
) -> Tuple[int, str, str, bool]:
    """Waits for process completion, reads output, closes handles.

    Reads stdout/stderr in dedicated threads concurrently with the process
    wait to avoid pipe buffer deadlock. If we waited for the process first
    and then read the pipes, a child producing more output than the pipe
    buffer (~64 KB) would block forever, and so would WaitForSingleObject.

    If ``job_handle`` is provided, uses ``TerminateJobObject`` on timeout
    to kill the entire process tree (including child processes like ping.exe
    that would otherwise keep pipe handles open).
    """
    kernel32 = _get_kernel32()
    loop = asyncio.get_event_loop()

    def _drain_stdout():
        return _read_pipe(stdout_handle, kernel32)

    def _drain_stderr():
        return _read_pipe(stderr_handle, kernel32)

    def _wait_process():
        timeout_ms = timeout_seconds * 1000
        result = kernel32.WaitForSingleObject(process_handle, timeout_ms)
        timed_out = result == _WAIT_TIMEOUT
        if timed_out:
            if job_handle:
                kernel32.TerminateJobObject(job_handle, 1)
            else:
                kernel32.TerminateProcess(process_handle, 1)
            kernel32.WaitForSingleObject(process_handle, 5000)
        return timed_out

    # Run pipe reads and process wait concurrently to prevent deadlock.
    stdout_future = loop.run_in_executor(None, _drain_stdout)
    stderr_future = loop.run_in_executor(None, _drain_stderr)
    wait_future = loop.run_in_executor(None, _wait_process)

    timed_out, stdout_data, stderr_data = await asyncio.gather(
        wait_future,
        stdout_future,
        stderr_future,
    )

    # Process has exited and pipes are drained — get exit code and clean up.
    exit_code = ctypes.wintypes.DWORD()
    kernel32.GetExitCodeProcess(process_handle, ctypes.byref(exit_code))

    kernel32.CloseHandle(stdout_handle)
    kernel32.CloseHandle(stderr_handle)
    kernel32.CloseHandle(process_handle)
    if job_handle:
        kernel32.CloseHandle(job_handle)

    return (
        exit_code.value,
        _decode_pipe_output(stdout_data),
        _decode_pipe_output(stderr_data),
        timed_out,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Sandbox registry (instance caching and parallel isolation)
# ═══════════════════════════════════════════════════════════════════════════


def _compute_config_fingerprint(config: SandboxConfig) -> str:
    """Computes a deterministic hash of the ACL-relevant configuration.

    Mirrors ``_compute_acl_fingerprint`` in the AppContainer backend so
    that fingerprint semantics are consistent across Windows sandbox modes.
    """
    python_dir = _get_python_install_dir()
    data = {
        "workspace_dir": os.path.normpath(config.workspace_dir),
        "deny_paths": sorted(
            os.path.normpath(os.path.expanduser(p)) for p in config.deny_paths
        ),
        "mounts": sorted(
            (os.path.normpath(m.path), m.writable, m.executable)
            for m in config.mounts
        ),
        "network_allow": sorted(config.network_allow),
        "python_dir": os.path.normpath(python_dir) if python_dir else None,
    }
    return hashlib.sha256(
        json.dumps(data, sort_keys=True).encode(),
    ).hexdigest()[:16]


def _sandboxes_dir(state_dir: Path) -> Path:
    """Returns the directory where sandbox metadata files are stored."""
    return state_dir / "sandboxes"


class _SandboxInstance:
    """A live sandbox instance with token handles and metadata."""

    def __init__(
        self,
        sandbox_id: str,
        username: str,
        user_sid_string: str,
        cap_sid: str,
        h_user_token: ctypes.wintypes.HANDLE,
        h_token: ctypes.wintypes.HANDLE,
        config_fingerprint: str,
        metadata_path: Path,
        network_blocked: bool,
        acl_entries: List[_AclEntry],
        profile_dir: Optional[str] = None,
    ):
        self.sandbox_id = sandbox_id
        self.username = username
        self.user_sid_string = user_sid_string
        self.cap_sid = cap_sid
        self.h_user_token = h_user_token
        self.h_token = h_token
        self.config_fingerprint = config_fingerprint
        self.metadata_path = metadata_path
        self.network_blocked = network_blocked
        self.acl_entries = acl_entries
        self.profile_dir = profile_dir

    def close(self) -> None:
        """Closes token handles."""
        kernel32 = _get_kernel32()
        if self.h_token:
            try:
                kernel32.CloseHandle(self.h_token)
            except OSError:
                pass
            self.h_token = None
        if self.h_user_token:
            try:
                kernel32.CloseHandle(self.h_user_token)
            except OSError:
                pass
            self.h_user_token = None


# ── Module-level state ──

_sandbox_state_dir = (
    Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / ".qwenpaw"
)


def _find_reusable_sandbox(
    sandbox_name: str,
) -> Optional[_SandboxInstance]:
    """Checks if a sandbox with the given name exists on disk and restores it.

    Mirrors ``_find_reusable_container`` in the AppContainer backend:
    the deterministic name encodes the config fingerprint, so a direct
    file lookup is sufficient — no need to scan all metadata files.
    """
    sb_dir = _sandboxes_dir(_sandbox_state_dir)
    meta_file = sb_dir / f"{sandbox_name}.json"
    if not meta_file.exists():
        return None
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return _restore_from_metadata(meta, meta_file)


def _resolve_profile_dir(
    h_token: ctypes.wintypes.HANDLE,
    username: str,
    stored_path: Optional[str] = None,
) -> str:
    """Resolves the user profile directory with fallback chain.

    Tries stored_path (if valid), then GetUserProfileDirectoryW,
    then constructs C:\\Users\\<username>.
    """
    if stored_path and os.path.isdir(stored_path):
        return stored_path
    api_path = _get_profile_directory(h_token)
    if api_path:
        return api_path
    sys_drive = os.environ.get("SystemDrive", "C:")
    return os.path.join(sys_drive + os.sep, "Users", username)


def _restore_from_metadata(
    meta: Dict[str, Any],
    meta_file: Path,
) -> Optional[_SandboxInstance]:
    """Restores a sandbox instance from persisted metadata."""
    try:
        username = meta["username"]

        # Try to use the persisted DPAPI-encrypted password to avoid
        # unnecessary password resets (which generate 4724 audit events).
        password = None
        encrypted_password = meta.get("encrypted_password")
        if encrypted_password:
            try:
                password = _dpapi_decrypt(encrypted_password)
            except OSError:
                logger.debug(
                    "DPAPI decryption failed for %s; will reset password",
                    username,
                )

        if password:
            # Try logging in with the persisted password first
            try:
                h_user_token = _logon_user(username, password)
            except OSError:
                # Password may be stale (manually changed externally);
                # fall back to reset
                password = None

        if not password:
            password = _random_password()
            if not _ensure_local_user(username, password):
                return None
            h_user_token = _logon_user(username, password)

        # Ensure WindowStation/Desktop access for restored sandboxes too
        user_sid = meta.get("user_sid", "")
        if user_sid:
            _grant_winsta_desktop_access(user_sid)

        cap_sid = meta["cap_sid"]

        h_token = _create_restricted_token(h_user_token, [cap_sid])

        acl_entries = [
            _AclEntry(e["path"], e["access_mode"], e["sid_type"])
            for e in meta.get("acl_entries", [])
        ]

        profile_dir = _resolve_profile_dir(
            h_user_token,
            meta["username"],
            meta.get("profile_dir"),
        )

        return _SandboxInstance(
            sandbox_id=meta["sandbox_id"],
            username=meta["username"],
            user_sid_string=meta["user_sid"],
            cap_sid=cap_sid,
            h_user_token=h_user_token,
            h_token=h_token,
            config_fingerprint=meta["config_fingerprint"],
            metadata_path=meta_file,
            network_blocked=meta.get("network_blocked", False),
            acl_entries=acl_entries,
            profile_dir=profile_dir,
        )
    except (OSError, KeyError, UnicodeDecodeError) as e:
        logger.warning("Failed to restore sandbox from %s: %s", meta_file, e)
        return None


def _create_new_sandbox(
    config: SandboxConfig,
    fingerprint: str,
) -> _SandboxInstance:
    """Creates a brand new sandbox with a fresh user account."""
    if not _is_admin():
        raise OSError(
            "WindowsRestrictedSandbox requires administrator privileges. "
            "Please run as administrator.",
        )

    sandbox_id = f"qwenpaw_{fingerprint[:12]}"
    username = sandbox_id
    password = _random_password()

    if not _provision_sandbox_user(username, password):
        raise OSError(f"Failed to provision sandbox user: {username}")

    h_user_token = _logon_user(username, password)
    user_sid_bytes = _get_user_sid_bytes(h_user_token)
    user_sid_buf = (ctypes.c_ubyte * len(user_sid_bytes))(*user_sid_bytes)
    user_sid_ptr = ctypes.cast(user_sid_buf, ctypes.c_void_p)
    user_sid_string = _sid_to_string(user_sid_ptr)

    # Create the user profile via the Windows API (userenv.dll CreateProfile).
    # This properly registers the profile in the ProfileList registry so that
    # LOGON_WITH_PROFILE will use the correct directory without appending a
    # machine-name suffix (e.g. "qwenpaw_xxx.DESKTOP-E7LJ27U").
    _create_user_profile(user_sid_string, username)
    profile_dir = _resolve_profile_dir(h_user_token, username)

    # Ensure essential subdirectories exist for TEMP/APPDATA.
    for sub in (
        os.path.join("AppData", "Local", "Temp"),
        os.path.join("AppData", "Roaming"),
    ):
        p = os.path.join(profile_dir, sub)
        os.makedirs(p, exist_ok=True)

    # Grant the sandbox user access to the current WindowStation and Desktop
    # so that DLL initialization in child processes can open the desktop
    # (even pure console apps go through user32.dll during DLL_PROCESS_ATTACH).
    # Without this, processes crash with STATUS_DLL_INIT_FAILED (0xC0000142).
    _grant_winsta_desktop_access(user_sid_string)

    network_blocked = not (
        bool(config.network_allow) and "*" in config.network_allow
    )
    if network_blocked:
        _install_wfp_block_filters(username, user_sid_string)

    cap_sid = _make_random_cap_sid_string()
    acl_entries = _apply_all_acls(config, cap_sid, user_sid_string)

    # Grant the sandbox user full access to its own profile directory so
    # that DLL initialization, TEMP writes, and APPDATA access work.
    # Both the capability SID (for WRITE_RESTRICTED check) and the user
    # SID (for normal DACL check) need full access.
    kernel32 = _get_kernel32()
    if os.path.exists(profile_dir):
        cap_psid = _string_to_sid(cap_sid)
        user_psid = _string_to_sid(user_sid_string)
        try:
            _add_allow_ace(profile_dir, cap_psid)
            _add_allow_ace(profile_dir, user_psid)
        finally:
            kernel32.LocalFree(cap_psid)
            kernel32.LocalFree(user_psid)

    h_token = _create_restricted_token(h_user_token, [cap_sid])

    sb_dir = _sandboxes_dir(_sandbox_state_dir)
    sb_dir.mkdir(parents=True, exist_ok=True)
    meta_path = sb_dir / f"{sandbox_id}.json"
    # Encrypt password via DPAPI for persistence (avoids password resets
    # on restore, which generate noisy 4724 audit events).
    encrypted_password = None
    try:
        encrypted_password = _dpapi_encrypt(password)
    except OSError:
        logger.debug("DPAPI encryption unavailable; password not persisted")

    meta = {
        "sandbox_id": sandbox_id,
        "username": username,
        "user_sid": user_sid_string,
        "cap_sid": cap_sid,
        "config_fingerprint": fingerprint,
        "network_blocked": network_blocked,
        "profile_dir": profile_dir,
        "owner_pid": os.getpid(),
        "encrypted_password": encrypted_password,
        "acl_entries": [
            {
                "path": e.path,
                "access_mode": e.access_mode,
                "sid_type": e.sid_type,
            }
            for e in acl_entries
        ],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    logger.debug(
        "Created sandbox %s (user=%s, cap_sid=%s, profile=%s)",
        sandbox_id,
        username,
        cap_sid,
        profile_dir,
    )

    return _SandboxInstance(
        sandbox_id=sandbox_id,
        username=username,
        user_sid_string=user_sid_string,
        cap_sid=cap_sid,
        h_user_token=h_user_token,
        h_token=h_token,
        config_fingerprint=fingerprint,
        metadata_path=meta_path,
        network_blocked=network_blocked,
        acl_entries=acl_entries,
        profile_dir=profile_dir,
    )


async def _acquire_sandbox(config: SandboxConfig) -> _SandboxInstance:
    """Acquires a sandbox instance matching the config.

    Mirrors the AppContainer backend's reuse strategy: derive a
    deterministic name from the config fingerprint, check on-disk
    metadata, and create a new sandbox only if no match is found.
    """
    fingerprint = _compute_config_fingerprint(config)
    sandbox_name = f"qwenpaw_{fingerprint[:12]}"

    existing = await asyncio.to_thread(
        _find_reusable_sandbox,
        sandbox_name,
    )
    if existing is not None:
        logger.debug("Reusing sandbox %s from disk", existing.sandbox_id)
        return existing

    inst = await asyncio.to_thread(
        _create_new_sandbox,
        config,
        fingerprint,
    )
    return inst


async def _release_sandbox(instance: _SandboxInstance) -> None:
    """Releases a sandbox instance by closing its token handles."""
    instance.close()
    logger.debug("Closed sandbox %s", instance.sandbox_id)


# ═══════════════════════════════════════════════════════════════════════════
# WindowsRestrictedSandbox class
# ═══════════════════════════════════════════════════════════════════════════


class WindowsRestrictedSandbox:
    """Windows elevated sandbox providing native process isolation via a
    WRITE_RESTRICTED token.

    Used when ``allow_read_all=True``: reads work automatically via normal
    DACL evaluation, writes are gated by the restricting SID list. Uses the
    module-level sandbox instance cache to manage instances. Multiple
    instances with the same config share a single underlying user account and
    token (reference-counted). Different configs get fully independent user
    accounts with no ACL interference.

    Lifecycle:
        ``__aenter__``: Acquires a sandbox instance from the registry.
        ``execute``: Launches a command with the restricted token.
        ``__aexit__`` / ``stop``: Terminates running process and releases
            the registry reference.
    """

    def __init__(self, config: SandboxConfig):
        self._config = config
        self._instance: Optional[_SandboxInstance] = None
        self._process_handle: Optional[ctypes.wintypes.HANDLE] = None
        self._process_id: Optional[int] = None
        self._job_handle: Optional[ctypes.wintypes.HANDLE] = None

    @property
    def config(self) -> SandboxConfig:
        return self._config

    async def __aenter__(self):
        """Acquires a sandbox instance from the registry."""
        self._instance = await _acquire_sandbox(self._config)
        return self

    async def execute(
        self,
        cmd: str,
        cwd: Optional[str] = None,
    ) -> ExecutionResult:
        """Executes a command inside the sandbox with a restricted token.

        Args:
            cmd: Shell command string to execute via the configured shell
                (cmd.exe, powershell.exe, pwsh.exe, or custom).
            cwd: Working directory override.

        Returns:
            An ``ExecutionResult`` with exit code, stdout, stderr, timeout
            status, and any detected sandbox violation.
        """
        if not self._instance:
            await self.__aenter__()

        assert self._instance is not None
        h_token = self._instance.h_token
        start = time.monotonic()
        effective_cwd = cwd or self._config.workspace_dir

        # Build environment — start from the host env but override identity
        # and profile variables so the sandbox process sees its own username
        # and writable profile paths, not the administrator's.
        env = dict(os.environ)
        sandbox_user = self._instance.username
        env["USERNAME"] = sandbox_user
        env["USERDOMAIN"] = os.environ.get("COMPUTERNAME", ".")

        # Override user profile paths using the actual profile directory
        # (resolved via CreateProfile/GetUserProfileDirectoryW).
        # If those env vars still point to the admin's profile, DLLs that
        # try to read/write APPDATA or LOCALAPPDATA will fail.
        sys_drive = os.environ.get("SystemDrive", "C:")
        sandbox_profile = self._instance.profile_dir or (
            f"{sys_drive}\\Users\\{sandbox_user}"
        )
        env["USERPROFILE"] = sandbox_profile
        env["APPDATA"] = f"{sandbox_profile}\\AppData\\Roaming"
        env["LOCALAPPDATA"] = f"{sandbox_profile}\\AppData\\Local"
        env["TEMP"] = f"{sandbox_profile}\\AppData\\Local\\Temp"
        env["TMP"] = f"{sandbox_profile}\\AppData\\Local\\Temp"
        # HOME/HOMEPATH for programs that use them (git, ssh, etc.)
        env["HOMEDRIVE"] = sys_drive
        env["HOMEPATH"] = sandbox_profile[len(sys_drive) :]

        # Set PYTHONHOME to the interpreter's prefix so that Python skips
        # build-tree detection (conda envs have Modules/Setup.local which
        # triggers "is in build tree" mode and breaks stdlib imports).
        python_dir = _get_python_install_dir()
        if python_dir and "PYTHONHOME" not in env:
            env["PYTHONHOME"] = python_dir

        if self._config.env_vars:
            for k, v in self._config.env_vars.items():
                env[k] = v

        try:
            (
                pid,
                proc_handle,
                stdout_handle,
                stderr_handle,
                job_handle,
            ) = await asyncio.to_thread(
                _create_process_with_token,
                h_token,
                cmd,
                effective_cwd,
                env,
                shell_executable=self._config.shell_executable,
            )
            self._process_handle = proc_handle
            self._process_id = pid
            self._job_handle = job_handle

            (
                exit_code,
                stdout,
                stderr,
                timed_out,
            ) = await _wait_and_read_process(
                proc_handle,
                stdout_handle,
                stderr_handle,
                self._config.timeout_seconds,
                job_handle=job_handle,
            )
            self._process_handle = None
            self._job_handle = None
            duration_ms = int((time.monotonic() - start) * 1000)

            # Detect sandbox violation
            violation = None
            if _VIOLATION_RE.search(stderr):
                violation = stderr.strip()
            elif exit_code != 0 and _VIOLATION_RE.search(stdout):
                violation = stdout.strip()

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
                duration_ms=duration_ms,
            )

    async def stop(self) -> None:
        """Terminates any running child process tree.

        Uses ``TerminateJobObject`` when a Job Object is available to kill
        the entire process tree (cmd.exe + all child processes). Falls back
        to ``OpenProcess`` + ``TerminateProcess`` if no job handle exists.
        """
        kernel32 = _get_kernel32()

        if self._job_handle is not None:
            # TerminateJobObject kills the entire process tree.
            try:
                kernel32.TerminateJobObject(self._job_handle, 1)
            except OSError:
                pass
            # Don't close the job handle here — _wait_and_read_process owns it
            # and will close it when it finishes draining pipes.
            self._job_handle = None
            self._process_id = None
            self._process_handle = None
        elif self._process_id is not None:
            try:
                _PROCESS_TERMINATE = 0x0001
                h = kernel32.OpenProcess(
                    _PROCESS_TERMINATE,
                    False,
                    self._process_id,
                )
                if h and h != ctypes.c_void_p(-1).value:
                    kernel32.TerminateProcess(h, 1)
                    kernel32.CloseHandle(h)
            except OSError:
                pass
            self._process_id = None
            self._process_handle = None

        if self._instance is not None:
            await _release_sandbox(self._instance)
            self._instance = None

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()


# ═══════════════════════════════════════════════════════════════════════════
# Shutdown cleanup — called on application exit to destroy all sandboxes
# ═══════════════════════════════════════════════════════════════════════════


def _run_powershell(
    script: str,
    timeout: int = 30,
) -> "subprocess.CompletedProcess":
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _run_cmd_sync(
    args: List[str],
    timeout: int = 30,
) -> Optional["subprocess.CompletedProcess"]:
    try:
        return subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _remove_firewall_rules_sync(username: str) -> bool:
    """Removes firewall block rules for a sandbox user (synchronous)."""
    rule_name_out = f"QwenPaw_Block_{username}_Out"
    rule_name_in = f"QwenPaw_Block_{username}_In"
    ps_script = (
        f"Remove-NetFirewallRule -DisplayName '{rule_name_out}' "
        f"-ErrorAction SilentlyContinue; "
        f"Remove-NetFirewallRule -DisplayName '{rule_name_in}' "
        f"-ErrorAction SilentlyContinue"
    )
    try:
        result = _run_powershell(ps_script)
        return result.returncode == 0
    except (OSError, Exception):
        return False


def _delete_local_user_sync(username: str) -> bool:
    """Deletes a local Windows user account."""
    result = _run_cmd_sync(["net", "user", username, "/delete"])
    return result is not None and result.returncode == 0


def _remove_profile_dir_sync(username: str) -> bool:
    """Removes user profile directory with takeown + icacls + rmtree."""
    import shutil
    import stat

    sys_drive = os.environ.get("SystemDrive", "C:")
    profile_dir = os.path.join(sys_drive + os.sep, "Users", username)
    if not os.path.exists(profile_dir):
        return True

    _run_cmd_sync(
        ["takeown", "/F", profile_dir, "/R", "/A", "/D", "Y"],
        timeout=300,
    )
    _run_cmd_sync(
        [
            "icacls",
            profile_dir,
            "/grant",
            "Administrators:(OI)(CI)F",
            "/T",
            "/C",
        ],
        timeout=300,
    )

    # Remove with error handler
    def _on_rm_error(func, path, _exc_info):
        try:
            os.chmod(
                path,
                stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO,
            )
            func(path)
        except OSError:
            pass

    try:
        # pylint: disable=deprecated-argument
        shutil.rmtree(profile_dir, onerror=_on_rm_error)
    except OSError:
        pass

    return not os.path.exists(profile_dir)


def _run_icacls_sync(args: List[str]) -> bool:
    """Runs icacls synchronously, returns True on success."""
    result = _run_cmd_sync(["icacls"] + args, timeout=180)
    return result is not None and result.returncode == 0


def _verify_acl_removed_sync(path: str, sid: str) -> bool:
    """Verifies that a SID no longer appears in the DACL of a path."""
    if not os.path.exists(path):
        return True
    result = _run_cmd_sync(["icacls", path], timeout=180)
    if result is None:
        return False
    output = result.stdout.decode("utf-8", errors="replace")
    if sid in output:
        return False
    if sid.upper() in output.upper():
        return False
    return True


def _remove_acl_with_verify_sync(path: str, sid: str) -> bool:
    """Removes ACEs for a SID using multi-strategy retry.

    Mirrors the approach in scripts/cleanup_windows_sandbox.py:
      1. Basic /remove
      2. Recursive /remove /T /C
      3. Explicit /remove:g and /remove:d
      4. /inheritance:e (re-enable inheritance) then /remove again
      5. Break inheritance then /remove
      6. Non-recursive /reset on target path only, then /remove
         (last resort — resets only the target directory's DACL,
         does not affect child objects)
    """
    if not os.path.exists(path):
        return True

    strategies = [
        # Strategy 1: simple remove
        lambda: _run_icacls_sync([path, "/remove", f"*{sid}"]),
        # Strategy 2: recursive remove
        lambda: _run_icacls_sync([path, "/remove", f"*{sid}", "/T", "/C"]),
        # Strategy 3: explicit grant + deny removal
        lambda: (
            _run_icacls_sync([path, "/remove:g", f"*{sid}", "/T", "/C"]),
            _run_icacls_sync([path, "/remove:d", f"*{sid}", "/T", "/C"]),
        ),
        # Strategy 4: re-enable inheritance then remove again
        lambda: (
            _run_icacls_sync([path, "/inheritance:e"]),
            _run_icacls_sync([path, "/remove", f"*{sid}", "/T", "/C"]),
        ),
        # Strategy 5: break inheritance (copy), then remove
        lambda: (
            _run_icacls_sync([path, "/inheritance:d"]),
            _run_icacls_sync([path, "/remove", f"*{sid}", "/T", "/C"]),
        ),
        # Strategy 6: non-recursive reset on target path only, then remove
        # (resets only the target directory's DACL to inherited defaults,
        # does NOT affect child objects — safe for workspace directories)
        lambda: (
            _run_icacls_sync([path, "/reset"]),
            _run_icacls_sync([path, "/remove", f"*{sid}", "/T", "/C"]),
        ),
    ]

    for attempt, strategy in enumerate(strategies, 1):
        strategy()

        if attempt > 1:
            time.sleep(1)

        if _verify_acl_removed_sync(path, sid):
            return True

    logger.warning(
        "ACL for SID %s could NOT be removed from %s after %d attempts",
        sid,
        path,
        len(strategies),
    )
    return False


def _is_pid_alive(pid: int) -> bool:
    """Checks whether a process with the given PID is still running.

    Uses kernel32.OpenProcess with PROCESS_QUERY_LIMITED_INFORMATION.
    Returns False if the process does not exist or has terminated.
    """
    if pid <= 0:
        return False
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    try:
        kernel32 = _get_kernel32()
        handle = kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid,
        )
        if not handle:
            return False
        # Process exists — check if it has exited
        exit_code = ctypes.wintypes.DWORD(0)
        kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        kernel32.CloseHandle(handle)
        # STILL_ACTIVE (259) means the process is still running
        return exit_code.value == 259
    except OSError:
        return False


def shutdown_cleanup() -> None:
    """Destroys sandbox instances owned by this process or orphaned.

    Performs full cleanup for each sandbox found on disk whose owner
    process is no longer running (or is our own PID). Sandboxes owned
    by other still-running QwenPaw processes are left untouched.

    Cleanup steps per sandbox:
      - Removes filesystem ACL entries
      - Removes Windows Firewall block rules
      - Deletes local user accounts
      - Removes user profile directories (with takeown)
      - Deletes on-disk metadata files

    This function is synchronous and blocking. It should be called from
    the application shutdown hook (FastAPI lifespan teardown or atexit).

    Safe to call multiple times (idempotent after first call).
    """
    sb_dir = _sandboxes_dir(_sandbox_state_dir)
    if not sb_dir.exists() or not list(sb_dir.glob("*.json")):
        return

    my_pid = os.getpid()

    for meta_file in sb_dir.glob("*.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        owner_pid = meta.get("owner_pid")

        # Skip sandboxes owned by other still-running processes
        if owner_pid is not None and owner_pid != my_pid:
            if _is_pid_alive(owner_pid):
                logger.debug(
                    "Skipping sandbox %s — owner pid %d still alive",
                    meta.get("sandbox_id", "?"),
                    owner_pid,
                )
                continue

        username = meta.get("username", "")
        if username:
            logger.info(
                "Cleaning sandbox metadata: %s",
                username,
            )
            _cleanup_from_metadata(meta, meta_file)

    _remove_python_dir_acl_marker()

    # Clean up the sandboxes directory if now empty
    if sb_dir.exists() and not list(sb_dir.glob("*.json")):
        try:
            sb_dir.rmdir()
        except OSError:
            pass


def _remove_acls_from_metadata(
    acl_entries: list,
    cap_sid: str,
    user_sid: str,
    username: str,
) -> None:
    """Remove ACL entries recorded in sandbox metadata."""
    for entry in acl_entries:
        entry_path = entry.get("path", "")
        sid_type = entry.get("sid_type", "")
        if not entry_path or not os.path.exists(entry_path):
            continue

        if sid_type == "cap":
            sid = cap_sid
        elif sid_type == "user":
            sid = user_sid
        else:
            sid = cap_sid or user_sid

        if sid:
            _remove_acl_with_verify_sync(entry_path, sid)

    # Remove ACLs from profile directory
    if username:
        sys_drive = os.environ.get("SystemDrive", "C:")
        profile_dir = os.path.join(
            sys_drive + os.sep,
            "Users",
            username,
        )
        if os.path.exists(profile_dir):
            if cap_sid:
                _remove_acl_with_verify_sync(
                    profile_dir,
                    cap_sid,
                )
            if user_sid:
                _remove_acl_with_verify_sync(
                    profile_dir,
                    user_sid,
                )


def _cleanup_from_metadata(meta: dict, meta_file: Path) -> None:
    """Cleanup a sandbox from its on-disk metadata.

    Mirrors _cleanup_single_restricted_sandbox in the cleanup script:
    ACL removal → firewall → user → profile → metadata.
    """
    username = meta.get("username", "")
    user_sid = meta.get("user_sid", "")
    cap_sid = meta.get("cap_sid", "")
    network_blocked = meta.get("network_blocked", False)
    acl_entries = meta.get("acl_entries", [])

    # Step 1: Remove ACL entries with verification
    _remove_acls_from_metadata(
        acl_entries,
        cap_sid,
        user_sid,
        username,
    )

    # Step 2: Remove firewall rules
    if network_blocked and username:
        _remove_firewall_rules_sync(username)

    # Step 3: Delete user account
    if username:
        _delete_local_user_sync(username)

    # Step 4: Remove profile directory
    if username:
        _remove_profile_dir_sync(username)

    # Step 5: Delete metadata file
    try:
        meta_file.unlink()
    except OSError:
        pass


# ── atexit safety net ──
# Register shutdown_cleanup as an atexit handler so that sandbox artifacts
# are cleaned up even if the FastAPI lifespan teardown is bypassed (e.g.
# SIGTERM handled by Python's default handler, or sys.exit() called from
# arbitrary code). The atexit handler is a best-effort safety net — it
# will NOT run on SIGKILL, power loss, or os._exit().
atexit.register(shutdown_cleanup)
