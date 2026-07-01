# -*- coding: utf-8 -*-
"""Windows AppContainer sandbox implementation.

Uses Windows AppContainer (SID ``S-1-15-2-*``) for native process isolation.

Architecture:
    1. Create (or reuse) an AppContainer profile via ``userenv.dll``.
    2. Set filesystem ACLs via ``icacls.exe`` (parallel for global grants,
       serial with inheritance-break for mounts and deny paths).
    3. Create an NTFS junction for CWD traversal into the workspace.
    4. Launch ``cmd.exe /c <command>`` with the AppContainer security token
       attached via ``PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES``.
    5. Capture stdout/stderr, decode with OEM code page awareness, and
       detect access-denied violations via regex.

Requirements:
    - Windows 10 1507+ (build 10240).
    - ``icacls.exe`` (ships with all Windows editions).
    - Python ``ctypes`` (for Win32 API calls via ``kernel32``,
      ``userenv``, ``advapi32``).
"""

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
_HRESULT_ERROR_ALREADY_EXISTS = -2147023649  # 0x800700B7


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

    if hr not in (0, _HRESULT_ERROR_ALREADY_EXISTS):
        raise OSError(
            f"CreateAppContainerProfile failed: "
            f"HRESULT=0x{hr & 0xFFFFFFFF:08x}",
        )

    # If already exists, get SID via DeriveAppContainerSid
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


async def _break_and_set_acl(
    path: str,
    sid: str,
    ace_type: str,
    permission: str,
) -> bool:
    """Breaks inheritance, removes existing ACEs for SID, then applies an ACE.

    This is the shared implementation for both mount grants and deny paths.
    AppContainer tokens ignore explicit deny ACEs when an inherited allow
    ACE exists, so breaking inheritance is always required first.

    Args:
        path: Filesystem path to set ACL on.
        sid: AppContainer SID string (``S-1-15-2-...``).
        ace_type: Either ``"grant"`` or ``"deny"``.
        permission: Permission string: ``"F"``, ``"RX"``, or ``"R"`` for
            grants; ``"F"`` for deny (full deny).

    Returns:
        True only if all three icacls steps succeed.
    """
    # Step 1: Break inheritance (convert inherited ACEs to explicit)
    ok1, err1 = await _run_icacls([path, "/inheritance:d"])
    if not ok1:
        logger.warning("Failed to disable inheritance on %s: %s", path, err1)

    # Step 2: Remove all existing ACEs for this SID
    ok2, err2 = await _run_icacls([path, "/remove", f"*{sid}"])
    if not ok2:
        logger.warning("Failed to remove ACL for SID on %s: %s", path, err2)

    # Step 3: Apply the grant or deny ACE (inheritable to children)
    ace_flag = "/deny" if ace_type == "deny" else "/grant"
    ok3, err3 = await _run_icacls(
        [path, ace_flag, f"*{sid}:(OI)(CI)({permission})"],
    )
    if not ok3:
        logger.warning(
            "Failed to %s %s ACL on %s: %s",
            ace_type,
            permission,
            path,
            err3,
        )

    return ok1 and ok2 and ok3


