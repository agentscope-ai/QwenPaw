# -*- coding: utf-8 -*-
# pylint: disable=too-many-nested-blocks,too-many-branches
# pylint: disable=too-many-return-statements,too-many-statements
"""Context manager for agents with compaction support."""
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Set

from agentscope.agent import ReActAgent
from agentscope.formatter import FormatterBase
from agentscope.message import Msg, TextBlock, ToolResultBlock, ToolUseBlock
from agentscope.model import ChatModelBase

from .agent_context import AgentContext
from .as_msg_handler import AsMsgHandler
from .base_context_manager import BaseContextManager, context_registry
from .compactor_prompts import (
    INITIAL_USER_MESSAGE_EN,
    INITIAL_USER_MESSAGE_ZH,
    SYSTEM_PROMPT_EN,
    SYSTEM_PROMPT_ZH,
    UPDATE_USER_MESSAGE_EN,
    UPDATE_USER_MESSAGE_ZH,
)
from ..model_factory import create_model_and_formatter
from ..tools.utils import truncate_text_output, DEFAULT_MAX_BYTES
from ..utils import check_valid_messages, get_token_counter
from ..utils.estimate_token_counter import EstimatedTokenCounter
from ...config.config import load_agent_config
from ...constant import MEMORY_COMPACT_KEEP_RECENT, TRUNCATION_NOTICE_MARKER

if TYPE_CHECKING:
    from ..react_agent import QwenPawAgent

logger = logging.getLogger(__name__)


