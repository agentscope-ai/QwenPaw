# -*- coding: utf-8 -*-
"""Linux Landlock sandbox implementation.

Uses Landlock LSM (Linux 5.13+) for kernel-level filesystem isolation.
Network restrictions require Landlock ABI v4 (kernel 6.7+).

Architecture:
    - Parent process compiles Landlock rules from SandboxConfig
    - Forks a child process that applies Landlock restrictions before exec
    - Child: prctl(PR_SET_NO_NEW_PRIVS) → create_ruleset → add_rules → restrict_self → exec

Reference:
    https://docs.kernel.org/userspace-api/landlock.html
"""
from __future__ import annotations

import asyncio
import ctypes
import ctypes.util
import logging
import os
import signal
import struct
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

from .config import ExecutionResult, MountSpec, PortRule, SandboxConfig, SandboxMode

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# Landlock constants and syscall numbers
# ═══════════════════════════════════════════════════════════════════════════════

# Syscall numbers (x86_64 and aarch64 share the same numbers for Landlock)
SYS_LANDLOCK_CREATE_RULESET = 444
SYS_LANDLOCK_ADD_RULE = 445
SYS_LANDLOCK_RESTRICT_SELF = 446

# prctl constants
PR_SET_NO_NEW_PRIVS = 38

# landlock_create_ruleset flags
LANDLOCK_CREATE_RULESET_VERSION = 1 << 0

# Rule types
LANDLOCK_RULE_PATH_BENEATH = 1
LANDLOCK_RULE_NET_PORT = 2  # ABI v4+

# Filesystem access rights (ABI v1)
LANDLOCK_ACCESS_FS_EXECUTE = 1 << 0
LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
LANDLOCK_ACCESS_FS_READ_FILE = 1 << 2
LANDLOCK_ACCESS_FS_READ_DIR = 1 << 3
LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
LANDLOCK_ACCESS_FS_MAKE_CHAR = 1 << 6
LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
LANDLOCK_ACCESS_FS_MAKE_BLOCK = 1 << 11
LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12

# ABI v2 additions
LANDLOCK_ACCESS_FS_REFER = 1 << 13

# ABI v3 additions
LANDLOCK_ACCESS_FS_TRUNCATE = 1 << 14

# Network access rights (ABI v4)
LANDLOCK_ACCESS_NET_BIND_TCP = 1 << 0
LANDLOCK_ACCESS_NET_CONNECT_TCP = 1 << 1

# Composite access masks
_FS_READ_ACCESS = (
    LANDLOCK_ACCESS_FS_READ_FILE
    | LANDLOCK_ACCESS_FS_READ_DIR
)

_FS_WRITE_ACCESS = (
    LANDLOCK_ACCESS_FS_WRITE_FILE
    | LANDLOCK_ACCESS_FS_REMOVE_DIR
    | LANDLOCK_ACCESS_FS_REMOVE_FILE
    | LANDLOCK_ACCESS_FS_MAKE_CHAR
    | LANDLOCK_ACCESS_FS_MAKE_DIR
    | LANDLOCK_ACCESS_FS_MAKE_REG
    | LANDLOCK_ACCESS_FS_MAKE_SOCK
    | LANDLOCK_ACCESS_FS_MAKE_FIFO
    | LANDLOCK_ACCESS_FS_MAKE_BLOCK
    | LANDLOCK_ACCESS_FS_MAKE_SYM
)

_FS_EXEC_ACCESS = LANDLOCK_ACCESS_FS_EXECUTE

# All filesystem access rights for ABI v1
_FS_ALL_ACCESS_V1 = _FS_READ_ACCESS | _FS_WRITE_ACCESS | _FS_EXEC_ACCESS


def _get_all_fs_access(abi_version: int) -> int:
    """Get all filesystem access rights supported by the given ABI version."""
    access = _FS_ALL_ACCESS_V1
    if abi_version >= 2:
        access |= LANDLOCK_ACCESS_FS_REFER
    if abi_version >= 3:
        access |= LANDLOCK_ACCESS_FS_TRUNCATE
    return access


# ═══════════════════════════════════════════════════════════════════════════════
# Landlock syscall wrappers
# ═══════════════════════════════════════════════════════════════════════════════


