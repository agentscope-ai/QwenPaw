# -*- coding: utf-8 -*-
"""Windows AppContainer sandbox implementation.

Uses Windows AppContainer for native process isolation:
  - Filesystem access controlled via icacls ACLs on the AppContainer SID
  - Network controlled via AppContainer capabilities
  - Process launched with PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES

Architecture:
    1. Create (or reuse) an AppContainer profile → obtain SID
    2. Set filesystem ACLs via icacls.exe (one command per directory, parallel)
    3. Create NTFS junction for CWD traversal
    4. Launch cmd.exe /c <command> with AppContainer security token
    5. Capture stdout/stderr and detect violations

Requirements:
    - Windows 10 1507+ (build 10240)
    - icacls.exe (ships with Windows)
    - Python ctypes (for Win32 API calls)
"""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import ExecutionResult, SandboxConfig

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════

# Critical system directories that always get read+execute
CRITICAL_SYSTEM_DIRS: List[str] = [
    r"C:\Windows",
    r"C:\Windows\System32",
    r"C:\Windows\SysWOW64",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
]

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
    r"|\u6743\u9650\u4e0d\u8db3"  # 权限不足 (Chinese: Insufficient permissions)
    r"|\u7cfb\u7edf\u65e0\u6cd5\u6267\u884c\u6307\u5b9a\u7684\u7a0b\u5e8f",  # 系统无法执行指定的程序
    re.IGNORECASE | re.MULTILINE,
)

# Win32 constants
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_CREATE_NO_WINDOW = 0x08000000
_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
_STARTF_USESTDHANDLES = 0x00000100
_HANDLE_FLAG_INHERIT = 0x00000001
_INFINITE = 0xFFFFFFFF
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_STILL_ACTIVE = 259
_HRESULT_ERROR_ALREADY_EXISTS = -2147023649  # 0x800700B7


# ═══════════════════════════════════════════════════════════════════════════════
# Win32 API wrappers (ctypes)
# ═══════════════════════════════════════════════════════════════════════════════


