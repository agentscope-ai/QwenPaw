# -*- coding: utf-8 -*-
"""Agent command handler for system commands.

This module handles system commands like /compact, /new, /clear, etc.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, TYPE_CHECKING

from agentscope.message import Msg, TextBlock

from .utils.context_stats import format_history_str
from ..config.config import load_agent_config, get_model_max_input_length
from ..constant import DEBUG_HISTORY_FILE, MAX_LOAD_HISTORY_COUNT
from ..exceptions import SystemCommandException

if TYPE_CHECKING:
    from agentscope.agent import Agent
    from agentscope.state import AgentState
    from .memory import BaseMemoryManager

logger = logging.getLogger(__name__)

# User-facing conversation commands and their summaries, used when
# advertising commands to clients (e.g. the ACP
# ``available_commands_update`` notification). Intentionally a small,
# curated subset of ``SYSTEM_COMMANDS`` — only the conversation commands
# meant to be typed by users are advertised (``/clear``, ``/compact``).
# The rest are still handled if typed but are not advertised, to keep the
# ACP command palette focused:
#   - ``new`` overlaps the dedicated ACP ``new_session`` affordance (clients
#     start a fresh session natively); ``/clear`` covers the in-session
#     "start over" need, so ``/new`` is not advertised over ACP.
#   - ``history``, ``plan``, ``compact_str``, ``summarize_status``,
#     ``message``, ``dump_history``, ``load_history``, ``proactive`` are
#     internal/programmatic.
# Descriptions mirror the console command palette copy
# (``console/src/locales/en.json`` → ``chat.commands``) where they overlap,
# so the same wording is shown across the web UI and ACP clients.
SYSTEM_COMMAND_DESCRIPTIONS: dict[str, str] = {
    "clear": "Clear the conversation context",
    "compact": (
        "Compact the conversation context; optional instruction supported"
    ),
}
# Manual ``/compact`` skips the auto ``trigger_ratio`` gate and runs compaction
# directly; the field is constrained ``gt=0``, so we use a negligible value
# rather than zero.
_FORCE_TRIGGER_RATIO = 1e-6


def _fmt_tokens(n: int) -> str:
    """Format token count as e.g. '82.3k' or '450'."""
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


class ConversationCommandHandlerMixin:
    """Mixin for conversation (system) commands: /compact, /new, /clear, etc.

    Expects self to have: agent_name, memory, formatter, memory_manager.
    """

    # Supported conversation commands (unchanged set)
    SYSTEM_COMMANDS = frozenset(
        {
            "compact",
            "new",
            "clear",
            "history",
            "compact_str",
            "summarize_status",
            "message",
            "dump_history",
            "load_history",
            "proactive",
            "plan",
            "system_prompt",
            "dream",
            "memorize",
            "reme_status",
        },
    )

    def is_conversation_command(self, query: str | None) -> bool:
        """Check if the query is a conversation system command.

        ``/plan <description>`` (with arguments) is NOT a command — it
        passes through the runner to activate plan mode.  Only bare
        ``/plan`` is treated as a status command.

        Args:
            query: User query string

        Returns:
            True if query is a system command
        """
        if not isinstance(query, str) or not query.startswith("/"):
            return False
        stripped = query.strip().lstrip("/")
        parts = stripped.split(" ", 1)
        cmd = parts[0] if parts else ""
        if cmd == "plan" and len(parts) > 1 and parts[1].strip():
            return False
        return cmd in self.SYSTEM_COMMANDS


class CommandHandler(ConversationCommandHandlerMixin):
    """Handler for system commands (uses ConversationCommandHandlerMixin)."""

    def __init__(
        self,
        agent_name: str,
        agent: "Agent | None" = None,
        memory_manager: "BaseMemoryManager | None" = None,
        offloader: Any = None,
        *,
        state: "AgentState | None" = None,
        agent_id: str = "default",
        workspace_dir: str | None = None,
        scroll_state: dict | None = None,
        session_id: str | None = None,
        prompt_context: Any = None,
    ):
        """Initialize command handler.

        Can be constructed in two modes:

        1. **Agent-backed**: pass ``agent`` — state is read from
           ``agent.state``.
        2. **Standalone**: pass ``state`` directly — no
           agent instance required.  Used by slash command adapters that
           load state from session before agent construction.

        Args:
            agent_name: Name of the agent for message creation.
            agent: The owning agent (optional in standalone mode).
            memory_manager: Optional long-term memory manager (ReMe).
            offloader: Optional offloader for persisting context to disk.
            state: Direct AgentState (standalone mode). Mutually
                exclusive with ``agent``.
            agent_id: Agent ID for config loading (standalone mode).
            workspace_dir: Workspace directory (standalone mode) — needed to
                open the scroll ``history.db`` when ``/compact`` runs under the
                scroll strategy.
            scroll_state: The session's persisted scroll checkpoint block, used
                to seed a standalone ``/compact`` so its eviction index stays
                continuous with prior compactions.
            prompt_context: Optional runtime HookContext used to rebuild
                the current system prompt in standalone slash-command mode.
        """
        if agent is not None and state is not None:
            raise ValueError(
                "agent and state are mutually exclusive; "
                "pass one or the other",
            )
        self.agent_name = agent_name
        self._agent = agent
        self._state_direct: "AgentState | None" = state
        self._agent_id = agent_id
        self.memory_manager: "BaseMemoryManager" = memory_manager
        self._offloader = offloader
        self._workspace_dir = workspace_dir
        self._scroll_state = scroll_state
        self._session_id = session_id
        self._prompt_context = prompt_context
        # Set by a standalone scroll ``/compact`` to the manager's refreshed
        # checkpoint, so the adapter can persist it back to the session.
        self._updated_scroll_state: dict | None = None

    @property
    def updated_scroll_state(self) -> dict | None:
        """The scroll checkpoint a standalone ``/compact`` produced, if any.

        ``None`` means no scroll compaction ran (native strategy, agent-backed
        mode, or a non-compacting command); the caller should then leave the
        session's existing scroll block untouched.
        """
        return self._updated_scroll_state

    def _get_agent_config(self):
        """Get hot-reloaded agent config."""
        if self.memory_manager is not None:
            return load_agent_config(self.memory_manager.agent_id)
        return load_agent_config(self._agent_id)

    # ------------------------------------------------------------------
    # State accessors — short-term memory lives on ``agent.state``
    # or the directly-provided ``_state_direct``.
    # ------------------------------------------------------------------

    @property
    def _state(self):
        """AgentState — from direct reference or agent.state."""
        if self._state_direct is not None:
            return self._state_direct
        return self._agent.state

    def _get_summary(self) -> str:
        """Read ``state.summary`` (string only — defensive against list
        form)."""
        s = self._state.summary
        return s if isinstance(s, str) else ""

    def _set_summary(self, value: str) -> None:
        """Write the rolling compaction summary."""
        self._state.summary = value or ""

    def _reset_modes(
        self,
    ) -> None:
        """Reset mode-owned state on /new or /clear."""
        ctx = self._prompt_context
        if ctx is None:
            return
        if getattr(ctx, "agent", None) is None and self._agent is not None:
            ctx.agent = self._agent

        for mode in getattr(
            getattr(getattr(ctx, "workspace", None), "plugins", None),
            "modes",
            [],
        ):
            try:
                mode.on_conversation_reset(ctx)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "mode '%s' reset raised",
                    getattr(mode, "name", "?"),
                    exc_info=True,
                )

    def is_command(self, query: str | None) -> bool:
        """Check if the query is a system command (alias for mixin)."""
        return self.is_conversation_command(query)

    async def _make_system_msg(
        self,
        text: str,
        metadata: dict | None = None,
    ) -> Msg:
        """Create a system response message.

        Args:
            text: Message text content
            metadata: Optional structured metadata for downstream consumers

        Returns:
            System message
        """
        return Msg(
            name=self.agent_name,
            role="assistant",
            content=[TextBlock(type="text", text=text)],
            metadata=metadata or {},
        )

    def _has_memory_manager(self) -> bool:
        """Check if memory manager is available."""
        return self.memory_manager is not None

    def _current_session_id(self) -> str:
        """Resolve the active session id on a best-effort basis.

        Prefers the explicitly-injected ``session_id`` (standalone slash
        command mode), falls back to ``state.session_id``, and finally to the
        request-scoped ``get_current_session_id()`` ContextVar (seeded by the
        contextvars setup hook). The last fallback covers reconstructed-state
        paths where ``state.session_id`` is absent but the dispatching request
        carried one. Command-triggered memory archival relies on this so ReMe
        ``auto_memory`` never runs with an empty ``session_id``.
        """
        from ..app.agent_context import get_current_session_id

        return str(
            self._session_id
            or getattr(self._state, "session_id", "")
            or get_current_session_id()
            or "",
        )

    def _forced_context_config(self, agent: "Agent"):
        """Clone the agent's ContextConfig for a manual ``/compact``.

        Only drops ``trigger_ratio`` so compaction runs now instead of waiting
        for the auto threshold. The ``reserve_ratio`` recent-tail budget is
        left untouched, so a manual ``/compact`` keeps the same tail as auto
        compaction under both strategies. (A side effect: a conversation that
        already fits inside the reserve has nothing to evict, so ``/compact``
        reports "nothing to compact" — which is honest, it doesn't need
        compacting.) Falls back to the agent's config if cloning fails."""
        base = getattr(agent, "context_config", None)
        if base is None:
            return None
        update: dict[str, Any] = {"trigger_ratio": _FORCE_TRIGGER_RATIO}
        try:
            return base.model_copy(update=update)
        except Exception:
            logger.warning(
                "Could not clone context_config to force /compact; "
                "falling back to the auto-gated config.",
            )
            return base

    async def _process_compact(
        self,
        messages: list[Msg],
        args: str = "",  # pylint: disable=unused-argument
    ) -> Msg:
        """Process /compact command.

        Delegates to agentscope's native ``Agent.compress_context()``.
        In standalone mode (no agent instance), a temporary lightweight
        Agent is built to perform the compression.
        """
        if not messages:
            return await self._make_system_msg(
                "📭 **No messages to compact.**\n\n"
                "- Current memory is empty\n"
                "- No action taken",
            )

        agent_config = self._get_agent_config()
        compact_config = (
            agent_config.running.light_context_config.context_compact_config
        )
        if not compact_config.enabled:
            return await self._make_system_msg(
                "🚫 **Compact skipped.**\n\n"
                "- Context compaction is disabled in config\n"
                "- Enable `light_context_config."
                "context_compact_config.enabled` "
                "to use `/compact`",
            )

        agent = self._agent
        if agent is None:
            agent = await self._build_tmp_agent()
            if agent is None:
                return await self._make_system_msg(
                    "🚫 **Compact failed — could not initialise model.**\n\n"
                    "- Check that an active model is configured",
                )

        # Manual command: force compaction, and measure before/after so the
        # reply reports what was actually evicted.
        forced_cfg = self._forced_context_config(agent)
        before = len(self._state.context)
        # Scroll keeps its compaction map in the eviction index
        # (``state.summary`` stays empty); native fills ``state.summary``.
        # Capture whichever applies.
        index_text = ""
        compress_stats: dict = {}
        try:
            # Agent-backed mode: ``QwenPawAgent.compress_context`` already
            # routes to scroll or native by itself. Standalone mode builds a
            # bare AgentScope ``Agent`` whose ``compress_context`` is always
            # native, so under the scroll strategy we drive the scroll manager
            # directly here. Native sessions fall through untouched.
            scroll_mgr = (
                self._build_standalone_scroll_manager()
                if self._agent is None
                else None
            )
            if scroll_mgr is not None:
                try:
                    scroll_mgr.load_state(self._scroll_state or {})
                    await scroll_mgr.compress(agent, forced_cfg)
                    self._updated_scroll_state = scroll_mgr.to_dict()
                    index_text = scroll_mgr.describe_index()
                    compress_stats = dict(scroll_mgr.last_compress)
                finally:
                    scroll_mgr.close()
            else:
                await agent.compress_context(forced_cfg)
                index_text = self._scroll_index_text(agent)
                cm = getattr(agent, "_context_manager", None)
                compress_stats = dict(
                    getattr(cm, "last_compress", None) or {},
                )
        except Exception as e:
            logger.exception("compress_context failed: %s", e)
            return await self._make_system_msg(
                f"❌ **Compact Failed!**\n\n- Reason: {e}\n"
                f"- Use `/clear` to reset the context if needed",
            )

        after = len(self._state.context)
        evicted = max(0, before - after)
        reme_cfg = agent_config.running.reme_light_memory_config
        if self._has_memory_manager() and reme_cfg.summarize_when_compact:
            self.memory_manager.add_summarize_task(
                messages=messages,
                session_id=self._current_session_id(),
            )

        summary = self._get_summary()
        folded = int(compress_stats.get("folded", 0) or 0)
        if evicted == 0 and folded == 0 and not summary and not index_text:
            return await self._make_system_msg(
                "ℹ️ **Nothing to compact.**\n\n"
                f"- Context is already minimal ({before} message(s))\n"
                "- No turns were evicted",
            )
        if index_text:
            detail = (
                "**Archived Turns:**\n"
                f"{self._format_scroll_compact_detail(index_text)}\n"
            )
        else:
            detail = f"**Compressed Summary:**\n{summary}\n"
        # The fold rewrites tool results in place (message count unchanged),
        # so it must be reported explicitly — a fold-only run used to claim
        # "Nothing to compact" while live outputs were replaced with stubs.
        folded_line = (
            f"- Tool results folded to recall stubs: {folded}\n"
            if folded
            else ""
        )
        return await self._make_system_msg(
            f"✅ **Compact Complete!**\n\n"
            f"- Messages compacted: {evicted}\n"
            f"{folded_line}"
            f"{detail}",
        )

    @staticmethod
    def _format_scroll_compact_detail(
        index_text: str,
        *,
        max_items: int = 5,
    ) -> str:
        """Return a user-readable summary of the scroll eviction index."""
        headlines = []
        for line in index_text.splitlines():
            match = re.search(r"⟦\s*(.*?)\s*⟧", line)
            if match:
                headline = match.group(1).strip()
                if headline:
                    headlines.append(headline)

        if not headlines:
            return (
                "- Older turns were archived and remain available through "
                "scroll history."
            )

        shown = headlines[-max_items:]
        lines = [f"- {headline}" for headline in shown]
        remaining = len(headlines) - len(shown)
        if remaining > 0:
            lines.append(f"- ...and {remaining} older archived turn(s)")
        lines.append(
            "\nOlder turns were removed from the live context but remain "
            "available in scroll history.",
        )
        return "\n".join(lines)

    @staticmethod
    def _scroll_index_text(agent: "Agent") -> str:
        """Scroll eviction-index map for a live agent, or '' under native."""
        cm = getattr(agent, "_context_manager", None)
        if cm is not None and hasattr(cm, "describe_index"):
            return cm.describe_index()
        return ""

    @staticmethod
    def _build_manual_context_config(agent_config: Any) -> Any:
        """Build a ContextConfig that forces manual /compact to run."""
        from agentscope.agent import ContextConfig

        ccc = agent_config.running.light_context_config.context_compact_config
        return ContextConfig(
            trigger_ratio=0.000001,
            reserve_ratio=ccc.reserve_threshold_ratio,
        )

    async def _build_tmp_agent(self) -> "Agent | None":
        """Build a minimal Agent for standalone compression.

        Shares ``self._state`` so compression side-effects (summary,
        context trimming, offloading) are reflected immediately.
        """
        try:
            from agentscope.agent import Agent

            from ..agents.model_factory import (
                create_model_and_formatter,
            )

            agent_config = self._get_agent_config()
            model, _fmt = create_model_and_formatter(
                agent_config.id,
            )

            return Agent(
                name="compactor",
                model=model,
                system_prompt=await self._get_current_system_prompt(),
                state=self._state,
                offloader=self._offloader,
                context_config=self._build_manual_context_config(
                    agent_config,
                ),
            )
        except Exception:
            logger.exception("Failed to build temporary agent for /compact")
            return None

    def _build_standalone_scroll_manager(self):
        """Build a ScrollContextManager for a standalone ``/compact``.

        Returns ``None`` unless the strategy is ``scroll`` and a workspace is
        known — in which case the caller stays on native compression. The
        manager opens the workspace ``history.db``; the caller must
        ``close()`` it. No model is needed at construction (compaction reads it
        from the agent passed to ``compress``).
        """
        try:
            lcc = self._get_agent_config().running.light_context_config
        except Exception:
            return None
        if (
            getattr(lcc, "strategy", "native") != "scroll"
            or not self._workspace_dir
        ):
            return None
        try:
            from .context.scroll.history import HistoryStore
            from .context.scroll.manager import ScrollContextManager

            sc = lcc.scroll_config
            history = HistoryStore(Path(self._workspace_dir) / sc.db_filename)
            # Must match the id normal turns persist under (the builder uses
            # ``ctx.session_id``), so these rows align with the live history.
            session_id = (
                self._session_id
                or getattr(self._state, "session_id", "")
                or "local"
            )
            return ScrollContextManager(
                history=history,
                session_id=session_id,
                agent_id=self._agent_id,
                # Already gated: the adapter only supplies an offloader when
                # ``offload_dialog`` is on, so this archives iff configured.
                offloader=self._offloader,
                summarize_unheadlined=getattr(
                    sc,
                    "summarize_unheadlined_evictions",
                    True,
                ),
                summarize_timeout_s=getattr(
                    sc,
                    "summarize_eviction_timeout_seconds",
                    20,
                ),
            )
        except Exception:
            logger.exception("Failed to build scroll manager for /compact")
            return None

    async def _process_new(self, messages: list[Msg], _args: str = "") -> Msg:
        """Process /new command."""
        self._reset_modes()
        if not messages:
            self._set_summary("")
            return await self._make_system_msg(
                "**No messages to summarize.**\n\n"
                "- Current memory is empty\n"
                "- Compressed summary is clear\n"
                "- Plan state cleared\n"
                "- No action taken",
                metadata={"clear_plan": True},
            )
        if not self._has_memory_manager():
            return await self._make_system_msg(
                "**Memory Manager Disabled**\n\n"
                "- Cannot start new conversation with summary\n"
                "- Enable memory manager to use this feature",
            )

        self.memory_manager.add_summarize_task(
            messages=messages,
            session_id=self._current_session_id(),
        )
        self._set_summary("")

        await self._persist_and_clear()
        return await self._make_system_msg(
            "**New Conversation Started!**\n\n"
            "- Summary task started in background\n"
            "- Plan state cleared\n"
            "- Ready for new conversation",
            metadata={"clear_plan": True},
        )

    async def _process_clear(
        self,
        _messages: list[Msg],
        _args: str = "",
    ) -> Msg:
        """Process /clear command."""
        await self._persist_and_clear()
        self._set_summary("")
        self._reset_modes()
        return await self._make_system_msg(
            "**History Cleared!**\n\n"
            "- Compressed summary reset\n"
            "- Memory is now empty\n"
            "- Plan state cleared",
            metadata={"clear_history": True, "clear_plan": True},
        )

    async def _persist_and_clear(self) -> None:
        """Persist current context to disk via offloader, then clear."""
        state = self._state
        if state.context and self._offloader is not None:
            try:
                session_id = getattr(state, "session_id", "") or ""
                await self._offloader.offload_context(
                    session_id,
                    list(state.context),
                )
            except Exception as e:
                logger.warning("offloader.offload_context failed: %s", e)
        state.context.clear()

    async def _process_compact_str(
        self,
        _messages: list[Msg],
        _args: str = "",
    ) -> Msg:
        """Process /compact_str command to show compressed summary."""
        summary = self._get_summary()
        if not summary:
            return await self._make_system_msg(
                "**No Compressed Summary**\n\n"
                "- No summary has been generated yet\n"
                "- Use /compact or wait for auto-compaction",
            )
        return await self._make_system_msg(
            f"**Compressed Summary**\n\n{summary}",
        )

    async def _process_history(
        self,
        _messages: list[Msg],
        _args: str = "",
    ) -> Msg:
        """Process /history command."""
        agent_config = self._get_agent_config()
        running_config = agent_config.running
        from .utils import get_token_counter

        history_str = await format_history_str(
            self._state,
            get_token_counter(agent_config),
            get_model_max_input_length(agent_config),
        )

        # Truncate if too long
        if len(history_str) > running_config.history_max_length:
            half = running_config.history_max_length // 2
            history_str = f"{history_str[:half]}\n...\n{history_str[-half:]}"

        history_str += (
            "\n\n---\n\n- Use /message <index> to view full message content"
        )

        # Add compact summary hint if available
        if self._get_summary():
            history_str += "\n- Use /compact_str to view full compact summary"

        return await self._make_system_msg(history_str)

    async def _process_system_prompt(
        self,
        _messages: list[Msg],
        _args: str = "",
    ) -> Msg:
        """Process /system_prompt command to show current system prompt."""
        prompt = await self._get_current_system_prompt()
        if not prompt:
            return await self._make_system_msg(
                "**No System Prompt**\n\n"
                "- Current system prompt is empty or unavailable",
            )
        return await self._make_system_msg(
            f"**System Prompt**\n\n```text\n{prompt}\n```",
        )

    async def _get_current_system_prompt(self) -> str:
        """Return the active system prompt when possible.

        In agent-backed mode, ask AgentScope for its dynamic system prompt
        so skill/offloader/middleware injections are included. In standalone
        slash-command mode, rebuild the prompt from the current HookContext.
        """
        agent = self._agent
        if agent is not None:
            get_system_prompt = getattr(agent, "_get_system_prompt", None)
            if callable(get_system_prompt):
                try:
                    return (await get_system_prompt()) or ""
                except Exception as e:
                    logger.warning("agent._get_system_prompt failed: %s", e)

            prompt = getattr(agent, "_system_prompt", None)
            if isinstance(prompt, str):
                return prompt

        ctx = self._prompt_context
        if ctx is not None:
            try:
                from ..runtime.builder import AgentBuilder

                builder = AgentBuilder(
                    app_services=getattr(ctx, "app_services", None),
                )
                return builder.build_prompt(ctx, self._get_agent_config())
            except Exception as e:
                logger.warning("rebuild system prompt failed: %s", e)

        return ""

    async def _process_summarize_status(
        self,
        _messages: list[Msg],
        _args: str = "",
    ) -> Msg:
        """Process /summarize_status command to show all status."""
        if not self._has_memory_manager():
            return await self._make_system_msg(
                "**Memory Manager Disabled**\n\n"
                "- Cannot list summary task status\n"
                "- Enable memory manager to use this feature",
            )

        task_list = self.memory_manager.list_summarize_status()
        if not task_list:
            return await self._make_system_msg(
                "**No Summary Tasks**\n\n"
                "- No summary tasks have been started",
            )

        status_lines = ["**Summary Task Status**\n\n"]
        for info in task_list:
            status_lines.append(
                f"- **{info['task_id']}**\n"
                f"  - Start: {info['start_time']}\n"
                f"  - Status: {info['status']}\n",
            )
            if info["status"] == "completed" and info["result"]:
                status_lines.append(f"  - Result: {info['result'][:200]}...\n")
            elif info["status"] == "failed" and info["error"]:
                status_lines.append(f"  - Error: {info['error']}\n")

        return await self._make_system_msg("".join(status_lines))

    async def _process_dream(
        self,
        _messages: list[Msg],
        args: str = "",
    ) -> Msg:
        """Process /dream command to run one auto-dream pass."""
        if not self._has_memory_manager():
            return await self._make_system_msg(
                "**Memory Manager Disabled**\n\n"
                "- Cannot run auto-dream\n"
                "- Enable memory manager to use this feature",
            )

        hint = args.strip()
        try:
            if hint:
                await self.memory_manager.dream(hint=hint)
            else:
                await self.memory_manager.dream()
        except Exception as e:
            logger.exception("auto-dream failed: %s", e)
            return await self._make_system_msg(
                f"**Auto-dream Failed**\n\n- Error: {e}",
            )

        return await self._make_system_msg(
            "**Auto-dream Complete**\n\n"
            "- Ran one auto-dream memory optimization pass",
        )

    async def _process_reme_status(
        self,
        _messages: list[Msg],
        _args: str = "",
    ) -> Msg:
        """Process /reme_status to report embedded ReMe memory usage."""
        if not self._has_memory_manager():
            return await self._make_system_msg(
                "**Memory Manager Disabled**\n\n"
                "- Cannot inspect ReMe memory usage\n"
                "- Enable the ReMe memory manager to use this feature",
            )

        try:
            response = await self.memory_manager.reme_status()
        except Exception as e:
            logger.exception("ReMe status failed: %s", e)
            return await self._make_system_msg(
                f"**ReMe Status Failed**\n\n- Error: {e}",
            )

        if response is None:
            return await self._make_system_msg(
                "**ReMe Status Unavailable**\n\n"
                "- ReMe is not started or this memory backend does not "
                "support status reporting",
            )

        answer = str(getattr(response, "answer", "") or "").strip()
        if not getattr(response, "success", False):
            return await self._make_system_msg(
                "**ReMe Status Failed**\n\n"
                f"- Error: {answer or 'Unknown ReMe error'}",
            )

        warning = (
            "⚠️ **Estimation note:** ReMe estimates `EMBEDDING_STORE`, "
            "`FILE_GRAPH`, `FILE_STORE`, and `KEYWORD_INDEX` independently. "
            "Objects shared across those components may be counted more than "
            "once, so the components total is not unique memory usage and "
            "should not be compared directly with process RSS."
        )
        return await self._make_system_msg(
            f"**ReMe Memory Status**\n\n```text\n{answer}\n```\n\n{warning}",
            metadata=dict(getattr(response, "metadata", None) or {}),
        )

    async def _process_memorize(
        self,
        messages: list[Msg],
        args: str = "",
    ) -> Msg:
        """Process /memorize command to run auto-memory for recent replies."""
        if not self._has_memory_manager():
            return await self._make_system_msg(
                "**Memory Manager Disabled**\n\n"
                "- Cannot run auto-memory\n"
                "- Enable memory manager to use this feature",
            )

        invalid_count_message: str | None = None
        try:
            count = int(args.strip() or "1")
        except ValueError:
            count = 0
            invalid_count_message = (
                f"**Invalid Count: '{args}'**\n\n"
                "- Count must be a positive integer\n"
                "- Examples: /memorize, /memorize 2"
            )

        if invalid_count_message is None and count <= 0:
            invalid_count_message = (
                f"**Invalid Count: {count}**\n\n"
                "- Count must be a positive integer\n"
                "- Examples: /memorize, /memorize 2"
            )

        if invalid_count_message is not None:
            return await self._make_system_msg(
                invalid_count_message,
            )

        reply_ids = self._latest_reply_ids(messages, count=count)
        if not reply_ids:
            return await self._make_system_msg(
                "**No Reply Messages Found**\n\n"
                "- No assistant replies are available to memorize",
            )

        memory_messages = self._messages_for_reply_ids(
            messages,
            reply_ids=reply_ids,
        )
        if not memory_messages:
            return await self._make_system_msg(
                "**No Messages Found**\n\n"
                "- Could not build a message range for the selected replies",
            )

        try:
            await self.memory_manager.auto_memory(
                memory_messages,
                session_id=self._current_session_id(),
                reply_id=reply_ids[-1],
                reply_ids=reply_ids,
            )
        except Exception as e:
            logger.exception("manual auto-memory failed: %s", e)
            return await self._make_system_msg(
                f"**Auto-memory Failed**\n\n- Error: {e}",
            )

        return await self._make_system_msg(
            "**Auto-memory Started**\n\n"
            f"- Reply groups: {len(reply_ids)}\n"
            f"- Messages submitted: {len(memory_messages)}",
        )

    def _latest_reply_ids(
        self,
        messages: list[Msg],
        *,
        count: int,
    ) -> list[str]:
        """Return latest assistant reply ids in chronological order."""
        reply_ids: list[str] = []
        for msg in reversed(messages):
            if msg.role != "assistant" or msg.name != self.agent_name:
                continue
            if not msg.id:
                continue
            reply_ids.append(msg.id)
            if len(reply_ids) >= count:
                break
        reply_ids.reverse()
        if reply_ids:
            return reply_ids

        # Standalone slash-command handling may not have the exact runtime
        # agent name available for older sessions.  Fall back to assistant
        # messages by role/id instead of reporting that no reply exists.
        for msg in reversed(messages):
            if msg.role != "assistant" or not msg.id:
                continue
            reply_ids.append(msg.id)
            if len(reply_ids) >= count:
                break
        reply_ids.reverse()
        return reply_ids

    def _messages_for_reply_ids(
        self,
        messages: list[Msg],
        *,
        reply_ids: list[str],
    ) -> list[Msg]:
        targets = set(reply_ids)
        if not targets:
            return []

        first_idx: int | None = None
        last_idx: int | None = None
        for idx, msg in enumerate(messages):
            if msg.role == "assistant" and msg.id in targets:
                if first_idx is None:
                    first_idx = idx
                last_idx = idx

        if first_idx is None or last_idx is None:
            return []

        start_idx = 0
        for idx in range(first_idx - 1, -1, -1):
            msg = messages[idx]
            if msg.role == "assistant" and msg.id:
                start_idx = idx + 1
                break

        return messages[start_idx : last_idx + 1]

    async def _process_message(
        self,
        messages: list[Msg],
        args: str = "",
    ) -> Msg:
        """Process /message x command to show the nth message.

        Args:
            messages: List of messages in memory
            args: Command arguments (message index)

        Returns:
            System message with the requested message content
        """
        agent_config = self._get_agent_config()
        history_max_length = agent_config.running.history_max_length

        if not args:
            return await self._make_system_msg(
                "**Usage: /message <index>**\n\n"
                "- Example: /message 1 (show first message)\n"
                f"- Available messages: 1 to {len(messages)}",
            )

        try:
            index = int(args.strip())
        except ValueError:
            return await self._make_system_msg(
                f"**Invalid Index: '{args}'**\n\n"
                "- Index must be a number\n"
                "- Example: /message 1",
            )

        if not messages:
            return await self._make_system_msg(
                "**No Messages Available**\n\n- Current memory is empty",
            )

        if index < 1 or index > len(messages):
            return await self._make_system_msg(
                f"**Index Out of Range: {index}**\n\n"
                f"- Available range: 1 to {len(messages)}\n"
                f"- Example: /message 1",
            )

        msg = messages[index - 1]

        # Handle content display with truncation
        content_str = str(msg.content)
        truncated = False
        if len(content_str) > history_max_length:
            half = history_max_length // 2
            content_str = f"{content_str[:half]}\n...\n{content_str[-half:]}"
            truncated = True

        truncation_hint = (
            "\n\n- Content truncated, use /dump_history to view full content"
            if truncated
            else ""
        )
        return await self._make_system_msg(
            f"**Message {index}/{len(messages)}**\n\n"
            f"- **Timestamp:** {msg.timestamp}\n"
            f"- **Name:** {msg.name}\n"
            f"- **Role:** {msg.role}\n"
            f"- **Content:**\n{content_str}{truncation_hint}",
        )

    async def _process_dump_history(
        self,
        messages: list[Msg],
        _args: str = "",
    ) -> Msg:
        """Process /dump_history command to save messages to a JSONL file.

        Args:
            messages: List of messages in memory
            _args: Command arguments (unused)

        Returns:
            System message with dump result
        """
        agent_config = self._get_agent_config()
        history_file = Path(agent_config.workspace_dir) / DEBUG_HISTORY_FILE

        try:
            # Check if there's a compressed summary
            compressed_summary = self._get_summary()
            has_summary = bool(compressed_summary)

            # Build dump messages: summary first (if exists), then messages
            dump_messages = []
            if has_summary:
                summary_msg = Msg(
                    name="user",
                    role="user",
                    content=[TextBlock(type="text", text=compressed_summary)],
                    metadata={"has_compressed_summary": "true"},
                )
                dump_messages.append(summary_msg)

            dump_messages.extend(messages)

            with open(history_file, "w", encoding="utf-8") as f:
                for msg in dump_messages:
                    f.write(
                        json.dumps(msg.to_dict(), ensure_ascii=False) + "\n",
                    )

            logger.info(
                f"Dumped {len(dump_messages)} messages to {history_file}",
            )
            return await self._make_system_msg(
                f"**History Dumped!**\n\n"
                f"- Messages saved: {len(dump_messages)}\n"
                f"- Has summary: {has_summary}\n"
                f"- File: `{history_file}`",
            )
        except Exception as e:
            logger.exception(f"Failed to dump history: {e}")
            return await self._make_system_msg(
                f"**Dump Failed**\n\n" f"- Error: {e}",
            )

    async def _process_load_history(
        self,
        _messages: list[Msg],
        _args: str = "",
    ) -> Msg:
        """Process /load_history command to load messages from a JSONL file.

        Args:
            _messages: List of messages in memory (unused)
            _args: Command arguments (unused)

        Returns:
            System message with load result
        """
        agent_config = self._get_agent_config()
        history_file = Path(agent_config.workspace_dir) / DEBUG_HISTORY_FILE

        if not history_file.exists():
            return await self._make_system_msg(
                f"**Load Failed**\n\n"
                f"- File not found: `{history_file}`\n"
                f"- Use /dump_history first to create the file",
            )

        try:
            loaded_messages: list[Msg] = []
            has_summary_marker = False
            with open(history_file, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    line = line.strip()
                    if line:
                        msg_dict = json.loads(line)
                        msg = Msg.from_dict(msg_dict)
                        loaded_messages.append(msg)
                        # Check first message for summary marker
                        if (
                            i == 0
                            and msg.metadata.get("has_compressed_summary")
                            == "true"
                        ):
                            has_summary_marker = True
                        if len(loaded_messages) >= MAX_LOAD_HISTORY_COUNT:
                            break

            # Clear existing context without persisting (this IS the
            # "replay history into state" path; new context is what we
            # just loaded from disk).
            self._state.context.clear()
            self._set_summary("")

            # If first message has summary marker, extract and restore summary
            if has_summary_marker and loaded_messages:
                summary_msg = loaded_messages.pop(0)
                summary_content = summary_msg.get_text_content() or ""
                self._set_summary(summary_content)
                logger.info("Restored compressed summary from history file")

            for msg in loaded_messages:
                self._state.context.append(msg)

            logger.info(
                f"Loaded {len(loaded_messages)} messages from {history_file}",
            )
            return await self._make_system_msg(
                f"**History Loaded!**\n\n"
                f"- Messages loaded: {len(loaded_messages)}\n"
                f"- Has summary: {has_summary_marker}\n"
                f"- File: `{history_file}`\n"
                f"- Memory cleared before loading",
            )
        except Exception as e:
            logger.exception(f"Failed to load history: {e}")
            return await self._make_system_msg(
                f"**Load Failed**\n\n" f"- Error: {e}",
            )

    async def handle_conversation_command(self, query: str) -> Msg:
        """Process conversation system commands.

        Args:
            query: Command string (e.g., "/compact", "/new", "/message 5")

        Returns:
            System response message

        Raises:
            SystemCommandException: If command is not recognized
        """
        # Snapshot the current short-term context for the conversation
        # command (most handlers don't need the messages list; the ones
        # that do — /compact, /dump_history — read it once).
        messages = list(self._state.context)
        # Parse command and arguments
        parts = query.strip().lstrip("/").split(" ", maxsplit=1)
        command = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        logger.info(f"Processing command: {command}, args: {args}")

        handler = getattr(self, f"_process_{command}", None)
        if handler is None:
            raise SystemCommandException(
                message=f"Unknown command: {query}",
            )
        return await handler(messages, args)

    async def handle_command(self, query: str) -> Msg:
        """Process system commands (alias for handle_conversation_command)."""
        return await self.handle_conversation_command(query)

    async def _process_plan(
        self,
        _messages: list[Msg],
        _args: str = "",
    ) -> Msg:
        """Stub for the legacy ``/plan`` command — plan mode is currently
        unavailable in qwenpaw.
        """
        return await self._make_system_msg(
            "**Plan Mode**\n\n"
            "- Status: **temporarily unavailable**\n"
            "- Plan mode is being migrated to the new task system "
            "and will be available in a future update.",
        )

    async def _process_proactive(
        self,
        _messages: list[Msg],
        args: str = "",
    ) -> Msg:
        """Process /proactive command for proactive message feature."""
        args = args.strip().lower()
        from .memory import enable_proactive_for_session
        from ..app.agent_context import get_current_agent_id

        # Get current agent ID and language
        active_agent_id = get_current_agent_id()
        agent_config = load_agent_config(active_agent_id)
        agent_lang = getattr(agent_config, "language", "en")

        # Define warnings in both languages
        warning_en = (
            "**NOTE**: In this mode, the agent bypasses tool "
            "protection mechanisms. Please note that the agent will "
            "read historical session memories and may take screenshots "
            "to obtain runtime environment information."
            "Proactive mode can be turned off via /proactive off."
        )

        warning_zh = (
            "**请注意**：在此模式下，代理会绕过工具保护机制。请注意，代理将会"
            "读取历史会话内存，并可能截取屏幕截图以获取运行环境信息。"
            "可通过 /proactive off 关闭主动模式。"
        )

        # Define all message templates in both languages
        msg_templates = {
            "en": {
                "enabled": (
                    "**Proactive Mode Enabled**\n\n"
                    "- Idle time: {minutes} minutes\n"
                    "- Status: {result}\n"
                    "- Proactive messages will be sent after "
                    "{minutes} minutes of inactivity\n\n{warning}"
                ),
                "disabled": (
                    "**Proactive Mode Disabled**\n\n"
                    "- Proactive monitoring has been stopped\n"
                    "- No more proactive messages will be sent"
                ),
                "error_en": ("**Error Enabling Proactive Mode**\n-{error}"),
                "error_dis": ("**Error Disabling Proactive Mode**\n- {error}"),
                "error_args": (
                    "**Error Enabling Proactive Mode**\n\n"
                    "- {error}"
                    "- Usage: /proactive [minutes|on|off]\n"
                    "- Examples:\n"
                    "  • /proactive (default 30 minutes)\n"
                    "  • /proactive 45 (45 minutes idle time)\n"
                    "  • /proactive on (default 30 minutes)\n"
                    "  • /proactive off (disable proactive mode)\n"
                ),
            },
            "zh": {
                "enabled": (
                    "**主动模式已启用**\n\n"
                    "- 空闲时间: {minutes} 分钟\n"
                    "- 状态: {result}\n"
                    "- 将在 {minutes} 分钟不活动后发送主动消息\n\n{warning}"
                ),
                "disabled": ("**主动模式已停用**\n" "- 不再发送主动消息"),
                "error_en": ("**启用主动模式时出错**\n\n-{error}"),
                "error_dis": ("**禁用主动模式时出错**\n\n- {error}"),
                "error_args": (
                    "**启用主动模式时出错**\n\n"
                    "- {error}"
                    "- 使用方法: /proactive [分钟数|on|off]\n"
                    "- 示例:\n"
                    "  • /proactive (默认30分钟)\n"
                    "  • /proactive 45 (45分钟空闲时间)\n"
                    "  • /proactive on (默认30分钟)\n"
                    "  • /proactive off (禁用主动模式)\n"
                ),
            },
        }

        # Select messages and warning based on agent language
        lang_key = "zh" if agent_lang.lower() == "zh" else "en"
        msgs = msg_templates[lang_key]
        selected_warning = warning_zh if lang_key == "zh" else warning_en

        if not args or args == "on":
            try:
                result = enable_proactive_for_session(
                    self.agent_name,
                    30,
                )
                return await self._make_system_msg(
                    msgs["enabled"].format(
                        minutes=30,
                        result=result,
                        warning=selected_warning,
                    ),
                )
            except Exception as e:
                return await self._make_system_msg(
                    msgs["error_en"].format(error=str(e)),
                )

        elif args == "off":
            try:
                import asyncio
                from .memory import proactive_tasks

                if self.agent_name in proactive_tasks:
                    task = proactive_tasks[self.agent_name]
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                    del proactive_tasks[self.agent_name]

                return await self._make_system_msg(
                    msgs["disabled"],
                )
            except Exception as e:
                return await self._make_system_msg(
                    msgs["error_dis"].format(error=str(e)),
                )
        else:
            try:
                minutes = int(args)
                if minutes <= 0:
                    raise ValueError("Minutes must be a positive integer")

                result = enable_proactive_for_session(
                    self.agent_name,
                    minutes,
                )
                return await self._make_system_msg(
                    msgs["enabled"].format(
                        minutes=minutes,
                        result=result,
                        warning=selected_warning,
                    ),
                )
            except Exception as e:
                return await self._make_system_msg(
                    msgs["error_args"].format(error=str(e)),
                )