async def _set_acl_grant(path: str, sid: str, permission: str) -> bool:
    """Grants an inheritable ACE on a path for the AppContainer SID.

    Unlike ``_break_and_set_acl``, this does NOT break inheritance. It is
    used for additive grants (e.g. system drive RX, workspace F) where
    inherited permissions from parent directories should be preserved.

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


async def _apply_all_acls(config: SandboxConfig, sid: str) -> Dict[str, Any]:
    """Applies all filesystem ACLs for an AppContainer profile.

    Executes ``icacls`` commands in three sequential phases:

    Phase 1 - Global read grants (parallel):
        When ``allow_read_all`` is True, grants RX on the system drive root,
        ``C:\\Users``, and the current user profile. Also grants RX on the
        Python interpreter directory unconditionally.

    Phase 2 - Workspace (single command):
        Grants full access (F) on ``workspace_dir``.

    Phase 3 - Mounts + deny paths (serial, depth-sorted):
        Each entry breaks inheritance, removes existing ACEs for the SID,
        then applies the exact permission (grant for mounts, deny for
        ``deny_paths``). Processed shallowest-first to ensure parent paths
        are handled before child paths.

    This ordering guarantees that workspace inheritable ACEs are established
    before overrides break them, and that deny paths reliably block access
    regardless of parent grants.

    Args:
        config: Sandbox configuration specifying paths and permissions.
        sid: AppContainer SID string to grant/deny.

    Returns:
        An ACL manifest dict recording all paths that were modified::

            {
                "grant_paths": ["C:\\\\", "C:\\\\Users", ...],
                "inheritance_broken_paths": ["~/.ssh", "/mount/path", ...],
            }

        ``grant_paths`` are paths where an ACE was added (simple grant,
        no inheritance break). ``inheritance_broken_paths`` are paths where
        ``/inheritance:d`` was applied before setting the ACE.
    """
    # Track all paths modified for the ACL manifest
    grant_paths: List[str] = []
    inheritance_broken_paths: List[str] = []

    # ── Phase 1: Global read grants (parallel) ─────────────────────
    # Note: Critical system directories (C:\Windows, C:\Program Files, etc.)
    # are NOT granted explicitly — on Windows 10+ they already have an ACE
    # for "ALL APPLICATION PACKAGES" (S-1-15-2-1) granting read+execute.
    grant_tasks: List[asyncio.Task] = []

    if config.allow_read_all:
        sys_drive = os.environ.get("SystemDrive", "C:")
        grant_paths.append(sys_drive + "\\")
        grant_tasks.append(
            asyncio.ensure_future(_set_acl_grant(sys_drive + "\\", sid, "RX")),
        )
        users_dir = sys_drive + "\\Users"
        if os.path.isdir(users_dir):
            grant_paths.append(users_dir)
            grant_tasks.append(
                asyncio.ensure_future(_set_acl_grant(users_dir, sid, "RX")),
            )
        user_profile = os.environ.get("USERPROFILE", "")
        if user_profile and os.path.isdir(user_profile):
            grant_paths.append(user_profile)
            grant_tasks.append(
                asyncio.ensure_future(_set_acl_grant(user_profile, sid, "RX")),
            )

    # Python interpreter directory
    python_dir = os.path.dirname(sys.executable)
    if python_dir and os.path.isdir(python_dir):
        grant_paths.append(python_dir)
        grant_tasks.append(
            asyncio.ensure_future(_set_acl_grant(python_dir, sid, "RX")),
        )

    if grant_tasks:
        await asyncio.gather(*grant_tasks, return_exceptions=True)

    # ── Phase 2: Workspace full access ─────────────────────────────
    grant_paths.append(config.workspace_dir)
    await _set_acl_grant(config.workspace_dir, sid, "F")

    # ── Phase 3: Mounts + Deny paths (serial, depth-sorted) ────
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
        inheritance_broken_paths.append(path)
        if action == "DENY":
            await _break_and_set_acl(path, sid, "deny", "F")
        else:
            await _break_and_set_acl(path, sid, "grant", action)

    return {
        "grant_paths": grant_paths,
        "inheritance_broken_paths": inheritance_broken_paths,
    }


# ═══════════════════════════════════════════════════════════════════════════
# NTFS Junction management
# ═══════════════════════════════════════════════════════════════════════════


def _create_workspace_junction(workspace_dir: str, state_dir: Path) -> str:
    """Creates an NTFS junction for CWD traversal into the workspace.

    The junction is placed at ``<state_dir>/junctions/<sha256[:12]>`` and
    points to ``workspace_dir``. If a junction already exists and points
    to the correct target, it is reused.

    Args:
        workspace_dir: Absolute path to the workspace directory.
        state_dir: QwenPaw state directory (``~/.qwenpaw``).

    Returns:
        The junction path string. Falls back to ``workspace_dir`` itself
        if junction creation fails.
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