def _create_appcontainer_profile(
    container_name: str,
    display_name: str,
    description: str,
) -> str:
    """Create an AppContainer profile and return its SID string.

    Uses userenv.dll:CreateAppContainerProfile.
    Returns the SID as a string like 'S-1-15-2-...'.

    Raises:
        OSError: If profile creation fails (and it doesn't already exist).
    """
    userenv = ctypes.WinDLL("userenv.dll", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32.dll", use_last_error=True)

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

    if hr != 0 and hr != _HRESULT_ERROR_ALREADY_EXISTS:
        raise OSError(
            f"CreateAppContainerProfile failed: HRESULT=0x{hr & 0xFFFFFFFF:08x}"
        )

    # If already exists, get the SID via DeriveAppContainerSidFromAppContainerName
    if hr == _HRESULT_ERROR_ALREADY_EXISTS:
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
    """Delete an AppContainer profile.

    Returns True if deleted successfully, False otherwise.
    """
    try:
        userenv = ctypes.WinDLL("userenv.dll", use_last_error=True)
        hr = userenv.DeleteAppContainerProfile(
            ctypes.c_wchar_p(container_name),
        )
        return hr == 0
    except OSError:
        return False


def _get_appcontainer_sid(container_name: str) -> Optional[str]:
    """Get SID string for an existing AppContainer profile.

    Uses userenv.dll:DeriveAppContainerSidFromAppContainerName.
    Returns None if the profile does not exist or the call fails.
    """
    try:
        userenv = ctypes.WinDLL("userenv.dll", use_last_error=True)
        advapi32 = ctypes.WinDLL("advapi32.dll", use_last_error=True)

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
    """Convert a PSID to a string representation (S-1-15-2-...)."""
    if advapi32 is None:
        advapi32 = ctypes.WinDLL("advapi32.dll", use_last_error=True)

    string_sid = ctypes.c_wchar_p()
    ret = advapi32.ConvertSidToStringSidW(
        psid,
        ctypes.byref(string_sid),
    )
    if not ret:
        raise OSError(
            f"ConvertSidToStringSidW failed: error={ctypes.get_last_error()}"
        )
    try:
        return string_sid.value
    finally:
        ctypes.windll.kernel32.LocalFree(string_sid)


def _string_to_sid(sid_string: str) -> ctypes.c_void_p:
    """Convert a SID string (S-1-15-2-...) to a PSID."""
    advapi32 = ctypes.WinDLL("advapi32.dll", use_last_error=True)
    psid = ctypes.c_void_p()
    ret = advapi32.ConvertStringSidToSidW(
        ctypes.c_wchar_p(sid_string),
        ctypes.byref(psid),
    )
    if not ret:
        raise OSError(
            f"ConvertStringSidToSidW failed for '{sid_string}': "
            f"error={ctypes.get_last_error()}"
        )
    return psid


# ═══════════════════════════════════════════════════════════════════════════════
# ACL management (icacls.exe)
# ═══════════════════════════════════════════════════════════════════════════════


async def _run_icacls(args: List[str], timeout: int = 120) -> Tuple[bool, str]:
    """Run icacls.exe with the given arguments.

    Args:
        args: Arguments to pass to icacls.
        timeout: Maximum seconds to wait (default 120 for large dirs).

    Returns (success, output_text).
    Decodes output using _decode_pipe_output to handle OEM code pages.
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


async def _set_acl_deny_mount(path: str, sid: str) -> bool:
    """Completely block access to a path by breaking inheritance and denying.

    AppContainer tokens ignore explicit deny ACEs when an inherited allow
    ACE exists. The only reliable way to block access is to:
      1. Break inheritance (stop inheriting parent's allow ACE)
      2. Remove any existing allow ACE for the SID
      3. Add an explicit deny ACE for defense-in-depth

    After this, the SID has zero access to this path and its children.
    """
    # Step 1: Break inheritance
    ok1, err1 = await _run_icacls([path, "/inheritance:d"])
    if not ok1:
        logger.warning("Failed to disable inheritance on %s: %s", path, err1)

    # Step 2: Remove all ACEs for this SID
    ok2, err2 = await _run_icacls([path, "/remove", f"*{sid}"])
    if not ok2:
        logger.warning("Failed to remove ACL for SID on %s: %s", path, err2)

    # Step 3: Add explicit deny (defense-in-depth, inheritable to children)
    ok3, err3 = await _run_icacls([path, "/deny", f"*{sid}:(OI)(CI)(F)"])
    if not ok3:
        logger.warning("Failed to set deny ACL on %s: %s", path, err3)

    return ok1 and ok2 and ok3


async def _set_acl_grant(path: str, sid: str, permission: str) -> bool:
    """Set grant ACL on path for the AppContainer SID.

    Args:
        permission: One of "F" (full), "RX" (read+execute), "R" (read-only)
    """
    ok, err = await _run_icacls(
        [path, "/grant", f"*{sid}:(OI)(CI)({permission})"]
    )
    if not ok:
        logger.warning("Failed to set %s ACL on %s: %s", permission, path, err)
    return ok


async def _set_acl_mount(path: str, sid: str, permission: str) -> bool:
    """Set exact permissions on a mount path, breaking inheritance first.

    Strategy: break ACL inheritance, remove any existing ACE for the SID,
    then grant the exact permission requested. This ensures the mount's
    effective permission is exactly what is specified, regardless of what
    the parent directory grants via inheritance.

    Args:
        path: Filesystem path to set ACL on.
        sid: AppContainer SID string.
        permission: "F" for full access, "RX" for read+execute.
    """
    # Step 1: Convert inherited ACEs to explicit
    ok1, err1 = await _run_icacls([path, "/inheritance:d"])
    if not ok1:
        logger.warning("Failed to disable inheritance on %s: %s", path, err1)

    # Step 2: Remove existing ACEs for this SID
    ok2, err2 = await _run_icacls([path, "/remove", f"*{sid}"])
    if not ok2:
        logger.warning("Failed to remove ACL for SID on %s: %s", path, err2)

    # Step 3: Grant exact permission (inheritable to children)
    ok3, err3 = await _run_icacls(
        [path, "/grant", f"*{sid}:(OI)(CI)({permission})"]
    )
    if not ok3:
        logger.warning(
            "Failed to grant %s ACL on %s: %s", permission, path, err3
        )
    return ok1 and ok2 and ok3


async def _apply_all_acls(config: SandboxConfig, sid: str) -> None:
    """Apply all ACLs for the AppContainer profile.

    Executes icacls commands in three sequential phases:

    Phase 1 — Global read grants: allow_read_all broad RX, Python dir
              (parallel within phase)
    Phase 2 — Workspace: grant full access on workspace_dir
    Phase 3 — Mounts + Deny paths: all path-level ACL overrides, sorted by
              depth (shallowest first), executed serially. Each entry breaks
              inheritance, removes the SID, then sets the exact permission
              (grant for mounts, deny for deny_paths).

    This ordering guarantees that:
    - Workspace inheritable ACEs are established before overrides break them
    - All overrides use break-inheritance to eliminate inherited allow ACEs
      (required because AppContainer ignores deny ACEs when inherited allow
      ACEs exist)
    - Parent paths are processed before child paths
    """
    # ── Phase 1: Global read grants (parallel) ──────────────────────────────
    grant_tasks: List[asyncio.Task] = []

    # Critical system directories — NOT granted explicitly.
    # On Windows 10+, C:\Windows, C:\Program Files etc. already have an ACE
    # for "ALL APPLICATION PACKAGES" (S-1-15-2-1) granting read+execute.
    logger.debug(
        "Skipping explicit ACL on system dirs (already have "
        "ALL APPLICATION PACKAGES ACE on Win10+)"
    )

    if config.allow_read_all:
        sys_drive = os.environ.get("SystemDrive", "C:")
        grant_tasks.append(
            asyncio.ensure_future(_set_acl_grant(sys_drive + "\\", sid, "RX"))
        )
        users_dir = sys_drive + "\\Users"
        if os.path.isdir(users_dir):
            grant_tasks.append(
                asyncio.ensure_future(_set_acl_grant(users_dir, sid, "RX"))
            )
        user_profile = os.environ.get("USERPROFILE", "")
        if user_profile and os.path.isdir(user_profile):
            grant_tasks.append(
                asyncio.ensure_future(_set_acl_grant(user_profile, sid, "RX"))
            )

    # Python interpreter directory
    python_dir = os.path.dirname(sys.executable)
    if python_dir and os.path.isdir(python_dir):
        grant_tasks.append(
            asyncio.ensure_future(_set_acl_grant(python_dir, sid, "RX"))
        )

    if grant_tasks:
        await asyncio.gather(*grant_tasks, return_exceptions=True)

    # ── Phase 2: Workspace full access ──────────────────────────────────────
    await _set_acl_grant(config.workspace_dir, sid, "F")

    # ── Phase 3: Mounts + Deny paths (serial, depth-sorted) ────────────────
    # Merge mounts and deny_paths into a single list of (path, action) entries.
    # action is either a permission string ("F", "RX") for mounts, or "DENY"
    # for deny_paths. All entries break inheritance before applying their ACL
    # to eliminate inherited allow ACEs from parent directories.
    from pathlib import PureWindowsPath as _WP

    path_entries: List[tuple] = []

    # Add mounts
    for mount in config.mounts:
        perm = "F" if mount.writable else "RX"
        path_entries.append((mount.path, perm))

    # Add deny_paths
    for deny_path in config.deny_paths:
        expanded = os.path.expanduser(deny_path)
        if os.path.exists(expanded):
            path_entries.append((expanded, "DENY"))

    # Sort by path depth (shallowest first) to ensure parent before child.
    path_entries.sort(key=lambda e: len(_WP(e[0]).parts))

    for path, action in path_entries:
        if action == "DENY":
            await _set_acl_deny_mount(path, sid)
        else:
            await _set_acl_mount(path, sid, action)


# ═══════════════════════════════════════════════════════════════════════════════
# NTFS Junction management
# ═══════════════════════════════════════════════════════════════════════════════


def _create_workspace_junction(workspace_dir: str, state_dir: Path) -> str:
    """Create an NTFS junction for CWD traversal.

    Creates: <state_dir>\\junctions\\<hash> → workspace_dir

    Returns the junction path. If the junction already exists and points
    to the correct target, returns it as-is.
    """
    ws_hash = hashlib.sha256(workspace_dir.encode()).hexdigest()[:12]
    junction_dir = state_dir / "junctions"
    junction_dir.mkdir(parents=True, exist_ok=True)
    junction_path = junction_dir / ws_hash

    if junction_path.exists():
        # Verify it points to the right place
        try:
            target = os.readlink(str(junction_path))
            if os.path.normpath(target) == os.path.normpath(workspace_dir):
                return str(junction_path)
            # Wrong target, remove and recreate
            os.rmdir(str(junction_path))
        except (OSError, ValueError):
            pass

    if not junction_path.exists():
        # Create junction: mklink /J <junction_path> <workspace_dir>
        try:
            subprocess.run(
                [
                    "cmd",
                    "/c",
                    "mklink",
                    "/J",
                    str(junction_path),
                    workspace_dir,
                ],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            logger.warning(
                "Failed to create junction %s -> %s: %s",
                junction_path,
                workspace_dir,
                e.stderr.decode("utf-8", errors="replace"),
            )
            # Fall back to using the workspace path directly
            return workspace_dir

    return str(junction_path)


# ═══════════════════════════════════════════════════════════════════════════════
# Network capability computation
# ═══════════════════════════════════════════════════════════════════════════════


def _compute_network_capabilities(
    config: SandboxConfig,
) -> List[str]:
    """Determine AppContainer network capabilities from config.

    Rules (matching linux_sandbox approach):
        - network_allow == [] or None: NO capabilities (all network blocked)
        - network_allow == ["*"]: all capabilities (full network)
        - network_allow has specific domains: all capabilities + warning
    """
    if not config.network_allow:
        return []  # Block all network (AppContainer default: no network)

    if "*" in config.network_allow:
        return [
            _CAP_INTERNET_CLIENT,
            _CAP_INTERNET_CLIENT_SERVER,
            _CAP_PRIVATE_NETWORK,
        ]

    # Partial domain list — domain-level filtering not possible
    logger.warning(
        "WindowsSandbox: domain-level network filtering not supported "
        "by AppContainer. Allowing all network access."
    )
    return [
        _CAP_INTERNET_CLIENT,
        _CAP_INTERNET_CLIENT_SERVER,
        _CAP_PRIVATE_NETWORK,
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# Pipe output decoding (handles OEM/ANSI/UTF-16LE code pages)
# ═══════════════════════════════════════════════════════════════════════════════

_cached_oem_encoding: Optional[str] = None
_cached_ansi_encoding: Optional[str] = None


def _get_system_ansi_encoding() -> str:
    """Return the codec name for the system ANSI code page."""
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
    """Return the codec name for the system OEM code page."""
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
    """Try to decode raw bytes as UTF-16LE using BOM and heuristic detection."""
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
    """Decode raw pipe output using multi-codec strategy.

    Handles the encoding complexity of Windows console output:
        1. UTF-16LE with BOM detection.
        2. UTF-16LE heuristic (>25% null bytes at odd positions).
        3. System OEM code page (GetOEMCP) — used by cmd.exe.
        4. System ANSI code page (GetACP).
        5. UTF-8 with replacement (final fallback).

    This is necessary because cmd.exe outputs in the OEM code page
    (e.g., cp936/GBK on Chinese Windows), not UTF-8.
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


# ═══════════════════════════════════════════════════════════════════════════════
# Process launch with AppContainer token
# ═══════════════════════════════════════════════════════════════════════════════


# ctypes structure definitions for CreateProcess with AppContainer


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


def _create_process_in_appcontainer(
    cmd: str,
    container_sid: str,
    capabilities: List[str],
    cwd: str,
    env: Optional[Dict[str, str]] = None,
) -> Tuple[
    int, ctypes.wintypes.HANDLE, ctypes.wintypes.HANDLE, ctypes.wintypes.HANDLE
]:
    """Launch a process inside the AppContainer.

    Uses CreateProcessW with PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES.

    Args:
        cmd: Command line to execute.
        container_sid: AppContainer SID string.
        capabilities: List of capability names.
        cwd: Working directory.
        env: Environment variables (full environment to pass).

    Returns:
        (process_id, process_handle, stdout_read_handle, stderr_read_handle)
    """
    kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)

    # Create pipes for stdout and stderr
    stdout_read = ctypes.wintypes.HANDLE()
    stdout_write = ctypes.wintypes.HANDLE()
    stderr_read = ctypes.wintypes.HANDLE()
    stderr_write = ctypes.wintypes.HANDLE()

    # Security attributes for inheritable handles
    sa = ctypes.c_byte * 24  # SECURITY_ATTRIBUTES size
    sa_buf = sa()
    ctypes.memmove(
        ctypes.addressof(sa_buf),
        ctypes.c_uint32(24).value.to_bytes(4, "little")
        + b"\x00" * 8  # lpSecurityDescriptor = NULL
        + b"\x01\x00\x00\x00"  # bInheritHandle = TRUE
        + b"\x00" * 8,  # padding
        24,
    )

    # Use a simpler approach: SECURITY_ATTRIBUTES struct
    class _SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("nLength", ctypes.wintypes.DWORD),
            ("lpSecurityDescriptor", ctypes.c_void_p),
            ("bInheritHandle", ctypes.wintypes.BOOL),
        ]

    sa = _SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(sa)
    sa.lpSecurityDescriptor = None
    sa.bInheritHandle = True

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

    # Make read ends non-inheritable
    kernel32.SetHandleInformation(stdout_read, _HANDLE_FLAG_INHERIT, 0)
    kernel32.SetHandleInformation(stderr_read, _HANDLE_FLAG_INHERIT, 0)

    # Convert AppContainer SID string to PSID
    app_container_psid = _string_to_sid(container_sid)

    # Build capability SID array
    cap_sids = []
    cap_psids = []  # Keep references alive
    for cap_name in capabilities:
        cap_sid_str = _CAPABILITY_SIDS.get(cap_name)
        if cap_sid_str:
            cap_psid = _string_to_sid(cap_sid_str)
            cap_psids.append(cap_psid)
            cap_sids.append(
                _SID_AND_ATTRIBUTES(Sid=cap_psid, Attributes=0x00000004)
            )  # SE_GROUP_ENABLED

    # Build SECURITY_CAPABILITIES
    sec_cap = _SECURITY_CAPABILITIES()
    sec_cap.AppContainerSid = app_container_psid
    sec_cap.CapabilityCount = len(cap_sids)
    sec_cap.Reserved = 0
    if cap_sids:
        cap_array = (_SID_AND_ATTRIBUTES * len(cap_sids))(*cap_sids)
        sec_cap.Capabilities = ctypes.cast(
            cap_array, ctypes.POINTER(_SID_AND_ATTRIBUTES)
        )
    else:
        sec_cap.Capabilities = None

    # Initialize proc thread attribute list
    size = ctypes.c_size_t(0)
    kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    attr_list_buf = (ctypes.c_byte * size.value)()
    attr_list = ctypes.cast(attr_list_buf, ctypes.c_void_p)

    if not kernel32.InitializeProcThreadAttributeList(
        attr_list, 1, 0, ctypes.byref(size)
    ):
        raise OSError(
            f"InitializeProcThreadAttributeList failed: "
            f"error={ctypes.get_last_error()}"
        )

    # Update attribute list with security capabilities
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
            f"error={ctypes.get_last_error()}"
        )

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

    cmd_line = f'cmd.exe /c "{cmd}"'

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
            f"CreateProcessW failed: error={ctypes.get_last_error()}"
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
    """Wait for process completion and read output.

    Returns (exit_code, stdout, stderr, timed_out).
    """
    kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)

    loop = asyncio.get_event_loop()

    def _blocking_wait():
        """Blocking wait in a thread."""
        timeout_ms = timeout_seconds * 1000
        result = kernel32.WaitForSingleObject(process_handle, timeout_ms)
        timed_out = result == _WAIT_TIMEOUT

        if timed_out:
            kernel32.TerminateProcess(process_handle, 1)
            kernel32.WaitForSingleObject(process_handle, 5000)

        # Get exit code
        exit_code = ctypes.wintypes.DWORD()
        kernel32.GetExitCodeProcess(process_handle, ctypes.byref(exit_code))

        # Read stdout
        stdout_data = _read_pipe(stdout_handle, kernel32)
        stderr_data = _read_pipe(stderr_handle, kernel32)

        # Close handles
        kernel32.CloseHandle(stdout_handle)
        kernel32.CloseHandle(stderr_handle)
        kernel32.CloseHandle(process_handle)

        return exit_code.value, stdout_data, stderr_data, timed_out

    (
        exit_code,
        stdout_data,
        stderr_data,
        timed_out,
    ) = await loop.run_in_executor(None, _blocking_wait)

    stdout = _decode_pipe_output(stdout_data)
    stderr = _decode_pipe_output(stderr_data)

    return exit_code, stdout, stderr, timed_out


