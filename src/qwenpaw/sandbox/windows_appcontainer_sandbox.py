# -*- coding: utf-8 -*-
"""Windows AppContainer sandbox implementation.

Uses the Windows AppContainer isolation mechanism (SID ``S-1-15-2-*``)
for native process isolation. Only paths with explicit ACEs for the
container SID are accessible — all other filesystem access is denied.

Selected when ``allow_read_all=False``. When ``allow_read_all=True``,
``WindowsElevatedSandbox`` or ``WindowsUnelevatedSandbox`` is used
instead.

Requires Windows 10 1507+ (build 10240) and Python ctypes.
"""

import asyncio
import atexit
import ctypes
import ctypes.wintypes
import hashlib
import json
import logging
import os
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
    _build_shell_command_line,
    _create_stdio_pipes,
    _decode_pipe_output,
    _get_python_install_dir,
    _is_admin,
    _is_pid_alive,
    _read_pipe,
    _remove_acl_with_verify_sync,
    _set_path_ace,
    _sid_to_string,
    _string_to_sid,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

# AppContainer network capability well-known SIDs
_CAP_INTERNET_CLIENT = "internetClient"
_CAP_INTERNET_CLIENT_SERVER = "internetClientServer"
_CAP_PRIVATE_NETWORK = "privateNetworkClientServer"

_CAPABILITY_SIDS: Dict[str, str] = {
    _CAP_INTERNET_CLIENT: "S-1-15-3-1",
    _CAP_INTERNET_CLIENT_SERVER: "S-1-15-3-2",
    _CAP_PRIVATE_NETWORK: "S-1-15-3-3",
}

# Win32 constants (AppContainer-specific only; shared ones via _WC)
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
_HRESULT_ERROR_ALREADY_EXISTS = (
    0x800700B7  # HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS=183)
)


# ═══════════════════════════════════════════════════════════════════════════
# Cached DLL accessors (module-local — different argtypes from shared)
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

    If a profile with the same name already exists, its SID is derived
    and returned without error.

    Args:
        container_name: Unique name for the container profile.
        display_name: Human-readable display name.
        description: Profile description.

    Returns:
        SID string for the created or existing profile.

    Raises:
        OSError: If profile creation fails with an unexpected HRESULT.
    """
    userenv = _get_userenv()
    advapi32 = _get_advapi32()

    psid = ctypes.c_void_p()
    hr = userenv.CreateAppContainerProfile(
        ctypes.c_wchar_p(container_name),
        ctypes.c_wchar_p(display_name),
        ctypes.c_wchar_p(description),
        None,
        ctypes.c_uint32(0),
        ctypes.byref(psid),
    )

    hr_unsigned = hr & 0xFFFFFFFF

    if hr_unsigned not in (0, _HRESULT_ERROR_ALREADY_EXISTS):
        raise OSError(
            f"CreateAppContainerProfile failed: HRESULT=0x{hr_unsigned:08x}",
        )

    if hr_unsigned == _HRESULT_ERROR_ALREADY_EXISTS:
        sid_str = _get_appcontainer_sid(container_name)
        if sid_str is None:
            raise OSError("AppContainer profile exists but cannot derive SID")
        return sid_str

    try:
        sid_str = _sid_to_string(psid, advapi32)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(psid)

    return sid_str


def _delete_appcontainer_profile(container_name: str) -> bool:
    """Deletes an AppContainer profile by name.

    Args:
        container_name: Profile name to delete.

    Returns:
        True if deletion succeeded.
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
        container_name: Profile name.

    Returns:
        SID string, or None if the profile does not exist.
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


# ═══════════════════════════════════════════════════════════════════════════
# ACL management (Win32 API — aligned with unelevated / restricted sandboxes)
# ═══════════════════════════════════════════════════════════════════════════

_ACL_FULL_ACCESS = (
    _WC.FILE_GENERIC_READ
    | _WC.FILE_GENERIC_WRITE
    | _WC.FILE_GENERIC_EXECUTE
    | _WC.DELETE
    | _WC.FILE_DELETE_CHILD
)

_ACL_READ_EXECUTE = _WC.FILE_GENERIC_READ | _WC.FILE_GENERIC_EXECUTE

