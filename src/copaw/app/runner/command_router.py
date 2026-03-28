# -*- coding: utf-8 -*-
"""CommandRouter: agent-layer unified command dispatcher.

Defines priority enum, queue payload wrapper, and command context
used by the dual-queue messaging architecture.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, TYPE_CHECKING

from agentscope.message import Msg, TextBlock

from .daemon_commands import (
    DaemonContext,
    DAEMON_SUBCOMMANDS,
    run_daemon_approve,
    run_daemon_logs,
    run_daemon_reload_config,
    run_daemon_restart,
    run_daemon_status,
    run_daemon_version,
)
from ...agents.command_handler import CommandHandler as ConvCommandHandler

if TYPE_CHECKING:
    from ..channels.base import BaseChannel
    from .task_tracker import TaskTracker
    from .runner import AgentRunner

logger = logging.getLogger(__name__)


class CommandPriority(IntEnum):
    """Command priority — lower value means higher priority."""

    CRITICAL = 0  # /stop
    HIGH = 1  # /approve
    NORMAL = 2  # /restart, /reload-config, /new, /clear
    LOW = 3  # /status, /version, /logs, /compact, /history, ...


@dataclass(order=True)
class PrioritizedPayload:
    """Priority wrapper stored in the per-channel CommandQueue.

    ``dataclass(order=True)`` sorts by (priority, sequence).
    Fields marked ``compare=False`` are excluded from ordering so that
    non-comparable payloads never cause a ``TypeError``.
    """

    priority: int
    sequence: int
    payload: Any = field(compare=False)
    command_name: str = field(compare=False)
    command_args: list[str] = field(default_factory=list, compare=False)


@dataclass
class CommandContext:
    """Unified context passed to every command handler."""

    channel: BaseChannel
    channel_id: str
    session_id: str
    user_id: str
    command_name: str
    command_args: list[str]
    raw_query: str
    payload: Any
    task_tracker: TaskTracker | None
    runner: AgentRunner | None


# Type alias for command handler functions.
CommandHandler = Callable[[CommandContext], Awaitable[Msg]]


class CommandRouter:
    """Agent-layer unified command dispatcher.

    Maintains a registry mapping command names to async handler functions
    and their priorities.  ``dispatch`` looks up the registry and calls
    the matching handler; unknown commands get a hint response, and
    handler exceptions are caught and returned as error messages.
    """

    def __init__(
        self,
        task_tracker: TaskTracker | None = None,
        runner: AgentRunner | None = None,
        channel_manager: Any = None,
    ) -> None:
        self._registry: dict[str, tuple[CommandHandler, CommandPriority]] = {}
        self._task_tracker = task_tracker
        self._runner = runner
        self._channel_manager = channel_manager
        self._register_builtins()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_command(
        self,
        name: str,
        handler: CommandHandler,
        priority: CommandPriority = CommandPriority.NORMAL,
    ) -> None:
        """Register a command handler with its priority.

        Args:
            name: Command name without the leading ``/`` (e.g. ``"stop"``).
            handler: Async callable ``(CommandContext) -> Msg``.
            priority: Processing priority (default ``NORMAL``).
        """
        self._registry[name] = (handler, priority)

    def get_priority(self, command_name: str) -> CommandPriority:
        """Return the priority for *command_name*.

        Falls back to ``NORMAL`` for unregistered commands.
        """
        entry = self._registry.get(command_name)
        if entry is not None:
            return entry[1]
        return CommandPriority.NORMAL

    def get_registered_commands(self) -> frozenset[str]:
        """Return the set of all registered command names."""
        return frozenset(self._registry.keys())

    async def dispatch(self, context: CommandContext) -> Msg:
        """Look up *context.command_name* and invoke its handler.

        * Known command → call handler, return its ``Msg``.
        * Unknown command → return a hint ``Msg``.
        * Handler exception → return an error ``Msg`` (never propagates).
        """
        entry = self._registry.get(context.command_name)
        if entry is None:
            return Msg(
                name="Friday",
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text=f"Unknown command: /{context.command_name}",
                    ),
                ],
            )

        handler, _priority = entry
        try:
            return await handler(context)
        except Exception:
            logger.exception(
                "Command handler error: /%s", context.command_name,
            )
            return Msg(
                name="Friday",
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error executing /{context.command_name}: "
                            "an internal error occurred."
                        ),
                    ),
                ],
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _register_builtins(self) -> None:
        """Register all built-in daemon and conversation command handlers."""
        # -- /stop (CRITICAL) ------------------------------------------
        async def _handle_stop(ctx: CommandContext) -> Msg:
            stopped = False

            # 1. Try TaskTracker (console channel uses this)
            if ctx.task_tracker and not stopped:
                run_key = ctx.channel.get_debounce_key(ctx.payload)
                stopped = await ctx.task_tracker.request_stop(run_key)

            # 2. Try cancelling active process task in ChannelManager
            #    (non-console channels like QQ, DingTalk use this path)
            if not stopped and self._channel_manager is not None:
                key = ctx.channel.get_debounce_key(ctx.payload)
                active_tasks = getattr(
                    self._channel_manager, "_active_process_tasks", {},
                )
                active = active_tasks.get((ctx.channel_id, key))
                if active and not active.done():
                    active.cancel()
                    stopped = True
                    logger.info(
                        "/stop cancelled active process task: "
                        "channel=%s key=%s",
                        ctx.channel_id, key,
                    )

            text = "Task stopped." if stopped else "No running task."
            return Msg(
                name="Friday",
                role="assistant",
                content=[TextBlock(type="text", text=text)],
            )

        self.register_command("stop", _handle_stop, CommandPriority.CRITICAL)

        # -- /approve (HIGH) -------------------------------------------
        async def _handle_approve(ctx: CommandContext) -> Msg:
            dc = self._build_daemon_context(ctx)
            text = await run_daemon_approve(dc, session_id=ctx.session_id)
            return Msg(
                name="Friday",
                role="assistant",
                content=[TextBlock(type="text", text=text)],
            )

        self.register_command("approve", _handle_approve, CommandPriority.HIGH)

        # -- /restart (NORMAL) -----------------------------------------
        async def _handle_restart(ctx: CommandContext) -> Msg:
            dc = self._build_daemon_context(ctx)
            text = await run_daemon_restart(dc)
            return Msg(
                name="Friday",
                role="assistant",
                content=[TextBlock(type="text", text=text)],
            )

        self.register_command(
            "restart", _handle_restart, CommandPriority.NORMAL,
        )

        # -- /reload-config (NORMAL) -----------------------------------
        async def _handle_reload_config(ctx: CommandContext) -> Msg:
            dc = self._build_daemon_context(ctx)
            text = run_daemon_reload_config(dc)
            return Msg(
                name="Friday",
                role="assistant",
                content=[TextBlock(type="text", text=text)],
            )

        self.register_command(
            "reload-config", _handle_reload_config, CommandPriority.NORMAL,
        )

        # -- /status (LOW) ---------------------------------------------
        async def _handle_status(ctx: CommandContext) -> Msg:
            dc = self._build_daemon_context(ctx)
            text = run_daemon_status(dc)
            return Msg(
                name="Friday",
                role="assistant",
                content=[TextBlock(type="text", text=text)],
            )

        self.register_command("status", _handle_status, CommandPriority.LOW)

        # -- /version (LOW) --------------------------------------------
        async def _handle_version(ctx: CommandContext) -> Msg:
            dc = self._build_daemon_context(ctx)
            text = run_daemon_version(dc)
            return Msg(
                name="Friday",
                role="assistant",
                content=[TextBlock(type="text", text=text)],
            )

        self.register_command("version", _handle_version, CommandPriority.LOW)

        # -- /logs (LOW) -----------------------------------------------
        async def _handle_logs(ctx: CommandContext) -> Msg:
            dc = self._build_daemon_context(ctx)
            n = 100
            for a in ctx.command_args:
                if a.isdigit():
                    n = max(1, min(int(a), 2000))
                    break
            text = run_daemon_logs(dc, lines=n)
            return Msg(
                name="Friday",
                role="assistant",
                content=[TextBlock(type="text", text=text)],
            )

        self.register_command("logs", _handle_logs, CommandPriority.LOW)

        # -- /daemon <sub> meta-command (delegates to sub handler) -----
        async def _handle_daemon(ctx: CommandContext) -> Msg:
            args = ctx.command_args
            sub = args[0].lower().replace("_", "-") if args else "status"
            if sub not in DAEMON_SUBCOMMANDS:
                return Msg(
                    name="Friday",
                    role="assistant",
                    content=[
                        TextBlock(
                            type="text",
                            text=f"Unknown daemon subcommand: {sub}",
                        ),
                    ],
                )
            # Build a new context with the resolved sub-command name
            sub_ctx = CommandContext(
                channel=ctx.channel,
                channel_id=ctx.channel_id,
                session_id=ctx.session_id,
                user_id=ctx.user_id,
                command_name=sub,
                command_args=args[1:] if len(args) > 1 else [],
                raw_query=f"/{sub}" + (
                    " " + " ".join(args[1:]) if len(args) > 1 else ""
                ),
                payload=ctx.payload,
                task_tracker=ctx.task_tracker,
                runner=ctx.runner,
            )
            return await self.dispatch(sub_ctx)

        self.register_command("daemon", _handle_daemon, CommandPriority.NORMAL)

        # ==============================================================
        # Conversation commands
        # ==============================================================
        for cmd_name in ConvCommandHandler.SYSTEM_COMMANDS:
            if cmd_name in ("new", "clear"):
                prio = CommandPriority.NORMAL
            else:
                prio = CommandPriority.LOW
            self.register_command(
                cmd_name,
                self._handle_conversation_command,
                prio,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _handle_conversation_command(self, ctx: CommandContext) -> Msg:
        """Generic wrapper for conversation commands.

        Builds memory/session_state context, creates a CommandHandler,
        executes the command, and persists the updated memory state.
        Reuses the context-building logic from ``run_command_path``.
        """
        runner = ctx.runner or self._runner
        if runner is None:
            return Msg(
                name="Friday",
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Conversation commands require"
                            " an active session."
                        ),
                    ),
                ],
            )

        session_id = ctx.session_id
        user_id = ctx.user_id

        # 1. Build memory context (mirrors run_command_path logic)
        memory = runner.memory_manager.get_in_memory_memory()
        session_state = await runner.session.get_session_state_dict(
            session_id=session_id,
            user_id=user_id,
        )
        memory_state = session_state.get("agent", {}).get("memory", {})
        memory.load_state_dict(memory_state, strict=False)

        # 2. Create CommandHandler instance
        conv_handler = ConvCommandHandler(
            agent_name="Friday",
            memory=memory,
            memory_manager=runner.memory_manager,
            enable_memory_manager=runner.memory_manager is not None,
        )

        # 3. Execute command
        try:
            response_msg = await conv_handler.handle_conversation_command(
                ctx.raw_query,
            )
        except RuntimeError as e:
            response_msg = Msg(
                name="Friday",
                role="assistant",
                content=[TextBlock(type="text", text=str(e))],
            )

        # 4. Persist memory state to session_state
        if session_id and user_id:
            await runner.session.update_session_state(
                session_id=session_id,
                key="agent.memory",
                value=memory.state_dict(),
                user_id=user_id,
            )
        else:
            logger.warning(
                "Skipping session_state update: missing session_id or "
                "user_id (session_id=%r, user_id=%r)",
                session_id,
                user_id,
            )

        return response_msg

    def _build_daemon_context(self, ctx: CommandContext) -> DaemonContext:
        """Build a ``DaemonContext`` from the command context and runner."""
        runner = ctx.runner or self._runner
        if runner is None:
            return DaemonContext(session_id=ctx.session_id)

        from ...config.config import load_agent_config

        agent_id = runner.agent_id
        return DaemonContext(
            load_config_fn=lambda: load_agent_config(agent_id),
            memory_manager=runner.memory_manager,
            manager=getattr(runner, "_manager", None),
            agent_id=agent_id,
            session_id=ctx.session_id,
        )