def _read_pipe(handle: ctypes.wintypes.HANDLE, kernel32: Any) -> bytes:
    """Read all data from a pipe handle until EOF.

    Handles ERROR_BROKEN_PIPE (109) which signals the write end was closed.
    """
    _ERROR_BROKEN_PIPE = 109
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


# ═══════════════════════════════════════════════════════════════════════════════
# Sandbox reuse (fingerprint + metadata)
# ═══════════════════════════════════════════════════════════════════════════════


def _compute_acl_fingerprint(config: SandboxConfig) -> str:
    """Compute a deterministic hash of the ACL configuration.

    Used to identify whether an existing container can be reused.
    """
    data = {
        "workspace_dir": os.path.normpath(config.workspace_dir),
        "deny_paths": sorted(
            os.path.normpath(os.path.expanduser(p)) for p in config.deny_paths
        ),
        "mounts": sorted(
            (os.path.normpath(m.path), m.writable, m.executable)
            for m in config.mounts
        ),
        "allow_read_all": config.allow_read_all,
        "network_allow": sorted(config.network_allow),
        "python_dir": os.path.normpath(os.path.dirname(sys.executable)),
    }
    return hashlib.sha256(
        json.dumps(data, sort_keys=True).encode()
    ).hexdigest()[:16]


def _load_container_metadata(state_dir: Path) -> List[Dict[str, Any]]:
    """Load all container metadata files from state directory."""
    containers_dir = state_dir / "containers"
    if not containers_dir.is_dir():
        return []

    results = []
    for meta_file in containers_dir.glob("*.json"):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                results.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue
    return results