_ACL_DENY_ALL = _ACL_FULL_ACCESS | _WC.GENERIC_ALL


def _apply_all_acls(config: SandboxConfig, sid: str) -> Dict[str, Any]:
    """Applies all filesystem ACLs for an AppContainer profile.

    Sets inheritable ACEs via Win32 API on workspace, mounts, Python
    install directory, and deny paths.

    Args:
        config: Sandbox configuration.
        sid: AppContainer SID string.

    Returns:
        Manifest dict with ``"grant_paths"`` and ``"deny_paths"`` lists.
    """
    kernel32 = _get_kernel32()
    psid = _string_to_sid(sid)
    grant_paths: List[str] = []
    deny_paths: List[str] = []

    try:
        grant_paths.append(config.workspace_dir)
        _set_path_ace(
            config.workspace_dir,
            psid,
            _ACL_FULL_ACCESS,
            _WC.SET_ACCESS,
        )

        ws_norm = os.path.normcase(os.path.normpath(config.workspace_dir))
        for mount in config.mounts:
            mount_norm = os.path.normcase(os.path.normpath(mount.path))
            if mount_norm == ws_norm:
                continue
            mask = _ACL_FULL_ACCESS if mount.writable else _ACL_READ_EXECUTE
            grant_paths.append(mount.path)
            _set_path_ace(mount.path, psid, mask, _WC.SET_ACCESS)

        python_dir = _get_python_install_dir()
        if python_dir and os.path.isdir(python_dir):
            python_norm = os.path.normcase(os.path.normpath(python_dir))
            if python_norm != ws_norm:
                grant_paths.append(python_dir)
                _set_path_ace(
                    python_dir,
                    psid,
                    _ACL_READ_EXECUTE,
                    _WC.SET_ACCESS,
                )
                logger.debug(
                    "Granted RX on Python install dir: %s",
                    python_dir,
                )

        for deny_path in config.deny_paths:
            expanded = os.path.expanduser(deny_path)
            if os.path.exists(expanded):
                deny_paths.append(expanded)
                _set_path_ace(
                    expanded,
                    psid,
                    _ACL_DENY_ALL,
                    _WC.DENY_ACCESS,
                )
    finally:
        kernel32.LocalFree(psid)

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

    Args:
        config: Sandbox configuration.

    Returns:
        List of capability names to grant (empty if network is blocked).
    """
    if not config.network_allow:
        return []

    if "*" not in config.network_allow:
        logger.warning(
            "WindowsAppContainerSandbox: domain-level network"
            " filtering not supported by AppContainer."
            " Allowing all network access.",
        )

    return [
        _CAP_INTERNET_CLIENT,
        _CAP_INTERNET_CLIENT_SERVER,
        _CAP_PRIVATE_NETWORK,
    ]


# ═══════════════════════════════════════════════════════════════════════════
# AppContainer-specific ctypes structures
# ═══════════════════════════════════════════════════════════════════════════


class _SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.POINTER(_SID_AND_ATTRIBUTES)),
        ("CapabilityCount", ctypes.wintypes.DWORD),
        ("Reserved", ctypes.wintypes.DWORD),
    ]


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", _STARTUPINFOW),
        ("lpAttributeList", ctypes.c_void_p),
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Process launch with AppContainer token
# ═══════════════════════════════════════════════════════════════════════════


def _setup_security_capabilities(
    kernel32: Any,
    container_sid: str,
    capabilities: List[str],
) -> Tuple[ctypes.c_void_p, List[ctypes.c_void_p], Any, Any]:
    """Builds SECURITY_CAPABILITIES and a proc-thread attribute list.

    Args:
        kernel32: Loaded kernel32 DLL handle.
        container_sid: AppContainer SID string.
        capabilities: Network capability names to include.

    Returns:
        Tuple of ``(app_container_psid, cap_psids, sec_cap,
        attr_list)``. All PSIDs must be freed by the caller.

    Raises:
        OSError: If attribute list initialization or update fails.
    """
    app_container_psid = _string_to_sid(container_sid)

    cap_sids = []
    cap_psids: List[ctypes.c_void_p] = []
    for cap_name in capabilities:
        cap_sid_str = _CAPABILITY_SIDS.get(cap_name)
        if cap_sid_str:
            cap_psid = _string_to_sid(cap_sid_str)
            cap_psids.append(cap_psid)
            cap_sids.append(
                _SID_AND_ATTRIBUTES(Sid=cap_psid, Attributes=0x00000004),
            )

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
    shell_executable: Optional[str] = None,
) -> Tuple[
    int,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.HANDLE,
]:
    """Launches a process inside the AppContainer via ``CreateProcessW``.

    Args:
        cmd: Command to execute.
        container_sid: AppContainer SID string.
        capabilities: Network capability names.
        cwd: Working directory for the child process.
        env: Optional environment variables.
        shell_executable: Shell binary path.

    Returns:
        Tuple of ``(pid, process_handle, stdout_read, stderr_read)``.

    Raises:
        OSError: If ``CreateProcessW`` fails.
    """
    kernel32 = _get_kernel32()

    stdout_read, stdout_write, stderr_read, stderr_write = _create_stdio_pipes(
        kernel32,
    )
    (
        app_container_psid,
        cap_psids,
        _sec_cap,
        attr_list,
    ) = _setup_security_capabilities(kernel32, container_sid, capabilities)

    si_ex = _STARTUPINFOEXW()
    si_ex.StartupInfo.cb = ctypes.sizeof(si_ex)
    si_ex.StartupInfo.dwFlags = _WC.STARTF_USESTDHANDLES
    si_ex.StartupInfo.hStdInput = None
    si_ex.StartupInfo.hStdOutput = stdout_write
    si_ex.StartupInfo.hStdError = stderr_write
    si_ex.lpAttributeList = attr_list

    env_block = None
    if env:
        env_str = "\x00".join(f"{k}={v}" for k, v in env.items()) + "\x00\x00"
        env_block = ctypes.create_unicode_buffer(env_str)

    pi = _PROCESS_INFORMATION()
    creation_flags = (
        _EXTENDED_STARTUPINFO_PRESENT
        | _WC.CREATE_UNICODE_ENVIRONMENT
        | _WC.CREATE_NO_WINDOW
    )

    cmd_line = _build_shell_command_line(cmd, shell_executable)

    success = kernel32.CreateProcessW(
        None,
        ctypes.c_wchar_p(cmd_line),
        None,
        None,
        True,
        creation_flags,
        ctypes.cast(env_block, ctypes.c_void_p) if env_block else None,
        ctypes.c_wchar_p(cwd),
        ctypes.byref(si_ex),
        ctypes.byref(pi),
    )

    kernel32.DeleteProcThreadAttributeList(attr_list)

    kernel32.CloseHandle(stdout_write)
    kernel32.CloseHandle(stderr_write)

    if not success:
        kernel32.CloseHandle(stdout_read)
        kernel32.CloseHandle(stderr_read)
        kernel32.LocalFree(app_container_psid)
        for psid in cap_psids:
            kernel32.LocalFree(psid)
        raise OSError(
            f"CreateProcessW failed: error={ctypes.get_last_error()}",
        )

    kernel32.CloseHandle(pi.hThread)

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
    """Waits for process completion and reads pipe output.

    Drains stdout/stderr in parallel with the process wait. Terminates
    the process on timeout.

    Args:
        process_handle: Handle to the child process.
        stdout_handle: Read end of the stdout pipe.
        stderr_handle: Read end of the stderr pipe.
        timeout_seconds: Maximum seconds to wait.

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