def _get_libc():
    """Get libc with syscall function configured."""
    lib_name = ctypes.util.find_library("c") or "libc.so.6"
    libc = ctypes.CDLL(lib_name, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    return libc


def _landlock_create_ruleset(
    libc, handled_access_fs: int, handled_access_net: int = 0, abi_version: int = 1,
) -> int:
    """Create a Landlock ruleset and return its fd.

    Args:
        handled_access_fs: Bitmask of filesystem access rights to handle.
        handled_access_net: Bitmask of network access rights (ABI v4+).
        abi_version: Detected ABI version.

    Returns:
        File descriptor for the ruleset.

    Raises:
        OSError: If the syscall fails.
    """
    # struct landlock_ruleset_attr for ABI v1-v3 (only handled_access_fs)
    if abi_version >= 4 and handled_access_net:
        # ABI v4: struct has handled_access_fs (u64) + handled_access_net (u64)
        attr = struct.pack("QQ", handled_access_fs, handled_access_net)
    else:
        # ABI v1-v3: struct has only handled_access_fs (u64)
        attr = struct.pack("Q", handled_access_fs)

    attr_buf = ctypes.create_string_buffer(attr)
    fd = libc.syscall(
        ctypes.c_long(SYS_LANDLOCK_CREATE_RULESET),
        ctypes.cast(attr_buf, ctypes.c_void_p),
        ctypes.c_size_t(len(attr)),
        ctypes.c_uint32(0),  # flags = 0 (create, not query version)
    )
    if fd < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, f"landlock_create_ruleset failed: errno={errno}")
    return fd


def _landlock_add_path_rule(libc, ruleset_fd: int, path: str, access: int) -> None:
    """Add a path-beneath rule to the ruleset.

    Args:
        ruleset_fd: Ruleset file descriptor.
        path: Filesystem path to allow access to.
        access: Bitmask of allowed access rights.
    """
    # Open the path to get an fd (O_PATH for minimal permissions)
    O_PATH = 0o10000000  # 010000000 octal
    path_fd = os.open(path, O_PATH | os.O_CLOEXEC)
    try:
        # struct landlock_path_beneath_attr { u64 allowed_access; s32 parent_fd; }
        # Pack as u64 + i32 + 4 bytes padding (struct alignment)
        attr = struct.pack("Qi", access, path_fd)
        attr_buf = ctypes.create_string_buffer(attr)
        ret = libc.syscall(
            ctypes.c_long(SYS_LANDLOCK_ADD_RULE),
            ctypes.c_int(ruleset_fd),
            ctypes.c_int(LANDLOCK_RULE_PATH_BENEATH),
            ctypes.cast(attr_buf, ctypes.c_void_p),
            ctypes.c_uint32(0),  # flags
        )
        if ret < 0:
            errno = ctypes.get_errno()
            logger.warning(
                "landlock_add_rule(path=%s) failed: errno=%d", path, errno
            )
    finally:
        os.close(path_fd)


def _landlock_add_net_port_rule(
    libc, ruleset_fd: int, port: int, access: int,
) -> None:
    """Add a network port rule to the ruleset (ABI v4+).

    Args:
        ruleset_fd: Ruleset file descriptor.
        port: TCP port number.
        access: Bitmask of allowed network access rights.
    """
    # struct landlock_net_port_attr { u64 allowed_access; u64 port; }
    attr = struct.pack("QQ", access, port)
    attr_buf = ctypes.create_string_buffer(attr)
    ret = libc.syscall(
        ctypes.c_long(SYS_LANDLOCK_ADD_RULE),
        ctypes.c_int(ruleset_fd),
        ctypes.c_int(LANDLOCK_RULE_NET_PORT),
        ctypes.cast(attr_buf, ctypes.c_void_p),
        ctypes.c_uint32(0),  # flags
    )
    if ret < 0:
        errno = ctypes.get_errno()
        logger.warning(
            "landlock_add_rule(net_port=%d) failed: errno=%d", port, errno
        )


def _landlock_restrict_self(libc, ruleset_fd: int) -> None:
    """Apply Landlock restrictions to the current process.

    Raises:
        OSError: If the syscall fails.
    """
    ret = libc.syscall(
        ctypes.c_long(SYS_LANDLOCK_RESTRICT_SELF),
        ctypes.c_int(ruleset_fd),
        ctypes.c_uint32(0),  # flags
    )
    if ret < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, f"landlock_restrict_self failed: errno={errno}")