def _create_process_in_appcontainer(
    cmd: str,
    container_sid: str,
    capabilities: List[str],
    cwd: str,
    env: Optional[Dict[str, str]] = None,
) -> Tuple[
    int,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
]:
    """Launches a process inside the AppContainer via ``CreateProcessW``.

    Creates stdout/stderr pipes, builds a ``SECURITY_CAPABILITIES`` struct
    with the container SID and requested capabilities, then launches
    ``cmd.exe /c "<cmd>"`` with
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

    Runs the blocking wait in a thread executor to avoid blocking the
    async event loop. If the process exceeds ``timeout_seconds``, it is
    terminated.

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

    def _blocking_wait():
        """Blocks until process exits or timeout, then reads pipes."""
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
        json.dumps(data, sort_keys=True).encode(),
    ).hexdigest()[:16]


def _load_container_metadata(state_dir: Path) -> List[Dict[str, Any]]:
    """Loads all container metadata JSON files from the state directory.

    Args:
        state_dir: QwenPaw state directory (``~/.qwenpaw``).

    Returns:
        List of parsed metadata dicts. Malformed files are silently skipped.
    """
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
    acl_manifest: Optional[Dict[str, Any]] = None,
) -> None:
    """Persists container metadata to a JSON file for future reuse.

    Args:
        state_dir: QwenPaw state directory (``~/.qwenpaw``).
        container_name: Unique AppContainer profile name.
        sid: AppContainer SID string.
        fingerprint: ACL configuration fingerprint hash.
        workspace_dir: Workspace directory path.
        junction_path: NTFS junction path (or empty string if none).
        acl_manifest: Optional dict recording all ACL-modified paths.
            Contains ``grant_paths`` (simple grants, no inheritance break)
            and ``inheritance_broken_paths`` (paths where inheritance was
            disabled). Used by the cleanup script for complete ACL removal.
    """
    containers_dir = state_dir / "containers"
    containers_dir.mkdir(parents=True, exist_ok=True)

    meta: Dict[str, Any] = {
        "container_name": container_name,
        "sid": sid,
        "acl_fingerprint": fingerprint,
        "workspace_dir": workspace_dir,
        "junction_path": junction_path,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if acl_manifest is not None:
        meta["acl_manifest"] = acl_manifest

    meta_file = containers_dir / f"{container_name}.json"
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def _find_reusable_container(
    state_dir: Path,
    fingerprint: str,
) -> Optional[Dict[str, Any]]:
    """Finds an existing container whose ACL fingerprint matches.

    Verifies that the container profile still exists by deriving its SID
    and comparing against the stored value.

    Args:
        state_dir: QwenPaw state directory (``~/.qwenpaw``).
        fingerprint: ACL configuration fingerprint to match.

    Returns:
        The metadata dict if a valid match is found, None otherwise.
    """
    for meta in _load_container_metadata(state_dir):
        if meta.get("acl_fingerprint") == fingerprint:
            # Verify the container still exists
            container_name = meta.get("container_name", "")
            sid = _get_appcontainer_sid(container_name)
            if sid and sid == meta.get("sid"):
                return meta
    return None


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
        """Sets up the AppContainer sandbox (creates or reuses a profile)."""
        # Check admin privileges
        if not _is_admin():
            print(
                "[QwenPaw Sandbox] WARNING: Not running as administrator. "
                "Sandbox ACL setup may fail.",
            )

        fingerprint = _compute_acl_fingerprint(self._config)

        # Try to reuse an existing container
        existing = _find_reusable_container(self._state_dir, fingerprint)
        if existing:
            self._container_name = existing["container_name"]
            self._container_sid = existing["sid"]
            self._junction_path = existing.get("junction_path")
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
            # Create a new container
            self._container_name = f"qwenpaw_{uuid.uuid4().hex[:12]}"
            self._container_sid = _create_appcontainer_profile(
                self._container_name,
                "QwenPaw Sandbox",
                "Sandboxed execution environment for QwenPaw",
            )

            # Apply ACLs
            acl_manifest = await _apply_all_acls(
                self._config,
                self._container_sid,
            )

            # Create junction for CWD traversal
            self._junction_path = _create_workspace_junction(
                self._config.workspace_dir,
                self._state_dir,
            )

            # Grant AppContainer read+traverse access to the junction directory
            junction_dir = str(self._state_dir / "junctions")
            await _set_acl_grant(junction_dir, self._container_sid, "RX")
            acl_manifest["grant_paths"].append(junction_dir)

            # Save metadata for reuse
            _save_container_metadata(
                self._state_dir,
                self._container_name,
                self._container_sid,
                fingerprint,
                self._config.workspace_dir,
                self._junction_path or "",
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

        Resolves the working directory (using the NTFS junction when CWD
        matches the workspace), launches the process with the AppContainer
        token, waits for completion (with timeout), and checks for
        access-denied violations in the output.

        Args:
            cmd: Shell command string to execute via ``cmd.exe /c``.
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
        # If the CWD is the workspace dir and we have a junction, use it
        if self._junction_path and os.path.normpath(
            effective_cwd,
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
            (
                pid,
                proc_handle,
                stdout_handle,
                stderr_handle,
            ) = _create_process_in_appcontainer(
                cmd,
                self._container_sid,
                capabilities,
                effective_cwd,
                env,
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
