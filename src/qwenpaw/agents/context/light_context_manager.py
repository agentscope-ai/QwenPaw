"""ReMeLight-backed context manager for agents."""
import asyncio
import json
import logging
import os
import uuid
from typing import TYPE_CHECKING, Any

from agentscope.message import Msg, TextBlock

from .base_context_manager import BaseContextManager, context_registry
from ..utils import check_valid_messages, get_token_counter
from ..utils.reme_mixin import ReMeLightMixin, _detect_memory_manager_backend
from ...config.config import load_agent_config
from ...constant import EnvVarLoader, MEMORY_COMPACT_KEEP_RECENT

if TYPE_CHECKING:
    from reme.memory.file_based.reme_in_memory_memory import ReMeInMemoryMemory

    from ..react_agent import QwenPawAgent

logger = logging.getLogger(__name__)


@context_registry.register("light")
class LightContextManager(ReMeLightMixin, BaseContextManager):
    """ReMeLight-backed context manager for agents.

    Handles conversation context compaction and the in-memory memory object.
    Delegates to a ``ReMeLight`` instance for all heavy lifting.

    Responsibilities:
    - Tool-result compaction via _compact_tool_result()
    - Context-size checking via _check_context()
    - Message compaction via _compact_context()
    - Context summarization via summarize_context()
    - In-memory memory retrieval via get_in_memory_memory()
    """

    def __init__(self, working_dir: str, agent_id: str):
        """Initialize with ReMeLight.

        Args:
            working_dir: Working directory for context storage.
            agent_id: Agent ID for config loading.
        """
        super().__init__(working_dir=working_dir, agent_id=agent_id)
        self._reme_version_ok: bool = self._check_reme_version()
        self._reme = None

        logger.info(
            f"LightContextManager init: "
            f"agent_id={agent_id}, working_dir={working_dir}",
        )

        memory_manager_backend = _detect_memory_manager_backend()

        from reme.reme_light import ReMeLight

        emb_config = self.get_embedding_config()
        vector_enabled = bool(emb_config["base_url"]) and bool(
            emb_config["model_name"],
        )

        log_cfg = {
            **emb_config,
            "api_key": self._mask_key(emb_config["api_key"]),
        }
        logger.info(
            f"Embedding config: {log_cfg}, vector_enabled={vector_enabled}",
        )

        fts_enabled = EnvVarLoader.get_bool("FTS_ENABLED", True)

        agent_config = load_agent_config(self.agent_id)

        store_name = "context"
        self._reme = ReMeLight(
            working_dir=working_dir,
            default_embedding_model_config=emb_config,
            default_file_store_config={
                "backend": memory_manager_backend,
                "store_name": store_name,
                "vector_enabled": vector_enabled,
                "fts_enabled": fts_enabled,
            },
            default_file_watcher_config={
                "rebuild_index_on_start": False,
                "recursive": agent_config.running.reme_light_memory_config.recursive_file_watcher,
            },
        )

    # ------------------------------------------------------------------
    # BaseContextManager interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the ReMeLight lifecycle."""
        self._warn_if_version_mismatch()
        if self._reme is None:
            return
        await self._reme.start()

    async def close(self) -> bool:
        """Close ReMeLight and perform cleanup."""
        self._warn_if_version_mismatch()
        logger.info(
            f"LightContextManager closing: agent_id={self.agent_id}",
        )
        if self._reme is None:
            return True
        result = await self._reme.close()
        logger.info(
            f"LightContextManager closed: "
            f"agent_id={self.agent_id}, result={result}",
        )
        return result

    async def _compact_tool_result(self, **kwargs):
        """Compact tool results by truncating large outputs."""
        self._warn_if_version_mismatch()
        if self._reme is None:
            return None
        return await self._reme.compact_tool_result(**kwargs)

    async def _check_context(self, **kwargs):
        """Check context size and determine if compaction is needed."""
        self._warn_if_version_mismatch()
        if self._reme is None:
            return None
        return await self._reme.check_context(**kwargs)

    async def _compact_context(
        self,
        messages: list[Msg],
        previous_summary: str = "",
        extra_instruction: str = "",
        as_llm: Any = None,
        as_llm_formatter: Any = None,
        **_kwargs,
    ) -> str:
        """Compact messages into a condensed summary.

        Returns the compacted string, or empty string on failure.
        """
        agent_config = load_agent_config(self.agent_id)
        cc = agent_config.running.light_context_config.context_compact_config

        compact_kwargs = dict(
            messages=messages,
            as_llm=as_llm,
            as_llm_formatter=as_llm_formatter,
            as_token_counter=get_token_counter(agent_config),
            language=agent_config.language,
            max_input_length=agent_config.running.max_input_length,
            compact_ratio=cc.compact_threshold_ratio,
            previous_summary=previous_summary,
            return_dict=True,
            add_thinking_block=cc.compact_with_thinking_block,
        )
        if extra_instruction:
            compact_kwargs["extra_instruction"] = extra_instruction

        result = await self._reme.compact_memory(**compact_kwargs)

        if isinstance(result, str):
            logger.error(
                "compact_context returned str instead of dict, "
                f"result: {result[:200]}... "
                "Please install the latest reme package.",
            )
            return result

        if not result.get("is_valid", True):
            unique_id = uuid.uuid4().hex[:8]
            filepath = os.path.join(
                agent_config.workspace_dir,
                f"compact_invalid_{unique_id}.json",
            )
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                logger.error(
                    f"Invalid compact result saved to {filepath}. "
                    f"user_msg: {result.get('user_message', '')[:200]}..., "
                    "history_compact: "
                    f"{result.get('history_compact', '')[:200]}...",
                )
                logger.error(
                    "Please upload the log to github issues",
                )
            except Exception as _e:
                logger.error(f"Failed to save invalid compact result: {_e}")
            return ""

        return result.get("history_compact", "")

    # ------------------------------------------------------------------
    # Agent lifecycle hook methods
    # ------------------------------------------------------------------

    _PRE_REASONING_REENTRANCY = "_ctx_pre_reasoning_running"
    _POST_ACTING_REENTRANCY = "_ctx_post_acting_running"

    @staticmethod
    async def _print_status_message(agent: "QwenPawAgent", text: str) -> None:
        msg = Msg(
            name=agent.name,
            role="assistant",
            content=[TextBlock(type="text", text=text)],
        )
        await agent.print(msg)

    async def pre_reply(
        self,
        agent: "QwenPawAgent",
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Augment ``msg`` with retrieved memory results before reply.

        When ``force_memory_search_config.enabled`` is enabled, calls
        ``memory_manager.retrieve()`` which appends a synthetic
        tool-use / tool-result message pair carrying the relevant memory
        snippets.  The augmented message list is returned as modified
        kwargs so ``reply()`` receives and stores the full context.
        Commands are skipped because ``reply()`` returns early before the
        ReAct loop runs.
        """
        msg = kwargs.get("msg")
        if msg is None:
            return None

        last_msg = msg[-1] if isinstance(msg, list) else msg
        query = last_msg.get_text_content() if isinstance(last_msg, Msg) else None

        # Commands are handled before the ReAct loop — skip memory search.
        command_handler = agent.command_handler
        if command_handler is not None and command_handler.is_command(query):
            return None

        agent_config = load_agent_config(self.agent_id)
        ms = agent_config.running.reme_light_memory_config.force_memory_search_config

        if not ms.enabled:
            return None

        memory_manager = agent.memory_manager
        if memory_manager is None:
            return None

        msgs = [msg] if isinstance(msg, Msg) else list(msg)

        try:
            augmented = await asyncio.wait_for(
                memory_manager.retrieve(msgs),
                timeout=ms.timeout,
            )
        except BaseException as e:
            logger.warning(
                "memory_manager.retrieve failed or timed out, skipping e=%s",
                e,
            )
            return None

        if len(augmented) > len(msgs):
            return {**kwargs, "msg": augmented}

        return None

    async def pre_reasoning(
        self,
        agent: "QwenPawAgent",
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Check context size and compact memory when threshold is exceeded.

        Mirrors the compaction logic from ``MemoryCompactionHook`` but
        excludes tool-result truncation, which is handled by
        ``post_acting``.
        """
        if getattr(agent, self._PRE_REASONING_REENTRANCY, False):
            return None
        setattr(agent, self._PRE_REASONING_REENTRANCY, True)

        try:
            memory_manager = agent.memory_manager
            if memory_manager is None:
                return None

            agent_config = load_agent_config(self.agent_id)
            running_config = agent_config.running
            token_counter = get_token_counter(agent_config)

            memory = agent.memory
            system_prompt = agent.sys_prompt
            compressed_summary = memory.get_compressed_summary()
            str_token_count = await token_counter.count(
                messages=[],
                text=(system_prompt or "") + (compressed_summary or ""),
            )

            memory_compact_threshold = int(
                running_config.max_input_length
                * running_config.light_context_config.context_compact_config.compact_threshold_ratio
            )
            memory_compact_reserve = int(
                running_config.max_input_length
                * running_config.light_context_config.context_compact_config.reserve_threshold_ratio
            )
            left_compact_threshold = memory_compact_threshold - str_token_count

            if left_compact_threshold <= 0:
                logger.warning(
                    "The memory_compact_threshold is set too low; "
                    "the combined token length of system_prompt and "
                    "compressed_summary exceeds the configured threshold. "
                    "Alternatively, you could use /clear to reset the context "
                    "and compressed_summary, ensuring the total remains "
                    "below the threshold.",
                )
                return None

            messages = await memory.get_memory(prepend_summary=False)

            (
                messages_to_compact,
                _,
                is_valid,
            ) = await self._check_context(
                messages=messages,
                memory_compact_threshold=left_compact_threshold,
                memory_compact_reserve=memory_compact_reserve,
                as_token_counter=token_counter,
            )

            if not messages_to_compact:
                return None

            if not is_valid:
                logger.warning(
                    "Please include the output of the /history command when "
                    "reporting the bug to the community. Invalid "
                    "messages=%s",
                    messages,
                )
                keep_length: int = MEMORY_COMPACT_KEEP_RECENT
                messages_length = len(messages)
                while keep_length > 0 and not check_valid_messages(
                    messages[max(messages_length - keep_length, 0) :],
                ):
                    keep_length -= 1

                if keep_length > 0:
                    messages_to_compact = messages[
                        : max(messages_length - keep_length, 0)
                    ]
                else:
                    messages_to_compact = messages

            if not messages_to_compact:
                return None

            if running_config.reme_light_memory_config.summarize_when_compact:
                memory_manager.add_summarize_task(
                    messages=messages_to_compact,
                )

            await self._print_status_message(
                agent,
                "🔄 Context compaction started...",
            )

            if running_config.light_context_config.context_compact_config.enabled:
                compact_content = await self._compact_context(
                    messages=messages_to_compact,
                    previous_summary=memory.get_compressed_summary(),
                    as_llm=agent.model,
                    as_llm_formatter=agent.formatter,
                )
                if not compact_content:
                    await self._print_status_message(
                        agent,
                        "⚠️ Context compaction failed.",
                    )
                else:
                    await self._print_status_message(
                        agent,
                        "✅ Context compaction completed",
                    )
            else:
                compact_content = ""
                await self._print_status_message(
                    agent,
                    "✅ Context compaction skipped",
                )

            updated_count = await memory.mark_messages_compressed(
                messages_to_compact,
            )
            logger.info(f"Marked {updated_count} messages as compacted")

            await memory.update_compressed_summary(compact_content)

        except Exception as e:
            logger.exception(
                "Failed to compact memory in pre_reasoning hook: %s",
                e,
                exc_info=True,
            )
        finally:
            setattr(agent, self._PRE_REASONING_REENTRANCY, False)

        return None

    async def post_acting(
        self,
        agent: "QwenPawAgent",
        kwargs: dict[str, Any],
        output: Any,
    ) -> Msg | None:
        """Truncate oversized tool-call results after each acting step."""
        if getattr(agent, self._POST_ACTING_REENTRANCY, False):
            return None
        setattr(agent, self._POST_ACTING_REENTRANCY, True)

        try:
            agent_config = load_agent_config(self.agent_id)
            trc = agent_config.running.light_context_config.tool_result_pruning_config
            if not trc.enabled:
                return None

            memory = agent.memory
            messages = await memory.get_memory(prepend_summary=False)
            await self._compact_tool_result(
                messages=messages,
                recent_n=trc.pruning_recent_n,
                old_max_bytes=trc.pruning_old_msg_max_bytes,
                recent_max_bytes=trc.pruning_recent_msg_max_bytes,
                retention_days=trc.offload_retention_days,
            )
        except Exception as e:
            logger.exception(
                "Failed to compact tool results in post_acting hook: %s",
                e,
                exc_info=True,
            )
        finally:
            setattr(agent, self._POST_ACTING_REENTRANCY, False)

        return None

    async def post_reply(
        self,
        agent: "QwenPawAgent",
        kwargs: dict[str, Any],
        output: Any,
    ) -> Msg | None:
        """Summarize memory periodically based on user query count.

        When ``summarize_interval`` is set (e.g., 2), this hook counts user
        messages in the memory and triggers summarization every N queries.
        """
        memory_manager = agent.memory_manager
        if memory_manager is None:
            return None

        agent_config = load_agent_config(self.agent_id)
        summarize_interval = agent_config.running.reme_light_memory_config.summarize_interval

        if summarize_interval is None or summarize_interval <= 0:
            return None

        memory = agent.memory
        # memory.content is list[tuple[Msg, marks]]
        user_msg_count = sum(
            1 for msg, _ in memory.content if msg.role == "user"
        )

        if user_msg_count > 0 and user_msg_count % summarize_interval == 0:
            messages = await memory.get_memory(prepend_summary=False)
            if messages:
                memory_manager.add_summarize_task(messages=messages)

        return None

    def get_in_memory_memory(self, **_kwargs) -> "ReMeInMemoryMemory":
        """Retrieve the in-memory memory object with token counting support."""
        self._warn_if_version_mismatch()
        if self._reme is None:
            return None
        agent_config = load_agent_config(self.agent_id)
        return self._reme.get_in_memory_memory(
            as_token_counter=get_token_counter(agent_config),
        )
