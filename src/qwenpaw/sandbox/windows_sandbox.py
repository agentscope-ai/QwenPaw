# -*- coding: utf-8 -*-
"""Windows AppContainer sandbox implementation (allow_read_all=False).

Uses Windows AppContainer (SID S-1-15-2-*) for native process isolation.
Only paths declared in mounts (plus the workspace) are readable. When
allow_read_all is True, WindowsRestrictedSandbox is used instead.

Requires Windows 10 1507+ (build 10240), icacls.exe, and Python ctypes.
"""

import asyncio
import atexit
import ctypes
import ctypes.wintypes
import hashlib
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import ExecutionResult, SandboxConfig

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

# AppContainer network capability well-known SIDs
# These are the string names recognized by the Windows API
_CAP_INTERNET_CLIENT = "internetClient"
_CAP_INTERNET_CLIENT_SERVER = "internetClientServer"
_CAP_PRIVATE_NETWORK = "privateNetworkClientServer"

# Well-known capability SID strings (S-1-15-3-N)
# internetClient = S-1-15-3-1
# internetClientServer = S-1-15-3-2
# privateNetworkClientServer = S-1-15-3-3
_CAPABILITY_SIDS: Dict[str, str] = {
    _CAP_INTERNET_CLIENT: "S-1-15-3-1",
    _CAP_INTERNET_CLIENT_SERVER: "S-1-15-3-2",
    _CAP_PRIVATE_NETWORK: "S-1-15-3-3",
}

# Violation detection regex (includes Chinese locale patterns)
_VIOLATION_RE = re.compile(
    r"Access is denied"
    r"|error 5\b"
    r"|0x80070005"
    r"|Permission denied"
    r"|\u62d2\u7edd\u8bbf\u95ee"  # 拒绝访问 (Chinese: Access denied)
    r"|\u6743\u9650\u4e0d\u8db3"  # 权限不足
    r"|\u7cfb\u7edf\u65e0\u6cd5\u6267\u884c"
    r"\u6307\u5b9a\u7684\u7a0b\u5e8f",  # 系统无法执行指定的程序
    re.IGNORECASE | re.MULTILINE,
)

# Win32 constants
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_CREATE_NO_WINDOW = 0x08000000
_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
_STARTF_USESTDHANDLES = 0x00000100
_HANDLE_FLAG_INHERIT = 0x00000001
_WAIT_TIMEOUT = 0x00000102
_HRESULT_ERROR_ALREADY_EXISTS = (
    0x800700B7  # HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS=183)
)


# ═══════════════════════════════════════════════════════════════════════════
# Cached DLL accessors (avoid repeated ctypes.WinDLL instantiation)
# ═══════════════════════════════════════════════════════════════════════════

_dll_kernel32: Optional[Any] = None
_dll_userenv: Optional[Any] = None
_dll_advapi32: Optional[Any] = None


def _get_kernel32():
    global _dll_kernel32
    if _dll_kernel32 is None:
        _dll_kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    return _dll_kernel32


def _get_userenv():
    global _dll_userenv
    if _dll_userenv is None:
        _dll_userenv = ctypes.WinDLL("userenv.dll", use_last_error=True)
    return _dll_userenv


def _get_advapi32():
    global _dll_advapi32
    if _dll_advapi32 is None:
        _dll_advapi32 = ctypes.WinDLL("advapi32.dll", use_last_error=True)
    return _dll_advapi32


# ═══════════════════════════════════════════════════════════════════════════
# Win32 API wrappers (ctypes)
# ═══════════════════════════════════════════════════════════════════════════


def _create_appcontainer_profile(
    container_name: str,
    display_name: str,
    description: str,
) -> str:
    """Creates an AppContainer profile and returns its SID string.

    Calls ``userenv.dll:CreateAppContainerProfile``. If the profile already
    exists (``HRESULT 0x800700B7``), derives the SID from the name instead.

    Args:
        container_name: Unique name for the AppContainer profile.
        display_name: Human-readable display name.
        description: Profile description text.

    Returns:
        The AppContainer SID as a string (e.g. ``S-1-15-2-...``).

    Raises:
        OSError: If profile creation fails for a reason other than
            already-existing.
    """
    userenv = _get_userenv()
    advapi32 = _get_advapi32()

    # HRESULT CreateAppContainerProfile(
    #   PCWSTR pszAppContainerName,
    #   PCWSTR pszDisplayName,
    #   PCWSTR pszDescription,
    #   PSID_AND_ATTRIBUTES pCapabilities,
    #   DWORD dwCapabilityCount,
    #   PSID *ppSidAppContainerSid
    # )
    psid = ctypes.c_void_p()
    hr = userenv.CreateAppContainerProfile(
        ctypes.c_wchar_p(container_name),
        ctypes.c_wchar_p(display_name),
        ctypes.c_wchar_p(description),
        None,  # No capabilities at profile creation time
        ctypes.c_uint32(0),
        ctypes.byref(psid),
    )

    hr_unsigned = hr & 0xFFFFFFFF

    if hr_unsigned not in (0, _HRESULT_ERROR_ALREADY_EXISTS):
        raise OSError(
            f"CreateAppContainerProfile failed: HRESULT=0x{hr_unsigned:08x}",
        )

    # If already exists, get SID via DeriveAppContainerSid
    if hr_unsigned == _HRESULT_ERROR_ALREADY_EXISTS:
        sid_str = _get_appcontainer_sid(container_name)
        if sid_str is None:
            raise OSError("AppContainer profile exists but cannot derive SID")
        return sid_str

    # Convert PSID to string
    try:
        sid_str = _sid_to_string(psid, advapi32)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(psid)

    return sid_str


