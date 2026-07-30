# -*- coding: utf-8 -*-
"""Windows elevated sandbox implementation.

Uses a dedicated local user account with a WRITE_RESTRICTED token and WFP
firewall rules for process isolation.  Read/execute access uses normal DACL
evaluation; only write operations check the restricting SID list.

Selected when ``allow_read_all=True`` and the process has administrator
privileges.  Requires Windows 10 1507+.
"""

import asyncio
import atexit
import base64
import ctypes
import ctypes.wintypes
import json
import logging
import os
import random
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import ExecutionResult, SandboxConfig
from .windows_unelevated_sandbox import (
    _PROCESS_INFORMATION,
    _SID_AND_ATTRIBUTES,
    _STARTUPINFOW,
    _WC,
    WindowsSandboxBase,
    _AclEntry,
    _build_explicit_access,
    _build_shell_command_line,
    _compute_config_fingerprint,
    _copy_sid_from_ptr,
    _create_job_object,
    _create_stdio_pipes,
    _create_well_known_sid,
    _enable_privilege,
    _get_logon_sid_bytes,
    _get_python_install_dir,
    _is_admin,
    _iter_orphaned_metadata,
    _make_env_block,
    _make_random_cap_sid_string,
    _qwenpaw_state_dir,
    _remove_acl_with_verify_sync,
    _sandbox_file_lock,
    _save_sandbox_metadata,
    _set_default_dacl,
    _set_path_ace,
    _sid_to_string,
    _string_to_sid,
    _wait_and_read_process,
)
from .windows_unelevated_sandbox import (
    _get_advapi32 as _get_shared_advapi32,
)
from .windows_unelevated_sandbox import (
    _get_kernel32 as _get_shared_kernel32,
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
# DLL accessors — extend shared ones with elevated-specific argtypes
# ═══════════════════════════════════════════════════════════════════════════

_elevated_kernel32_ready: bool = False
_elevated_advapi32_ready: bool = False
_dll_netapi32: Optional[Any] = None
_dll_ntdll: Optional[Any] = None
_dll_user32: Optional[Any] = None
_dll_userenv: Optional[Any] = None


def _get_kernel32():
    """Returns shared kernel32 with elevated-specific argtypes added."""
    global _elevated_kernel32_ready
    dll = _get_shared_kernel32()
    if not _elevated_kernel32_ready:
        dll.CreateFileW.argtypes = [
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.HANDLE,
        ]
        dll.CreateFileW.restype = ctypes.wintypes.HANDLE
        dll.GetCurrentThreadId.argtypes = []
        dll.GetCurrentThreadId.restype = ctypes.wintypes.DWORD
        _elevated_kernel32_ready = True
    return dll


def _get_advapi32():
    """Returns shared advapi32 with elevated-specific argtypes added."""
    global _elevated_advapi32_ready
    dll = _get_shared_advapi32()
    if not _elevated_advapi32_ready:
        dll.LogonUserW.argtypes = [
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
            ctypes.POINTER(ctypes.wintypes.HANDLE),
        ]
        dll.LogonUserW.restype = ctypes.wintypes.BOOL
        dll.LookupAccountNameW.argtypes = [
            ctypes.wintypes.LPCWSTR,
            ctypes.wintypes.LPCWSTR,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.wintypes.DWORD),
            ctypes.wintypes.LPWSTR,
            ctypes.POINTER(ctypes.wintypes.DWORD),
            ctypes.POINTER(ctypes.wintypes.DWORD),
        ]
        dll.LookupAccountNameW.restype = ctypes.wintypes.BOOL
        dll.CreateProcessWithTokenW.argtypes = [
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
        dll.CreateProcessWithTokenW.restype = ctypes.wintypes.BOOL
        dll.GetSecurityInfo.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        dll.GetSecurityInfo.restype = ctypes.wintypes.DWORD
        dll.SetSecurityInfo.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        dll.SetSecurityInfo.restype = ctypes.wintypes.DWORD
        dll.GetSecurityDescriptorDacl.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.wintypes.BOOL),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.wintypes.BOOL),
        ]
        dll.GetSecurityDescriptorDacl.restype = ctypes.wintypes.BOOL
        dll.InitializeSecurityDescriptor.argtypes = [
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
        ]
        dll.InitializeSecurityDescriptor.restype = ctypes.wintypes.BOOL
        dll.SetSecurityDescriptorDacl.argtypes = [
            ctypes.c_void_p,
            ctypes.wintypes.BOOL,
            ctypes.c_void_p,
            ctypes.wintypes.BOOL,
        ]
        dll.SetSecurityDescriptorDacl.restype = ctypes.wintypes.BOOL
        dll.MakeSelfRelativeSD.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.wintypes.DWORD),
        ]
        dll.MakeSelfRelativeSD.restype = ctypes.wintypes.BOOL
        _elevated_advapi32_ready = True
    return dll


def _get_netapi32():
    global _dll_netapi32
    if _dll_netapi32 is None:
        _dll_netapi32 = ctypes.WinDLL("netapi32.dll", use_last_error=True)
    return _dll_netapi32