@context_registry.register("light")
class LightContextManager(BaseContextManager):
    """Context manager for agents with compaction support.

    Handles conversation context compaction and the agent context object.

    Responsibilities:
    - Tool-result compaction via _compact_tool_result()
    - Context-size checking via _check_context()
    - Message compaction via _compact_context()
    - Agent context retrieval via get_agent_context()
    """

    def __init__(self, working_dir: str, agent_id: str):
        """Initialize context manager.

        Args:
            working_dir: Working directory for context storage.
            agent_id: Agent ID for config loading.
        """
        super().__init__(working_dir=working_dir, agent_id=agent_id)
        logger.info(
            f"LightContextManager init: "
            f"agent_id={agent_id}, working_dir={working_dir}",
        )

    # ------------------------------------------------------------------
    # BaseContextManager interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the context manager lifecycle."""

    async def close(self) -> bool:
        """Close context manager and cleanup expired tool result files."""
        logger.info(f"LightContextManager closing: agent_id={self.agent_id}")
        self._cleanup_expired_tool_result_files()
        logger.info(f"LightContextManager closed: agent_id={self.agent_id}")
        return True

    def _cleanup_expired_tool_result_files(self) -> int:
        """Clean up tool result files older than retention_days.

        Returns:
            Number of files successfully deleted.
        """
        agent_config = load_agent_config(self.agent_id)
        lcc = agent_config.running.light_context_config
        trc = lcc.tool_result_pruning_config
        tool_result_dir = Path(self.working_dir) / trc.tool_results_cache
        retention_days = trc.offload_retention_days

        if not tool_result_dir.exists():
            return 0

        cutoff = datetime.now() - timedelta(days=retention_days)
        deleted = failed = 0

        for fp in tool_result_dir.glob("*.txt"):
            try:
                stat = os.stat(fp)
                if sys.platform == "win32":
                    ts = stat.st_ctime  # creation time on Windows
                else:
                    ts = getattr(
                        stat,
                        "st_birthtime",
                        stat.st_mtime,
                    )  # macOS/BSD; Linux fallback to mtime
                if datetime.fromtimestamp(ts) < cutoff:
                    fp.unlink()
                    deleted += 1
            except FileNotFoundError:
                pass  # deleted by another process between glob and stat/unlink
            except Exception as e:
                failed += 1
                logger.warning("Failed to delete %s: %s", fp, e)

        if deleted or failed:
            logger.info(
                "Cleaned up %d expired tool result files (%d failed)",
                deleted,
                failed,
            )
        return deleted

    def _truncate_tool_result(
        self,
        content: str,
        max_bytes: int,
        encoding: str = "utf-8",
    ) -> str:
        """Truncate tool result content, saving full content to file if needed.

        Args:
            content: The content to truncate.
            max_bytes: Maximum bytes allowed.
            encoding: Character encoding.

        Returns:
            Truncated content with notice if truncated,
            or original if under limit.
        """
        if not content:
            return content

        # Already truncated content - retruncate with new limit
        if TRUNCATION_NOTICE_MARKER in content:
            return truncate_text_output(
                content,
                max_bytes=max_bytes,
                encoding=encoding,
            )

        # Check if content fits within limit (with small slack)
        try:
            content_bytes = len(content.encode(encoding))
        except UnicodeEncodeError as e:
            logger.warning("Failed to encode content: %s", e)
            return content

        if content_bytes <= max_bytes + 100:
            return content

        # Save full content to file
        agent_config = load_agent_config(self.agent_id)
        lcc = agent_config.running.light_context_config
        trc = lcc.tool_result_pruning_config
        tool_result_dir = Path(self.working_dir) / trc.tool_results_cache

        try:
            tool_result_dir.mkdir(parents=True, exist_ok=True)
            fp = tool_result_dir / f"{uuid.uuid4().hex}.txt"
            fp.write_text(content, encoding=encoding)
            saved_path = str(fp)
        except OSError as e:
            logger.exception(f"Failed to save tool result to file: {e}")
            # Fallback: truncate without saving
            return truncate_text_output(
                content,
                max_bytes=max_bytes,
                encoding=encoding,
            )

        # Truncate and include file path in notice
        return truncate_text_output(
            content,
            start_line=1,
            total_lines=content.count("\n") + 1,
            max_bytes=max_bytes,
            file_path=saved_path,
            encoding=encoding,
        )

    def _compact_output(
        self,
        output: str | list[dict],
        max_bytes: int,
        encoding: str = "utf-8",
    ) -> str | list[dict]:
        """Compact output by truncating to max_bytes.

        Args:
            output: The output to compact (str or list[dict]).
            max_bytes: Maximum bytes allowed.
            encoding: Character encoding.

        Returns:
            Compacted output.
        """
        if isinstance(output, str):
            return self._truncate_tool_result(output, max_bytes, encoding)
        if isinstance(output, list):
            for block in output:
                if isinstance(block, dict) and block.get("type") == "text":
                    block["text"] = self._truncate_tool_result(
                        block.get("text", ""),
                        max_bytes,
                        encoding,
                    )
        return output

    async def _compact_tool_result(
        self,
        messages: list[Msg],
        recent_n: int = 1,
        old_max_bytes: int = 3000,
        recent_max_bytes: int = DEFAULT_MAX_BYTES,
        **_kwargs,
    ) -> list[Msg]:
        """Process all messages, truncating large tool results.

        Args:
            messages: List of messages to process.
            recent_n: Number of recent messages to treat with recent_max_bytes.
            old_max_bytes: Maximum bytes for older tool results.
            recent_max_bytes: Maximum bytes for recent tool results.
            retention_days: Days to retain offloaded files
                (unused here, set in init).

        Returns:
            Processed messages list.
        """
        if not messages:
            return messages

        # Count recent tool_result messages from the end
        recent_count = 0
        for msg in reversed(messages):
            if not isinstance(msg.content, list) or not any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in msg.content
            ):
                break
            recent_count += 1
        split_index = max(0, len(messages) - max(recent_count, recent_n))

        # Detect tool_use IDs for exempt file extensions and tool names
        exempt_tool_ids: Set[str] = set()
        try:
            # Load exempt lists from config
            agent_config = load_agent_config(self.agent_id)
            lcc = agent_config.running.light_context_config
            trc = lcc.tool_result_pruning_config
            exempt_extensions = set(
                ext.lower() for ext in trc.exempt_file_extensions
            )
            exempt_tools = set(name.lower() for name in trc.exempt_tool_names)

            for msg in messages:
                if not isinstance(msg.content, list):
                    continue

                for block in msg.content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_use"
                    ):
                        tool_id = block.get("id", "")
                        if not tool_id:
                            continue

                        tool_name = block.get("name", "").lower()
                        raw_input = (block.get("raw_input") or "").lower()

                        # Check if tool name is in exempt list
                        if tool_name in exempt_tools:
                            exempt_tool_ids.add(tool_id)
                            continue

                        # Check if file extension is in exempt list
                        # for read_file
                        if tool_name == "read_file":
                            for ext in exempt_extensions:
                                if ext in raw_input:
                                    exempt_tool_ids.add(tool_id)
                                    break
        except Exception as e:
            logger.warning("Failed to detect exempt tool ids: %s", e)

        # Compact tool_result blocks
        for idx, msg in enumerate(messages):
            if not isinstance(msg.content, list):
                continue
            is_recent = idx >= split_index
            max_bytes = recent_max_bytes if is_recent else old_max_bytes

            for block in msg.content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_result"
                ):
                    tool_id = block.get("id", "")
                    output = block.get("output")
                    if not output:
                        continue

                    # Use recent_max_bytes for exempt tool results
                    effective_max_bytes = (
                        recent_max_bytes
                        if tool_id in exempt_tool_ids
                        else max_bytes
                    )
                    block["output"] = self._compact_output(
                        output,
                        effective_max_bytes,
                    )

        return messages

    async def _check_context(
        self,
        messages: list[Msg],
        context_compact_threshold: int,
        context_compact_reserve: int,
        as_token_counter: EstimatedTokenCounter,
    ) -> tuple[list[Msg], list[Msg], bool]:
        """Check context size and determine if compaction is needed.

        Uses AsMsgHandler to analyze messages and split them into
        messages_to_compact and messages_to_keep based on token thresholds.

        Args:
            messages: List of conversation messages to check.
            context_compact_threshold: Token threshold triggering compaction.
            context_compact_reserve: Token limit for messages to keep.
            as_token_counter: Token counter instance.

        Returns:
            Tuple of (messages_to_compact, messages_to_keep, is_valid):
            - messages_to_compact: Older messages exceeding reserve limit.
            - messages_to_keep: Recent messages within reserve limit.
            - is_valid: True if tool_use/tool_result ids are aligned.
        """
        msg_handler = AsMsgHandler(as_token_counter)
        return await msg_handler.context_check(
            messages=messages,
            context_compact_threshold=context_compact_threshold,
            context_compact_reserve=context_compact_reserve,
        )

    @staticmethod
    def _is_valid_summary(content: str) -> bool:
        """Check if the summary content is valid.

        Args:
            content: The summary content to validate.

        Returns:
            True if valid, False otherwise.
        """
        if not content or not content.strip():
            return False
        if "##" not in content:
            return False
        return True

    async def _compact_context(
        self,
        messages: list[Msg],
        previous_summary: str = "",
        extra_instruction: str = "",
        as_llm: ChatModelBase | None = None,
        as_llm_formatter: FormatterBase | None = None,
        as_token_counter: EstimatedTokenCounter | None = None,
        language: str = "en",
        max_input_length: int = 100000,
        compact_ratio: float = 0.5,
        add_thinking_block: bool = True,
        **_kwargs,
    ) -> dict:
        """Compact messages into a condensed summary.

        Args:
            messages: List of messages to compact.
            previous_summary: Previous summary to update.
            extra_instruction: Extra instruction for compaction.
            as_llm: LLM model instance.
            as_llm_formatter: Formatter for LLM output.
            as_token_counter: Token counter instance.
            language: Language for prompts ("en" or "zh").
            max_input_length: Maximum input length for token calculation.
            compact_ratio: Ratio for compact threshold calculation.
            add_thinking_block: Whether to include thinking blocks.

        Returns:
            Dict with keys: user_message, history_compact, is_valid.
        """
        if not messages:
            return {
                "user_message": "",
                "history_compact": "",
                "is_valid": False,
            }

        agent_config = load_agent_config(self.agent_id)

        # Use provided token counter or get from config
        token_counter = as_token_counter or get_token_counter(agent_config)

        msg_handler = AsMsgHandler(token_counter)
        before_token_count = await msg_handler.count_msgs_token(messages)

        # Calculate compact threshold
        memory_compact_threshold = int(max_input_length * compact_ratio)

        history_formatted_str: str = await msg_handler.format_msgs_to_str(
            messages=messages,
            context_compact_threshold=memory_compact_threshold,
            include_thinking=add_thinking_block,
        )
        after_token_count = await msg_handler.count_str_token(
            history_formatted_str,
        )
        logger.info(
            f"Compactor before_token_count={before_token_count} "
            f"after_token_count={after_token_count}",
        )

        if not history_formatted_str:
            logger.warning(f"No history to compact. messages={messages}")
            return {
                "user_message": "",
                "history_compact": "",
                "is_valid": False,
            }

        # Select prompts based on language
        is_zh = language.lower() == "zh"
        system_prompt = SYSTEM_PROMPT_ZH if is_zh else SYSTEM_PROMPT_EN
        initial_user_msg = (
            INITIAL_USER_MESSAGE_ZH if is_zh else INITIAL_USER_MESSAGE_EN
        )
        update_user_msg = (
            UPDATE_USER_MESSAGE_ZH if is_zh else UPDATE_USER_MESSAGE_EN
        )

        # Create ReActAgent for compaction
        agent = ReActAgent(
            name="qwenpaw_compactor",
            model=as_llm,
            sys_prompt=system_prompt,
            formatter=as_llm_formatter,
        )
        agent.set_console_output_enabled(False)

        # Build user message
        if previous_summary:
            user_message: str = (
                f"# conversation\n{history_formatted_str}\n\n"
                f"# previous-summary\n{previous_summary}\n\n{update_user_msg}"
            )
        else:
            user_message = (
                f"# conversation\n{history_formatted_str}\n\n"
                f"{initial_user_msg}"
            )

        if extra_instruction:
            user_message += f"\n\n# extra-instruction\n{extra_instruction}"

        logger.info(
            f"Compactor sys_prompt={agent.sys_prompt} "
            f"user_message={user_message[:500]}...",
        )

        compact_msg: Msg = await agent.reply(
            Msg(
                name="compactor",
                role="user",
                content=user_message,
            ),
        )

        history_compact: str = compact_msg.get_text_content() or ""
        is_valid: bool = self._is_valid_summary(history_compact)

        if not is_valid:
            logger.warning(
                f"Invalid summary result: {history_compact[:200]}...",
            )
            return {
                "user_message": user_message,
                "history_compact": history_compact,
                "is_valid": False,
            }

        logger.info(f"Compactor Result:\n{history_compact[:500]}...")

        return {
            "user_message": user_message,
            "history_compact": history_compact,
            "is_valid": True,
        }

    async def compact_context(
        self,
        messages: list[Msg],
        previous_summary: str = "",
        extra_instruction: str = "",
    ) -> str:
        """Public interface for context compaction.

        Args:
            messages: List of messages to compact.
            previous_summary: Previous summary to update (if exists).
            extra_instruction: Extra instruction for compaction.

        Returns:
            Compacted summary string, or empty string if compaction failed.
        """
        try:
            agent_config = load_agent_config(self.agent_id)
            running_config = agent_config.running
            ccc = running_config.light_context_config.context_compact_config

            # Create model and formatter for compaction
            model, formatter = create_model_and_formatter(self.agent_id)

            result = await self._compact_context(
                messages=messages,
                previous_summary=previous_summary,
                extra_instruction=extra_instruction,
                as_llm=model,
                as_llm_formatter=formatter,
                as_token_counter=get_token_counter(agent_config),
                language=agent_config.language,
                max_input_length=running_config.max_input_length,
                compact_ratio=ccc.compact_threshold_ratio,
                add_thinking_block=ccc.compact_with_thinking_block,
            )
            if result.get("is_valid"):
                return result.get("history_compact", "")
        except Exception as e:
            logger.warning("compact_context failed: %s", e)
        return ""

    # ------------------------------------------------------------------
    # Agent lifecycle hook methods
    # ------------------------------------------------------------------

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

        When ``auto_memory_search_config.enabled`` is enabled, calls
        ``memory_manager.retrieve()`` which returns a string of memory
        snippets. If non-empty, appends a synthetic tool-use / tool-result
        message pair carrying the content. Commands are skipped because
        ``reply()`` returns early before the ReAct loop runs.
        """
        msg = kwargs.get("msg")
        if msg is None:
            return None

        last_msg = msg[-1] if isinstance(msg, list) else msg
        query = (
            last_msg.get_text_content() if isinstance(last_msg, Msg) else None
        )

        # Commands are handled before the ReAct loop — skip memory search.
        command_handler = agent.command_handler
        if command_handler is not None and command_handler.is_command(query):
            return None

        agent_config = load_agent_config(self.agent_id)
        rlmc = agent_config.running.reme_light_memory_config
        ms = rlmc.auto_memory_search_config

        if not ms.enabled:
            return None

        memory_manager = agent.memory_manager
        if memory_manager is None:
            return None

        msgs = [msg] if isinstance(msg, Msg) else list(msg)

        try:
            retrieved_text = await memory_manager.retrieve(msgs)
        except BaseException as e:
            logger.warning(
                "memory_manager.retrieve failed, skipping e=%s",
                e,
            )
            return None

        if not retrieved_text:
            return None

        # Build query from the newest messages (same logic as retrieve)
        query_parts: list[str] = []
        total = 0
        for m in reversed(msgs):
            remaining = 100 - total
            if remaining <= 0:
                break
            text = (m.get_text_content() or "").strip()
            if not text:
                continue
            chunk = text[:remaining]
            query_parts.insert(0, chunk)
            total += len(chunk)
        query_str = " ".join(query_parts).strip() or query or ""

        _id = uuid.uuid4().hex
        max_results = ms.max_results
        min_score = ms.min_score
        tool_use_input = {
            "query": query_str,
            "max_results": max_results,
            "min_score": min_score,
        }

        assistant_msg = Msg(
            name=agent.name,
            role="assistant",
            content=[
                TextBlock(
                    type="text",
                    text="Let me search memory based on the user's query.",
                ),
                ToolUseBlock(
                    type="tool_use",
                    id=_id,
                    name="memory_search",
                    input=tool_use_input,
                    raw_input=json.dumps(tool_use_input, ensure_ascii=False),
                ),
            ],
        )

        content_blocks = [TextBlock(type="text", text=retrieved_text)]
        tool_result_msg = Msg(
            name=agent.name,
            role="system",
            content=[
                ToolResultBlock(
                    type="tool_result",
                    id=_id,
                    name="memory_search",
                    output=content_blocks,
                ),
            ],
        )

        return {**kwargs, "msg": msgs + [assistant_msg, tool_result_msg]}

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

            ccc = running_config.light_context_config.context_compact_config
            context_compact_threshold = int(
                running_config.max_input_length * ccc.compact_threshold_ratio,
            )
            context_compact_reserve = int(
                running_config.max_input_length * ccc.reserve_threshold_ratio,
            )
            left_compact_threshold = (
                context_compact_threshold - str_token_count
            )

            if left_compact_threshold <= 0:
                logger.warning(
                    "The context_compact_threshold is set too low; "
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
                context_compact_threshold=left_compact_threshold,
                context_compact_reserve=context_compact_reserve,
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

            ccc = running_config.light_context_config.context_compact_config
            if ccc.enabled:
                result = await self._compact_context(
                    messages=messages_to_compact,
                    previous_summary=memory.get_compressed_summary(),
                    as_llm=agent.model,
                    as_llm_formatter=agent.formatter,
                    as_token_counter=token_counter,
                    language=agent_config.language,
                    max_input_length=running_config.max_input_length,
                    compact_ratio=ccc.compact_threshold_ratio,
                    add_thinking_block=ccc.compact_with_thinking_block,
                )
                compact_content = (
                    result.get("history_compact", "")
                    if result.get("is_valid")
                    else ""
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

        return None

    async def post_acting(
        self,
        agent: "QwenPawAgent",
        kwargs: dict[str, Any],
        output: Any,
    ) -> Msg | None:
        """Truncate oversized tool-call results after each acting step."""
        try:
            agent_config = load_agent_config(self.agent_id)
            lcc = agent_config.running.light_context_config
            trc = lcc.tool_result_pruning_config
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

        return None

    async def post_reply(
        self,
        agent: "QwenPawAgent",
        kwargs: dict[str, Any],
        output: Any,
    ) -> Msg | None:
        """Auto memory periodically based on user query count.

        When ``auto_memory_interval`` is set (e.g., 2), this hook counts user
        messages in the memory and triggers auto memory every N queries.
        """
        try:
            memory_manager = agent.memory_manager
            if memory_manager is None:
                return None

            agent_config = load_agent_config(self.agent_id)
            rlmc = agent_config.running.reme_light_memory_config
            auto_memory_interval = rlmc.auto_memory_interval

            if auto_memory_interval is None or auto_memory_interval <= 0:
                return None

            memory = agent.memory
            # memory.content is list[tuple[Msg, marks]]
            user_msg_count = sum(
                1 for msg, _ in memory.content if msg.role == "user"
            )

            if (
                user_msg_count > 0
                and user_msg_count % auto_memory_interval == 0
            ):
                messages = await memory.get_memory(prepend_summary=False)
                if messages:
                    memory_manager.add_summarize_task(messages=messages)
        except Exception as e:
            logger.warning("post_reply hook failed: %s", e)

        return None

    def get_agent_context(self, **_kwargs) -> AgentContext:
        """Retrieve the agent context object with token counting support."""
        agent_config = load_agent_config(self.agent_id)
        dialog_path = os.path.join(
            self.working_dir,
            agent_config.running.light_context_config.dialog_path,
        )
        return AgentContext(
            token_counter=get_token_counter(agent_config),
            dialog_path=dialog_path,
        )
