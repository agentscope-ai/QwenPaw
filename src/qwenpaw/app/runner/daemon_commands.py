# -*- coding: utf-8 -*-
"""Daemon command execution layer and DaemonCommandHandlerMixin.

Shared by in-chat /daemon <sub> and the CLI daemon command.
Logs: tail the project log file. Restart: in-process reload of channels,
cron and MCP (no process exit); works on Mac/Windows without a process manager.
"""
# pylint: disable=too-many-return-statements
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, TYPE_CHECKING

from agentscope.message import Msg, TextBlock

from ...constant import WORKING_DIR
from ...config import load_config
from ...utils.logging import LOG_NAMESPACE, LOG_FILE_PATH

if TYPE_CHECKING:
    from ...config.config import AgentProfileConfig
    from ..multi_agent_manager import MultiAgentManager

logger = logging.getLogger(__name__)


class RestartInProgressError(Exception):
    """Raised when /daemon restart is invoked while another restart runs."""


DAEMON_PREFIX = "/daemon"
DAEMON_SUBCOMMANDS = frozenset(
    {"status", "restart", "reload-config", "version", "logs", "approve"},
)
# Short names: /restart -> /daemon restart, etc.
DAEMON_SHORT_ALIASES = {
    "restart": "restart",
    "status": "status",
    "reload-config": "reload-config",
    "reload_config": "reload-config",
    "version": "version",
    "logs": "logs",
    "approve": "approve",
}

LOG_PATH = LOG_FILE_PATH


@dataclass
class DaemonContext:
    """Context for daemon commands (inject deps from runner or CLI)."""

    working_dir: Path = WORKING_DIR
    load_config_fn: Callable[[], Any] = load_config
    memory_manager: Optional[Any] = None
    context_manager: Optional[Any] = None
    # For /daemon restart: manager and agent_id for zero-downtime reload
    manager: Optional["MultiAgentManager"] = None
    agent_id: Optional[str] = None
    # Session ID for approval commands.
    session_id: str = ""


def _get_last_lines(
    path: Path,
    lines: int = 100,
    max_bytes: int = 512 * 1024,
) -> str:
    """Read last N lines from a text file (tail) with bounded memory.

    Reads at most max_bytes from the end of the file so large logs
    do not cause high memory usage or latency.
    """
    path = Path(path)
    if not path.exists() or not path.is_file():
        return f"(Log file not found: {path})"
    try:
        size = path.stat().st_size
        if size == 0:
            return "(empty)"
        with open(path, "rb") as f:
            if size <= max_bytes:
                content = f.read().decode("utf-8", errors="replace")
            else:
                f.seek(size - max_bytes)
                content = f.read().decode("utf-8", errors="replace")
                first_nl = content.find("\n")
                if first_nl != -1:
                    content = content[first_nl + 1 :]
                else:
                    content = ""
        all_lines = content.splitlines()
        last = all_lines[-lines:] if len(all_lines) > lines else all_lines
        return "\n".join(last) if last else "(empty)"
    except OSError as e:
        return f"(Error reading log: {e})"


def run_daemon_status(context: DaemonContext) -> str:
    """Return status text (health, config, memory_manager)."""
    parts = ["**Daemon Status**", ""]
    try:
        cfg = context.load_config_fn()
        parts.append("- Config loaded: yes")
        # Support both AgentProfileConfig (has 'running' directly)
        # and Config (has 'agents.running')
        if hasattr(cfg, "running"):
            max_in = getattr(cfg.running, "max_input_length", "N/A")
            parts.append(f"- Max input length: {max_in}")
        elif getattr(cfg, "agents", None) and getattr(
            cfg.agents,
            "running",
            None,
        ):
            max_in = getattr(cfg.agents.running, "max_input_length", "N/A")
            parts.append(f"- Max input length: {max_in}")
    except Exception as e:
        parts.append(f"- Config loaded: no ({e})")

    parts.append(f"- Working dir: {context.working_dir}")
    if context.memory_manager is not None:
        parts.append("- Memory manager: running")
    else:
        parts.append("- Memory manager: not attached")
    if context.context_manager is not None:
        parts.append("- Context manager: running")
    else:
        parts.append("- Context manager: not attached")
    return "\n".join(parts)


async def run_daemon_restart(context: DaemonContext) -> str:
    """Trigger zero-downtime agent reload or instruct user."""
    if context.manager is not None and context.agent_id is not None:
        try:
            success = await context.manager.reload_agent(context.agent_id)
            if success:
                return (
                    "**Restart completed**\n\n"
                    "- Agent reloaded with zero-downtime "
                    "(channels, cron, MCP)."
                )
            else:
                return (
                    "**Restart skipped**\n\n"
                    "- Agent not currently loaded. "
                    "Will reload on next request."
                )
        except Exception as e:
            return f"**Restart failed**\n\n- {e}"
    return (
        "**Restart**\n\n"
        "- Not running inside app. "
        f"Run the app (e.g. `{LOG_NAMESPACE} app`) "
        "and use /daemon restart in chat, "
        "or restart the process with systemd/supervisor/docker."
    )