def _delete_appcontainer_profile(container_name: str) -> bool:
    """Deletes an AppContainer profile by name.

    Args:
        container_name: Name of the AppContainer profile to delete.

    Returns:
        True if deleted successfully, False otherwise.
    """
    try:
        userenv = _get_userenv()
        hr = userenv.DeleteAppContainerProfile(
            ctypes.c_wchar_p(container_name),
        )
        return hr == 0
    except OSError:
        return False


def _get_appcontainer_sid(container_name: str) -> Optional[str]:
    """Derives the SID string for an existing AppContainer profile.

    Args:
        container_name: Name of the AppContainer profile.

    Returns:
        The SID string, or None if the profile does not exist or the
        call fails.
    """
    try:
        userenv = _get_userenv()
        advapi32 = _get_advapi32()

        psid = ctypes.c_void_p()
        hr = userenv.DeriveAppContainerSidFromAppContainerName(
            ctypes.c_wchar_p(container_name),
            ctypes.byref(psid),
        )
        if hr != 0:
            return None

        try:
            return _sid_to_string(psid, advapi32)
        finally:
            ctypes.windll.ole32.CoTaskMemFree(psid)
    except OSError:
        return None


def _sid_to_string(psid: ctypes.c_void_p, advapi32: Any = None) -> str:
    """Converts a PSID pointer to its string representation.

    Args:
        psid: Pointer to a SID structure.
        advapi32: Optional pre-loaded advapi32 DLL handle.

    Returns:
        SID string in the form ``S-1-15-2-...``.

    Raises:
        OSError: If ``ConvertSidToStringSidW`` fails.
    """
    if advapi32 is None:
        advapi32 = _get_advapi32()

    string_sid = ctypes.c_wchar_p()
    ret = advapi32.ConvertSidToStringSidW(
        psid,
        ctypes.byref(string_sid),
    )
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
        ctypes.windll.kernel32.LocalFree(string_sid)


def _string_to_sid(sid_string: str) -> ctypes.c_void_p:
    """Converts a SID string to a PSID pointer.

    Args:
        sid_string: SID in string form (e.g. ``S-1-15-2-...``).

    Returns:
        Pointer to the allocated SID structure. Caller must free with
        ``LocalFree``.

    Raises:
        OSError: If ``ConvertStringSidToSidW`` fails.
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


# ═══════════════════════════════════════════════════════════════════════════
# ACL management (icacls.exe)
# ═══════════════════════════════════════════════════════════════════════════


async def _run_icacls(args: List[str], timeout: int = 120) -> Tuple[bool, str]:
    """Runs ``icacls.exe`` asynchronously with the given arguments.

    Args:
        args: Command-line arguments to pass to ``icacls``.
        timeout: Maximum seconds to wait before declaring failure.

    Returns:
        A tuple of ``(success, output_text)``. Output is decoded using
        the OEM code page strategy via ``_decode_pipe_output``.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "icacls",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode == 0, _decode_pipe_output(stdout)
    except asyncio.TimeoutError:
        return False, "icacls timed out"
    except OSError as e:
        return False, str(e)


async def _set_acl_deny(path: str, sid: str, permission: str) -> bool:
    """Applies a deny ACE on a path for the AppContainer SID.

    Uses a single icacls command without breaking inheritance. Explicit
    deny ACEs take precedence over inherited allow ACEs in standard
    Windows DACL evaluation order (explicit deny > explicit allow >
    inherited deny > inherited allow).

    Args:
        path: Filesystem path to deny access on.
        sid: AppContainer SID string (``S-1-15-2-...``).
        permission: Permission string, typically ``"F"`` (full deny).

    Returns:
        True if the icacls command succeeded.
    """
    ok, err = await _run_icacls(
        [path, "/deny", f"*{sid}:(OI)(CI)({permission})"],
    )
    if not ok:
        logger.warning("Failed to deny %s on %s: %s", permission, path, err)
    return ok


async def _set_acl_grant(path: str, sid: str, permission: str) -> bool:
    """Grants an inheritable ACE on a path for the AppContainer SID.

    Does NOT break inheritance — used for additive grants (workspace F,
    mount RX/F) where inherited permissions should be preserved.

    Args:
        path: Filesystem path to grant access on.
        sid: AppContainer SID string.
        permission: One of ``"F"`` (full), ``"RX"`` (read+execute),
            ``"R"`` (read-only).

    Returns:
        True if the icacls command succeeded.
    """
    ok, err = await _run_icacls(
        [path, "/grant", f"*{sid}:(OI)(CI)({permission})"],
    )
    if not ok:
        logger.warning("Failed to set %s ACL on %s: %s", permission, path, err)
    return ok