def _get_ntdll():
    """Returns ntdll with NtSetSecurityObject configured."""
    global _dll_ntdll
    if _dll_ntdll is None:
        _dll_ntdll = ctypes.WinDLL("ntdll.dll", use_last_error=True)
        _dll_ntdll.NtSetSecurityObject.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
        ]
        _dll_ntdll.NtSetSecurityObject.restype = ctypes.wintypes.LONG
    return _dll_ntdll


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
    """Resolves a local account name to a SID buffer.

    Args:
        account_name: Local account or group name.

    Returns:
        ``(sid_buffer, sid_size)`` tuple, or ``None`` if not found.
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
    """Generates a random password for sandbox user accounts."""
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
        OSError: If CryptProtectData fails.
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
        OSError: If CryptUnprotectData fails.
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

    The restricting SID list is
    ``[capabilities…, user_sid, logon_sid, Everyone]``.

    Args:
        h_base_token: Handle to the sandbox user's logon token.
        cap_sid_strings: Capability SID strings to include in the
            restricting list.

    Returns:
        Handle to the new restricted token.

    Raises:
        OSError: If CreateRestrictedToken fails.
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

    Enables SeRestorePrivilege, SeBackupPrivilege,
    SeTakeOwnershipPrivilege, SeImpersonatePrivilege,
    SeAssignPrimaryTokenPrivilege, and SeIncreaseQuotaPrivilege.

    Called once; subsequent calls are no-ops.
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


def _set_path_ace_elevated(
    path: str,
    psid: ctypes.c_void_p,
    access_mask: int,
    access_mode: int,
) -> bool:
    """Sets a single inheritable ACE after enabling admin privileges."""
    _ensure_privileges()
    return _set_path_ace(path, psid, access_mask, access_mode, inherit=True)


_ACL_READ_EXECUTE = _WC.FILE_GENERIC_READ | _WC.FILE_GENERIC_EXECUTE

_ACL_FULL_ACCESS = (
    _WC.FILE_GENERIC_READ
    | _WC.FILE_GENERIC_WRITE
    | _WC.FILE_GENERIC_EXECUTE
    | _WC.DELETE
    | _WC.FILE_DELETE_CHILD
)

_ACL_DENY_ALL = _ACL_FULL_ACCESS | _WC.GENERIC_ALL

# Minimal traverse mask: allows PowerShell/.NET to validate each path
# segment via Directory.Exists() without granting content read access.
# FILE_LIST_DIRECTORY (0x0001) + FILE_TRAVERSE (0x0020) +
# READ_CONTROL (0x00020000) + SYNCHRONIZE (0x00100000)
_ACL_TRAVERSE = 0x00120021


def _add_traverse_ace(  # pylint: disable=too-many-return-statements
    path: str,
    psid: ctypes.c_void_p,
) -> bool:
    """Adds a non-inheritable traverse ACE on a directory.

    Uses NtSetSecurityObject.

    Uses the NT native API to directly write the modified DACL, bypassing
    the Win32 layer's expensive recursive inheritance propagation.  This is
    O(1) regardless of how many children the directory contains.

    Grants FILE_LIST_DIRECTORY | FILE_TRAVERSE | READ_CONTROL |
    SYNCHRONIZE — the minimum for PowerShell/.NET path validation.
    """
    _ensure_privileges()

    advapi32 = _get_advapi32()
    kernel32 = _get_kernel32()
    ntdll = _get_ntdll()

    # Open directory handle with WRITE_DAC | READ_CONTROL
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _OPEN_EXISTING = 3
    _FILE_SHARE_ALL = 0x07
    _WRITE_DAC = 0x00040000
    _READ_CONTROL = 0x00020000

    h_dir = kernel32.CreateFileW(
        ctypes.c_wchar_p(path),
        _WRITE_DAC | _READ_CONTROL,
        _FILE_SHARE_ALL,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if not h_dir or h_dir == ctypes.c_void_p(-1).value:
        logger.warning(
            "_add_traverse_ace: CreateFileW(%s) failed: err=%d",
            path,
            ctypes.get_last_error(),
        )
        return False

    try:
        # Read existing DACL
        p_sd = ctypes.c_void_p()
        p_dacl = ctypes.c_void_p()
        rc = advapi32.GetSecurityInfo(
            h_dir,
            _WC.SE_FILE_OBJECT,
            _WC.DACL_SECURITY_INFORMATION,
            None,
            None,
            ctypes.byref(p_dacl),
            None,
            ctypes.byref(p_sd),
        )
        if rc != 0:
            logger.warning(
                "_add_traverse_ace: GetSecurityInfo(%s) failed: rc=%d",
                path,
                rc,
            )
            return False

        try:
            # Build and merge the new ACE
            ea = _build_explicit_access(
                psid,
                _ACL_TRAVERSE,
                _WC.SET_ACCESS,
                0,
            )
            new_dacl = ctypes.c_void_p()
            rc2 = advapi32.SetEntriesInAclW(
                1,
                ctypes.byref(ea),
                p_dacl,
                ctypes.byref(new_dacl),
            )
            if rc2 != 0:
                logger.warning(
                    "_add_traverse_ace: SetEntriesInAclW(%s) failed: rc=%d",
                    path,
                    rc2,
                )
                return False

            try:
                # Build self-relative SD for NtSetSecurityObject
                _SECURITY_DESCRIPTOR_REVISION = 1
                sd_size = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 20
                sd_abs = (ctypes.c_ubyte * sd_size)()
                advapi32.InitializeSecurityDescriptor(
                    ctypes.cast(sd_abs, ctypes.c_void_p),
                    _SECURITY_DESCRIPTOR_REVISION,
                )
                advapi32.SetSecurityDescriptorDacl(
                    ctypes.cast(sd_abs, ctypes.c_void_p),
                    True,
                    new_dacl,
                    False,
                )

                sr_size = ctypes.wintypes.DWORD(0)
                advapi32.MakeSelfRelativeSD(
                    ctypes.cast(sd_abs, ctypes.c_void_p),
                    None,
                    ctypes.byref(sr_size),
                )
                if sr_size.value == 0:
                    logger.warning(
                        "_add_traverse_ace: "
                        "MakeSelfRelativeSD size query failed",
                    )
                    return False

                sd_sr = (ctypes.c_ubyte * sr_size.value)()
                ok = advapi32.MakeSelfRelativeSD(
                    ctypes.cast(sd_abs, ctypes.c_void_p),
                    ctypes.cast(sd_sr, ctypes.c_void_p),
                    ctypes.byref(sr_size),
                )
                if not ok:
                    logger.warning(
                        "_add_traverse_ace: MakeSelfRelativeSD failed",
                    )
                    return False

                # Write directly via NT API (no inheritance propagation)
                status = ntdll.NtSetSecurityObject(
                    h_dir,
                    _WC.DACL_SECURITY_INFORMATION,
                    ctypes.cast(sd_sr, ctypes.c_void_p),
                )
                if status != 0:
                    logger.warning(
                        "_add_traverse_ace: NtSetSecurityObject(%s) failed: "
                        "NTSTATUS=0x%08X",
                        path,
                        status & 0xFFFFFFFF,
                    )
                    return False
                return True
            finally:
                if new_dacl:
                    kernel32.LocalFree(new_dacl)
        finally:
            if p_sd:
                kernel32.LocalFree(p_sd)
    finally:
        kernel32.CloseHandle(h_dir)


def _remove_traverse_ace(  # pylint: disable=R0911,R0912,R0915
    path: str,
    sid_string: str,
) -> bool:
    """Removes traverse ACEs for a SID from a directory.

    Uses NtSetSecurityObject.

    Uses the NT native API to write the modified DACL directly, avoiding
    the expensive recursive inheritance propagation triggered by
    SetNamedSecurityInfoW.

    Args:
        path: Filesystem path to clean.
        sid_string: SID string to remove from the DACL.

    Returns:
        True if the SID was removed or the path does not exist.
    """
    if not os.path.exists(path):
        return True

    _ensure_privileges()

    advapi32 = _get_advapi32()
    kernel32 = _get_kernel32()
    ntdll = _get_ntdll()

    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _OPEN_EXISTING = 3
    _FILE_SHARE_ALL = 0x07
    _WRITE_DAC = 0x00040000
    _READ_CONTROL = 0x00020000

    h_dir = kernel32.CreateFileW(
        ctypes.c_wchar_p(path),
        _WRITE_DAC | _READ_CONTROL,
        _FILE_SHARE_ALL,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if not h_dir or h_dir == ctypes.c_void_p(-1).value:
        logger.warning(
            "_remove_traverse_ace: CreateFileW(%s) failed: err=%d",
            path,
            ctypes.get_last_error(),
        )
        return False

    try:
        # Read existing DACL
        p_sd = ctypes.c_void_p()
        p_dacl = ctypes.c_void_p()
        rc = advapi32.GetSecurityInfo(
            h_dir,
            _WC.SE_FILE_OBJECT,
            _WC.DACL_SECURITY_INFORMATION,
            None,
            None,
            ctypes.byref(p_dacl),
            None,
            ctypes.byref(p_sd),
        )
        if rc != 0:
            logger.warning(
                "_remove_traverse_ace: GetSecurityInfo(%s) failed: rc=%d",
                path,
                rc,
            )
            return False

        try:
            # Resolve SID string to pointer for comparison
            psid_target = _string_to_sid(sid_string)
            try:
                # Find and delete matching ACEs
                class _ACL_SIZE_INFORMATION(ctypes.Structure):
                    _fields_ = [
                        ("AceCount", ctypes.wintypes.DWORD),
                        ("AclBytesInUse", ctypes.wintypes.DWORD),
                        ("AclBytesFree", ctypes.wintypes.DWORD),
                    ]

                acl_info = _ACL_SIZE_INFORMATION()
                ok = advapi32.GetAclInformation(
                    p_dacl,
                    ctypes.byref(acl_info),
                    ctypes.sizeof(acl_info),
                    2,
                )
                if not ok:
                    return False

                to_delete = []
                for i in range(acl_info.AceCount):
                    ace_ptr = ctypes.c_void_p()
                    if not advapi32.GetAce(p_dacl, i, ctypes.byref(ace_ptr)):
                        continue
                    if ace_ptr.value is None:
                        continue
                    sid_ptr = ctypes.c_void_p(ace_ptr.value + 8)
                    if advapi32.IsValidSid(sid_ptr) and advapi32.EqualSid(
                        sid_ptr,
                        psid_target,
                    ):
                        to_delete.append(i)

                if not to_delete:
                    return True  # Nothing to remove

                for idx in reversed(to_delete):
                    advapi32.DeleteAce(p_dacl, idx)

                # Build self-relative SD and write via NtSetSecurityObject
                _SECURITY_DESCRIPTOR_REVISION = 1
                sd_size = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 20
                sd_abs = (ctypes.c_ubyte * sd_size)()
                advapi32.InitializeSecurityDescriptor(
                    ctypes.cast(sd_abs, ctypes.c_void_p),
                    _SECURITY_DESCRIPTOR_REVISION,
                )
                advapi32.SetSecurityDescriptorDacl(
                    ctypes.cast(sd_abs, ctypes.c_void_p),
                    True,
                    p_dacl,
                    False,
                )

                sr_size = ctypes.wintypes.DWORD(0)
                advapi32.MakeSelfRelativeSD(
                    ctypes.cast(sd_abs, ctypes.c_void_p),
                    None,
                    ctypes.byref(sr_size),
                )
                if sr_size.value == 0:
                    return False

                sd_sr = (ctypes.c_ubyte * sr_size.value)()
                ok = advapi32.MakeSelfRelativeSD(
                    ctypes.cast(sd_abs, ctypes.c_void_p),
                    ctypes.cast(sd_sr, ctypes.c_void_p),
                    ctypes.byref(sr_size),
                )
                if not ok:
                    return False

                status = ntdll.NtSetSecurityObject(
                    h_dir,
                    _WC.DACL_SECURITY_INFORMATION,
                    ctypes.cast(sd_sr, ctypes.c_void_p),
                )
                if status != 0:
                    logger.warning(
                        "_remove_traverse_ace: "
                        "NtSetSecurityObject(%s) failed: "
                        "NTSTATUS=0x%08X",
                        path,
                        status & 0xFFFFFFFF,
                    )
                    return False
                return True
            finally:
                kernel32.LocalFree(psid_target)
        finally:
            if p_sd:
                kernel32.LocalFree(p_sd)
    finally:
        kernel32.CloseHandle(h_dir)


def _allow_ace_matches_any_sid(
    advapi32: Any,
    ace_ptr: ctypes.c_void_p,
    sids: List[ctypes.c_void_p],
    required_access_mask: int = 0,
) -> bool:
    """Returns whether an ALLOW ACE grants the requested access to a SID."""
    if ace_ptr.value is None:
        return False

    # ACE layout: header (4 bytes), mask (4 bytes), then SID.
    ace_type = ctypes.cast(
        ace_ptr,
        ctypes.POINTER(ctypes.c_ubyte),
    )[0]
    if ace_type != 0:  # ACCESS_ALLOWED_ACE_TYPE
        return False

    access_mask = ctypes.cast(
        ctypes.c_void_p(ace_ptr.value + 4),
        ctypes.POINTER(ctypes.wintypes.DWORD),
    )[0]
    if required_access_mask and (access_mask & required_access_mask) != (
        required_access_mask
    ):
        return False

    sid_ptr = ctypes.c_void_p(ace_ptr.value + 8)
    if not advapi32.IsValidSid(sid_ptr):
        return False
    return any(advapi32.EqualSid(sid_ptr, candidate) for candidate in sids)


def _check_any_sid_in_dacl(
    path: str,
    sids: List[ctypes.c_void_p],
    required_access_mask: int = 0,
) -> bool:
    """Checks whether any of the given SIDs has an ALLOW ACE in the path.

    Uses the Win32 API directly (no subprocess) to enumerate ACEs and
    compare SIDs via EqualSid.

    Args:
        path: Filesystem path to check.
        sids: List of SID pointers to look for.

    Returns:
        True if at least one ACCESS_ALLOWED ACE matching any SID exists.
    """
    if not sids:
        return False

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
        return False

    try:

        class _ACL_SIZE_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("AceCount", ctypes.wintypes.DWORD),
                ("AclBytesInUse", ctypes.wintypes.DWORD),
                ("AclBytesFree", ctypes.wintypes.DWORD),
            ]

        acl_info = _ACL_SIZE_INFORMATION()
        _AclSizeInformation = 2
        ok = advapi32.GetAclInformation(
            p_dacl,
            ctypes.byref(acl_info),
            ctypes.sizeof(acl_info),
            _AclSizeInformation,
        )
        if not ok:
            return False

        for i in range(acl_info.AceCount):
            ace_ptr = ctypes.c_void_p()
            if not advapi32.GetAce(p_dacl, i, ctypes.byref(ace_ptr)):
                continue
            if _allow_ace_matches_any_sid(
                advapi32,
                ace_ptr,
                sids,
                required_access_mask,
            ):
                return True

        return False
    finally:
        if p_sd:
            kernel32.LocalFree(p_sd)


def _add_allow_ace(path: str, psid: ctypes.c_void_p) -> bool:
    return _set_path_ace_elevated(path, psid, _ACL_FULL_ACCESS, _WC.SET_ACCESS)


def _add_allow_read_ace(path: str, psid: ctypes.c_void_p) -> bool:
    return _set_path_ace_elevated(
        path,
        psid,
        _ACL_READ_EXECUTE,
        _WC.SET_ACCESS,
    )


def _add_deny_all_ace(path: str, psid: ctypes.c_void_p) -> bool:
    return _set_path_ace_elevated(path, psid, _ACL_DENY_ALL, _WC.DENY_ACCESS)


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


def _python_executable_has_group_acl(
    python_dir: str,
    group_psid: ctypes.c_void_p,
) -> bool:
    """Checks that the active Python executable still has the group ACE."""
    python_executable = os.path.abspath(sys.executable)
    try:
        inside_python_dir = os.path.commonpath(
            [python_executable, os.path.abspath(python_dir)],
        ) == os.path.abspath(python_dir)
    except ValueError:
        inside_python_dir = False

    if not inside_python_dir or not os.path.isfile(python_executable):
        return False
    return _check_any_sid_in_dacl(
        python_executable,
        [group_psid],
        required_access_mask=_ACL_READ_EXECUTE,
    )


def _grant_python_dir_group_acl_recursive(python_dir: str) -> bool:
    """Recursively restores RX access for existing Python runtime files."""
    result = _run_cmd_sync(
        [
            "icacls",
            python_dir,
            "/grant",
            f"{SANDBOX_USERS_GROUP}:(OI)(CI)RX",
            "/T",
            "/C",
            "/Q",
        ],
        timeout=300,
    )
    if result is None or result.returncode != 0:
        logger.warning(
            "Failed to recursively grant RX to %s on Python dir: %s",
            SANDBOX_USERS_GROUP,
            python_dir,
        )
        return False
    return True


def _ensure_python_dir_group_acl() -> None:
    """Grants read/execute access to QwenpawUsers on the Python install dir.

    The active Python executable is checked even when the marker exists because
    another sandbox manager may have rebuilt inherited ACLs after the initial
    grant. Existing runtime files are repaired recursively when that happens.
    """
    global _python_dir_acl_granted

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
    acl_present = _python_executable_has_group_acl(python_dir, group_psid)
    if acl_present:
        logger.debug(
            "_ensure_python_dir_group_acl: Python executable ACL is valid",
        )
        _python_dir_acl_granted = True
        return

    logger.info(
        "Granting RX to %s on Python dir: %s (recursive, may be slow)",
        SANDBOX_USERS_GROUP,
        python_dir,
    )
    result = _grant_python_dir_group_acl_recursive(python_dir)
    if result and _python_executable_has_group_acl(python_dir, group_psid):
        try:
            with open(marker_path, "w", encoding="utf-8") as f:
                f.write(SANDBOX_USERS_GROUP)
        except OSError:
            pass
        _python_dir_acl_granted = True
    else:
        _python_dir_acl_granted = False


def _ensure_workspace_traverse_acls(
    workspace_dir: str,
    user_psid: ctypes.c_void_p,
) -> List[_AclEntry]:
    """Grants traverse ACEs on parent dirs up to workspace_dir.

    Uses NtSetSecurityObject which completes in <1ms per directory regardless
    of child count.  Since the overhead is negligible, we unconditionally set
    traverse ACEs on every parent directory without checking existing
    permissions first.

    Args:
        workspace_dir: The sandbox workspace directory path.
        user_psid: Pointer to the sandbox user's SID.

    Returns:
        List of :class:`_AclEntry` entries for newly applied traverse
        ACEs (to be included in sandbox metadata for cleanup).
    """
    entries: List[_AclEntry] = []

    ws_norm = os.path.normpath(workspace_dir)
    drive_root = os.path.splitdrive(ws_norm)[0] + os.sep

    # Collect all parent directories from drive root (exclusive) down to
    # the immediate parent of workspace_dir (inclusive).
    intermediates: List[str] = []
    current = os.path.dirname(ws_norm)
    root_norm = os.path.normcase(os.path.normpath(drive_root))
    while True:
        current_norm = os.path.normcase(os.path.normpath(current))
        if current_norm == root_norm:
            break
        parent = os.path.dirname(current)
        if os.path.normcase(parent) == current_norm:
            break  # reached filesystem root
        intermediates.append(current)
        current = parent

    intermediates.reverse()  # top-down order

    for d in intermediates:
        if not os.path.isdir(d):
            continue
        if _add_traverse_ace(d, user_psid):
            entries.append(_AclEntry(d, "traverse", "user"))
            logger.debug("  Traverse ACE set on: %s", d)
        else:
            logger.warning("  Failed to set traverse ACE on: %s", d)

    return entries


def _apply_all_acls(
    config: SandboxConfig,
    cap_sid_string: str,
    user_sid_string: str,
) -> List[_AclEntry]:
    """Applies filesystem ACLs for the elevated sandbox.

    Grants write to workspace/mounts for both the capability SID and user
    SID, denies deny_paths, ensures Python dir is readable, and grants
    traverse on parent directories.

    Args:
        config: Sandbox configuration.
        cap_sid_string: Capability SID string for the restricting list.
        user_sid_string: Sandbox user's SID string.

    Returns:
        List of applied ACL entries.
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

        user_psid = _string_to_sid(user_sid_string)
        try:
            _grant_workspace_and_mounts(user_psid, "user")

            # Grant traverse on all parent directories from drive root
            # to workspace_dir using the sandbox user's SID.
            # Uses NtSetSecurityObject (<1ms per dir, no propagation).
            # These are per-sandbox and cleaned up on exit.
            traverse_entries = _ensure_workspace_traverse_acls(
                config.workspace_dir,
                user_psid,
            )
            entries.extend(traverse_entries)

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

    Tries CreateProcessWithTokenW first and falls back to
    CreateProcessAsUserW on failure.

    Args:
        h_token: Restricted token handle.
        cmd: Command to execute.
        cwd: Working directory for the child process.
        env: Environment variables for the child process.
        shell_executable: Shell binary path.

    Returns:
        Tuple of (pid, process_handle, stdout_read, stderr_read,
        job_handle).

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
# Pipe reading and process waiting (delegates to shared helper)
# ═══════════════════════════════════════════════════════════════════════════


