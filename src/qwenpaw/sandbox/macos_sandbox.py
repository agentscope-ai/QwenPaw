# -*- coding: utf-8 -*-
"""macOS Seatbelt sandbox implementation.

Uses ``sandbox-exec`` (the Seatbelt profile language) to construct a
deny-default filesystem + network policy for command isolation.

Architecture:
    - Parent process compiles a Seatbelt ``.sb`` profile from
      ``SandboxConfig``.
    - ``sandbox-exec -p '<profile>' <shell> -c '<cmd>'`` enforces the
      policy in-kernel while exec'ing the user command.
    - The parent waits for completion and captures stdout/stderr.

Reference:
    https://developer.apple.com/library/archive/documentation/Security/Conceptual/SeatBeltBook/SeatBeltBook.html
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Optional

from .config import ExecutionResult
from .local_sandbox import LocalSandbox

logger = logging.getLogger(__name__)

# Seatbelt violation patterns. Substring matching against generic words
# like ``"deny"`` or ``"sandbox"`` is far too lossy — application logs
# routinely contain those tokens and would be mis-flagged as sandbox
# violations. Match the actual diagnostic shapes emitted by
# ``sandbox-exec`` / the Seatbelt kernel:
#   - ``deny(1) file-read-data ...``  / ``deny(1) network-outbound ...``
#   - ``Sandbox: <bin>(<pid>) deny(1) ...``
#   - ``sandbox-exec: <error message>``
#   - ``Operation not permitted`` (full phrase, case-insensitive)
# TODO: this remains a heuristic. A robust solution would be to read
#   structured violation events via Endpoint Security or an audit log
#   stream rather than scraping stderr.
_SEATBELT_VIOLATION_RE = re.compile(
    r"\bdeny\(\d+\)"  # `deny(1)`, `deny(2)` ...
    r"|^Sandbox:\s"  # macOS kernel violation line prefix
    r"|^sandbox-exec:\s"  # sandbox-exec error prefix
    r"|\bOperation not permitted\b",
    re.IGNORECASE | re.MULTILINE,
)


class MacOSSandbox(LocalSandbox):
    """macOS sandbox using sandbox-exec (Seatbelt profiles).

    deny-default whitelist model:
      - Basic system paths are read-only (/System, /usr/lib, /usr/share,
        /Library, /dev)
      - workspace_dir is read-write
      - Paths declared in mounts are ro/rw based on ``writable``
      - Network access is governed by ``network_allow``
      - Sensitive paths such as ~/.ssh are explicitly denied
    """

    @staticmethod
    def _sanitize_seatbelt_path(path: str) -> str:
        """Sanitize a filesystem path for safe embedding in a Seatbelt profile.

        Prevents Seatbelt rule injection by escaping characters that could
        break out of the S-expression string literal (double-quote,
        backslash, newlines, and parentheses).

        Raises:
            ValueError: if the path contains control characters other than
                common whitespace (tab).
        """
        # Reject newlines — no valid filesystem path contains them and they
        # can break the profile grammar.
        if "\n" in path or "\r" in path:
            raise ValueError(
                "Seatbelt path contains newlines "
                f"(possible injection): {path!r}",
            )
        # Escape backslash first (order matters), then double-quote.
        path = path.replace("\\", "\\\\")
        path = path.replace('"', '\\"')
        return path

    def _compile_seatbelt_profile(  # noqa: E501  pylint: disable=too-many-branches,too-many-statements
        self,
    ) -> str:
        """Build the Seatbelt .sb policy string."""
        config = self._config
        _san = self._sanitize_seatbelt_path  # shorthand
        lines = [
            "(version 1)",
            "",
            "(deny default)",
            "",
            "; Basic system operations",
            "(allow process-exec*)",
            "(allow process-fork)",
            "(allow signal)",
            "(allow sysctl-read)",
            "",
            "; System file access (readonly)",
            "(allow file-read*",
            '  (subpath "/System")',
            '  (subpath "/usr/lib")',
            '  (subpath "/usr/share")',
            '  (subpath "/Library")',
            '  (subpath "/private/var/db/timezone")',
            '  (literal "/dev/null")',
            '  (literal "/dev/zero")',
            '  (literal "/dev/random")',
            '  (literal "/dev/urandom")',
            '  (literal "/dev/tty")',
            '  (literal "/dev/dtracehelper")',
            ")",
            "",
            "; Mach operations",
            "(allow mach-lookup)",
            "(allow ipc-posix-shm)",
            "",
            "; Sysctl operations",
            "(allow sysctl-read",
            '  (sysctl-name-prefix "hw.")',
            '  (sysctl-name-prefix "kern.")',
            '  (sysctl-name-prefix "machdep.cpu.")',
            ")",
        ]

        # Network
        lines.append("")
        lines.append("; Network")
        if config.network_allow and ("*" in config.network_allow):
            lines.append(
                "; WARNING: Domain-level filtering not implemented",
            )
            domains = [d for d in config.network_allow if d != "*"]
            if domains:
                lines.append(
                    "; The following domains are in allowedDomains "
                    "but not enforced:",
                )
                for d in domains:
                    lines.append(f";   - {d}")
            lines.append("; All network access is allowed")
            lines.append("(allow network*)")
        elif config.network_allow:
            lines.append(
                "; Partial network (domain filtering not enforceable)",
            )
            lines.append("(allow network*)")
        else:
            lines.append("(deny network*)")

        # File read paths
        lines.append("")
        lines.append("; File read")
        if config.allow_read_all:
            # deny-list mode: allow reading everything, then deny
            # specific paths
            lines.append("(allow file-read*)")
        else:
            # allow-list mode: only allow reading declared mounts
            for mount in config.mounts:
                lines.append("(allow file-read*")
                lines.append(f'  (subpath "{_san(mount.path)}")')

        # Deny sensitive paths (read + write)
        if config.deny_paths:
            lines.append("")
            lines.append("; Denied sensitive paths")
            for p in config.deny_paths:
                expanded = _san(os.path.expanduser(p))
                lines.append("(deny file-read*")
                lines.append(f'  (subpath "{expanded}")')
                lines.append("(deny file-write*")
                lines.append(f'  (subpath "{expanded}")')

        # File write paths (whitelist)
        lines.append("")
        lines.append("; File write")
        # Always allow /dev/null, /dev/zero, /dev/tty, /tmp
        write_always = [
            "/dev/null",
            "/dev/zero",
            "/dev/tty",
            "/tmp",
            "/private/tmp",
        ]
        for p in write_always:
            lines.append("(allow file-write*")
            lines.append(f'  (subpath "{p}"))')

        # Workspace and explicit mounts
        for mount in config.mounts:
            if mount.writable:
                lines.append("(allow file-write*")
                lines.append(f'  (subpath "{_san(mount.path)}")')

        # Executable control
        non_exec_mounts = [m for m in config.mounts if not m.executable]
        if non_exec_mounts:
            lines.append("")
            lines.append("; Deny execution in specific paths")
            for mount in non_exec_mounts:
                lines.append("(deny process-exec*")
                lines.append(f'  (subpath "{_san(mount.path)}")')

        # Platform hints: extra seatbelt rules
        # WARNING: seatbelt_extra_rules is an ADMIN-ONLY escape hatch.
        # Content is embedded verbatim — it MUST NOT come from user input
        # or untrusted approval flows.
        extra_rules = config.platform_hints.get("seatbelt_extra_rules")
        if extra_rules:
            if "\n" in str(extra_rules):
                logger.warning(
                    "MacOSSandbox: seatbelt_extra_rules contains newlines; "
                    "verify this is from a trusted admin source.",
                )
            lines.append("")
            lines.append(
                "; Platform hints: extra rules (admin-only, verbatim)",
            )
            lines.append(str(extra_rules))

        # Log warnings for unsupported features on macOS
        if config.max_processes is not None:
            logger.warning(
                "MacOSSandbox: max_processes=%d is not supported by "
                "Seatbelt; ignoring.",
                config.max_processes,
            )
        if config.max_memory_mb is not None:
            logger.warning(
                "MacOSSandbox: max_memory_mb=%d is not supported by "
                "Seatbelt; ignoring.",
                config.max_memory_mb,
            )
        if config.network_ports:
            logger.warning(
                "MacOSSandbox: network_ports (port-level filtering) is not "
                "supported by Seatbelt; ignoring.",
            )

        return "\n".join(lines)

    async def execute(
        self,
        cmd: str,
        cwd: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute via ``sandbox-exec -p '<profile>' /bin/bash -c '<cmd>'``."""
        profile = self._compile_seatbelt_profile()
        cwd = cwd or self._config.workspace_dir

        # Find shell
        shell = os.environ.get("SHELL", "/bin/bash")
        if not os.path.exists(shell):
            shell = "/bin/bash"

        # Build subprocess env: inherit + apply env_vars (overrides)
        env = dict(os.environ)
        if self._config.env_vars:
            env.update(self._config.env_vars)

        start = time.monotonic()
        try:
            self._process = await asyncio.create_subprocess_exec(
                "sandbox-exec",
                "-p",
                profile,
                shell,
                "-c",
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                start_new_session=True,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                self._process.communicate(),
                timeout=self._config.timeout_seconds,
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            # Detect sandbox violation from stderr.
            # Use precise regex against Seatbelt's actual diagnostic
            # shapes so legitimate application output containing
            # tokens like "deny" or "sandbox" is not mis-flagged.
            violation = None
            if (
                self._process.returncode != 0
                and _SEATBELT_VIOLATION_RE.search(stderr)
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