def run_daemon_reload_config(context: DaemonContext) -> str:
    """Reload config (re-call load_config); no process restart."""
    try:
        context.load_config_fn()
        return (
            "**Config reloaded**\n\n- load_config() re-invoked successfully."
        )
    except Exception as e:
        return f"**Reload failed**\n\n- {e}"


def run_daemon_version(context: DaemonContext) -> str:
    """Return version and paths."""
    try:
        from ...__version__ import __version__ as ver
    except ImportError:
        ver = "unknown"
    return (
        f"**Daemon version**\n\n"
        f"- Version: {ver}\n"
        f"- Working dir: {context.working_dir}\n"
        f"- Log file: {LOG_PATH}"
    )


def run_daemon_logs(lines: int = 100) -> str:
    """Tail last N lines from the project log file."""
    log_path = LOG_PATH
    content = _get_last_lines(log_path, lines=lines)
    return f"**Console log (last {lines} lines)**\n\n```\n{content}\n```"


async def run_daemon_approve(
    _context: DaemonContext,
    session_id: str = "",
) -> str:
    """Resolve the next pending tool-guard approval for *session_id*.

    Called when the user sends ``/daemon approve`` in the chat while a
    tool-guard approval is pending.  The runner intercepts the message
    before it reaches this function in most cases, but this serves as
    a fallback and returns a helpful message when no approval is
    pending.
    """
    try:
        from ..approvals import get_approval_service
        from ...security.tool_guard.approval import ApprovalDecision

        svc = get_approval_service()
        pending = await svc.get_pending_by_session(session_id)
        if pending is None:
            return (
                "**No pending approval**\n\n"
                "- There is no tool-guard approval waiting for this "
                "session.\n"
                "- This command is only valid when a sensitive tool "
                "call is awaiting your review."
            )
        await svc.resolve_request(
            pending.request_id,
            ApprovalDecision.APPROVED,
        )
        return (
            f"**Tool execution approved** ✅\n\n"
            f"- Tool: `{pending.tool_name}`\n"
            f"- Request: `{pending.request_id[:8]}…`"
        )
    except Exception as exc:
        logger.warning("run_daemon_approve error: %s", exc, exc_info=True)
        return f"**Approve failed**\n\n- {exc}"


def parse_daemon_query(query: str) -> Optional[tuple[str, list[str]]]:
    """Parse /daemon <sub> or /<short>. Return (subcommand, args) or None."""
    if not query or not isinstance(query, str):
        return None
    raw = query.strip()
    if not raw.startswith("/"):
        return None
    rest = raw.lstrip("/").strip()
    if not rest:
        return None
    parts = rest.split()
    first = parts[0].lower() if parts else ""

    if first == "daemon":
        if len(parts) < 2:
            return ("status", [])
        sub = parts[1].lower().replace("_", "-")
        if sub not in DAEMON_SUBCOMMANDS and "reload" in sub:
            sub = "reload-config"
        if sub not in DAEMON_SUBCOMMANDS:
            return None
        args = parts[2:] if len(parts) > 2 else []
        return (sub, args)
    if first in DAEMON_SHORT_ALIASES:
        sub = DAEMON_SHORT_ALIASES[first]
        return (sub, parts[1:] if len(parts) > 1 else [])
    return None


class DaemonCommandHandlerMixin:
    """Mixin for daemon commands: /daemon status, restart, logs, etc."""

    def is_daemon_command(self, query: str | None) -> bool:
        """True if query is /daemon <sub> or short name (/restart, etc.)."""
        return parse_daemon_query(query or "") is not None

    async def handle_daemon_command(
        self,
        query: str,
        context: DaemonContext,
    ) -> Msg:
        """Run daemon subcommand; return a single assistant Msg."""
        parsed = parse_daemon_query(query)
        if not parsed:
            return Msg(
                name="Friday",
                role="assistant",
                content=[
                    TextBlock(type="text", text="Unknown daemon command."),
                ],
            )
        sub, args = parsed
        if sub == "status":
            text = run_daemon_status(context)
        elif sub == "restart":
            text = await run_daemon_restart(context)
        elif sub == "reload-config":
            text = run_daemon_reload_config(context)
        elif sub == "version":
            text = run_daemon_version(context)
        elif sub == "logs":
            n = 100
            for a in args:
                if a.isdigit():
                    n = max(1, min(int(a), 2000))
                    break
            text = run_daemon_logs(lines=n)
        elif sub == "approve":
            session_id = getattr(context, "session_id", "") or ""
            text = await run_daemon_approve(context, session_id=session_id)
        else:
            text = "Unknown daemon subcommand."
        logger.info("handle_daemon_command %s completed", query)
        return Msg(
            name="Friday",
            role="assistant",
            content=[TextBlock(type="text", text=text)],
        )