# ═══════════════════════════════════════════════════════════════════════════
# Sandbox reuse (fingerprint + metadata)
# ═══════════════════════════════════════════════════════════════════════════


def _compute_acl_fingerprint(config: SandboxConfig) -> str:
    """Computes a deterministic hash of ACL-relevant configuration.

    Used to derive a stable container name for profile reuse across
    invocations with identical sandbox constraints.

    Args:
        config: Sandbox configuration.

    Returns:
        16-character hex fingerprint string.
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
    """Checks if an AppContainer profile already exists.

    Args:
        container_name: Profile name to look up.

    Returns:
        SID string if the profile exists, None otherwise.
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
    """Persists AppContainer metadata for the cleanup script.

    Args:
        state_dir: Base state directory (``~/.qwenpaw``).
        container_name: AppContainer profile name.
        sid: Container SID string.
        workspace_dir: Workspace directory path.
        acl_manifest: Optional dict of granted/denied paths.
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
# WindowsAppContainerSandbox class
# ═══════════════════════════════════════════════════════════════════════════


class WindowsAppContainerSandbox(WindowsSandboxBase):
    """Windows AppContainer sandbox providing native process isolation.

    Filesystem access is controlled via Win32 API ACLs on the
    AppContainer SID. Network access is controlled via AppContainer
    capabilities.

    Only used when ``allow_read_all=False``. Raises ``ValueError``
    if instantiated with ``allow_read_all=True``.

    Lifecycle:
        ``__aenter__``: Creates or reuses an AppContainer profile and
            applies filesystem ACLs (only on first creation).
        ``execute``: Launches a command with the AppContainer security
            token.
        ``__aexit__`` / ``stop``: Terminates any running child process.
            The AppContainer profile is preserved for reuse.
    """

    def __init__(self, config: SandboxConfig):
        if config.allow_read_all:
            raise ValueError(
                "WindowsAppContainerSandbox (AppContainer"
                " backend) does not support"
                " allow_read_all=True — it would require"
                " granting read access "
                "on a large set of system directories. Use "
                "WindowsElevatedSandbox (the allow_read_all=True backend) "
                "instead, or let create_sandbox() pick the right backend.",
            )
        super().__init__(config)
        self._process_id: Optional[int] = None
        self._container_name: Optional[str] = None
        self._container_sid: Optional[str] = None
        self._state_dir = (
            Path(os.environ.get("USERPROFILE", os.path.expanduser("~")))
            / ".qwenpaw"
        )

    async def __aenter__(self):
        """Sets up the AppContainer sandbox (creates or reuses a profile)."""
        if not _is_admin():
            print(
                "[QwenPaw Sandbox] WARNING: Not running as administrator. "
                "Sandbox ACL setup may fail.",
            )

        fingerprint = _compute_acl_fingerprint(self._config)
        self._container_name = f"qwenpaw_{fingerprint[:12]}"

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

            acl_manifest = await asyncio.to_thread(
                _apply_all_acls,
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
        """Executes a command inside the AppContainer."""
        if not self._container_sid:
            await self.__aenter__()

        assert self._container_sid is not None
        start = time.monotonic()

        effective_cwd = cwd or self._config.workspace_dir
        capabilities = _compute_network_capabilities(self._config)
        env = self._build_base_env()

        try:
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
            self._process_handle = None

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
        """Terminates any running child process.

        Does NOT delete the AppContainer profile (preserved for reuse).
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
# Shutdown cleanup
# ═══════════════════════════════════════════════════════════════════════════

