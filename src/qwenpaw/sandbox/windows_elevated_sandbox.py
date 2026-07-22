# -*- coding: utf-8 -*-
"""Windows elevated sandbox implementation.

Uses a dedicated local user account with a WRITE_RESTRICTED token and
WFP firewall rules for process isolation. Read/execute access uses
normal DACL evaluation (no per-directory read ACEs needed); only write
operations check the restricting SID list.

Selected when ``allow_read_all=True`` and the process has administrator
privileges. Without admin, ``WindowsUnelevatedSandbox`` is used instead.

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
from .windows_unelevated_sandbox import (
    _PROCESS_INFORMATION,
    _SID_AND_ATTRIBUTES,
    _STARTUPINFOW,
    _WC,
    WindowsSandboxBase,
    _build_explicit_access,
    _build_shell_command_line,
    _copy_sid_from_ptr,
    _create_job_object,
    _create_stdio_pipes,
    _create_well_known_sid,
    _decode_pipe_output,
    _enable_privilege,
    _get_logon_sid_bytes,
    _get_python_install_dir,
    _is_admin,
    _is_pid_alive,
    _make_env_block,
    _make_random_cap_sid_string,
    _read_pipe,
    _set_default_dacl,
    _sid_to_string,
    _string_to_sid,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Constants (module-specific)
# ═══════════════════════════════════════════════════════════════════════════

SANDBOX_USERS_GROUP = "QwenpawUsers"

_LUA_TOKEN = 0x04

_TokenUser = 1

# CreateProcessWithTokenW logon flags
_LOGON_WITH_PROFILE = 0x00000001

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
# Cached DLL accessors (module-local — different argtypes from shared)
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
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.HANDLE,
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
            ctypes.wintypes.DWORD,
            ctypes.wintypes.BOOL,
            ctypes.wintypes.DWORD,
        ]
        _dll_kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
        _dll_kernel32.TerminateProcess.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.c_uint,
        ]
        _dll_kernel32.TerminateProcess.restype = ctypes.wintypes.BOOL
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
        _dll_kernel32.GetCurrentThreadId.argtypes = []
        _dll_kernel32.GetCurrentThreadId.restype = ctypes.wintypes.DWORD
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
        _dll_advapi32.LogonUserW.argtypes = [
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
            ctypes.POINTER(ctypes.wintypes.HANDLE),
        ]
        _dll_advapi32.LogonUserW.restype = ctypes.wintypes.BOOL
        _dll_advapi32.LookupAccountNameW.argtypes = [
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.LPCWSTR,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.wintypes.DWORD),
            ctypes.wintypes.LPWSTR,
            ctypes.POINTER(ctypes.wintypes.DWORD),
            ctypes.POINTER(ctypes.wintypes.DWORD),
        ]
        _dll_advapi32.LookupAccountNameW.restype = ctypes.wintypes.BOOL
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
        _dll_advapi32.CreateProcessWithTokenW.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.LPWSTR,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.wintypes.LPCWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        _dll_advapi32.CreateProcessWithTokenW.restype = ctypes.wintypes.BOOL
        _dll_advapi32.GetSecurityInfo.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        _dll_advapi32.GetSecurityInfo.restype = ctypes.wintypes.DWORD
        _dll_advapi32.SetSecurityInfo.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        _dll_advapi32.SetSecurityInfo.restype = ctypes.wintypes.DWORD
        _dll_advapi32.GetSecurityDescriptorDacl.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.wintypes.BOOL),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.wintypes.BOOL),
        ]
        _dll_advapi32.GetSecurityDescriptorDacl.restype = ctypes.wintypes.BOOL
        _dll_advapi32.InitializeSecurityDescriptor.argtypes = [
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
        ]
        _dll_advapi32.InitializeSecurityDescriptor.restype = (
            ctypes.wintypes.BOOL
        )
        _dll_advapi32.SetSecurityDescriptorDacl.argtypes = [
            ctypes.c_void_p,
            ctypes.wintypes.BOOL,
            ctypes.c_void_p,
            ctypes.wintypes.BOOL,
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
            ctypes.wintypes.HANDLE,
            ctypes.POINTER(ctypes.wintypes.DWORD),
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
            ctypes.POINTER(ctypes.wintypes.DWORD),
        ]
        _dll_user32.GetUserObjectSecurity.restype = ctypes.wintypes.BOOL
        _dll_user32.SetUserObjectSecurity.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.POINTER(ctypes.wintypes.DWORD),
            ctypes.c_void_p,
        ]
        _dll_user32.SetUserObjectSecurity.restype = ctypes.wintypes.BOOL
    return _dll_user32


def _get_userenv():
    global _dll_userenv
    if _dll_userenv is None:
        _dll_userenv = ctypes.WinDLL("userenv.dll", use_last_error=True)
        _dll_userenv.CreateProfile.argtypes = [
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.LPCWSTR,
            ctypes.c_wchar_p,
            ctypes.wintypes.DWORD,
        ]
        _dll_userenv.CreateProfile.restype = ctypes.wintypes.LONG
        _dll_userenv.GetUserProfileDirectoryW.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.wintypes.DWORD),
        ]
        _dll_userenv.GetUserProfileDirectoryW.restype = ctypes.wintypes.BOOL
    return _dll_userenv


# ═══════════════════════════════════════════════════════════════════════════
# SID utilities (module-specific)
# ═══════════════════════════════════════════════════════════════════════════


def _lookup_account_sid(
    account_name: str,
) -> Optional[Tuple[ctypes.Array, int]]:
    """Resolves an account name to a SID buffer.

    Args:
        account_name: Local account or group name.

    Returns:
        Tuple of ``(sid_buffer, sid_size)``, or None if the account
        is not found.
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
    """Generates a random password for sandbox user accounts.

    Args:
        length: Password length.

    Returns:
        Random password string.
    """
    chars = (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        "0123456789!@#$%^&*()-_=+"
    )
    return "".join(random.choice(chars) for _ in range(length))


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.c_void_p),
    ]