def _save_container_metadata(
    state_dir: Path,
    container_name: str,
    sid: str,
    fingerprint: str,
    workspace_dir: str,
    junction_path: str,
) -> None:
    """Save container metadata to state directory."""
    containers_dir = state_dir / "containers"
    containers_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "container_name": container_name,
        "sid": sid,
        "acl_fingerprint": fingerprint,
        "workspace_dir": workspace_dir,
        "junction_path": junction_path,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    meta_file = containers_dir / f"{container_name}.json"
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def _find_reusable_container(
    state_dir: Path, fingerprint: str
) -> Optional[Dict[str, Any]]:
    """Find an existing container with matching ACL fingerprint.

    Returns metadata dict if found and valid, None otherwise.
    """
    for meta in _load_container_metadata(state_dir):
        if meta.get("acl_fingerprint") == fingerprint:
            # Verify the container still exists
            container_name = meta.get("container_name", "")
            sid = _get_appcontainer_sid(container_name)
            if sid and sid == meta.get("sid"):
                return meta
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# WindowsSandbox class
# ═══════════════════════════════════════════════════════════════════════════════


class WindowsSandbox:
    """Windows AppContainer sandbox.

    Uses Windows AppContainer (SID S-1-15-2-*) for native process isolation.
    Filesystem access is controlled via icacls ACLs on the AppContainer SID.
    Network access is controlled via AppContainer capabilities.

    Lifecycle:
        __aenter__: Create or reuse AppContainer profile, set ACLs if new
        execute: Launch process with AppContainer security token
        __aexit__/stop: Kill running process (profile preserved for reuse)
    """

    def __init__(self, config: SandboxConfig):
        self._config = config
        self._process_handle: Optional[ctypes.wintypes.HANDLE] = None
        self._process_id: Optional[int] = None
        self._container_name: Optional[str] = None
        self._container_sid: Optional[str] = None
        self._junction_path: Optional[str] = None
        self._state_dir = (
            Path(os.environ.get("USERPROFILE", os.path.expanduser("~")))
            / ".qwenpaw"
        )

    @property
    def config(self) -> SandboxConfig:
        return self._config

    async def __aenter__(self):
        """Set up the AppContainer sandbox (create or reuse)."""
        fingerprint = _compute_acl_fingerprint(self._config)

        # Try to reuse an existing container
        existing = _find_reusable_container(self._state_dir, fingerprint)
        if existing:
            self._container_name = existing["container_name"]
            self._container_sid = existing["sid"]
            self._junction_path = existing.get("junction_path")
            logger.debug(
                "Reusing AppContainer '%s' (fingerprint=%s)",
                self._container_name,
                fingerprint,
            )
        else:
            # Create a new container
            self._container_name = f"qwenpaw_{uuid.uuid4().hex[:12]}"
            self._container_sid = _create_appcontainer_profile(
                self._container_name,
                "QwenPaw Sandbox",
                "Sandboxed execution environment for QwenPaw",
            )

            # Apply ACLs
            await _apply_all_acls(self._config, self._container_sid)

            # Create junction for CWD traversal
            self._junction_path = _create_workspace_junction(
                self._config.workspace_dir, self._state_dir
            )

            # Grant AppContainer access to the junction directory
            junction_dir = str(self._state_dir / "junctions")
            await _set_acl_grant(junction_dir, self._container_sid, "F")

            # Save metadata for reuse
            _save_container_metadata(
                self._state_dir,
                self._container_name,
                self._container_sid,
                fingerprint,
                self._config.workspace_dir,
                self._junction_path or "",
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
        """Execute a command inside the AppContainer.

        Steps:
            1. Resolve working directory (use junction if needed)
            2. Compute network capabilities
            3. Build environment
            4. Launch process with AppContainer security token
            5. Wait for completion with timeout
            6. Detect sandbox violations
            7. Return ExecutionResult
        """
        if not self._container_sid:
            # Lazy init if not entered via context manager
            await self.__aenter__()

        start = time.monotonic()

        # Resolve CWD
        effective_cwd = cwd or self._config.workspace_dir
        # If the CWD is the workspace dir and we have a junction, use it
        if self._junction_path and os.path.normpath(
            effective_cwd
        ) == os.path.normpath(self._config.workspace_dir):
            effective_cwd = self._junction_path

        # Compute network capabilities
        capabilities = _compute_network_capabilities(self._config)

        # Build environment
        env = dict(os.environ)
        if self._config.env_vars:
            for k, v in self._config.env_vars.items():
                env[k] = v

        try:
            # Launch process
            pid, proc_handle, stdout_handle, stderr_handle = (
                _create_process_in_appcontainer(
                    cmd,
                    self._container_sid,
                    capabilities,
                    effective_cwd,
                    env,
                )
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
        """Kill any running process (do NOT delete the container profile)."""
        if self._process_handle is not None:
            try:
                kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
                kernel32.TerminateProcess(self._process_handle, 1)
                kernel32.CloseHandle(self._process_handle)
            except OSError:
                pass
            self._process_handle = None

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()
