# -*- coding: utf-8 -*-
"""ADBPG Memory Manager for CoPaw agents (v0.10.0).

Provides ADBPGInMemoryMemory (an InMemoryMemory subclass with
compressed-summary management and message marking) and
ADBPGMemoryManager (the full memory-manager implementation backed
by AnalyticDB for PostgreSQL).

Adapted for multi-agent architecture: each agent gets its own
ADBPGMemoryManager instance with isolated memory via agent_id.
"""
import asyncio
import logging
import re
import threading
from pathlib import Path
from typing import Any

from agentscope.agent._react_agent import _MemoryMark
from agentscope.formatter import FormatterBase
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg, TextBlock
from agentscope.model import ChatModelBase
from agentscope.tool import ToolResponse

from copaw.agents.model_factory import create_model_and_formatter
from copaw.agents.utils import (
    check_valid_messages,
    get_copaw_token_counter,
)
from copaw.config.config import load_agent_config

from .adbpg_client import (
    ADBPGConfig,
    ADBPGMemoryClient,
    ConfigurationError,
    close_shared_pool,
    reset_configured_connections,
)
from .base_memory_manager import BaseMemoryManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ADBPGInMemoryMemory: session-local message store with summary support
# ---------------------------------------------------------------------------


class ADBPGInMemoryMemory(InMemoryMemory):
    """In-memory message store with compressed-summary and marking support.

    Extends ``InMemoryMemory`` with:
    - A ``compressed_summary`` string that is prepended to retrieved
      messages when requested.
    - Per-message marks (e.g. ``COMPRESSED``) for tracking compaction.
    """

    def __init__(self, token_counter: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._compressed_summary: str = ""
        self._long_term_context: str = ""
        self._token_counter = token_counter

    # -- Compressed summary management --
    # The compressed summary is a condensed representation of older
    # conversation history, prepended to retrieved messages so the
    # agent retains context across compaction cycles.

    def get_compressed_summary(self) -> str:
        """Return the current compressed summary."""
        return self._compressed_summary

    async def update_compressed_summary(self, summary: str) -> None:
        """Replace the compressed summary."""
        self._compressed_summary = summary

    def clear_compressed_summary(self) -> None:
        """Reset the compressed summary to an empty string."""
        self._compressed_summary = ""

    # -- Message retrieval with filtering / summary prepend --

    async def get_memory(
        self,
        exclude_mark: Any = None,
        prepend_summary: bool = True,
        **kwargs: Any,
    ) -> list[Msg]:
        """Return stored messages, optionally filtering and prepending summary."""
        messages: list[Msg] = []
        for msg, marks in self.content:
            if exclude_mark is not None and exclude_mark in marks:
                continue
            messages.append(msg)

        prefix_msgs: list[Msg] = []

        if prepend_summary and self._compressed_summary:
            prefix_msgs.append(
                Msg(
                    name="system",
                    role="system",
                    content=self._compressed_summary,
                ),
            )

        if prepend_summary and self._long_term_context:
            prefix_msgs.append(
                Msg(
                    name="system",
                    role="system",
                    content=self._long_term_context,
                ),
            )

        return prefix_msgs + messages

    # -- Message marking --
    # Marks (e.g. COMPRESSED) are attached to individual messages so
    # that compacted messages can be excluded from future LLM calls
    # while still being retained in memory for history display.

    async def update_messages_mark(
        self,
        new_mark: Any,
        msg_ids: list[str],
    ) -> int:
        """Add *new_mark* to messages identified by *msg_ids*."""
        id_set = set(msg_ids)
        count = 0
        for msg, marks in self.content:
            if msg.id in id_set:
                if new_mark not in marks:
                    marks.append(new_mark)
                count += 1
        return count

    async def mark_messages_compressed(
        self,
        messages: list[Msg],
    ) -> int:
        """Mark *messages* as ``COMPRESSED``."""
        return await self.update_messages_mark(
            new_mark=_MemoryMark.COMPRESSED,
            msg_ids=[msg.id for msg in messages],
        )

    # -- Clear --

    def clear_content(self) -> None:
        """Remove all messages from memory."""
        self.content.clear()

    # -- History string --

    async def get_history_str(
        self,
        max_input_length: int | None = None,
    ) -> str:
        """Return a human-readable history string."""
        parts: list[str] = []
        if self._compressed_summary:
            parts.append(
                f"[Compressed Summary]\n{self._compressed_summary}\n",
            )
        for msg, marks in self.content:
            mark_str = ""
            if marks:
                mark_str = f" [{', '.join(str(m) for m in marks)}]"
            text = (
                msg.get_text_content()
                if hasattr(msg, "get_text_content")
                else str(msg.content)
            )
            parts.append(f"{msg.role}{mark_str}: {text}")
        result = "\n".join(parts)
        if max_input_length is not None and len(result) > max_input_length:
            result = result[-max_input_length:]
        return result

    # -- Serialisation --

    def state_dict(self) -> dict:
        """Serialise memory state to a dict."""
        state = super().state_dict()
        state["_compressed_summary"] = self._compressed_summary
        return state

    def load_state_dict(self, state: Any) -> None:
        """Restore memory state from a dict."""
        if isinstance(state, dict):
            self._compressed_summary = state.pop(
                "_compressed_summary",
                "",
            )
            super().load_state_dict(state)
        else:
            super().load_state_dict(state)
            self._compressed_summary = ""


# ---------------------------------------------------------------------------
# ADBPGMemoryManager: full memory-manager backed by AnalyticDB for PG
# ---------------------------------------------------------------------------


class ADBPGMemoryManager(BaseMemoryManager):
    """Memory manager backed by AnalyticDB for PostgreSQL (ADBPG).

    Standalone implementation that does NOT inherit from ``ReMeLight``.
    Inherits from ``BaseMemoryManager`` to satisfy the interface contract
    used by ``CoPawAgent``, ``MemoryCompactionHook``, ``CommandHandler``,
    and ``Runner``.

    Multi-agent support: each instance is bound to an ``agent_id``,
    which is used as the ADBPG ``agent_id`` parameter for data
    isolation between agents.
    """

    def __init__(
        self,
        working_dir: str,
        agent_id: str,
    ) -> None:
        """Initialise ADBPGMemoryManager.

        Args:
            working_dir: Working directory path for memory storage.
            agent_id: Unique agent identifier for memory isolation.
        """
        super().__init__(working_dir=working_dir, agent_id=agent_id)
        self._adbpg_config = None
        self._adbpg_runtime_config: ADBPGConfig | None = None
        self._client: ADBPGMemoryClient | None = None
        self._in_memory_memory: ADBPGInMemoryMemory | None = None
        self._user_id: str = ""
        self._persisted_msg_ids: set[str] = set()
        self._effective_agent_id: str = "shared"
        self._effective_user_id: str = "shared"
        self._effective_run_id: str = "shared"
        self._auto_retrieved: bool = False
        self.chat_model: ChatModelBase | None = None
        self.formatter: FormatterBase | None = None

    # -- Properties --

    @property
    def user_id(self) -> str:
        """Return the current user ID for ADBPG data isolation."""
        return self._user_id

    @user_id.setter
    def user_id(self, value: str) -> None:
        """Set the user ID for ADBPG data isolation."""
        self._user_id = value or ""

    def set_request_context(
        self,
        user_id: str = "",
        session_id: str = "",
    ) -> None:
        """Update per-request isolation IDs.

        Called by the runner/agent before each query so that
        run_isolation can use the real session_id.

        Args:
            user_id: User ID from the incoming request.
            session_id: Session ID from the incoming request.
        """
        self._user_id = user_id or ""
        # If run_isolation is enabled and no static run_id was
        # resolved at start(), use the request session_id.
        if self._adbpg_config and getattr(
            self._adbpg_config,
            "run_isolation",
            False,
        ):
            self._effective_run_id = session_id if session_id else "shared"

    # -- Lifecycle --

    async def start(self) -> None:
        """Initialise resources: create client, connect, and configure.

        The underlying connection pool is shared across all agents;
        ``ADBPGMemoryClient`` will create it lazily on first use.

        If the ADBPG database is unreachable the agent will still
        start, but long-term memory features will be disabled
        (``self._client`` stays ``None``).
        """
        self._in_memory_memory = ADBPGInMemoryMemory()

        # Load ADBPG config from per-agent config via agent_id
        agent_config = load_agent_config(self.agent_id)
        self._adbpg_config = agent_config.running.adbpg

        # Determine memory isolation mode
        isolation = (
            self._adbpg_config.memory_isolation
            if self._adbpg_config
            and hasattr(self._adbpg_config, "memory_isolation")
            else False
        )
        self._effective_agent_id = self.agent_id if isolation else "shared"

        # Determine user isolation mode
        user_iso = (
            self._adbpg_config.user_isolation
            if self._adbpg_config
            and hasattr(self._adbpg_config, "user_isolation")
            else False
        )
        if user_iso:
            uid = (
                getattr(
                    self._adbpg_config,
                    "user_isolation_id",
                    "",
                )
                or ""
            )
            self._effective_user_id = uid if uid else "shared"
        else:
            self._effective_user_id = "shared"

        # Determine run (session) isolation mode
        run_iso = (
            self._adbpg_config.run_isolation
            if self._adbpg_config
            and hasattr(self._adbpg_config, "run_isolation")
            else False
        )
        self._effective_run_id = "" if run_iso else "shared"

        try:
            # Build config from per-agent config (set via console UI).
            api_mode = (
                getattr(
                    self._adbpg_config,
                    "api_mode",
                    "sql",
                )
                if self._adbpg_config
                else "sql"
            )

            if api_mode == "rest":
                # REST mode: only api_key is required
                if not (
                    self._adbpg_config and self._adbpg_config.rest_api_key
                ):
                    raise ConfigurationError(
                        "ADBPG memory REST API key not configured in "
                        "agent.json. Please configure it via the console "
                        "UI (Agent Config → Memory Manager → API Mode).",
                    )
            else:
                # SQL mode: host is required
                if not (self._adbpg_config and self._adbpg_config.host):
                    raise ConfigurationError(
                        "ADBPG connection not configured in agent.json. "
                        "Please configure it via the console UI "
                        "(Agent Config → Memory Manager).",
                    )
            config = ADBPGConfig(
                host=self._adbpg_config.host,
                port=self._adbpg_config.port,
                user=self._adbpg_config.user,
                password=self._adbpg_config.password,
                dbname=self._adbpg_config.dbname,
                llm_model=self._adbpg_config.llm_model,
                llm_api_key=self._adbpg_config.llm_api_key,
                llm_base_url=self._adbpg_config.llm_base_url,
                embedding_model=self._adbpg_config.embedding_model,
                embedding_api_key=self._adbpg_config.embedding_api_key,
                embedding_base_url=self._adbpg_config.embedding_base_url,
                embedding_dims=self._adbpg_config.embedding_dims,
                search_timeout=self._adbpg_config.search_timeout,
                pool_minconn=self._adbpg_config.pool_minconn,
                pool_maxconn=self._adbpg_config.pool_maxconn,
                tool_compact_mode=self._adbpg_config.tool_compact_mode,
                tool_compact_max_len=self._adbpg_config.tool_compact_max_len,
                memory_isolation=self._adbpg_config.memory_isolation,
                user_isolation=(self._adbpg_config.user_isolation),
                user_isolation_id=(self._adbpg_config.user_isolation_id),
                run_isolation=(self._adbpg_config.run_isolation),
                api_mode=api_mode,
                rest_api_key=self._adbpg_config.rest_api_key,
                rest_base_url=self._adbpg_config.rest_base_url,
                custom_fact_extraction_prompt=(
                    self._adbpg_config.custom_fact_extraction_prompt
                ),
            )
        except Exception as e:
            logger.warning(
                "ADBPG configuration incomplete for agent '%s': %s. "
                "Long-term memory is DISABLED — the agent will run "
                "with in-memory-only context.",
                self.agent_id,
                e,
            )
            self._client = None
            return

        try:
            # Force re-configuration of pooled connections so that
            # any config changes (e.g. custom_fact_extraction_prompt)
            # take effect without a process restart.
            reset_configured_connections()
            client = ADBPGMemoryClient(config)
            # Eagerly validate connectivity (also warms the shared pool)
            client.configure()
            self._client = client
            self._adbpg_runtime_config = config
            logger.info(
                "ADBPGMemoryManager started for agent '%s'.",
                self.agent_id,
            )
        except Exception as e:
            logger.warning(
                "Failed to connect to ADBPG for agent '%s': %s. "
                "Long-term memory is DISABLED — the agent will run "
                "with in-memory-only context.",
                self.agent_id,
                e,
            )
            self._client = None

    async def close(self) -> bool:
        """Clean up resources: await pending tasks.

        The shared connection pool is NOT closed here — it stays
        alive for other agents.  Call ``close_shared_pool()`` at
        process shutdown to release all connections.

        Returns:
            ``True`` if shutdown completed successfully.
        """
        await self.await_summary_tasks()
        self._client = None
        logger.info(
            "ADBPGMemoryManager closed for agent '%s'.",
            self.agent_id,
        )
        return True

    # -- Model / formatter initialisation --

    def prepare_model_formatter(self) -> None:
        """Ensure ``chat_model`` and ``formatter`` are initialised."""
        if self.chat_model is None or self.formatter is None:
            logger.warning("Model and formatter not initialized.")
            chat_model, formatter = create_model_and_formatter(self.agent_id)
            if self.chat_model is None:
                self.chat_model = chat_model
            if self.formatter is None:
                self.formatter = formatter

    # -- Core helpers --

    @staticmethod
    def _format_messages_for_llm(messages: list[Msg]) -> str:
        """Format messages into a single conversation string."""
        parts: list[str] = []
        for msg in messages:
            text = (
                msg.get_text_content()
                if hasattr(msg, "get_text_content")
                else str(msg.content)
            )
            parts.append(f"{msg.role}: {text}")
        return "\n".join(parts)

    @staticmethod
    def _filter_user_messages(messages: list[Msg]) -> list[dict]:
        """Extract only role=user messages for ADBPG storage."""
        return [
            {
                "role": "user",
                "content": (
                    msg.get_text_content()
                    if hasattr(msg, "get_text_content")
                    else str(msg.content)
                ),
            }
            for msg in messages
            if msg.role == "user"
        ]

    def _fire_and_forget_add(self, user_messages: list[dict]) -> None:
        """Store messages to ADBPG in a background daemon thread."""
        if self._client is None:
            return
        agent_id = self._effective_agent_id
        user_id = self._effective_user_id
        run_id = self._effective_run_id
        client = self._client

        def _do_add() -> None:
            try:
                client.add_memory(
                    messages=user_messages,
                    user_id=user_id,
                    run_id=run_id,
                    agent_id=agent_id,
                )
            except Exception as e:
                logger.error(f"Background memory add failed: {e}")

        thread = threading.Thread(target=_do_add, daemon=True)
        thread.start()

    def _auto_retrieve_memories(self, messages: list[Msg]) -> None:
        """Search ADBPG for relevant long-term memories and inject into context.

        Uses the latest user message as a search query, performs a
        synchronous search against ADBPG, and prepends results to the
        ``compressed_summary`` so the agent sees them during reasoning.

        Only executes once per conversation turn to avoid redundant
        searches during ReAct reasoning-acting iterations.
        """
        if self._client is None or self._auto_retrieved:
            return
        self._auto_retrieved = True

        query = ""
        for msg in reversed(messages):
            if msg.role == "user":
                query = (
                    msg.get_text_content()
                    if hasattr(msg, "get_text_content")
                    else str(msg.content)
                )
                break

        if not query or len(query.strip()) < 2:
            return

        logger.debug(
            "ADBPG auto-retrieve query for agent '%s': %s",
            self.agent_id,
            query[:200],
        )

        try:
            results = self._client.search_memory(
                query=query,
                user_id=self._effective_user_id,
                run_id=self._effective_run_id,
                agent_id=self._effective_agent_id,
                limit=3,
            )
            logger.debug(
                "ADBPG search returned %d result(s) for agent '%s'.",
                len(results) if results else 0,
                self.agent_id,
            )
            if not results:
                return

            parts: list[str] = []
            for item in results:
                content = item.get("content", item.get("memory", ""))
                if content:
                    parts.append(f"- {content}")
            if not parts:
                return

            memory_block = "[Long-term Memory from ADBPG]\n" + "\n".join(parts)

            logger.debug(
                "ADBPG memory block injected for agent '%s':\n%s",
                self.agent_id,
                memory_block,
            )

            self._in_memory_memory._long_term_context = memory_block
            logger.info(
                "Injected %d ADBPG memory snippet(s) into context "
                "for agent '%s'.",
                len(parts),
                self.agent_id,
            )
        except Exception as e:
            logger.warning(f"Auto-retrieve ADBPG memories failed: {e}")

    # -- Core interface methods --

    async def compact_memory(
        self,
        messages: list[Msg],
        previous_summary: str = "",
        **kwargs: Any,
    ) -> str:
        """Compact messages into a summary and store to ADBPG long-term memory.

        Uses agent-specific config for language, max_input_length, etc.
        Fire-and-forget stores user messages to ADBPG.
        """
        self.prepare_model_formatter()

        agent_config = load_agent_config(self.agent_id)
        token_counter = get_copaw_token_counter(agent_config)
        language = agent_config.language
        max_input_length = agent_config.running.max_input_length
        compact_ratio = getattr(
            getattr(agent_config.running, "context_compact", None),
            "memory_compact_ratio",
            getattr(agent_config.running, "memory_compact_ratio", 0.7),
        )

        # Build conversation text
        conversation = self._format_messages_for_llm(messages)

        # Truncate to fit prompt budget
        max_prompt_tokens = int(max_input_length * compact_ratio)
        try:
            conv_token_ids = token_counter.tokenizer.encode(conversation)
            if len(conv_token_ids) > max_prompt_tokens:
                conversation = token_counter.tokenizer.decode(
                    conv_token_ids[:max_prompt_tokens],
                )
        except Exception:
            # Fallback: character-based truncation
            max_chars = max_prompt_tokens * 4
            if len(conversation) > max_chars:
                conversation = conversation[:max_chars]

        # Build prompt based on language (zh / en)
        prompt = self._build_compact_prompt(
            conversation,
            previous_summary,
            language,
        )

        # Call LLM
        system_content = (
            "你是一个上下文压缩助手。你的角色是创建对话的结构化摘要，"
            "这些摘要可以在未来会话中用于恢复上下文。"
            "专注于保留关键信息，同时减少token数量。"
            if language == "zh"
            else "You are a context compaction assistant. Your role is "
            "to create structured summaries of conversations that can "
            "be used to restore context in future sessions. Focus on "
            "preserving critical information while reducing token count."
        )
        system_msg = Msg(name="system", role="system", content=system_content)
        prompt_msg = Msg(name="user", role="user", content=prompt)
        formatted = self.formatter.format(system_msg, prompt_msg)
        response = await self.chat_model(messages=formatted)
        summary = response.text if hasattr(response, "text") else str(response)

        return summary

    @staticmethod
    def _build_compact_prompt(
        conversation: str,
        previous_summary: str,
        language: str,
    ) -> str:
        """Build the structured compaction prompt."""
        if language == "zh":
            if previous_summary:
                prompt = (
                    f"<conversation>\n{conversation}\n</conversation>\n\n"
                    f"以上消息是需要整合到现有摘要中的新对话内容，"
                    f"现有摘要位于<previous-summary>标签中。\n\n"
                    f"<previous-summary>\n{previous_summary}\n"
                    f"</previous-summary>\n\n"
                    f"用新信息更新现有的结构化摘要。规则：\n"
                    f"- 保留来自先前摘要的所有现有信息\n"
                    f"- 从新消息中添加新的进展、决策和上下文\n"
                    f"- 更新进度部分：当完成时将项目从'进行中'移到'已完成'\n"
                    f"- 根据已完成的内容更新'下一步'\n"
                    f"- 保留确切的文件路径、函数名称和错误消息\n"
                    f"- 如果某些内容不再相关，您可以删除它\n\n"
                )
            else:
                prompt = (
                    f"<conversation>\n{conversation}\n</conversation>\n\n"
                    f"上述消息是一场需要总结的对话。创建一个结构化的"
                    f"上下文检查点摘要，以便另一个LLM可以用来继续工作。\n\n"
                )
            prompt += (
                f"使用此确切格式：\n\n"
                f"## 目标\n"
                f"[用户试图完成什么？如果会话涵盖不同任务，"
                f"可以有多个项目。]\n\n"
                f"## 约束和偏好\n"
                f"- [任何用户提到的约束、偏好或要求]\n"
                f'- [或者如果没有提到则为"(none)"]\n\n'
                f"## 进展\n"
                f"### 已完成\n"
                f"- [x] [已完成的任务/更改]\n\n"
                f"### 进行中\n"
                f"- [ ] [当前工作]\n\n"
                f"### 阻塞\n"
                f"- [如果有任何阻碍进展的问题]\n\n"
                f"## 关键决策\n"
                f"- **[决策]**: [简短理由]\n\n"
                f"## 下一步\n"
                f"1. [接下来应该发生的事情的有序列表]\n\n"
                f"## 关键上下文\n"
                f"- [任何继续工作所需的数据、示例或参考资料]\n"
                f'- [或者如果不适用则为"(none)"]\n\n'
                f"保持每个部分简洁。"
                f"保留确切的文件路径、函数名称和错误消息。"
            )
        else:
            if previous_summary:
                prompt = (
                    f"<conversation>\n{conversation}\n</conversation>\n\n"
                    f"The messages above are NEW conversation messages to "
                    f"incorporate into the existing summary provided in "
                    f"<previous-summary> tags.\n\n"
                    f"<previous-summary>\n{previous_summary}\n"
                    f"</previous-summary>\n\n"
                    f"Update the existing structured summary with new "
                    f"information. RULES:\n"
                    f"- PRESERVE all existing information from the "
                    f"previous summary\n"
                    f"- ADD new progress, decisions, and context from "
                    f"the new messages\n"
                    f"- UPDATE the Progress section: move items from "
                    f'"In Progress" to "Done" when completed\n'
                    f'- UPDATE "Next Steps" based on what was '
                    f"accomplished\n"
                    f"- PRESERVE exact file paths, function names, "
                    f"and error messages\n"
                    f"- If something is no longer relevant, you may "
                    f"remove it\n\n"
                )
            else:
                prompt = (
                    f"<conversation>\n{conversation}\n</conversation>\n\n"
                    f"The messages above are a conversation to summarize. "
                    f"Create a structured context checkpoint summary that "
                    f"another LLM will use to continue the work.\n\n"
                )
            prompt += (
                f"Use this EXACT format:\n\n"
                f"## Goal\n"
                f"[What is the user trying to accomplish? Can be multiple "
                f"items if the session covers different tasks.]\n\n"
                f"## Constraints & Preferences\n"
                f"- [Any constraints, preferences, or requirements "
                f"mentioned by user]\n"
                f'- [Or "(none)" if none were mentioned]\n\n'
                f"## Progress\n"
                f"### Done\n"
                f"- [x] [Completed tasks/changes]\n\n"
                f"### In Progress\n"
                f"- [ ] [Current work]\n\n"
                f"### Blocked\n"
                f"- [Issues preventing progress, if any]\n\n"
                f"## Key Decisions\n"
                f"- **[Decision]**: [Brief rationale]\n\n"
                f"## Next Steps\n"
                f"1. [Ordered list of what should happen next]\n\n"
                f"## Critical Context\n"
                f"- [Any data, examples, or references needed to "
                f"continue]\n"
                f'- [Or "(none)" if not applicable]\n\n'
                f"Keep each section concise. Preserve exact file paths, "
                f"function names, and error messages."
            )
        return prompt

    async def summary_memory(
        self,
        messages: list[Msg],
        **kwargs: Any,
    ) -> str:
        """Persist user messages to ADBPG long-term memory.

        Sends each user message individually to ADBPG so that the
        server-side LLM extracts memories from a single message at a
        time instead of the entire conversation history.  No local LLM
        call — compression is handled by ``compact_memory``.
        """
        if self._client is not None:
            user_messages = self._filter_user_messages(messages)
            if user_messages:
                for single in user_messages:
                    self._fire_and_forget_add([single])
                return (
                    f"Persisted {len(user_messages)} user message(s) "
                    f"to ADBPG for agent '{self.agent_id}'."
                )
        return "No messages persisted (ADBPG client not available)."

    async def check_context(
        self,
        messages: list[Msg],
        memory_compact_threshold: int,
        memory_compact_reserve: int,
        as_token_counter: Any = None,
        **kwargs: Any,
    ) -> tuple[list[Msg], list[Msg], bool]:
        """Check context size and auto-retrieve ADBPG long-term memories.

        Compatible with v0.10.0 MemoryCompactionHook which passes
        ``as_token_counter`` instead of ``token_counter``.
        """
        token_counter = as_token_counter
        if not messages:
            return [], [], True

        # Persist only the latest user message to ADBPG long-term
        # memory on each conversation turn.  Earlier messages are
        # either already persisted or will be covered by compaction.
        latest_user_msg: Msg | None = None
        for msg in reversed(messages):
            if msg.role == "user":
                latest_user_msg = msg
                break

        if (
            latest_user_msg is not None
            and latest_user_msg.id not in self._persisted_msg_ids
        ):
            self.add_async_summary_task([latest_user_msg])
            self._persisted_msg_ids.add(latest_user_msg.id)
            # Reset auto-retrieve flag for the new conversation turn
            self._auto_retrieved = False

        # Auto-retrieve relevant long-term memories from ADBPG
        if self._client is not None:
            self._auto_retrieve_memories(messages)

        # Count tokens for each message
        msg_tokens: list[int] = []
        total_tokens = 0
        for msg in messages:
            text = (
                msg.get_text_content()
                if hasattr(msg, "get_text_content")
                else str(msg.content)
            )
            if not text:
                text = ""
            try:
                count = len(token_counter.tokenizer.encode(text))
            except Exception:
                count = len(text.encode("utf-8")) // 4
            msg_tokens.append(count)
            total_tokens += count

        if total_tokens <= memory_compact_threshold:
            return [], messages, True

        # Split: keep recent messages within reserve, compact the rest
        kept_tokens = 0
        split_idx = len(messages)
        for i in range(len(messages) - 1, -1, -1):
            if kept_tokens + msg_tokens[i] > memory_compact_reserve:
                break
            kept_tokens += msg_tokens[i]
            split_idx = i

        messages_to_compact = messages[:split_idx]
        kept_messages = messages[split_idx:]
        is_valid = check_valid_messages(kept_messages)
        return messages_to_compact, kept_messages, is_valid

    async def compact_tool_result(
        self,
        messages: list[Msg],
        recent_n: int = 1,
        old_max_bytes: int = 1000,
        recent_max_bytes: int = 30000,
        retention_days: int = 3,
        **kwargs: Any,
    ) -> None:
        """Compact verbose tool-call results in messages.

        Supports ``summarize`` (default) and ``truncate`` modes via
        ``ADBPG_TOOL_COMPACT_MODE`` env var. Compatible with v0.10.0
        MemoryCompactionHook parameter signature.
        """
        compact_mode = "summarize"
        max_summary_len = 500
        if self._adbpg_runtime_config is not None:
            compact_mode = self._adbpg_runtime_config.tool_compact_mode
            max_summary_len = self._adbpg_runtime_config.tool_compact_max_len

        # Split messages into old / recent based on recent_n,
        # mirroring reme ToolResultCompactor behaviour.
        split_index = max(0, len(messages) - recent_n)

        for idx, msg in enumerate(messages):
            if not hasattr(msg, "content") or not isinstance(
                msg.content,
                list,
            ):
                continue

            # Recent messages use the more lenient recent_max_bytes
            threshold = (
                recent_max_bytes if idx >= split_index else old_max_bytes
            )

            for i, block in enumerate(msg.content):
                if isinstance(block, dict):
                    if block.get("type") != "tool_result":
                        continue
                    output = block.get("output", "")
                    if isinstance(output, str) and len(output) > threshold:
                        block["output"] = await self._compact_text(
                            output,
                            compact_mode,
                            max_summary_len,
                            block.get("name", "unknown"),
                        )
                    elif isinstance(output, list):
                        for sub in output:
                            if isinstance(sub, dict):
                                text = sub.get("text", "")
                                if (
                                    isinstance(text, str)
                                    and len(text) > threshold
                                ):
                                    sub["text"] = await self._compact_text(
                                        text,
                                        compact_mode,
                                        max_summary_len,
                                        block.get("name", "unknown"),
                                    )
                elif (
                    hasattr(block, "type")
                    and getattr(block, "type", None) == "tool_result"
                ):
                    text = getattr(block, "text", "") or ""
                    if len(text) > threshold:
                        compacted = await self._compact_text(
                            text,
                            compact_mode,
                            max_summary_len,
                            getattr(block, "name", "unknown"),
                        )
                        try:
                            block.text = compacted
                        except (AttributeError, TypeError):
                            new_block = {
                                "type": "tool_result",
                                "text": compacted,
                            }
                            for k in ("id", "name"):
                                val = getattr(block, k, None)
                                if val is not None:
                                    new_block[k] = val
                            msg.content[i] = new_block

    async def _compact_text(
        self,
        text: str,
        mode: str,
        max_len: int,
        tool_name: str,
    ) -> str:
        """Compact a single text string via truncation or LLM summary."""
        if mode == "summarize":
            return await self._summarize_tool_output(
                text,
                max_len,
                tool_name,
            )
        keep = max_len // 2
        return text[:keep] + "\n...[truncated]...\n" + text[-keep:]

    async def _summarize_tool_output(
        self,
        text: str,
        max_len: int,
        tool_name: str,
    ) -> str:
        """Use the chat model to summarize a tool output."""
        try:
            self.prepare_model_formatter()
            agent_config = load_agent_config(self.agent_id)
            language = agent_config.language

            if language == "zh":
                prompt = (
                    f"以下是工具 `{tool_name}` 的输出结果。"
                    f"请将其压缩为不超过 {max_len} 字符的简洁摘要。\n"
                    f"保留关键数据、错误信息和结论，去除冗余细节。\n\n"
                    f"工具输出:\n{text}\n\n请生成简洁摘要:"
                )
            else:
                prompt = (
                    f"The following is the output of tool `{tool_name}`. "
                    f"Compress it into a concise summary of at most "
                    f"{max_len} characters.\n"
                    f"Preserve key data, error messages, and conclusions.\n\n"
                    f"Tool output:\n{text}\n\nConcise summary:"
                )

            prompt_msg = Msg(name="user", role="user", content=prompt)
            formatted = self.formatter.format(prompt_msg)
            response = await self.chat_model(messages=formatted)
            summary = (
                response.text if hasattr(response, "text") else str(response)
            )
            if len(summary) > max_len:
                summary = summary[:max_len] + "..."
            return f"[Tool output summarized]\n{summary}"
        except Exception as e:
            logger.warning(
                "LLM tool-output summarization failed for %s: %s, "
                "falling back to truncation.",
                tool_name,
                e,
            )
            keep = max_len // 2
            return text[:keep] + "\n...[truncated]...\n" + text[-keep:]

    def _search_local_memory_files(
        self,
        query: str,
        max_results: int = 3,
    ) -> list[tuple[str, str]]:
        """Keyword-search ``MEMORY.md`` and ``memory/*.md`` files.

        Splits each file into paragraphs (double-newline separated),
        scores them by how many query tokens appear, and returns the
        top *max_results* hits as ``(relative_path, snippet)`` tuples.
        """
        workspace = Path(self.working_dir).expanduser()
        candidates: list[Path] = []

        # MEMORY.md in workspace root
        memory_md = workspace / "MEMORY.md"
        if memory_md.is_file():
            candidates.append(memory_md)

        # memory/*.md
        memory_dir = workspace / "memory"
        if memory_dir.is_dir():
            candidates.extend(sorted(memory_dir.glob("*.md")))

        if not candidates:
            return []

        # Tokenise query into lowercase keywords (>= 2 chars)
        tokens = {t for t in query.lower().split() if len(t) >= 2}
        if not tokens:
            return []

        scored: list[tuple[float, str, str]] = []
        for filepath in candidates:
            try:
                text = filepath.read_text(encoding="utf-8")
            except Exception:
                continue
            # Split into paragraphs
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            for para in paragraphs:
                lower = para.lower()
                hits = sum(1 for t in tokens if t in lower)
                if hits == 0:
                    continue
                score = hits / len(tokens)
                rel_path = str(filepath.relative_to(workspace))
                # Truncate long paragraphs
                snippet = para if len(para) <= 500 else para[:500] + "..."
                scored.append((score, rel_path, snippet))

        # Sort by score descending, take top N
        scored.sort(key=lambda x: x[0], reverse=True)
        return [(path, snippet) for _, path, snippet in scored[:max_results]]

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0.1,
    ) -> ToolResponse:
        """Search memories from both ADBPG and local memory files.

        Combines results from two sources:
        1. ADBPG database (semantic search via ``adbpg_llm_memory.search``)
        2. Local ``MEMORY.md`` and ``memory/*.md`` files (keyword matching)

        Results are merged with ADBPG results first (higher quality),
        followed by local file matches, capped at *max_results*.
        """
        parts: list[str] = []

        # --- Source 1: ADBPG database search ---
        if self._client is not None:
            try:
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(
                    None,
                    lambda: self._client.search_memory(
                        query=query,
                        user_id=self._effective_user_id,
                        agent_id=self._effective_agent_id,
                        limit=max_results,
                    ),
                )
                for item in results or []:
                    content = item.get("content", item.get("memory", ""))
                    score = item.get("score", 0)
                    if score < min_score or not content:
                        continue
                    idx = len(parts) + 1
                    parts.append(
                        f"[{idx}] (adbpg, score: {score:.2f})\n{content}",
                    )
            except Exception as e:
                logger.warning("ADBPG memory search failed: %s", e)

        # --- Source 2: Local memory files (keyword match) ---
        try:
            local_hits = self._search_local_memory_files(
                query,
                max_results=max(max_results - len(parts), 3),
            )
            for filepath, snippet in local_hits:
                idx = len(parts) + 1
                parts.append(f"[{idx}] (file: {filepath})\n{snippet}")
        except Exception as e:
            logger.warning("Local memory file search failed: %s", e)

        if not parts:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text="No relevant memories found.",
                    ),
                ],
            )

        # Cap at max_results
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="\n\n".join(parts[:max_results]),
                ),
            ],
        )

    def get_in_memory_memory(self, **kwargs: Any) -> ADBPGInMemoryMemory:
        """Return a fresh in-memory memory instance for each session.

        A new ``ADBPGInMemoryMemory`` is created on every call so that
        the caller (``CoPawAgent``) starts with a clean message store.
        This prevents message leakage between sessions that share the
        same ``ADBPGMemoryManager`` singleton.

        Per-session tracking state (``_persisted_msg_ids`` and
        ``_auto_retrieved``) is also reset so that long-term memory
        retrieval and persistence work correctly for the new session.
        """
        self._in_memory_memory = ADBPGInMemoryMemory()
        self._persisted_msg_ids.clear()
        self._auto_retrieved = False
        return self._in_memory_memory