def _local_free(ptr: int) -> None:
    ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(ptr))


def _dpapi_encrypt(plaintext: str) -> str:
    """Encrypts a string using DPAPI (current user scope).

    Args:
        plaintext: String to encrypt.

    Returns:
        Base64-encoded ciphertext.

    Raises:
        OSError: If ``CryptProtectData`` fails.
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
        None,
        None,
        None,
        None,
        0,
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

    Args:
        ciphertext_b64: Base64-encoded DPAPI ciphertext.

    Returns:
        Decrypted plaintext string.

    Raises:
        OSError: If ``CryptUnprotectData`` fails.
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
        None,
        None,
        None,
        None,
        0,
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
    advapi32 = _get_advapi32()

    result = _lookup_account_sid(username)
    if result is None:
        raise OSError(
            f"LookupAccountNameW failed for '{username}': "
            f"error={ctypes.get_last_error()}",
        )
    sid_buf, _ = result
    psid = ctypes.cast(sid_buf, ctypes.c_void_p)

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
    advapi32 = _get_advapi32()
    h_token = ctypes.wintypes.HANDLE()
    ok = advapi32.LogonUserW(
        ctypes.c_wchar_p(username),
        ctypes.c_wchar_p("."),
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
    userenv = _get_userenv()
    buf = ctypes.create_unicode_buffer(260)
    hr = userenv.CreateProfile(
        ctypes.c_wchar_p(user_sid_string),
        ctypes.c_wchar_p(username),
        buf,
        ctypes.wintypes.DWORD(260),
    )
    if hr == 0:
        profile_path = buf.value
        logger.debug("CreateProfile succeeded: %s", profile_path)
        return profile_path
    elif hr == -2147024713:
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
    userenv = _get_userenv()
    size = ctypes.wintypes.DWORD(0)
    userenv.GetUserProfileDirectoryW(h_token, None, ctypes.byref(size))
    if size.value == 0:
        return None
    buf = ctypes.create_unicode_buffer(size.value)
    ok = userenv.GetUserProfileDirectoryW(h_token, buf, ctypes.byref(size))
    if ok:
        return buf.value
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Token creation (module-specific — different params from unelevated)
# ═══════════════════════════════════════════════════════════════════════════


def _get_token_info_raw(
    h_token: ctypes.wintypes.HANDLE,
    info_class: int,
    label: str,
) -> ctypes.Array:
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


def _get_user_sid_bytes(h_token: ctypes.wintypes.HANDLE) -> bytes:
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
    """Creates a WRITE_RESTRICTED token for the elevated sandbox.

    In WRITE_RESTRICTED mode only write access checks the restricting
    SID list; read/execute access uses normal DACL evaluation.

    The restricting SID list is:
    ``[capabilities…, user_sid, logon_sid, Everyone]``.

    Args:
        h_base_token: Handle to the sandbox user's logon token.
        cap_sid_strings: Capability SID strings to include in the
            restricting list.

    Returns:
        Handle to the new restricted token.

    Raises:
        OSError: If ``CreateRestrictedToken`` fails.
    """
    advapi32 = _get_advapi32()
    kernel32 = _get_kernel32()

    logon_sid_bytes = _get_logon_sid_bytes(h_base_token)
    user_sid_bytes = _get_user_sid_bytes(h_base_token)

    sid_buffers: List[Any] = []
    entries: List[_SID_AND_ATTRIBUTES] = []
    cap_psids: List[ctypes.c_void_p] = []

    for sid_str in cap_sid_strings:
        psid = _string_to_sid(sid_str)
        cap_psids.append(psid)
        entries.append(_SID_AND_ATTRIBUTES(Sid=psid, Attributes=0))

    user_buf = (ctypes.c_ubyte * len(user_sid_bytes))(*user_sid_bytes)
    sid_buffers.append(user_buf)
    user_ptr = ctypes.cast(user_buf, ctypes.c_void_p)
    entries.append(_SID_AND_ATTRIBUTES(Sid=user_ptr, Attributes=0))

    logon_buf = (ctypes.c_ubyte * len(logon_sid_bytes))(*logon_sid_bytes)
    sid_buffers.append(logon_buf)
    logon_ptr = ctypes.cast(logon_buf, ctypes.c_void_p)
    entries.append(_SID_AND_ATTRIBUTES(Sid=logon_ptr, Attributes=0))

    _WinWorldSid = 1
    everyone_bytes = _create_well_known_sid(_WinWorldSid)
    everyone_buf = (ctypes.c_ubyte * len(everyone_bytes))(*everyone_bytes)
    sid_buffers.append(everyone_buf)
    everyone_ptr = ctypes.cast(everyone_buf, ctypes.c_void_p)
    entries.append(_SID_AND_ATTRIBUTES(Sid=everyone_ptr, Attributes=0))

    array_type = _SID_AND_ATTRIBUTES * len(entries)
    restricting_sids = array_type(*entries)
    flags = _WC.DISABLE_MAX_PRIVILEGE | _LUA_TOKEN | _WC.WRITE_RESTRICTED
    new_token = ctypes.wintypes.HANDLE()
    ok = advapi32.CreateRestrictedToken(
        h_base_token,
        flags,
        0,
        None,
        0,
        None,
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

    try:
        dacl_sids = [logon_ptr] + cap_psids
        _set_default_dacl(new_token, dacl_sids)
        _enable_privilege(new_token, _WC.SE_CHANGE_NOTIFY_NAME)
    except Exception:
        kernel32.CloseHandle(new_token)
        raise
    finally:
        for psid in cap_psids:
            kernel32.LocalFree(psid)

    return new_token


# ═══════════════════════════════════════════════════════════════════════════
# ACL management via Win32 API (module-specific — calls _ensure_privileges)
# ═══════════════════════════════════════════════════════════════════════════


_privileges_enabled = False


def _ensure_privileges() -> None:
    """Enables required security privileges on the current process token.

    Privileges enabled: ``SeRestorePrivilege``, ``SeBackupPrivilege``,
    ``SeTakeOwnershipPrivilege``, ``SeImpersonatePrivilege``,
    ``SeAssignPrimaryTokenPrivilege``, ``SeIncreaseQuotaPrivilege``.

    Called once and cached; subsequent calls are no-ops.
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
    """Sets a single inheritable ACE on a filesystem path's DACL.

    Args:
        path: Filesystem path.
        psid: Pointer to the trustee SID.
        access_mask: Access rights bitmask.
        access_mode: ``SET_ACCESS``, ``GRANT_ACCESS``, or
            ``DENY_ACCESS``.

    Returns:
        True if the ACE was set successfully.
    """
    _ensure_privileges()
    advapi32 = _get_advapi32()
    kernel32 = _get_kernel32()

    p_sd = ctypes.c_void_p()
    p_dacl = ctypes.c_void_p()
    code = advapi32.GetNamedSecurityInfoW(
        ctypes.c_wchar_p(path),
        _WC.SE_FILE_OBJECT,
        _WC.DACL_SECURITY_INFORMATION,
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
        _WC.CONTAINER_INHERIT_ACE | _WC.OBJECT_INHERIT_ACE,
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
        _WC.SE_FILE_OBJECT,
        _WC.DACL_SECURITY_INFORMATION,
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


_ACL_READ_EXECUTE = _WC.FILE_GENERIC_READ | _WC.FILE_GENERIC_EXECUTE

_ACL_FULL_ACCESS = (
    _WC.FILE_GENERIC_READ
    | _WC.FILE_GENERIC_WRITE
    | _WC.FILE_GENERIC_EXECUTE
    | _WC.DELETE
    | _WC.FILE_DELETE_CHILD
)

_ACL_DENY_ALL = _ACL_FULL_ACCESS | _WC.GENERIC_ALL


def _add_allow_ace(path: str, psid: ctypes.c_void_p) -> bool:
    return _set_path_ace(path, psid, _ACL_FULL_ACCESS, _WC.SET_ACCESS)


def _add_allow_read_ace(path: str, psid: ctypes.c_void_p) -> bool:
    return _set_path_ace(path, psid, _ACL_READ_EXECUTE, _WC.SET_ACCESS)


def _add_deny_all_ace(path: str, psid: ctypes.c_void_p) -> bool:
    return _set_path_ace(path, psid, _ACL_DENY_ALL, _WC.DENY_ACCESS)


def _allow_null_device(psid: ctypes.c_void_p) -> None:
    kernel32 = _get_kernel32()
    advapi32 = _get_advapi32()

    desired = 0x00020000 | 0x00040000
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
        _WC.DACL_SECURITY_INFORMATION,
        None,
        None,
        ctypes.byref(p_dacl),
        None,
        ctypes.byref(p_sd),
    )
    if code == 0:
        entry = _build_explicit_access(
            psid,
            _WC.FILE_GENERIC_READ
            | _WC.FILE_GENERIC_WRITE
            | _WC.FILE_GENERIC_EXECUTE,
            _WC.SET_ACCESS,
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
                _WC.DACL_SECURITY_INFORMATION,
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


_python_dir_acl_granted: bool = False


def _ensure_python_dir_group_acl() -> None:
    """Grants read/execute access to the ``QwenpawUsers`` group.

    Targets the Python install directory.

    This is a one-time operation: a marker file is written after the
    ACL is set to skip the grant on subsequent calls.
    """
    global _python_dir_acl_granted
    if _python_dir_acl_granted:
        return

    python_dir = _get_python_install_dir()
    if not python_dir or not os.path.isdir(python_dir):
        _python_dir_acl_granted = True
        return

    result = _lookup_account_sid(SANDBOX_USERS_GROUP)
    if result is None:
        logger.debug(
            "_ensure_python_dir_group_acl: group %s not found, skipping",
            SANDBOX_USERS_GROUP,
        )
        _python_dir_acl_granted = True
        return

    sid_buf, _ = result
    group_psid = ctypes.cast(sid_buf, ctypes.c_void_p)

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
        try:
            with open(marker_path, "w", encoding="utf-8") as f:
                f.write(SANDBOX_USERS_GROUP)
        except OSError:
            pass

    _python_dir_acl_granted = True


def _remove_python_dir_acl_marker() -> None:
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
    path: str
    access_mode: str
    sid_type: str


def _apply_all_acls(
    config: SandboxConfig,
    cap_sid_string: str,
    user_sid_string: str,
) -> List[_AclEntry]:
    """Applies filesystem ACLs for the elevated sandbox.

    Grants write access to workspace and mounts for both the capability
    SID and the user SID, denies access to deny_paths for the user SID,
    and ensures the Python install directory is readable via the
    ``QwenpawUsers`` group.

    Args:
        config: Sandbox configuration.
        cap_sid_string: Capability SID string for the restricting list.
        user_sid_string: Sandbox user's SID string.

    Returns:
        List of ``_AclEntry`` records describing the ACLs applied.
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
    rule_name_out = f"QwenPaw_Block_{username}_Out"
    rule_name_in = f"QwenPaw_Block_{username}_In"

    sddl_user = f"D:(A;;CC;;;{user_sid})"

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
    user32 = _get_user32()
    advapi32 = _get_advapi32()
    kernel32 = _get_kernel32()

    if not h_obj:
        logger.debug("_grant_object_access(%s): NULL handle", label)
        return

    si_flags = ctypes.wintypes.DWORD(_WC.DACL_SECURITY_INFORMATION)

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
        _WC.GENERIC_ALL,
        _WC.GRANT_ACCESS,
        _WC.CONTAINER_INHERIT_ACE | _WC.OBJECT_INHERIT_ACE,
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

    _SECURITY_DESCRIPTOR_REVISION = 1
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
        True,
        p_new_dacl,
        False,
    )
    if not ok:
        kernel32.LocalFree(p_new_dacl)
        logger.debug(
            "_grant_object_access(%s): SetSecurityDescriptorDacl failed",
            label,
        )
        return

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
# Process spawn with restricted token
# ═══════════════════════════════════════════════════════════════════════════


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

    Tries ``CreateProcessWithTokenW`` first and falls back to
    ``CreateProcessAsUserW`` on failure.

    Args:
        h_token: Restricted token handle.
        cmd: Command to execute.
        cwd: Working directory for the child process.
        env: Environment variables for the child process.
        shell_executable: Shell binary path.

    Returns:
        Tuple of ``(pid, process_handle, stdout_read, stderr_read,
        job_handle)``.

    Raises:
        OSError: If both process creation methods fail.
    """
    kernel32 = _get_kernel32()
    advapi32 = _get_advapi32()

    stdout_read, stdout_write, stderr_read, stderr_write = _create_stdio_pipes(
        kernel32,
    )

    si = _STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.dwFlags = _WC.STARTF_USESTDHANDLES
    si.hStdInput = None
    si.hStdOutput = stdout_write
    si.hStdError = stderr_write
    si.lpDesktop = "WinSta0\\Default"

    env_block = _make_env_block(env)
    pi = _PROCESS_INFORMATION()
    creation_flags = _WC.CREATE_UNICODE_ENVIRONMENT | _WC.CREATE_NO_WINDOW

    _ensure_privileges()
    shell_cmd = _build_shell_command_line(cmd, shell_executable)
    cmd_line = ctypes.create_unicode_buffer(shell_cmd)

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
        err_with_token = ctypes.get_last_error()
        logger.debug(
            "CreateProcessWithTokenW failed (error=%d), "
            "falling back to CreateProcessAsUserW",
            err_with_token,
        )
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


async def _wait_and_read_process(
    process_handle: ctypes.wintypes.HANDLE,
    stdout_handle: ctypes.wintypes.HANDLE,
    stderr_handle: ctypes.wintypes.HANDLE,
    timeout_seconds: int,
    job_handle: Optional[ctypes.wintypes.HANDLE] = None,
) -> Tuple[int, str, str, bool]:
    """Waits for process completion and reads pipe output.

    Drains stdout/stderr in parallel with the process wait. On timeout,
    terminates via the Job Object (if available) or directly.

    Args:
        process_handle: Handle to the child process.
        stdout_handle: Read end of the stdout pipe.
        stderr_handle: Read end of the stderr pipe.
        timeout_seconds: Maximum seconds to wait.
        job_handle: Optional Job Object handle for group termination.

    Returns:
        Tuple of ``(exit_code, stdout, stderr, timed_out)``.
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
        timed_out = result == _WC.WAIT_TIMEOUT
        if timed_out:
            if job_handle:
                kernel32.TerminateJobObject(job_handle, 1)
            else:
                kernel32.TerminateProcess(process_handle, 1)
            kernel32.WaitForSingleObject(process_handle, 5000)
        return timed_out

    stdout_future = loop.run_in_executor(None, _drain_stdout)
    stderr_future = loop.run_in_executor(None, _drain_stderr)
    wait_future = loop.run_in_executor(None, _wait_process)

    timed_out, stdout_data, stderr_data = await asyncio.gather(
        wait_future,
        stdout_future,
        stderr_future,
    )

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
    return state_dir / "sandboxes"


class _SandboxInstance:
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


_sandbox_state_dir = (
    Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / ".qwenpaw"
)


def _find_reusable_sandbox(
    sandbox_name: str,
) -> Optional[_SandboxInstance]:
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
    try:
        username = meta["username"]

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
            try:
                h_user_token = _logon_user(username, password)
            except OSError:
                password = None

        if not password:
            password = _random_password()
            if not _ensure_local_user(username, password):
                return None
            h_user_token = _logon_user(username, password)

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
    if not _is_admin():
        raise OSError(
            "WindowsElevatedSandbox requires administrator privileges. "
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

    _create_user_profile(user_sid_string, username)
    profile_dir = _resolve_profile_dir(h_user_token, username)

    for sub in (
        os.path.join("AppData", "Local", "Temp"),
        os.path.join("AppData", "Roaming"),
    ):
        p = os.path.join(profile_dir, sub)
        os.makedirs(p, exist_ok=True)

    _grant_winsta_desktop_access(user_sid_string)

    network_blocked = not (
        bool(config.network_allow) and "*" in config.network_allow
    )
    if network_blocked:
        _install_wfp_block_filters(username, user_sid_string)

    cap_sid = _make_random_cap_sid_string()
    acl_entries = _apply_all_acls(config, cap_sid, user_sid_string)

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
    instance.close()
    logger.debug("Closed sandbox %s", instance.sandbox_id)


# ═══════════════════════════════════════════════════════════════════════════
# WindowsElevatedSandbox class
# ═══════════════════════════════════════════════════════════════════════════


class WindowsElevatedSandbox(WindowsSandboxBase):
    """Windows elevated sandbox with a WRITE_RESTRICTED token.

    Uses a dedicated user account for process isolation.

    Used when ``allow_read_all=True`` and the process has administrator
    privileges. Reads work via normal DACL evaluation; writes are gated
    by the restricting SID list. Network is blocked via WFP firewall
    rules when ``network_allow`` is empty.

    Sandbox instances are cached on disk and reused across invocations
    with identical configurations.

    Lifecycle:
        ``__aenter__``: Acquires a sandbox instance (creates or reuses).
        ``execute``: Launches a command with the restricted token.
        ``__aexit__`` / ``stop``: Terminates the running process and
            releases the instance reference.
    """

    def __init__(self, config: SandboxConfig):
        super().__init__(config)
        self._instance: Optional[_SandboxInstance] = None
        self._process_id: Optional[int] = None

    async def __aenter__(self):
        self._instance = await _acquire_sandbox(self._config)
        return self

    async def execute(
        self,
        cmd: str,
        cwd: Optional[str] = None,
    ) -> ExecutionResult:
        if not self._instance:
            await self.__aenter__()

        assert self._instance is not None
        h_token = self._instance.h_token
        start = time.monotonic()
        effective_cwd = cwd or self._config.workspace_dir

        env = self._build_base_env()
        sandbox_user = self._instance.username
        env["USERNAME"] = sandbox_user
        env["USERDOMAIN"] = os.environ.get("COMPUTERNAME", ".")

        sys_drive = os.environ.get("SystemDrive", "C:")
        sandbox_profile = self._instance.profile_dir or (
            f"{sys_drive}\\Users\\{sandbox_user}"
        )
        env["USERPROFILE"] = sandbox_profile
        env["APPDATA"] = f"{sandbox_profile}\\AppData\\Roaming"
        env["LOCALAPPDATA"] = f"{sandbox_profile}\\AppData\\Local"
        env["TEMP"] = f"{sandbox_profile}\\AppData\\Local\\Temp"
        env["TMP"] = f"{sandbox_profile}\\AppData\\Local\\Temp"
        env["HOMEDRIVE"] = sys_drive
        env["HOMEPATH"] = sandbox_profile[len(sys_drive) :]

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
                duration_ms=duration_ms,
            )

    async def stop(self) -> None:
        kernel32 = _get_kernel32()

        if self._job_handle is not None:
            try:
                kernel32.TerminateJobObject(self._job_handle, 1)
            except OSError:
                pass
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
# Shutdown cleanup
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
    result = _run_cmd_sync(["net", "user", username, "/delete"])
    return result is not None and result.returncode == 0


def _remove_profile_dir_sync(username: str) -> bool:
    import shutil
    import stat

    sys_drive = os.environ.get("SystemDrive", "C:")
    profile_dir = os.path.join(sys_drive + os.sep, "Users", username)
    if not os.path.exists(profile_dir):
        return True

    _run_cmd_sync(
        ["takeown", "/F", profile_dir, "/A", "/D", "Y"],
        timeout=30,
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
        timeout=60,
    )

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


_SHUTDOWN_ACL_DEADLINE: float = 0.0
_SHUTDOWN_ACL_TIMEOUT_PER_SANDBOX: float = 10.0


def _remaining_budget() -> float:
    if not _SHUTDOWN_ACL_DEADLINE:
        return 3600.0
    remaining = _SHUTDOWN_ACL_DEADLINE - time.monotonic()
    return max(0.0, remaining)


def _run_icacls_sync_local(
    args: List[str],
    timeout: Optional[float] = None,
) -> bool:
    """Module-local ``icacls`` runner with budget-aware timeout.

    Args:
        args: Arguments to pass to ``icacls``.
        timeout: Maximum seconds. Defaults to the remaining shutdown
            budget (capped at 180 s).

    Returns:
        True if icacls exited with code 0.
    """
    if timeout is None:
        timeout = min(180.0, _remaining_budget())
    if timeout <= 0:
        return False
    result = _run_cmd_sync(
        ["icacls"] + args,
        timeout=int(timeout),
    )
    return result is not None and result.returncode == 0


def _verify_acl_removed_sync_local(
    path: str,
    sid: str,
    timeout: Optional[float] = None,
) -> bool:
    if not os.path.exists(path):
        return True
    if timeout is None:
        timeout = min(180.0, _remaining_budget())
    if timeout <= 0:
        return False
    result = _run_cmd_sync(
        ["icacls", path],
        timeout=int(timeout),
    )
    if result is None:
        return False
    output = result.stdout.decode("utf-8", errors="replace")
    if sid in output:
        return False
    if sid.upper() in output.upper():
        return False
    return True


def _remove_acl_with_verify_sync_local(
    path: str,
    sid: str,
    *,
    reset_only: bool = False,
) -> bool:
    """Budget-aware ACL removal for elevated sandbox shutdown cleanup.

    Uses the same multi-strategy approach as the shared
    ``_remove_acl_with_verify_sync``, but respects the module-level
    shutdown deadline.

    Args:
        path: Filesystem path to clean.
        sid: SID string to remove from the DACL.
        reset_only: If True, only use the reset+remove strategy.

    Returns:
        True if the SID was successfully removed.
    """
    if not os.path.exists(path):
        return True

    strategies = [
        lambda: _run_icacls_sync_local([path, "/remove", f"*{sid}"]),
        lambda: _run_icacls_sync_local(
            [path, "/remove", f"*{sid}", "/T", "/C"],
        ),
        lambda: (
            _run_icacls_sync_local([path, "/remove:g", f"*{sid}", "/T", "/C"]),
            _run_icacls_sync_local([path, "/remove:d", f"*{sid}", "/T", "/C"]),
        ),
        lambda: (
            _run_icacls_sync_local([path, "/inheritance:e"]),
            _run_icacls_sync_local([path, "/remove", f"*{sid}", "/T", "/C"]),
        ),
        lambda: (
            _run_icacls_sync_local([path, "/inheritance:d"]),
            _run_icacls_sync_local([path, "/remove", f"*{sid}", "/T", "/C"]),
        ),
        lambda: (
            _run_icacls_sync_local([path, "/reset"]),
            _run_icacls_sync_local([path, "/remove", f"*{sid}", "/T", "/C"]),
        ),
    ]

    if reset_only:
        strategies = [strategies[-1]]

    for attempt, strategy in enumerate(strategies, 1):
        if (
            _SHUTDOWN_ACL_DEADLINE
            and time.monotonic() > _SHUTDOWN_ACL_DEADLINE
        ):
            logger.warning(
                "ACL cleanup timeout reached; skipping remaining ACL "
                "removal for %s (will retry on next admin startup)",
                path,
            )
            return False

        strategy()

        if attempt > 1:
            remaining = _remaining_budget()
            if remaining <= 0:
                logger.warning(
                    "ACL cleanup budget exhausted between strategies; "
                    "skipping remaining attempts for %s",
                    path,
                )
                return False
            time.sleep(min(1.0, remaining))

        if _verify_acl_removed_sync_local(path, sid):
            return True

    logger.warning(
        "ACL for SID %s could NOT be removed from %s after %d attempts",
        sid,
        path,
        len(strategies),
    )
    return False


def shutdown_cleanup() -> None:
    """Destroys elevated sandbox instances owned by this process or orphaned.

    Iterates metadata files under ``~/.qwenpaw/sandboxes/``, skips
    sandboxes whose owner process is still alive, and cleans up the
    rest (ACLs, firewall rules, local user accounts, profile
    directories).
    """
    global _SHUTDOWN_ACL_DEADLINE

    from ..utils.platform import is_windows_admin

    if not is_windows_admin():
        return

    sb_dir = _sandboxes_dir(_sandbox_state_dir)
    if not sb_dir.exists() or not list(sb_dir.glob("*.json")):
        return

    sandbox_count = len(list(sb_dir.glob("*.json")))
    _SHUTDOWN_ACL_DEADLINE = (
        time.monotonic() + sandbox_count * _SHUTDOWN_ACL_TIMEOUT_PER_SANDBOX
    )

    my_pid = os.getpid()

    for meta_file in sb_dir.glob("*.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        owner_pid = meta.get("owner_pid")

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

    if sb_dir.exists() and not list(sb_dir.glob("*.json")):
        try:
            sb_dir.rmdir()
        except OSError:
            pass


def _remove_acls_from_metadata(
    acl_entries: list,
    cap_sid: str,
    user_sid: str,
    _username: str,
) -> None:
    _workspace_default = os.path.normpath(
        os.path.join(
            os.path.expanduser("~"),
            ".qwenpaw",
            "workspaces",
            "default",
        ),
    )

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
            use_reset_only = os.path.normpath(entry_path) == _workspace_default
            _remove_acl_with_verify_sync_local(
                entry_path,
                sid,
                reset_only=use_reset_only,
            )


def _cleanup_from_metadata(meta: dict, meta_file: Path) -> None:
    username = meta.get("username", "")
    user_sid = meta.get("user_sid", "")
    cap_sid = meta.get("cap_sid", "")
    network_blocked = meta.get("network_blocked", False)
    acl_entries = meta.get("acl_entries", [])

    _remove_acls_from_metadata(
        acl_entries,
        cap_sid,
        user_sid,
        username,
    )

    if network_blocked and username:
        _remove_firewall_rules_sync(username)

    if username:
        _delete_local_user_sync(username)

    if username:
        _remove_profile_dir_sync(username)

    try:
        meta_file.unlink()
    except OSError:
        pass


atexit.register(shutdown_cleanup)