def _get_python_install_dir() -> Optional[str]:
    """Returns the Python installation root directory, or None.

    Uses ``sys.executable`` to locate the running interpreter and walks
    up to the installation root.  For standard installs the executable
    lives directly in the root (``C:\\Python311\\python.exe``); for
    virtual-envs it may be under ``Scripts/``.
    """
    import sys as _sys

    exe = _sys.executable
    if not exe or not os.path.isfile(exe):
        return None

    # Standard layout: <prefix>/python.exe  or  <prefix>/Scripts/python.exe
    install_dir = os.path.dirname(os.path.abspath(exe))
    # If we're inside a venv Scripts/ dir, go one level up
    if os.path.basename(install_dir).lower() == "scripts":
        install_dir = os.path.dirname(install_dir)
    return install_dir


async def _apply_all_acls(config: SandboxConfig, sid: str) -> Dict[str, Any]:
    """Applies all filesystem ACLs for an AppContainer profile.

    This backend is only used when ``allow_read_all`` is False, so no global
    read grants are applied — AppContainer processes execute system binaries
    via the built-in ``ALL APPLICATION PACKAGES`` (S-1-15-2-1) ACE on Windows
    10+, and everything else must be explicitly mounted.

    Grants (additive, single-step):
        Workspace (F) and non-workspace mounts (F or RX).

    Python interpreter grant:
        The Python installation directory (derived from ``sys.executable``)
        is granted RX so that the interpreter and its standard library are
        accessible from AppContainer processes.  Many install locations
        (e.g. per-user installs under ``%LOCALAPPDATA%``) lack the
        ``ALL APPLICATION PACKAGES`` ACE that system-wide installs carry.

    Deny paths (single-step deny ACE):
        Explicit deny ACEs are applied directly without breaking
        inheritance. Explicit deny ACEs take precedence over inherited
        allow ACEs in standard Windows DACL evaluation order.

    Args:
        config: Sandbox configuration specifying paths and permissions.
        sid: AppContainer SID string to grant/deny.

    Returns:
        An ACL manifest dict recording all paths that were modified.
    """
    grant_paths: List[str] = []
    deny_paths: List[str] = []

    # ── Workspace grant ──────────────────────────────────────────────
    grant_paths.append(config.workspace_dir)
    await _set_acl_grant(config.workspace_dir, sid, "F")

    # ── Mount grants (skip workspace — already granted above) ────────
    ws_norm = os.path.normcase(os.path.normpath(config.workspace_dir))
    for mount in config.mounts:
        mount_norm = os.path.normcase(os.path.normpath(mount.path))
        if mount_norm == ws_norm:
            continue
        perm = "F" if mount.writable else "RX"
        grant_paths.append(mount.path)
        await _set_acl_grant(mount.path, sid, perm)

    # ── Python interpreter grant ─────────────────────────────────────
    python_dir = _get_python_install_dir()
    if python_dir and os.path.isdir(python_dir):
        python_norm = os.path.normcase(os.path.normpath(python_dir))
        if python_norm != ws_norm:
            grant_paths.append(python_dir)
            await _set_acl_grant(python_dir, sid, "RX")
            logger.debug(
                "Granted RX on Python install dir: %s",
                python_dir,
            )

    # ── Deny paths (single-step deny ACE) ─────────────────────────────
    for deny_path in config.deny_paths:
        expanded = os.path.expanduser(deny_path)
        if os.path.exists(expanded):
            deny_paths.append(expanded)
            await _set_acl_deny(expanded, sid, "F")

    return {
        "grant_paths": grant_paths,
        "deny_paths": deny_paths,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Network capability computation
# ═══════════════════════════════════════════════════════════════════════════


def _compute_network_capabilities(
    config: SandboxConfig,
) -> List[str]:
    """Determines AppContainer network capabilities from sandbox config.

    AppContainer network isolation is binary: either all network capabilities
    are granted or none are. Domain-level filtering is not supported natively;
    if specific domains are listed, a warning is logged and full access is
    granted.

    Args:
        config: Sandbox configuration containing ``network_allow`` list.

    Returns:
        A list of capability name strings to pass to
        ``SECURITY_CAPABILITIES``. Empty list means all network blocked.
    """
    if not config.network_allow:
        return []  # Block all network (AppContainer default: no network)

    if "*" not in config.network_allow:
        logger.warning(
            "WindowsSandbox: domain-level network filtering not supported "
            "by AppContainer. Allowing all network access.",
        )

    return [
        _CAP_INTERNET_CLIENT,
        _CAP_INTERNET_CLIENT_SERVER,
        _CAP_PRIVATE_NETWORK,
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Pipe output decoding (handles OEM/ANSI/UTF-16LE code pages)
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
    """Attempts to decode raw bytes as UTF-16LE.

    Uses BOM detection first, then a heuristic (>25% null bytes at odd
    positions in the first 64 bytes).

    Args:
        raw: Raw byte data from pipe output.

    Returns:
        Decoded string if UTF-16LE was detected, None otherwise.
    """
    if len(raw) < 2:
        return None

    # Check for UTF-16LE BOM
    if raw[:2] == b"\xff\xfe":
        try:
            return raw.decode("utf-16-le")
        except (UnicodeDecodeError, ValueError):
            return None

    # Heuristic: if >25% of bytes at odd positions are \x00, it's UTF-16LE
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

    ``cmd.exe`` outputs in the OEM code page (e.g. ``cp936``/GBK on Chinese
    Windows), not UTF-8. This function tries codecs in priority order:

    1. UTF-16LE (BOM detection and null-byte heuristic).
    2. System OEM code page (``GetOEMCP``).
    3. System ANSI code page (``GetACP``).
    4. UTF-8 with replacement characters (final fallback).

    Args:
        raw: Raw bytes read from a pipe handle.

    Returns:
        Decoded string. Never raises on encoding errors.
    """
    if not raw:
        return ""

    # Try UTF-16LE detection (BOM and heuristic)
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
# Process launch with AppContainer token
# ═══════════════════════════════════════════════════════════════════════════


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Sid", ctypes.c_void_p),
        ("Attributes", ctypes.wintypes.DWORD),
    ]


class _SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.POINTER(_SID_AND_ATTRIBUTES)),
        ("CapabilityCount", ctypes.wintypes.DWORD),
        ("Reserved", ctypes.wintypes.DWORD),
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


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", _STARTUPINFOW),
        ("lpAttributeList", ctypes.c_void_p),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", ctypes.wintypes.HANDLE),
        ("hThread", ctypes.wintypes.HANDLE),
        ("dwProcessId", ctypes.wintypes.DWORD),
        ("dwThreadId", ctypes.wintypes.DWORD),
    ]


def _create_stdio_pipes(
    kernel32: Any,
) -> Tuple[
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
]:
    """Creates inheritable stdout/stderr pipes for child process I/O.

    Returns:
        A 4-tuple of (stdout_read, stdout_write,
        stderr_read, stderr_write) handles.

    Raises:
        OSError: If CreatePipe fails.
    """

    class _SA(ctypes.Structure):
        _fields_ = [
            ("nLength", ctypes.wintypes.DWORD),
            ("lpSecurityDescriptor", ctypes.c_void_p),
            ("bInheritHandle", ctypes.wintypes.BOOL),
        ]

    sa = _SA()
    sa.nLength = ctypes.sizeof(sa)
    sa.lpSecurityDescriptor = None
    sa.bInheritHandle = True

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


def _setup_security_capabilities(
    kernel32: Any,
    container_sid: str,
    capabilities: List[str],
) -> Tuple[ctypes.c_void_p, List[ctypes.c_void_p], Any, Any]:
    """Builds SECURITY_CAPABILITIES and proc thread attribute list.

    Args:
        kernel32: Pre-loaded kernel32 DLL handle.
        container_sid: AppContainer SID string.
        capabilities: List of capability name strings.

    Returns:
        A 4-tuple of (app_container_psid, cap_psids,
        sec_cap, attr_list). Caller must free psids and
        delete the attribute list after use.

    Raises:
        OSError: If attribute list initialization fails.
    """
    app_container_psid = _string_to_sid(container_sid)

    # Build capability SID array
    cap_sids = []
    cap_psids: List[ctypes.c_void_p] = []
    for cap_name in capabilities:
        cap_sid_str = _CAPABILITY_SIDS.get(cap_name)
        if cap_sid_str:
            cap_psid = _string_to_sid(cap_sid_str)
            cap_psids.append(cap_psid)
            cap_sids.append(
                _SID_AND_ATTRIBUTES(Sid=cap_psid, Attributes=0x00000004),
            )  # SE_GROUP_ENABLED

    # Build SECURITY_CAPABILITIES
    sec_cap = _SECURITY_CAPABILITIES()
    sec_cap.AppContainerSid = app_container_psid
    sec_cap.CapabilityCount = len(cap_sids)
    sec_cap.Reserved = 0
    if cap_sids:
        cap_array = (_SID_AND_ATTRIBUTES * len(cap_sids))(*cap_sids)
        sec_cap.Capabilities = ctypes.cast(
            cap_array,
            ctypes.POINTER(_SID_AND_ATTRIBUTES),
        )
    else:
        sec_cap.Capabilities = None

    # Initialize proc thread attribute list
    size = ctypes.c_size_t(0)
    kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    attr_list_buf = (ctypes.c_byte * size.value)()
    attr_list = ctypes.cast(attr_list_buf, ctypes.c_void_p)

    if not kernel32.InitializeProcThreadAttributeList(
        attr_list,
        1,
        0,
        ctypes.byref(size),
    ):
        raise OSError(
            f"InitializeProcThreadAttributeList failed: "
            f"error={ctypes.get_last_error()}",
        )

    # Attach security capabilities to attribute list
    if not kernel32.UpdateProcThreadAttribute(
        attr_list,
        0,
        _PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
        ctypes.byref(sec_cap),
        ctypes.sizeof(sec_cap),
        None,
        None,
    ):
        kernel32.DeleteProcThreadAttributeList(attr_list)
        raise OSError(
            f"UpdateProcThreadAttribute failed: "
            f"error={ctypes.get_last_error()}",
        )

    return app_container_psid, cap_psids, sec_cap, attr_list


def _is_powershell_exe(executable: Optional[str]) -> bool:
    """Check if the given executable path is a PowerShell variant."""
    if not executable:
        return False
    name = os.path.basename(executable).lower()
    return name in ("powershell", "powershell.exe", "pwsh", "pwsh.exe")


def _is_cmd_exe(executable: Optional[str]) -> bool:
    """Check if the given executable path is cmd.exe."""
    if not executable:
        return False
    name = os.path.basename(executable).lower()
    return name in ("cmd", "cmd.exe")


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
    if shell_executable and _is_powershell_exe(shell_executable):
        ps_cmd = cmd.replace('"', '\\"')
        return (
            f"{shell_executable} -NoProfile -NonInteractive "
            f'-ExecutionPolicy Bypass -Command "{ps_cmd}"'
        )
    elif not shell_executable or _is_cmd_exe(shell_executable):
        shell = shell_executable or "cmd.exe"
        return f'{shell} /c "{cmd}"'
    else:
        # POSIX-like shell on Windows (e.g. Git Bash, MSYS2)
        escaped = cmd.replace('"', '\\"')
        return f'{shell_executable} -c "{escaped}"'


def _create_process_in_appcontainer(
    cmd: str,
    container_sid: str,
    capabilities: List[str],
    cwd: str,
    env: Optional[Dict[str, str]] = None,
    shell_executable: Optional[str] = None,
) -> Tuple[
    int,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
]:
    """Launches a process inside the AppContainer via ``CreateProcessW``.

    Creates stdout/stderr pipes, builds a ``SECURITY_CAPABILITIES`` struct
    with the container SID and requested capabilities, then launches the
    command via the specified shell (or ``cmd.exe`` by default) with
    ``PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES``.

    Args:
        cmd: Shell command string to execute.
        container_sid: AppContainer SID string (``S-1-15-2-...``).
        capabilities: List of capability names (e.g. ``"internetClient"``).
        cwd: Working directory for the child process.
        env: Full environment dict to pass. If None, no environment block
            is passed (child inherits nothing).

    Returns:
        A 4-tuple of ``(process_id, process_handle, stdout_read_handle,
        stderr_read_handle)``. Caller owns all handles and must close them.

    Raises:
        OSError: If ``CreatePipe``, attribute list setup, or
            ``CreateProcessW`` fails.
    """
    kernel32 = _get_kernel32()

    # Create pipes and set up security capabilities
    stdout_read, stdout_write, stderr_read, stderr_write = _create_stdio_pipes(
        kernel32,
    )
    (
        app_container_psid,
        cap_psids,
        _sec_cap,
        attr_list,
    ) = _setup_security_capabilities(kernel32, container_sid, capabilities)

    # Build STARTUPINFOEXW
    si_ex = _STARTUPINFOEXW()
    si_ex.StartupInfo.cb = ctypes.sizeof(si_ex)
    si_ex.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
    si_ex.StartupInfo.hStdInput = None
    si_ex.StartupInfo.hStdOutput = stdout_write
    si_ex.StartupInfo.hStdError = stderr_write
    si_ex.lpAttributeList = attr_list

    # Build environment block
    env_block = None
    if env:
        env_str = "\x00".join(f"{k}={v}" for k, v in env.items()) + "\x00\x00"
        env_block = ctypes.create_unicode_buffer(env_str)

    # CreateProcessW
    pi = _PROCESS_INFORMATION()
    creation_flags = (
        _EXTENDED_STARTUPINFO_PRESENT
        | _CREATE_UNICODE_ENVIRONMENT
        | _CREATE_NO_WINDOW
    )

    cmd_line = _build_shell_command_line(cmd, shell_executable)

    success = kernel32.CreateProcessW(
        None,  # lpApplicationName
        ctypes.c_wchar_p(cmd_line),  # lpCommandLine
        None,  # lpProcessAttributes
        None,  # lpThreadAttributes
        True,  # bInheritHandles
        creation_flags,
        ctypes.cast(env_block, ctypes.c_void_p) if env_block else None,
        ctypes.c_wchar_p(cwd),
        ctypes.byref(si_ex),
        ctypes.byref(pi),
    )

    # Clean up attribute list
    kernel32.DeleteProcThreadAttributeList(attr_list)

    # Close write ends of pipes (parent doesn't need them)
    kernel32.CloseHandle(stdout_write)
    kernel32.CloseHandle(stderr_write)

    if not success:
        kernel32.CloseHandle(stdout_read)
        kernel32.CloseHandle(stderr_read)
        # Free SIDs
        kernel32.LocalFree(app_container_psid)
        for psid in cap_psids:
            kernel32.LocalFree(psid)
        raise OSError(
            f"CreateProcessW failed: error={ctypes.get_last_error()}",
        )

    # Close thread handle (not needed)
    kernel32.CloseHandle(pi.hThread)

    # Free SIDs (they were copied into the token)
    kernel32.LocalFree(app_container_psid)
    for psid in cap_psids:
        kernel32.LocalFree(psid)

    return (pi.dwProcessId, pi.hProcess, stdout_read, stderr_read)


async def _wait_and_read_process(
    process_handle: ctypes.wintypes.HANDLE,
    stdout_handle: ctypes.wintypes.HANDLE,
    stderr_handle: ctypes.wintypes.HANDLE,
    timeout_seconds: int,
) -> Tuple[int, str, str, bool]:
    """Waits for process completion, reads pipe output, and closes handles.

    Reads stdout/stderr in dedicated threads concurrently with the process
    wait to avoid pipe-buffer deadlock — a child producing more than ~64 KB
    would block the pipe write, and WaitForSingleObject would never return.

    Args:
        process_handle: Handle to the child process.
        stdout_handle: Read end of the stdout pipe.
        stderr_handle: Read end of the stderr pipe.
        timeout_seconds: Maximum wait time before termination.

    Returns:
        A 4-tuple of ``(exit_code, stdout_str, stderr_str, timed_out)``.
        All handles are closed before returning.
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
            kernel32.TerminateProcess(process_handle, 1)
            kernel32.WaitForSingleObject(process_handle, 5000)
        return timed_out

    timed_out, stdout_data, stderr_data = await asyncio.gather(
        loop.run_in_executor(None, _wait_process),
        loop.run_in_executor(None, _drain_stdout),
        loop.run_in_executor(None, _drain_stderr),
    )

    exit_code = ctypes.wintypes.DWORD(0)
    kernel32.GetExitCodeProcess(process_handle, ctypes.byref(exit_code))

    kernel32.CloseHandle(stdout_handle)
    kernel32.CloseHandle(stderr_handle)
    kernel32.CloseHandle(process_handle)

    return (
        exit_code.value,
        _decode_pipe_output(stdout_data),
        _decode_pipe_output(stderr_data),
        timed_out,
    )


def _read_pipe(handle: ctypes.wintypes.HANDLE, kernel32: Any) -> bytes:
    """Reads all data from a pipe handle until EOF.

    Args:
        handle: Read end of a pipe handle.
        kernel32: Pre-loaded kernel32 DLL handle.

    Returns:
        Concatenated bytes read from the pipe. Returns empty bytes if
        the pipe was already closed (``ERROR_BROKEN_PIPE = 109``).
    """
    _ERROR_BROKEN_PIPE = 109
    chunks: List[bytes] = []
    buf_size = 8192
    buf = (ctypes.c_ubyte * buf_size)()
    bytes_read = ctypes.c_uint32(0)

    while True:
        ok = kernel32.ReadFile(
            handle,
            buf,
            buf_size,
            ctypes.byref(bytes_read),
            None,
        )
        if not ok:
            # Capture any partial data before the failure
            if bytes_read.value > 0:
                chunks.append(bytes(buf[: bytes_read.value]))
            err = ctypes.get_last_error()
            if err == _ERROR_BROKEN_PIPE:
                break  # Normal EOF — writer closed the pipe
            break
        if bytes_read.value == 0:
            break
        chunks.append(bytes(buf[: bytes_read.value]))

    return b"".join(chunks)


# ═══════════════════════════════════════════════════════════════════════════
# Sandbox reuse (fingerprint + metadata)
# ═══════════════════════════════════════════════════════════════════════════


def _compute_acl_fingerprint(config: SandboxConfig) -> str:
    """Computes a deterministic hash of the ACL-relevant configuration.

    Used to determine whether an existing AppContainer profile with
    matching ACLs can be reused, avoiding redundant ``icacls`` calls.

    Args:
        config: Sandbox configuration to fingerprint.

    Returns:
        A 16-character hex digest string.
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


def _find_reusable_container(
    container_name: str,
) -> Optional[str]:
    """Checks if an AppContainer profile already exists by name.

    ``DeriveAppContainerSidFromAppContainerName`` always returns a SID
    regardless of whether the profile was ever created, so we verify
    existence with ``GetAppContainerFolderPath`` which fails for
    non-existent profiles.

    Args:
        container_name: Deterministic container name
            (qwenpaw_<fingerprint>).

    Returns:
        The container SID string if the profile exists, None otherwise.
    """
    try:
        userenv = _get_userenv()
        path_ptr = ctypes.c_wchar_p()
        hr = userenv.GetAppContainerFolderPath(
            ctypes.c_wchar_p(container_name),
            ctypes.byref(path_ptr),
        )
        if hr != 0:
            return None
        ctypes.windll.ole32.CoTaskMemFree(path_ptr)
    except OSError:
        return None
    return _get_appcontainer_sid(container_name)


def _save_container_metadata(
    state_dir: Path,
    container_name: str,
    sid: str,
    workspace_dir: str,
    acl_manifest: Optional[Dict[str, Any]] = None,
) -> None:
    """Persists container metadata for the cleanup script.

    Args:
        state_dir: QwenPaw state directory (``~/.qwenpaw``).
        container_name: AppContainer profile name.
        sid: AppContainer SID string.
        workspace_dir: Workspace directory path.
        acl_manifest: Optional dict recording ACL-modified paths.
    """
    containers_dir = state_dir / "containers"
    containers_dir.mkdir(parents=True, exist_ok=True)

    meta: Dict[str, Any] = {
        "container_name": container_name,
        "sid": sid,
        "workspace_dir": workspace_dir,
        "owner_pid": os.getpid(),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if acl_manifest is not None:
        meta["acl_manifest"] = acl_manifest

    meta_file = containers_dir / f"{container_name}.json"
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Admin privilege check
# ═══════════════════════════════════════════════════════════════════════════


def _is_admin() -> bool:
    """Returns True if the current process has administrator privileges."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


# ═══════════════════════════════════════════════════════════════════════════
# WindowsSandbox class
# ═══════════════════════════════════════════════════════════════════════════


class WindowsSandbox:
    """Windows AppContainer sandbox providing native process isolation.

    Filesystem access is controlled via ``icacls`` ACLs on the AppContainer
    SID. Network access is controlled via AppContainer capabilities
    (``internetClient``, ``internetClientServer``,
    ``privateNetworkClientServer``).

    Intended usage as an async context manager::

        async with WindowsSandbox(config) as sandbox:
            result = await sandbox.execute("python script.py")

    Lifecycle:
        ``__aenter__``: Creates or reuses an AppContainer profile and sets
            filesystem ACLs (only on first creation).
        ``execute``: Launches a command with the AppContainer security token.
        ``__aexit__`` / ``stop``: Terminates any running child process.
            The AppContainer profile is preserved for reuse.

    Attributes:
        config: The ``SandboxConfig`` this sandbox was created with.
    """

    def __init__(self, config: SandboxConfig):
        if config.allow_read_all:
            raise ValueError(
                "WindowsSandbox (AppContainer backend) does not support "
                "allow_read_all=True — it would require granting read access "
                "on a large set of system directories. Use "
                "WindowsRestrictedSandbox (the allow_read_all=True backend) "
                "instead, or let create_sandbox() pick the right backend.",
            )
        self._config = config
        self._process_handle: Optional[ctypes.wintypes.HANDLE] = None
        self._process_id: Optional[int] = None
        self._container_name: Optional[str] = None
        self._container_sid: Optional[str] = None
        self._state_dir = (
            Path(os.environ.get("USERPROFILE", os.path.expanduser("~")))
            / ".qwenpaw"
        )

    @property
    def config(self) -> SandboxConfig:
        return self._config

    async def __aenter__(self):
        """Sets up the AppContainer sandbox (creates or reuses a profile)."""
        if not _is_admin():
            print(
                "[QwenPaw Sandbox] WARNING: Not running as administrator. "
                "Sandbox ACL setup may fail.",
            )

        fingerprint = _compute_acl_fingerprint(self._config)
        self._container_name = f"qwenpaw_{fingerprint[:12]}"

        # Try to reuse an existing container (name encodes fingerprint)
        existing_sid = _find_reusable_container(self._container_name)
        if existing_sid:
            self._container_sid = existing_sid
            print(
                f"[QwenPaw Sandbox] Reusing existing sandbox "
                f"'{self._container_name}'.",
            )
            logger.debug(
                "Reusing AppContainer '%s' (fingerprint=%s)",
                self._container_name,
                fingerprint,
            )
        else:
            print(
                "[QwenPaw Sandbox] Initializing new sandbox "
                "(first run may take longer due to ACL setup)...",
            )
            self._container_sid = _create_appcontainer_profile(
                self._container_name,
                "QwenPaw Sandbox",
                "Sandboxed execution environment for QwenPaw",
            )

            acl_manifest = await _apply_all_acls(
                self._config,
                self._container_sid,
            )

            _save_container_metadata(
                self._state_dir,
                self._container_name,
                self._container_sid,
                self._config.workspace_dir,
                acl_manifest,
            )

            print(
                f"[QwenPaw Sandbox] Sandbox '{self._container_name}' "
                f"initialized successfully.",
            )
            logger.debug(
                "Created AppContainer '%s' (sid=%s, fingerprint=%s)",
                self._container_name,
                self._container_sid,
                fingerprint,
            )

        return self

    async def execute(
        self,
        cmd: str,
        cwd: Optional[str] = None,
    ) -> ExecutionResult:
        """Executes a command inside the AppContainer.

        Launches the process with the AppContainer token, waits for
        completion (with timeout), and checks for access-denied violations
        in the output.

        Args:
            cmd: Shell command string to execute via the configured shell.
            cwd: Working directory override. Defaults to
                ``config.workspace_dir``.

        Returns:
            An ``ExecutionResult`` with exit code, stdout, stderr,
            timeout status, and any detected sandbox violation.
        """
        if not self._container_sid:
            # Lazy init if not entered via context manager
            await self.__aenter__()

        assert self._container_sid is not None
        start = time.monotonic()

        # Resolve CWD
        effective_cwd = cwd or self._config.workspace_dir

        # Compute network capabilities
        capabilities = _compute_network_capabilities(self._config)

        # Build environment
        env = dict(os.environ)
        if self._config.env_vars:
            for k, v in self._config.env_vars.items():
                env[k] = v

        try:
            # Launch process
            (
                pid,
                proc_handle,
                stdout_handle,
                stderr_handle,
            ) = await asyncio.to_thread(
                _create_process_in_appcontainer,
                cmd,
                self._container_sid,
                capabilities,
                effective_cwd,
                env,
                shell_executable=self._config.shell_executable,
            )
            self._process_handle = proc_handle
            self._process_id = pid

            # Wait and read output
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
            )
            self._process_handle = None  # Handle closed by _wait_and_read

            duration_ms = int((time.monotonic() - start) * 1000)

            # Detect sandbox violation
            # Check stderr for access-denied patterns regardless of exit code,
            # because some Windows commands (e.g., del) return exit_code=0
            # even when the operation fails due to ACL denial.
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
        """Terminates any running child process.

        Does NOT delete the AppContainer profile (it is preserved for
        reuse by future invocations with the same ACL fingerprint).
        """
        if self._process_handle is not None:
            try:
                kernel32 = _get_kernel32()
                kernel32.TerminateProcess(self._process_handle, 1)
                kernel32.CloseHandle(self._process_handle)
            except OSError:
                pass
            self._process_handle = None

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()


# ═══════════════════════════════════════════════════════════════════════════
# Shutdown cleanup (mirrors restricted sandbox's atexit approach)
# ═══════════════════════════════════════════════════════════════════════════

_state_dir = (
    Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / ".qwenpaw"
)


def _is_pid_alive(pid: int) -> bool:
    """Checks whether a process with the given PID is still running."""
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
        exit_code = ctypes.wintypes.DWORD(0)
        kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        kernel32.CloseHandle(handle)
        return exit_code.value == 259  # STILL_ACTIVE
    except OSError:
        return False


def _run_icacls_sync(args: List[str]) -> bool:
    """Runs icacls synchronously (for use in shutdown cleanup)."""
    try:
        result = subprocess.run(
            ["icacls"] + args,
            capture_output=True,
            timeout=30,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _verify_acl_removed_sync(path: str, sid: str) -> bool:
    """Verifies that a SID no longer appears in the DACL of a path."""
    if not os.path.exists(path):
        return True
    try:
        result = subprocess.run(
            ["icacls", path],
            capture_output=True,
            timeout=180,
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


def _remove_acl_with_verify_sync(path: str, sid: str) -> bool:
    """Removes ACEs for a SID using multi-strategy retry with verification.

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


def _cleanup_single_container(meta: dict, meta_file: Path) -> None:
    """Cleans up a single AppContainer sandbox from its metadata.

    Steps (mirroring scripts/cleanup_windows_sandbox.py):
      1. Remove ACL entries (grants and denies) from recorded paths
      2. Delete the AppContainer profile
      3. Delete the metadata JSON file
    """
    container_name = meta.get("container_name", "")
    sid = meta.get("sid", "")
    workspace_dir = meta.get("workspace_dir", "")
    acl_manifest = meta.get("acl_manifest")

    # Step 1: Remove ACL entries
    if sid:
        if acl_manifest:
            # Collect all recorded paths (grants, denies, legacy keys)
            all_paths = (
                acl_manifest.get("grant_paths", [])
                + acl_manifest.get("deny_paths", [])
                + acl_manifest.get("inheritance_broken_paths", [])
            )
            for path in all_paths:
                if path:
                    _remove_acl_with_verify_sync(path, sid)
            if workspace_dir:
                _remove_acl_with_verify_sync(workspace_dir, sid)
        elif workspace_dir:
            _remove_acl_with_verify_sync(workspace_dir, sid)

    # Step 2: Delete the AppContainer profile
    if container_name:
        try:
            userenv = _get_userenv()
            userenv.DeleteAppContainerProfile(
                ctypes.c_wchar_p(container_name),
            )
        except OSError:
            pass

    # Step 3: Delete the metadata JSON file
    try:
        meta_file.unlink()
    except OSError:
        pass


def shutdown_cleanup() -> None:
    """Destroys AppContainer sandboxes owned by this process or orphaned.

    For each container metadata file in ~/.qwenpaw/containers/:
      - Skips containers owned by other still-running processes
      - Removes filesystem ACL entries
      - Deletes the AppContainer profile
      - Deletes the metadata JSON file

    Safe to call multiple times (idempotent).
    """
    containers_dir = _state_dir / "containers"
    if not containers_dir.exists() or not list(containers_dir.glob("*.json")):
        return

    my_pid = os.getpid()

    for meta_file in containers_dir.glob("*.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        owner_pid = meta.get("owner_pid")

        # Skip containers owned by other still-running processes
        if owner_pid is not None and owner_pid != my_pid:
            if _is_pid_alive(owner_pid):
                logger.debug(
                    "Skipping container %s — owner pid %d still alive",
                    meta.get("container_name", "?"),
                    owner_pid,
                )
                continue

        container_name = meta.get("container_name", "")
        if container_name:
            logger.info("Cleaning AppContainer: %s", container_name)
            _cleanup_single_container(meta, meta_file)

    # Clean up the containers directory if now empty
    if containers_dir.exists() and not list(containers_dir.glob("*.json")):
        try:
            containers_dir.rmdir()
        except OSError:
            pass


# ── atexit safety net ──
# Register shutdown_cleanup as an atexit handler so that AppContainer
# profiles and ACLs are cleaned up on exit. The handler is best-effort
# and will NOT run on SIGKILL, power loss, or os._exit().
atexit.register(shutdown_cleanup)