async def _async_wait_and_read(
    process_handle: ctypes.wintypes.HANDLE,
    stdout_handle: ctypes.wintypes.HANDLE,
    stderr_handle: ctypes.wintypes.HANDLE,
    timeout_seconds: int,
    job_handle: Optional[ctypes.wintypes.HANDLE] = None,
) -> Tuple[int, str, str, bool]:
    """Async wrapper around the shared ``_wait_and_read_process``."""
    return await asyncio.to_thread(
        _wait_and_read_process,
        process_handle,
        stdout_handle,
        stderr_handle,
        timeout_seconds,
        job_handle,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Sandbox registry (instance caching and parallel isolation)
# ═══════════════════════════════════════════════════════════════════════════


def _compute_elevated_fingerprint(config: SandboxConfig) -> str:
    python_dir = _get_python_install_dir()
    return _compute_config_fingerprint(
        config,
        extra_fields={
            "python_dir": os.path.normpath(python_dir) if python_dir else None,
        },
    )


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


def _find_reusable_sandbox(
    sandbox_name: str,
) -> Optional[_SandboxInstance]:
    sb_dir = _sandboxes_dir(_qwenpaw_state_dir)
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

        password_was_reset = False
        if password:
            try:
                h_user_token = _logon_user(username, password)
            except OSError:
                password = None

        if not password:
            password = _random_password()
            if not _ensure_local_user(username, password):
                return None
            try:
                h_user_token = _logon_user(username, password)
            except OSError as e:
                # If logon still fails after password reset, grant batch
                # logon right (may have been lost) and retry once.
                logger.debug(
                    "LogonUserW failed after password reset for %s: %s; "
                    "re-granting SeBatchLogonRight and retrying",
                    username,
                    e,
                )
                try:
                    _grant_batch_logon_right(username)
                except OSError:
                    pass
                h_user_token = _logon_user(username, password)
            password_was_reset = True

        # Always update owner_pid so that shutdown_cleanup in other
        # processes knows this sandbox is actively in use.  Also persist
        # the new password when it was reset, so subsequent startups
        # don't encounter stale credentials (error 1326).
        try:
            meta["owner_pid"] = os.getpid()
            if password_was_reset:
                meta["encrypted_password"] = _dpapi_encrypt(password)
            meta_file.write_text(
                json.dumps(meta, indent=2),
                encoding="utf-8",
            )
        except OSError:
            logger.debug(
                "Failed to persist updated metadata for %s",
                username,
            )

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
    meta_path = _save_sandbox_metadata(
        _sandboxes_dir(_qwenpaw_state_dir),
        sandbox_id,
        meta,
    )

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


def _acquire_sandbox_sync(config: SandboxConfig) -> _SandboxInstance:
    """Acquires a sandbox instance under a cross-process file lock.

    Serializes concurrent callers to prevent password-reset races.
    """
    fingerprint = _compute_elevated_fingerprint(config)
    sandbox_name = f"qwenpaw_{fingerprint[:12]}"

    with _sandbox_file_lock(sandbox_name):
        existing = _find_reusable_sandbox(sandbox_name)
        if existing is not None:
            logger.debug("Reusing sandbox %s from disk", existing.sandbox_id)
            return existing

        return _create_new_sandbox(config, fingerprint)


async def _acquire_sandbox(config: SandboxConfig) -> _SandboxInstance:
    return await asyncio.to_thread(_acquire_sandbox_sync, config)


async def _release_sandbox(instance: _SandboxInstance) -> None:
    instance.close()
    logger.debug("Closed sandbox %s", instance.sandbox_id)


# ═══════════════════════════════════════════════════════════════════════════
# WindowsElevatedSandbox class
# ═══════════════════════════════════════════════════════════════════════════


class WindowsElevatedSandbox(WindowsSandboxBase):
    """Elevated sandbox using a dedicated user + WRITE_RESTRICTED token.

    Reads use normal DACL evaluation; writes are gated by the
    restricting SID list.  Network is blocked via WFP firewall rules
    when ``network_allow`` is empty.  Instances are cached on disk and
    reused across invocations with identical configurations.
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
            ) = await _async_wait_and_read(
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
        except asyncio.CancelledError:
            await self.stop()
            raise
        except OSError as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            await self.stop()
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

        When no process was ever started (e.g. CreateProcess OSError), skip
        loading ``kernel32`` so cross-platform unit tests can still exercise
        the error-mapping path without ``ctypes.WinDLL``.
        """
        has_process = (
            self._job_handle is not None
            or self._process_id is not None
            or self._process_handle is not None
        )
        if not has_process:
            if self._instance is not None:
                await _release_sandbox(self._instance)
                self._instance = None
            return
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
    """Removes inbound/outbound firewall block rules for a sandbox user."""
    rule_name_out = f"QwenPaw_Block_{username}_Out"
    rule_name_in = f"QwenPaw_Block_{username}_In"

    ok = True
    for rule_name in (rule_name_out, rule_name_in):
        result = _run_cmd_sync(
            [
                "netsh",
                "advfirewall",
                "firewall",
                "delete",
                "rule",
                f"name={rule_name}",
            ],
            timeout=15,
        )
        # netsh returns 0 on success, 1 if rule not found (acceptable).
        if result is None:
            ok = False

    return ok


def _delete_local_user_sync(username: str) -> bool:
    result = _run_cmd_sync(["net", "user", username, "/delete"])
    return result is not None and result.returncode == 0


def _remove_profile_dir_sync(username: str, user_sid: str = "") -> bool:
    """Removes the sandbox user's profile directory.

    Uses ``reg unload`` + ``rd /s /q``; falls back to ``takeown /R``
    if the first attempt leaves remnants.
    """
    sys_drive = os.environ.get("SystemDrive", "C:")
    profile_dir = os.path.join(sys_drive + os.sep, "Users", username)
    if not os.path.exists(profile_dir):
        return True

    # Unload the user's registry hive to release NTUSER.DAT lock.
    if user_sid:
        _run_cmd_sync(
            ["reg", "unload", f"HKU\\{user_sid}"],
            timeout=15,
        )

    # Fast kernel-mode recursive delete.
    _run_cmd_sync(
        ["cmd", "/c", "rd", "/s", "/q", profile_dir],
        timeout=60,
    )

    if not os.path.exists(profile_dir):
        return True

    # Fallback: take ownership recursively then retry.
    _run_cmd_sync(
        ["takeown", "/F", profile_dir, "/R", "/A", "/D", "Y"],
        timeout=60,
    )
    _run_cmd_sync(
        ["cmd", "/c", "rd", "/s", "/q", profile_dir],
        timeout=60,
    )

    return not os.path.exists(profile_dir)


_SHUTDOWN_ACL_DEADLINE: float = 0.0
_SHUTDOWN_ACL_TIMEOUT_PER_SANDBOX: float = 20.0


def _remaining_budget() -> float:
    if not _SHUTDOWN_ACL_DEADLINE:
        return 3600.0
    remaining = _SHUTDOWN_ACL_DEADLINE - time.monotonic()
    return max(0.0, remaining)


def _run_icacls_sync_local(
    args: List[str],
    timeout: Optional[float] = None,
) -> bool:
    """Runs icacls with budget-aware timeout.

    Args:
        args: Arguments to pass to icacls.
        timeout: Maximum seconds (defaults to remaining shutdown budget,
            capped at 180 s).

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


def _remove_acl_with_verify_sync_local(  # pylint: disable=unused-argument
    path: str,
    sid: str,
    *,
    reset_only: bool = False,
) -> bool:
    """Budget-aware ACL removal for elevated sandbox shutdown cleanup.

    Delegates to the shared _remove_acl_with_verify_sync; falls back to
    ``icacls /reset`` on failure.

    Args:
        path: Filesystem path to clean.
        sid: SID string to remove from the DACL.
        reset_only: Unused (kept for API compatibility).

    Returns:
        True if the SID was successfully removed.
    """
    if not os.path.exists(path):
        return True

    if _SHUTDOWN_ACL_DEADLINE and time.monotonic() > _SHUTDOWN_ACL_DEADLINE:
        logger.warning(
            "ACL cleanup timeout reached; skipping removal for %s "
            "(will retry on next admin startup)",
            path,
        )
        return False

    deadline = _SHUTDOWN_ACL_DEADLINE if _SHUTDOWN_ACL_DEADLINE else 0.0
    if _remove_acl_with_verify_sync(path, sid, deadline=deadline):
        return True

    # Last-resort fallback: reset DACL inheritance and retry removal.
    _run_icacls_sync_local([path, "/reset"])
    if _remove_acl_with_verify_sync(path, sid, deadline=deadline):
        return True

    logger.warning(
        "ACL for SID %s could NOT be removed from %s after all attempts",
        sid,
        path,
    )
    return False


def shutdown_cleanup() -> None:
    """Cleans up elevated sandbox instances owned by this process or orphaned.

    Removes ACLs, firewall rules, local user accounts, and profile
    directories for sandboxes whose owner process is dead.
    """
    global _SHUTDOWN_ACL_DEADLINE

    from ..utils.platform import is_windows_admin

    if not is_windows_admin():
        return

    sb_dir = _sandboxes_dir(_qwenpaw_state_dir)
    orphaned = _iter_orphaned_metadata(sb_dir)
    if not orphaned:
        return

    t_start = time.monotonic()
    _SHUTDOWN_ACL_DEADLINE = (
        time.monotonic() + len(orphaned) * _SHUTDOWN_ACL_TIMEOUT_PER_SANDBOX
    )
    logger.info(
        "Elevated sandbox shutdown_cleanup: %d sandbox(es) to process",
        len(orphaned),
    )

    for meta_file, meta in orphaned:
        username = meta.get("username", "")
        if username:
            logger.info("Cleaning sandbox metadata: %s", username)
            _cleanup_from_metadata(meta, meta_file)

    if sb_dir.exists() and not list(sb_dir.glob("*.json")):
        try:
            sb_dir.rmdir()
        except OSError:
            pass

    logger.info(
        "Elevated sandbox shutdown_cleanup complete: %.2fs total",
        time.monotonic() - t_start,
    )


def _remove_acls_from_metadata(
    acl_entries: list,
    cap_sid: str,
    user_sid: str,
    _username: str,
) -> int:
    """Removes ACLs from metadata entries. Returns count of failures."""
    _workspace_default = os.path.normpath(
        os.path.join(
            os.path.expanduser("~"),
            ".qwenpaw",
            "workspaces",
            "default",
        ),
    )

    failed = 0
    for entry in acl_entries:
        entry_path = entry.get("path", "")
        sid_type = entry.get("sid_type", "")
        access_mode = entry.get("access_mode", "")
        if not entry_path or not os.path.exists(entry_path):
            continue

        if sid_type == "cap":
            sid = cap_sid
        elif sid_type == "user":
            sid = user_sid
        elif sid_type == "group":
            # Traverse ACEs for QwenpawUsers group are persistent
            # (one-time, never cleaned up) — skip.
            continue
        else:
            continue

        if sid:
            t_entry = time.monotonic()
            if access_mode == "traverse":
                # Use fast NtSetSecurityObject path for traverse ACEs
                ok = _remove_traverse_ace(entry_path, sid)
            else:
                use_reset_only = (
                    os.path.normpath(entry_path) == _workspace_default
                )
                ok = _remove_acl_with_verify_sync_local(
                    entry_path,
                    sid,
                    reset_only=use_reset_only,
                )
            if not ok:
                failed += 1
            logger.debug(
                "  ACL remove [%s] %s sid_type=%s: %.2fs (%s)",
                "OK" if ok else "FAIL",
                entry_path,
                sid_type,
                time.monotonic() - t_entry,
                sid[:20] + "..." if len(sid) > 20 else sid,
            )
    return failed


def _move_to_failed_cleanup_elevated(
    meta: dict,
    meta_file: Path,
    reason: str,
) -> None:
    """Moves metadata to failed_cleanup/ when cleanup fails."""
    import datetime

    failed_dir = _qwenpaw_state_dir / "failed_cleanup"
    failed_dir.mkdir(parents=True, exist_ok=True)
    dest = failed_dir / meta_file.name
    counter = 1
    while dest.exists():
        dest = failed_dir / f"{meta_file.stem}_{counter}.json"
        counter += 1
    meta["_cleanup_error"] = {
        "reason": reason,
        "timestamp": datetime.datetime.now().isoformat(),
    }
    try:
        dest.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        return
    try:
        meta_file.unlink()
    except OSError:
        pass
    logger.info("Cleanup failed, metadata preserved: %s", dest.name)


def _cleanup_from_metadata(  # pylint: disable=R0912
    meta: dict,
    meta_file: Path,
) -> None:
    username = meta.get("username", "")
    user_sid = meta.get("user_sid", "")
    cap_sid = meta.get("cap_sid", "")
    network_blocked = meta.get("network_blocked", False)
    acl_entries = meta.get("acl_entries", [])
    sandbox_id = meta.get("sandbox_id", username)

    t0 = time.monotonic()
    acl_failed = _remove_acls_from_metadata(
        acl_entries,
        cap_sid,
        user_sid,
        username,
    )
    t1 = time.monotonic()
    logger.info(
        "[%s] ACL removal: %.2fs (%d entries, %d failed)",
        sandbox_id,
        t1 - t0,
        len(acl_entries),
        acl_failed,
    )

    firewall_ok = True
    if network_blocked and username:
        firewall_ok = _remove_firewall_rules_sync(username)
        t2 = time.monotonic()
        logger.info(
            "[%s] Firewall rules removal: %.2fs",
            sandbox_id,
            t2 - t1,
        )
    else:
        t2 = t1

    user_ok = True
    if username:
        user_ok = _delete_local_user_sync(username)
        t3 = time.monotonic()
        logger.info(
            "[%s] User account deletion: %.2fs",
            sandbox_id,
            t3 - t2,
        )
    else:
        t3 = t2

    profile_ok = True
    if username:
        profile_ok = _remove_profile_dir_sync(username, user_sid)
        t4 = time.monotonic()
        logger.info(
            "[%s] Profile directory removal: %.2fs",
            sandbox_id,
            t4 - t3,
        )
    else:
        t4 = t3

    # Determine if any step failed
    failures: List[str] = []
    if acl_failed > 0:
        failures.append(f"ACL removal failed for {acl_failed} path(s)")
    if not firewall_ok:
        failures.append("firewall rule removal failed")
    if not user_ok:
        failures.append("user account deletion failed")
    if not profile_ok:
        failures.append("profile directory removal failed")

    if failures:
        _move_to_failed_cleanup_elevated(
            meta,
            meta_file,
            "; ".join(failures),
        )
    else:
        try:
            meta_file.unlink()
        except OSError:
            pass

    logger.info(
        "[%s] Total cleanup: %.2fs",
        sandbox_id,
        time.monotonic() - t0,
    )


atexit.register(shutdown_cleanup)