def _prctl_set_no_new_privs(libc) -> None:
    """Set PR_SET_NO_NEW_PRIVS (required before landlock_restrict_self)."""
    libc.prctl.restype = ctypes.c_int
    libc.prctl.argtypes = [
        ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
        ctypes.c_ulong, ctypes.c_ulong,
    ]
    ret = libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)
    if ret != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, f"prctl(PR_SET_NO_NEW_PRIVS) failed: errno={errno}")


# ═══════════════════════════════════════════════════════════════════════════════
# Helper: Generate the sandbox wrapper script
# ═══════════════════════════════════════════════════════════════════════════════


def _generate_sandbox_script(
    config: SandboxConfig,
    cmd: str,
    cwd: str,
    abi_version: int,
) -> str:
    """Generate a Python script that applies Landlock and execs the command.

    This script is executed in the child process. It:
    1. Calls prctl(PR_SET_NO_NEW_PRIVS)
    2. Creates a Landlock ruleset
    3. Adds path rules based on SandboxConfig
    4. Restricts itself
    5. Execs the shell command
    """
    # Compute access rights for the ruleset
    handled_fs = _get_all_fs_access(abi_version)

    # Build path rules: list of (path, access_mask)
    path_rules: List[Tuple[str, int]] = []

    # System paths (always readable)
    system_read_paths = [
        "/usr", "/lib", "/lib64", "/etc", "/proc", "/sys",
        "/dev", "/run", "/bin", "/sbin",
    ]
    for sp in system_read_paths:
        if os.path.exists(sp):
            path_rules.append((sp, _FS_READ_ACCESS | _FS_EXEC_ACCESS))

    # /tmp always writable (many tools need it)
    if os.path.exists("/tmp"):
        path_rules.append(("/tmp", _FS_READ_ACCESS | _FS_WRITE_ACCESS | _FS_EXEC_ACCESS))

    # Mounts from config
    for mount in config.mounts:
        if not os.path.exists(mount.path):
            continue
        access = _FS_READ_ACCESS
        if mount.writable:
            access |= _FS_WRITE_ACCESS
            if abi_version >= 3:
                access |= LANDLOCK_ACCESS_FS_TRUNCATE
            if abi_version >= 2:
                access |= LANDLOCK_ACCESS_FS_REFER
        if mount.executable:
            access |= _FS_EXEC_ACCESS
        path_rules.append((mount.path, access))

    # allow_read_all mode:
    # On Linux Landlock (whitelist model), granting "/" would make deny_paths ineffective
    # because there's no way to revoke access for subdirectories once parent is granted.
    # Strategy: grant system paths (done above) + enumerate HOME subdirs individually,
    # SKIPPING deny_paths entries to achieve effective read-deny.
    if config.allow_read_all:
        deny_expanded = set()
        for dp in (config.deny_paths or []):
            deny_expanded.add(os.path.expanduser(dp))

        if deny_expanded:
            # Selective granting: grant common top-level paths individually
            # (system paths /usr, /lib, etc. already granted above)
            extra_system_paths = ["/opt", "/var", "/srv", "/mnt", "/media", "/home"]
            home = os.path.expanduser("~")

            for sp in extra_system_paths:
                if not os.path.exists(sp):
                    continue
                # If this path IS home's parent (e.g. /home), handle specially
                if home.startswith(sp + "/") or sp == home:
                    continue  # Will handle home separately below
                # If any deny_path is under this path, skip it (shouldn't happen
                # since deny_paths are all under ~, but just in case)
                if any(dp.startswith(sp + "/") for dp in deny_expanded):
                    continue
                path_rules.append((sp, _FS_READ_ACCESS | _FS_EXEC_ACCESS))

            # Handle HOME: enumerate direct children, skip deny_paths
            if os.path.isdir(home):
                try:
                    for entry in os.listdir(home):
                        full_path = os.path.join(home, entry)
                        # Skip if this entry IS a deny_path
                        if full_path in deny_expanded:
                            continue
                        # Skip if any deny_path is nested under this entry
                        has_nested_deny = any(
                            dp.startswith(full_path + "/") for dp in deny_expanded
                        )
                        if has_nested_deny:
                            # Enumerate one level deeper, excluding deny_paths
                            if os.path.isdir(full_path):
                                try:
                                    for sub_entry in os.listdir(full_path):
                                        sub_path = os.path.join(full_path, sub_entry)
                                        if sub_path not in deny_expanded:
                                            path_rules.append((sub_path, _FS_READ_ACCESS))
                                except OSError:
                                    pass
                        else:
                            path_rules.append((full_path, _FS_READ_ACCESS))
                except OSError:
                    logger.warning(
                        "LinuxSandbox: failed to enumerate HOME %s; "
                        "falling back to granting root",
                        home,
                    )
                    path_rules.append(("/", _FS_READ_ACCESS | _FS_EXEC_ACCESS))
        else:
            # No deny_paths: safe to grant everything
            path_rules.append(("/", _FS_READ_ACCESS | _FS_EXEC_ACCESS))
    elif not config.allow_read_all:
        # Strict mode: only system paths + workspace (from mounts above) are readable.
        # No HOME enumeration — truly whitelist-only.
        pass

    # Network rules (ABI v4+)
    handled_net = 0
    net_port_rules: List[Tuple[int, int]] = []
    if abi_version >= 4:
        if not config.network_allow or config.network_allow == []:
            # No network: handle all net access but add no rules → all denied
            handled_net = LANDLOCK_ACCESS_NET_BIND_TCP | LANDLOCK_ACCESS_NET_CONNECT_TCP
        elif "*" in config.network_allow:
            # All network allowed: don't handle network at all
            handled_net = 0
        else:
            # Partial: domain filtering not possible in Landlock, allow all
            # (Landlock only supports port-level, not domain-level)
            handled_net = 0
            logger.warning(
                "LinuxSandbox: domain-level network filtering not supported "
                "by Landlock. Allowing all network access."
            )

        # Port-level rules
        if config.network_ports and handled_net:
            for port_rule in config.network_ports:
                access = 0
                if port_rule.direction == "connect" and port_rule.allow:
                    access = LANDLOCK_ACCESS_NET_CONNECT_TCP
                elif port_rule.direction == "bind" and port_rule.allow:
                    access = LANDLOCK_ACCESS_NET_BIND_TCP
                if access:
                    net_port_rules.append((port_rule.port, access))

    # Log unsupported features
    if config.max_processes is not None:
        logger.warning(
            "LinuxSandbox: max_processes=%d requires cgroups, not implemented; ignoring.",
            config.max_processes,
        )
    if config.max_memory_mb is not None:
        logger.warning(
            "LinuxSandbox: max_memory_mb=%d requires cgroups, not implemented; ignoring.",
            config.max_memory_mb,
        )

    # Generate the Python enforcement script
    script_lines = [
        "import ctypes, ctypes.util, os, struct, sys",
        "",
        "libc = ctypes.CDLL(ctypes.util.find_library('c') or 'libc.so.6', use_errno=True)",
        "libc.syscall.restype = ctypes.c_long",
        "",
        "# prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)",
        "libc.prctl.restype = ctypes.c_int",
        "libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]",
        f"assert libc.prctl({PR_SET_NO_NEW_PRIVS}, 1, 0, 0, 0) == 0, 'prctl failed'",
        "",
        f"# Create ruleset (handled_fs=0x{handled_fs:x}, handled_net=0x{handled_net:x})",
    ]

    if handled_net:
        script_lines.append(f"attr = struct.pack('QQ', 0x{handled_fs:x}, 0x{handled_net:x})")
    else:
        script_lines.append(f"attr = struct.pack('Q', 0x{handled_fs:x})")

    script_lines += [
        "attr_buf = ctypes.create_string_buffer(attr)",
        f"fd = libc.syscall(ctypes.c_long({SYS_LANDLOCK_CREATE_RULESET}), "
        "ctypes.cast(attr_buf, ctypes.c_void_p), ctypes.c_size_t(len(attr)), ctypes.c_uint32(0))",
        "assert fd >= 0, f'create_ruleset failed: {{ctypes.get_errno()}}'",
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
        f"        libc.syscall(ctypes.c_long({SYS_LANDLOCK_ADD_RULE}), ctypes.c_int(fd), "
        f"ctypes.c_int({LANDLOCK_RULE_PATH_BENEATH}), ctypes.cast(ab, ctypes.c_void_p), ctypes.c_uint32(0))",
        "    finally:",
        "        os.close(pfd)",
        "",
    ]

    # Add path rules
    for path, access in path_rules:
        # Skip deny_paths
        skip = False
        if config.deny_paths:
            for dp in config.deny_paths:
                expanded = os.path.expanduser(dp)
                if path == expanded or path.startswith(expanded + "/"):
                    skip = True
                    break
        if not skip:
            script_lines.append(f"add_path({path!r}, 0x{access:x})")

    # Add network port rules if applicable
    if net_port_rules:
        script_lines += [
            "",
            "def add_net_port(port, access):",
            "    a = struct.pack('QQ', access, port)",
            "    ab = ctypes.create_string_buffer(a)",
            f"    libc.syscall(ctypes.c_long({SYS_LANDLOCK_ADD_RULE}), ctypes.c_int(fd), "
            f"ctypes.c_int({LANDLOCK_RULE_NET_PORT}), ctypes.cast(ab, ctypes.c_void_p), ctypes.c_uint32(0))",
            "",
        ]
        for port, access in net_port_rules:
            script_lines.append(f"add_net_port({port}, 0x{access:x})")

    # Restrict self and exec
    script_lines += [
        "",
        "# Restrict self",
        f"ret = libc.syscall(ctypes.c_long({SYS_LANDLOCK_RESTRICT_SELF}), "
        "ctypes.c_int(fd), ctypes.c_uint32(0))",
        "os.close(fd)",
        "assert ret == 0, f'restrict_self failed: {ctypes.get_errno()}'",
        "",
        "# Exec the command",
        f"os.chdir({cwd!r})",
        f"os.execvp('/bin/sh', ['/bin/sh', '-c', {cmd!r}])",
    ]

    return "\n".join(script_lines)