# ---------------------------------------------------------------------------
# Utility: strip local-file memory instructions from AGENTS.md
# ---------------------------------------------------------------------------

# Regex: match "## 记忆" or "## Memory" H2 section (including all H3
# sub-sections) up to the next H2 heading or end of file.
_LOCAL_MEMORY_SECTION_RE = re.compile(
    r"(?m)^## (?:记忆|Memory)\s*\n(?:.*?)(?=\n## |\Z)",
    re.DOTALL,
)


def strip_local_memory_from_agents_md(workspace_dir: Path) -> None:
    """Remove the local-file memory section from AGENTS.md.

    Reads AGENTS.md, strips the "## 记忆" / "## Memory" section that
    instructs the agent to use write_file/read_file for memory, and
    writes the result back.  No-op if the file doesn't exist or the
    section is not found.
    """
    agents_md = workspace_dir / "AGENTS.md"
    if not agents_md.exists():
        return
    try:
        content = agents_md.read_text(encoding="utf-8")
        new_content = _LOCAL_MEMORY_SECTION_RE.sub("", content)
        if new_content != content:
            # Clean up excessive blank lines
            new_content = re.sub(r"\n{3,}", "\n\n", new_content).strip()
            new_content += "\n"
            agents_md.write_text(new_content, encoding="utf-8")
            logger.info("Stripped local memory section from AGENTS.md")
    except Exception as e:
        logger.warning("Failed to strip local memory from AGENTS.md: %s", e)
