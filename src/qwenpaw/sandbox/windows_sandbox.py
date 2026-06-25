# -*- coding: utf-8 -*-
"""Windows sandbox — WSL2 delegation.

Delegates command execution to a WSL2 Linux distribution where Landlock LSM
is available for kernel-level filesystem isolation.

Architecture:
    1. Detect WSL2 availability (wsl.exe --status)
    2. Translate Windows paths to WSL mount paths (/mnt/c/...)
    3. Generate a Landlock enforcement script (reuses linux_sandbox logic)
    4. Execute via: wsl.exe -d <distro> -- python3 <script>
    5. Capture stdout/stderr and detect violations

Path mapping:
    - C:\\Users\\foo\\project → /mnt/c/Users/foo/project
    - deny_paths like ~\\.ssh → /home/<wsl_user>/.ssh (inside WSL)

Requirements:
    - Windows 10 21H2+ or Windows 11 with WSL2 enabled
    - A WSL2 distro with kernel >= 5.13 (Ubuntu 22.04+ recommended)
    - python3 installed inside the WSL2 distro
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time
from typing import List, Optional, Tuple

from .config import ExecutionResult, SandboxConfig

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Path translation: Windows ↔ WSL
# ═══════════════════════════════════════════════════════════════════════════════


def win_to_wsl_path(win_path: str) -> str:
    """Convert a Windows path to its WSL /mnt/<drive>/... equivalent.

    Examples:
        C:\\Users\\foo\\project → /mnt/c/Users/foo/project
        D:\\data → /mnt/d/data
        ~/foo → ~/foo (relative paths passed as-is)
    """
    # Normalize backslashes
    path = win_path.replace("\\", "/")

    # Match drive letter pattern: C:/ or c:/
    match = re.match(r"^([A-Za-z]):/(.*)$", path)
    if match:
        drive = match.group(1).lower()
        rest = match.group(2)
        return f"/mnt/{drive}/{rest}".rstrip("/")

    # Handle ~ (user home) — map to WSL home
    if path.startswith("~/") or path == "~":
        return path  # Let WSL expand ~ natively

    return path


def wsl_to_win_path(wsl_path: str) -> str:
    """Convert a WSL /mnt/<drive>/... path back to Windows format.

    Examples:
        /mnt/c/Users/foo → C:\\Users\\foo
    """
    match = re.match(r"^/mnt/([a-z])/(.*)$", wsl_path)
    if match:
        drive = match.group(1).upper()
        rest = match.group(2).replace("/", "\\")
        return f"{drive}:\\{rest}"
    return wsl_path


# ═══════════════════════════════════════════════════════════════════════════════
# WSL2 probe helpers
# ═══════════════════════════════════════════════════════════════════════════════


def probe_wsl2_availability() -> Tuple[bool, str, str]:
    """Probe whether WSL2 is available and find a suitable distro.

    Returns:
        (available, distro_name, reason)
    """
    # Check wsl.exe exists
    wsl_exe = shutil.which("wsl") or shutil.which("wsl.exe")
    if not wsl_exe:
        return False, "", "wsl.exe not found in PATH"

    import subprocess

    # Check WSL status
    try:
        result = subprocess.run(
            ["wsl", "--status"],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        # On some systems --status might not be available; continue anyway
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return False, "", f"wsl --status failed: {e}"

    # List distributions and find a WSL2 one
    try:
        result = subprocess.run(
            ["wsl", "--list", "--verbose"],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-16-le",
            errors="replace",
            check=False,
        )
        output = result.stdout
        # Parse output: NAME   STATE   VERSION
        # Look for lines with VERSION=2 and STATE=Running or Stopped
        lines = output.strip().split("\n")
        for line in lines[1:]:  # skip header
            # Remove leading * (default marker)
            clean = line.strip().lstrip("*").strip()
            parts = clean.split()
            if len(parts) >= 3:
                name = parts[0]
                version = parts[-1]
                if version == "2":
                    return True, name, f"WSL2 distro found: {name}"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return False, "", f"wsl --list failed: {e}"

    return False, "", "No WSL2 distribution found"


def check_wsl_python3(distro: str) -> bool:
    """Check if python3 is available in the given WSL2 distro."""
    import subprocess

    try:
        result = subprocess.run(
            ["wsl", "-d", distro, "--", "which", "python3"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def check_wsl_landlock(distro: str) -> Tuple[bool, int]:
    """Check if Landlock is supported in the WSL2 distro's kernel.

    Returns:
        (supported, abi_version)
    """
    import subprocess

    check_script = (
        "import ctypes, ctypes.util, os, struct; "
        "libc = ctypes.CDLL("
        "ctypes.util.find_library('c') or 'libc.so.6', "
        "use_errno=True); "
        "libc.syscall.restype = ctypes.c_long; "
        "abi = libc.syscall("
        "ctypes.c_long(444), None, ctypes.c_size_t(0), "
        "ctypes.c_uint32(1)); "
        "print(abi)"
    )
    try:
        result = subprocess.run(
            ["wsl", "-d", distro, "--", "python3", "-c", check_script],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            abi = int(result.stdout.strip())
            if abi > 0:
                return True, abi
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
        pass

    return False, 0


# ═══════════════════════════════════════════════════════════════════════════════
# Landlock script generation (WSL-adapted)
# ═══════════════════════════════════════════════════════════════════════════════

# Reuse constants from linux_sandbox
_FS_READ_ACCESS = 0x0C  # READ_FILE | READ_DIR
_FS_WRITE_ACCESS = 0x1FE2  # All write-related bits
_FS_EXEC_ACCESS = 0x01  # EXECUTE
_FS_ALL_ACCESS_V1 = _FS_READ_ACCESS | _FS_WRITE_ACCESS | _FS_EXEC_ACCESS

# Syscall numbers (same for x86_64 and aarch64)
SYS_LANDLOCK_CREATE_RULESET = 444
SYS_LANDLOCK_ADD_RULE = 445
SYS_LANDLOCK_RESTRICT_SELF = 446
LANDLOCK_RULE_PATH_BENEATH = 1
PR_SET_NO_NEW_PRIVS = 38


def _get_all_fs_access_wsl(abi_version: int) -> int:
    """Get all filesystem access rights for given ABI version."""
    access = _FS_ALL_ACCESS_V1
    if abi_version >= 2:
        access |= 1 << 13  # REFER
    if abi_version >= 3:
        access |= 1 << 14  # TRUNCATE
    return access


def _generate_wsl_sandbox_script(  # pylint: disable=too-many-branches
    config: SandboxConfig,
    cmd: str,
    wsl_cwd: str,
    abi_version: int,
    wsl_home: str = "/root",
) -> str:
    """Generate a Python Landlock enforcement script for WSL2 execution.

    Similar to linux_sandbox._generate_sandbox_script but operates on
    WSL paths.
    """
    handled_fs = _get_all_fs_access_wsl(abi_version)

    # Build path rules: (wsl_path, access_mask)
    path_rules: List[Tuple[str, int]] = []

    # System paths (always readable inside WSL)
    system_read_paths = [
        "/usr",
        "/lib",
        "/lib64",
        "/etc",
        "/proc",
        "/sys",
        "/dev",
        "/run",
        "/bin",
        "/sbin",
    ]
    for sp in system_read_paths:
        path_rules.append((sp, _FS_READ_ACCESS | _FS_EXEC_ACCESS))

    # /tmp always writable
    path_rules.append(
        ("/tmp", _FS_READ_ACCESS | _FS_WRITE_ACCESS | _FS_EXEC_ACCESS),
    )

    # /mnt (for access to Windows drives through WSL)
    # This allows reading mounted Windows drives
    if config.allow_read_all:
        # Build deny set in WSL path space
        deny_wsl_paths = set()
        for dp in config.deny_paths or []:
            # deny_paths can be Windows paths or ~ paths
            if dp.startswith("~"):
                # Map to WSL home
                deny_wsl_paths.add(
                    (
                        wsl_home + "/" + dp[2:]
                        if dp.startswith("~/")
                        else wsl_home
                    ),
                )
            else:
                deny_wsl_paths.add(win_to_wsl_path(dp))

        if deny_wsl_paths:
            # Selective grant: grant /mnt paths excluding deny,
            # grant home excluding deny
            # Grant /mnt for Windows drive access
            path_rules.append(("/mnt", _FS_READ_ACCESS | _FS_EXEC_ACCESS))

            # Grant WSL home subdirectories individually, skipping deny_paths
            path_rules.append((wsl_home, _FS_READ_ACCESS))
            # Note: The actual HOME enumeration happens at runtime inside WSL
            # so we add a dynamic enumeration block in the script
        else:
            # No deny paths — safe to grant broadly
            path_rules.append(("/mnt", _FS_READ_ACCESS | _FS_EXEC_ACCESS))
            path_rules.append((wsl_home, _FS_READ_ACCESS))

    # Workspace mount (writable)
    wsl_workspace = win_to_wsl_path(config.workspace_dir)
    path_rules.append(
        (wsl_workspace, _FS_READ_ACCESS | _FS_WRITE_ACCESS | _FS_EXEC_ACCESS),
    )

    # Extra mounts from config
    for mount in config.mounts:
        wsl_mount_path = win_to_wsl_path(mount.path)
        access = _FS_READ_ACCESS
        if mount.writable:
            access |= _FS_WRITE_ACCESS
        if mount.executable:
            access |= _FS_EXEC_ACCESS
        path_rules.append((wsl_mount_path, access))

    # Build deny set for filtering
    deny_wsl_set = set()
    for dp in config.deny_paths or []:
        if dp.startswith("~"):
            deny_wsl_set.add(
                wsl_home + "/" + dp[2:] if dp.startswith("~/") else wsl_home,
            )
        else:
            deny_wsl_set.add(win_to_wsl_path(dp))

    # Generate script
    script_lines = [
        "import ctypes, ctypes.util, os, struct, sys",
        "",
        (
            "libc = ctypes.CDLL("
            "ctypes.util.find_library('c') or 'libc.so.6', "
            "use_errno=True)"
        ),
        "libc.syscall.restype = ctypes.c_long",
        "",
        "# prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)",
        "libc.prctl.restype = ctypes.c_int",
        (
            "libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, "
            "ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]"
        ),
        (
            f"assert libc.prctl({PR_SET_NO_NEW_PRIVS}, 1, 0, 0, 0) "
            f"== 0, 'prctl failed'"
        ),
        "",
        f"# Create ruleset (handled_fs=0x{handled_fs:x})",
        f"attr = struct.pack('Q', 0x{handled_fs:x})",
        "attr_buf = ctypes.create_string_buffer(attr)",
        (
            f"fd = libc.syscall(ctypes.c_long({SYS_LANDLOCK_CREATE_RULESET}), "
            "ctypes.cast(attr_buf, ctypes.c_void_p), "
            "ctypes.c_size_t(len(attr)), ctypes.c_uint32(0))"
        ),
        "assert fd >= 0, f'create_ruleset failed: {ctypes.get_errno()}'",
        "",
        "O_PATH = 0o10000000",
        "",
        "def add_path(path, access):",
        "    try:",
        "        pfd = os.open(path, O_PATH | os.O_CLOEXEC)",
        "    except OSError:",
        "        return",
        "    try:",
        "        a = struct.pack('Qi', access, pfd)",
        "        ab = ctypes.create_string_buffer(a)",
        (
            f"        libc.syscall(ctypes.c_long({SYS_LANDLOCK_ADD_RULE}), "
            f"ctypes.c_int(fd), "
            f"ctypes.c_int({LANDLOCK_RULE_PATH_BENEATH}), "
            f"ctypes.cast(ab, ctypes.c_void_p), ctypes.c_uint32(0))"
        ),
        "    finally:",
        "        os.close(pfd)",
        "",
    ]

    # Add static path rules (excluding deny paths)
    for path, access in path_rules:
        skip = False
        for dp in deny_wsl_set:
            if path == dp or path.startswith(dp + "/"):
                skip = True
                break
        if not skip:
            script_lines.append(f"add_path({path!r}, 0x{access:x})")

    # If we have deny_paths under WSL home, enumerate home subdirs dynamically
    home_deny_paths = [
        dp for dp in deny_wsl_set if dp.startswith(wsl_home + "/")
    ]
    if home_deny_paths and config.allow_read_all:
        script_lines += [
            "",
            "# Enumerate WSL home subdirs, skipping deny_paths",
            f"_deny_set = {set(home_deny_paths)!r}",
            f"_home = {wsl_home!r}",
            "if os.path.isdir(_home):",
            "    for _entry in os.listdir(_home):",
            "        _full = os.path.join(_home, _entry)",
            "        if _full not in _deny_set:",
            f"            add_path(_full, 0x{_FS_READ_ACCESS:x})",
        ]

    # Restrict self and exec
    script_lines += [
        "",
        "# Restrict self",
        f"ret = libc.syscall(ctypes.c_long({SYS_LANDLOCK_RESTRICT_SELF}), "
        "ctypes.c_int(fd), ctypes.c_uint32(0))",
        "os.close(fd)",
        "assert ret == 0, f'restrict_self failed: {ctypes.get_errno()}'",
        "",
    ]

    # Apply env_vars (e.g. mask blacklisted env keys with empty string)
    if config.env_vars:
        env_vars_repr = repr(list(config.env_vars.items()))
        script_lines.append("# Apply env_vars (override / mask)")
        script_lines.append(f"for _k, _v in {env_vars_repr}:")
        script_lines.append("    os.environ[_k] = _v")
        script_lines.append("")

    script_lines += [
        "# Exec the command",
        f"os.chdir({wsl_cwd!r})",
        f"os.execvp('/bin/sh', ['/bin/sh', '-c', {cmd!r}])",
    ]

    return "\n".join(script_lines)


# ═══════════════════════════════════════════════════════════════════════════════
# WindowsSandbox class
# ═══════════════════════════════════════════════════════════════════════════════


class WindowsSandbox:
    """Windows sandbox using WSL2 + Landlock delegation.

    Executes commands inside a WSL2 Linux environment where Landlock LSM
    provides kernel-level filesystem isolation.

    Lifecycle: per-tool-call (create, execute, stop/discard).
    """

    def __init__(self, config: SandboxConfig, distro: str = ""):
        """
        Args:
            config: Sandbox configuration.
            distro: WSL2 distribution name. If empty, auto-detect.
        """
        self._config = config
        self._distro = distro
        self._process: Optional[asyncio.subprocess.Process] = None
        self._abi_version = 1  # Will be detected on first execute
        self._wsl_home = "/root"  # Will be detected

    @property
    def config(self) -> SandboxConfig:
        return self._config

    @property
    def distro(self) -> str:
        return self._distro

    async def _detect_wsl_info(self) -> None:
        """Detect WSL distro name, home dir, and Landlock ABI version."""
        if not self._distro:
            available, distro, reason = probe_wsl2_availability()
            if not available:
                raise RuntimeError(f"WSL2 not available: {reason}")
            self._distro = distro

        # Detect WSL home directory
        try:
            proc = await asyncio.create_subprocess_exec(
                "wsl",
                "-d",
                self._distro,
                "--",
                "sh",
                "-c",
                "echo $HOME",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            home = stdout.decode().strip()
            if home:
                self._wsl_home = home
        except (asyncio.TimeoutError, OSError):
            pass

        # Detect Landlock ABI version
        try:
            check_cmd = (
                "import ctypes,ctypes.util;"
                "libc=ctypes.CDLL("
                "ctypes.util.find_library('c') or 'libc.so.6',"
                "use_errno=True);"
                "libc.syscall.restype=ctypes.c_long;"
                "print(libc.syscall("
                "ctypes.c_long(444),None,ctypes.c_size_t(0),"
                "ctypes.c_uint32(1)))"
            )
            proc = await asyncio.create_subprocess_exec(
                "wsl",
                "-d",
                self._distro,
                "--",
                "python3",
                "-c",
                check_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            abi = int(stdout.decode().strip())
            if abi > 0:
                self._abi_version = abi
        except (asyncio.TimeoutError, OSError, ValueError):
            pass

    async def execute(
        self,
        cmd: str,
        cwd: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute a command inside WSL2 with Landlock isolation.

        Steps:
            1. Auto-detect WSL info (first call only)
            2. Translate paths to WSL equivalents
            3. Generate Landlock enforcement script
            4. Run via wsl.exe -d <distro> -- python3 /tmp/script.py
            5. Return ExecutionResult
        """
        # Lazy initialization
        if not self._distro:
            await self._detect_wsl_info()

        cwd = cwd or self._config.workspace_dir
        wsl_cwd = win_to_wsl_path(cwd)

        start = time.monotonic()

        # Generate the enforcement script
        script = _generate_wsl_sandbox_script(
            self._config,
            cmd,
            wsl_cwd,
            self._abi_version,
            self._wsl_home,
        )

        # Write script to a temp location accessible from WSL
        # Use /tmp inside WSL (write via wsl command)
        import hashlib

        script_name = (
            f"landlock_wsl_{hashlib.md5(cmd.encode()).hexdigest()[:8]}.py"
        )
        wsl_script_path = f"/tmp/{script_name}"

        try:
            # Write script into WSL's /tmp via stdin
            write_proc = await asyncio.create_subprocess_exec(
                "wsl",
                "-d",
                self._distro,
                "--",
                "sh",
                "-c",
                f"cat > {wsl_script_path} && chmod +x {wsl_script_path}",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(
                write_proc.communicate(input=script.encode("utf-8")),
                timeout=10,
            )

            if write_proc.returncode != 0:
                duration_ms = int((time.monotonic() - start) * 1000)
                return ExecutionResult(
                    exit_code=-1,
                    stdout="",
                    stderr="Failed to write sandbox script to WSL",
                    duration_ms=duration_ms,
                )

            # Execute the script inside WSL
            self._process = await asyncio.create_subprocess_exec(
                "wsl",
                "-d",
                self._distro,
                "--",
                "python3",
                wsl_script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                self._process.communicate(),
                timeout=self._config.timeout_seconds,
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            # Detect sandbox violation
            violation = None
            if self._process.returncode != 0 and (
                "permission denied" in stderr.lower()
                or "operation not permitted" in stderr.lower()
                or "landlock" in stderr.lower()
                or "eacces" in stderr.lower()
            ):
                violation = stderr.strip()

            return ExecutionResult(
                exit_code=self._process.returncode or 0,
                stdout=stdout,
                stderr=stderr,
                timed_out=False,
                duration_ms=duration_ms,
                sandbox_violation=violation,
            )
        except asyncio.TimeoutError:
            duration_ms = int((time.monotonic() - start) * 1000)
            await self.stop()
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="Command timed out",
                timed_out=True,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_ms=duration_ms,
            )
        finally:
            # Clean up script inside WSL
            try:
                cleanup = await asyncio.create_subprocess_exec(
                    "wsl",
                    "-d",
                    self._distro,
                    "--",
                    "rm",
                    "-f",
                    wsl_script_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(cleanup.communicate(), timeout=5)
            except (asyncio.TimeoutError, OSError):
                pass

    async def stop(self) -> None:
        """Kill any running subprocess."""
        if self._process and self._process.returncode is None:
            try:
                self._process.kill()
            except (ProcessLookupError, OSError):
                pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()