# ═══════════════════════════════════════════════════════════════════════════════
# LinuxSandbox class
# ═══════════════════════════════════════════════════════════════════════════════


class LinuxSandbox:
    """Linux Landlock sandbox.

    Uses Landlock LSM (Linux 5.13+) to enforce filesystem isolation.
    The sandbox forks a child process that applies Landlock restrictions
    before exec'ing the target command.

    deny-default whitelist model:
      - System paths (/usr, /lib, /etc, /proc, /sys, /dev) readonly + exec
      - /tmp writable
      - config.mounts paths with declared permissions
      - allow_read_all=True → "/" readable
      - network controlled via ABI v4 (if available)
    """

    def __init__(self, config: SandboxConfig):
        self._config = config
        self._process: Optional[asyncio.subprocess.Process] = None
        self._abi_version = self._detect_abi_version()

    @property
    def config(self) -> SandboxConfig:
        return self._config

    def _detect_abi_version(self) -> int:
        """Detect Landlock ABI version via syscall probe."""
        try:
            libc = _get_libc()
            libc.syscall.argtypes = [
                ctypes.c_long, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32,
            ]
            abi = libc.syscall(
                ctypes.c_long(SYS_LANDLOCK_CREATE_RULESET),
                None,
                ctypes.c_size_t(0),
                ctypes.c_uint32(LANDLOCK_CREATE_RULESET_VERSION),
            )
            if abi < 0:
                return 1  # Fallback: assume v1 if kernel + LSM check passed
            return int(abi)
        except (OSError, AttributeError):
            return 1

    async def execute(self, cmd: str, cwd: Optional[str] = None) -> ExecutionResult:
        """Execute a command inside the Landlock sandbox.

        Implementation:
            1. Generate a Python script that applies Landlock rules then execs
            2. Run it as a subprocess
            3. Capture stdout/stderr and detect violations
        """
        cwd = cwd or self._config.workspace_dir
        if not os.path.isdir(cwd):
            cwd = self._config.workspace_dir

        start = time.monotonic()

        # Generate the enforcement script
        script = _generate_sandbox_script(
            self._config, cmd, cwd, self._abi_version,
        )

        # Write script to a temp file (in /tmp which is always accessible)
        script_fd, script_path = tempfile.mkstemp(
            prefix="landlock_", suffix=".py", dir="/tmp",
        )
        try:
            os.write(script_fd, script.encode("utf-8"))
            os.close(script_fd)
            os.chmod(script_path, 0o755)

            # Find python3
            python = sys.executable or "/usr/bin/python3"
            if not os.path.exists(python):
                python = "/usr/bin/python3"

            try:
                self._process = await asyncio.create_subprocess_exec(
                    python, script_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    start_new_session=True,
                )
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    self._process.communicate(),
                    timeout=self._config.timeout_seconds,
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                stdout = stdout_bytes.decode("utf-8", errors="replace")
                stderr = stderr_bytes.decode("utf-8", errors="replace")

                # Detect sandbox violation from stderr
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
            # Clean up the script file
            try:
                os.unlink(script_path)
            except OSError:
                pass

    async def stop(self) -> None:
        """Kill any running subprocess."""
        if self._process and self._process.returncode is None:
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()