_state_dir = (
    Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / ".qwenpaw"
)


def _cleanup_single_container(meta: dict, meta_file: Path) -> None:
    """Cleans up a single AppContainer sandbox from its metadata.

    Removes ACLs, deletes the AppContainer profile, and removes the
    metadata file.

    Args:
        meta: Container metadata dict.
        meta_file: Path to the metadata JSON file.
    """
    container_name = meta.get("container_name", "")
    sid = meta.get("sid", "")
    workspace_dir = meta.get("workspace_dir", "")
    acl_manifest = meta.get("acl_manifest")

    if sid:
        if acl_manifest:
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

    if container_name:
        try:
            userenv = _get_userenv()
            userenv.DeleteAppContainerProfile(
                ctypes.c_wchar_p(container_name),
            )
        except OSError:
            pass

    try:
        meta_file.unlink()
    except OSError:
        pass


def shutdown_cleanup() -> None:
    """Destroys AppContainer sandboxes owned by this process or orphaned.

    Iterates metadata files under ``~/.qwenpaw/containers/``, skips
    containers whose owner process is still alive, and cleans up the
    rest.
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

    if containers_dir.exists() and not list(containers_dir.glob("*.json")):
        try:
            containers_dir.rmdir()
        except OSError:
            pass


atexit.register(shutdown_cleanup)
