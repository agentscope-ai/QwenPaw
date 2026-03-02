# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches
"""Memory Manager for CoPaw agents.

Inherits from ReMeFs to provide memory management capabilities including:
- Message compaction and summarization
- Semantic memory search
- Memory file retrieval
"""
import asyncio
import datetime
import json
import logging
import os
import platform
from pathlib import Path
from typing import Any

from agentscope._utils._common import _save_base64_data
from agentscope.agent import ReActAgent
from agentscope.formatter import DashScopeChatFormatter
from agentscope.formatter._dashscope_formatter import (
    _format_dashscope_media_block,
    _reformat_messages,
)
from agentscope.formatter._formatter_base import FormatterBase
from agentscope.message import (
    ImageBlock,
    AudioBlock,
    VideoBlock,
    TextBlock,
    URLSource,
)
from agentscope.message import Msg
from agentscope.model import ChatModelBase
from agentscope.tool import ToolResponse, Toolkit

from ..tools import (
    read_file,
    write_file,
    edit_file,
)
from ..utils import safe_count_str_tokens
from ..utils.tool_message_utils import _truncate_text as _truncate_text_impl
from ...config.utils import load_config
from ...constant import MEMORY_COMPACT_RATIO

logger = logging.getLogger(__name__)

# Default max length for text truncation
_DEFAULT_MAX_FORMATTER_TEXT_LENGTH = 10000


def _truncate_text(text: str, max_length: int | None = None) -> str:
    """Truncate text to max length, keeping head and tail portions.

    Args:
        text: The text to truncate
        max_length: Maximum allowed length (from env or default 4000)

    Returns:
        Truncated text with middle replaced by [...truncated...]
    """
    if max_length is None:
        max_length = int(
            os.environ.get(
                "MAX_FORMATTER_TEXT_LENGTH",
                _DEFAULT_MAX_FORMATTER_TEXT_LENGTH,
            ),
        )
    return _truncate_text_impl(text, max_length)


class TimestampedDashScopeChatFormatter(DashScopeChatFormatter):
    """DashScope formatter that includes timestamp in formatted messages.

    Extends DashScopeChatFormatter to add the timestamp to each formatted
    message as a 'time_created' field. Also supports file blocks.
    """

    def __init__(self, memory_compact_threshold: int, **kwargs):
        super().__init__(**kwargs)
        self._memory_compact_threshold = memory_compact_threshold

    @staticmethod
    def convert_tool_result_to_string(
        output: str | list[dict],
    ) -> tuple[str, list[tuple[str, dict]]]:
        """Convert tool result to string with file block support.

        Extends base class to:
        - Support file blocks
        - Handle invalid blocks gracefully (log warning instead of raising)
        """
        if isinstance(output, str):
            return output, []

        textual_output = []
        multimodal_data = []

        for block in output:
            try:
                if not isinstance(block, dict) or "type" not in block:
                    logger.warning(
                        "Invalid block: %s, expected a dict with 'type' key, "
                        "skipped.",
                        block,
                    )
                    continue

                block_type = block["type"]

                if block_type == "text":
                    textual_output.append(block["text"])

                elif block_type in ["image", "audio", "video"]:
                    if "source" not in block:
                        logger.warning(
                            "Invalid %s block: %s, 'source' key is required, "
                            "skipped.",
                            block_type,
                            block,
                        )
                        continue

                    source = block["source"]
                    if source["type"] == "url":
                        textual_output.append(
                            f"The returned {block_type} can be found "
                            f"at: {source['url']}",
                        )
                        path_multimodal_file = source["url"]

                    elif source["type"] == "base64":
                        path_multimodal_file = _save_base64_data(
                            source["media_type"],
                            source["data"],
                        )
                        textual_output.append(
                            f"The returned {block_type} can be found "
                            f"at: {path_multimodal_file}",
                        )

                    else:
                        logger.warning(
                            "Invalid %s source type: %s, expected 'url' or "
                            "'base64', skipped.",
                            block_type,
                            source.get("type"),
                        )
                        continue

                    multimodal_data.append((path_multimodal_file, block))

                elif block_type == "file":
                    # Handle file blocks
                    file_path = block.get("path", "") or block.get("url", "")
                    file_name = block.get("name", file_path)

                    textual_output.append(
                        f"The returned file '{file_name}' "
                        f"can be found at: {file_path}",
                    )
                    multimodal_data.append((file_path, block))

                else:
                    # Unknown block type: log warning and discard
                    logger.warning(
                        "Unsupported block type '%s' in tool result, skipped.",
                        block_type,
                    )

            except Exception as e:
                logger.warning(
                    "Failed to process block %s: %s, skipped.",
                    block,
                    e,
                )

        if len(textual_output) == 0:
            return "", multimodal_data
        elif len(textual_output) == 1:
            return textual_output[0], multimodal_data
        else:
            return (
                "\n".join("- " + _ for _ in textual_output),
                multimodal_data,
            )

    # pylint: disable=too-many-statements,too-many-nested-blocks
    async def _format(
        self,
        msgs: list[Msg],
    ) -> list[dict[str, Any]]:
        """Format message objects into DashScope API format with timestamps.

        Messages are processed in reverse order (newest first) and older
        messages are skipped when token count exceeds memory_compact_threshold.

        Args:
            msgs (`list[Msg]`):
                The list of message objects to format.

        Returns:
            `list[dict[str, Any]]`:
                The formatted messages with  time_created fields.
        """
        # Import required modules from parent implementation

        self.assert_list_of_msgs(msgs)

        formatted_msgs: list[dict] = []
        total_token_count = 0

        # Process messages in reverse order (newest first)
        # Use index-based iteration to handle inserted messages
        i = len(msgs) - 1
        while i >= 0:
            msg = msgs[i]
            content_blocks: list[dict[str, Any]] = []
            tool_calls = []
            msg_token_count = 0

            for block in msg.get_content_blocks():
                typ = block.get("type")

                if typ == "text":
                    text_content = _truncate_text(block.get("text", ""))
                    content_blocks.append({"text": text_content})
                    msg_token_count += safe_count_str_tokens(text_content)

                elif typ in ["image", "audio", "video"]:
                    content_blocks.append(
                        _format_dashscope_media_block(
                            block,  # type: ignore[arg-type]
                        ),
                    )
                    # Estimate fixed token cost for media
                    msg_token_count += 100

                elif typ == "tool_use":
                    arguments_str = json.dumps(
                        block.get("input", {}),
                        ensure_ascii=False,
                    )
                    tool_calls.append(
                        {
                            "id": block.get("id"),
                            "type": "function",
                            "function": {
                                "name": block.get("name"),
                                "arguments": arguments_str,
                            },
                        },
                    )
                    msg_token_count += safe_count_str_tokens(arguments_str)

                elif typ == "tool_result":
                    (
                        textual_output,
                        multimodal_data,
                    ) = self.convert_tool_result_to_string(block["output"])

                    # Truncate tool result text
                    textual_output = _truncate_text(textual_output)
                    msg_token_count += safe_count_str_tokens(textual_output)

                    # First add the tool result message in DashScope API format
                    formatted_msgs.append(
                        {
                            "role": "tool",
                            "tool_call_id": block.get("id"),
                            "content": textual_output,
                            "name": block.get("name"),
                        },
                    )

                    # Then, handle the multimodal data if any
                    promoted_blocks: list = []
                    for url, multimodal_block in multimodal_data:
                        if (
                            multimodal_block["type"] == "image"
                            and self.promote_tool_result_images
                        ):
                            promoted_blocks.extend(
                                [
                                    TextBlock(
                                        type="text",
                                        text=f"\n- The image from '{url}': ",
                                    ),
                                    ImageBlock(
                                        type="image",
                                        source=URLSource(
                                            type="url",
                                            url=url,
                                        ),
                                    ),
                                ],
                            )
                        elif (
                            multimodal_block["type"] == "audio"
                            and self.promote_tool_result_audios
                        ):
                            promoted_blocks.extend(
                                [
                                    TextBlock(
                                        type="text",
                                        text=f"\n- The audio from '{url}': ",
                                    ),
                                    AudioBlock(
                                        type="audio",
                                        source=URLSource(
                                            type="url",
                                            url=url,
                                        ),
                                    ),
                                ],
                            )
                        elif (
                            multimodal_block["type"] == "video"
                            and self.promote_tool_result_videos
                        ):
                            promoted_blocks.extend(
                                [
                                    TextBlock(
                                        type="text",
                                        text=f"\n- The video from '{url}': ",
                                    ),
                                    VideoBlock(
                                        type="video",
                                        source=URLSource(
                                            type="url",
                                            url=url,
                                        ),
                                    ),
                                ],
                            )

                    if promoted_blocks:
                        # Format promoted blocks directly
                        # and add to formatted_msgs
                        # (instead of inserting into msgs,
                        # which won't work in reverse iteration)
                        promoted_blocks = [
                            TextBlock(
                                type="text",
                                text="<system-info>The following are "
                                f"the media contents from the tool "
                                f"result of '{block['name']}':",
                            ),
                            *promoted_blocks,
                            TextBlock(
                                type="text",
                                text="</system-info>",
                            ),
                        ]

                        # Format the promoted blocks directly
                        promoted_content_blocks: list[dict[str, Any]] = []
                        for promoted_block in promoted_blocks:
                            promoted_block_dict = (
                                promoted_block
                                if isinstance(promoted_block, dict)
                                else promoted_block.model_dump()
                            )
                            promoted_typ = promoted_block_dict.get("type")
                            if promoted_typ == "text":
                                promoted_content_blocks.append(
                                    {
                                        "text": promoted_block_dict.get(
                                            "text",
                                            "",
                                        ),
                                    },
                                )
                            elif promoted_typ in ["image", "audio", "video"]:
                                promoted_content_blocks.append(
                                    _format_dashscope_media_block(
                                        promoted_block_dict,
                                    ),
                                )

                        # Add the promoted user message to formatted_msgs
                        formatted_msgs.append(
                            {
                                "role": "user",
                                "content": promoted_content_blocks,
                            },
                        )

                else:
                    logger.warning(
                        "Unsupported block type %s in the message, skipped.",
                        typ,
                    )

            msg_dashscope = {
                "role": msg.role,
                "content": content_blocks,
                "time_created": msg.timestamp,  # Add timestamp here
            }

            if tool_calls:
                msg_dashscope["tool_calls"] = tool_calls

            total_token_count += msg_token_count
            # Check if adding this message would exceed threshold
            if self._memory_compact_threshold <= total_token_count:
                # Skip older messages when threshold exceeded
                logger.info(
                    "Skipping older messages: token count %d >= %d",
                    total_token_count,
                    self._memory_compact_threshold,
                )
                break

            formatted_msgs.append(msg_dashscope)

            # Move to previous message
            i -= 1

        # Reverse to restore chronological order
        formatted_msgs.reverse()

        return _reformat_messages(formatted_msgs)


# Try to import reme, log warning if it fails
try:
    from reme import ReMeFb

    _REME_AVAILABLE = True
except ImportError:
    logger.warning("reme not found!")
    _REME_AVAILABLE = False

    class ReMeFb:  # type: ignore
        """Placeholder when reme is not available."""


class MemoryManager(ReMeFb):
    """Memory manager that extends ReMeFs functionality for CoPaw agents.

    Provides methods for managing conversation history, searching memories,
    and retrieving specific memory content.
    """

    def __init__(
        self,
        *args,
        working_dir: str,
        **kwargs,
    ):
        """Initialize MemoryManager with ReMeFs configuration."""
        if not _REME_AVAILABLE:
            raise RuntimeError("reme package not installed.")

        # Get max_input_length from config
        config = load_config()
        max_input_length = config.agents.running.max_input_length

        # Memory compaction threshold: configurable ratio of max_input_length
        self._memory_compact_threshold = int(
            max_input_length
            * MEMORY_COMPACT_RATIO
            * 0.9,  # Safety factor to stay below token limit
        )

        (
            embedding_api_key,
            embedding_base_url,
            embedding_model_name,
            embedding_dimensions,
            embedding_cache_enabled,
            embedding_max_cache_size,
            embedding_max_input_length,
            embedding_max_batch_size,
        ) = self.get_emb_envs()

        vector_enabled = bool(embedding_api_key)
        if vector_enabled:
            logger.info("Vector search enabled.")
        else:
            logger.warning(
                "Vector search disabled. "
                "Memory search functionality will be restricted. "
                "To enable, configure: EMBEDDING_API_KEY, EMBEDDING_BASE_URL, "
                "EMBEDDING_MODEL_NAME, and EMBEDDING_DIMENSIONS.",
            )
        fts_enabled = os.environ.get("FTS_ENABLED", "true").lower() == "true"
        working_path: Path = Path(working_dir)

        # Determine memory backend: use MEMORY_STORE_BACKEND env var,
        # default "auto" selects based on platform
        # (Windows=local, others=chroma)
        memory_store_backend = os.environ.get("MEMORY_STORE_BACKEND", "auto")
        if memory_store_backend == "auto":
            memory_backend = (
                "local" if platform.system() == "Windows" else "chroma"
            )
        else:
            memory_backend = memory_store_backend

        super().__init__(
            *args,
            working_dir=working_dir,
            enable_logo=False,
            log_to_console=False,
            llm_api_key="",
            llm_base_url="",
            embedding_api_key=embedding_api_key,
            embedding_base_url=embedding_base_url,
            default_llm_config={},
            default_embedding_model_config={
                "model_name": embedding_model_name,
                "dimensions": embedding_dimensions,
                "enable_cache": embedding_cache_enabled,
                "max_cache_size": embedding_max_cache_size,
                "max_input_length": embedding_max_input_length,
                "max_batch_size": embedding_max_batch_size,
            },
            default_file_store_config={
                "backend": memory_backend,
                "store_name": "copaw",
                "vector_enabled": vector_enabled,
                "fts_enabled": fts_enabled,
            },
            default_file_watcher_config={
                "watch_paths": [
                    str(working_path / "MEMORY.md"),
                    str(working_path / "memory.md"),
                    str(working_path / "memory"),
                ],
            },
            **kwargs,
        )

        global_config = load_config()
        language = global_config.agents.language

        if language == "zh":
            self.language = "zh"
        else:
            self.language = ""

        self.summary_tasks: list[asyncio.Task] = []

        self.toolkit = Toolkit()
        self.toolkit.register_tool_function(read_file)
        self.toolkit.register_tool_function(write_file)
        self.toolkit.register_tool_function(edit_file)

        self.chat_model: ChatModelBase | None = None
        self.formatter: FormatterBase | None = None

    @staticmethod
    def _safe_int(value: str | None, default: int) -> int:
        """Safely convert string to int, return default on failure."""
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            logger.warning(
                f"Invalid int value '{value}', using default {default}",
            )
            return default

    @staticmethod
    def get_emb_envs():
        embedding_api_key = os.environ.get("EMBEDDING_API_KEY", "")
        embedding_base_url = os.environ.get(
            "EMBEDDING_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        embedding_model_name = os.environ.get(
            "EMBEDDING_MODEL_NAME",
            "text-embedding-v4",
        )
        embedding_dimensions = MemoryManager._safe_int(
            os.environ.get("EMBEDDING_DIMENSIONS"),
            1024,
        )
        embedding_cache_enabled = (
            os.environ.get("EMBEDDING_CACHE_ENABLED", "true").lower() == "true"
        )
        embedding_max_cache_size = MemoryManager._safe_int(
            os.environ.get("EMBEDDING_MAX_CACHE_SIZE"),
            2000,
        )
        embedding_max_input_length = MemoryManager._safe_int(
            os.environ.get("EMBEDDING_MAX_INPUT_LENGTH"),
            8192,
        )
        embedding_max_batch_size = MemoryManager._safe_int(
            os.environ.get("EMBEDDING_MAX_BATCH_SIZE"),
            10,
        )
        return (
            embedding_api_key,
            embedding_base_url,
            embedding_model_name,
            embedding_dimensions,
            embedding_cache_enabled,
            embedding_max_cache_size,
            embedding_max_input_length,
            embedding_max_batch_size,
        )

    def update_emb_envs(self):
        (
            embedding_api_key,
            embedding_base_url,
            embedding_model_name,
            embedding_dimensions,
            embedding_cache_enabled,
            embedding_max_cache_size,
            embedding_max_input_length,
            embedding_max_batch_size,
        ) = self.get_emb_envs()

        if embedding_api_key:
            os.environ["REME_EMBEDDING_API_KEY"] = embedding_api_key

        if embedding_base_url:
            os.environ["REME_EMBEDDING_BASE_URL"] = embedding_base_url

        self.default_embedding_model.model_name = embedding_model_name
        self.default_embedding_model.dimensions = embedding_dimensions
        self.default_embedding_model.enable_cache = embedding_cache_enabled
        self.default_embedding_model.max_cache_size = embedding_max_cache_size
        self.default_embedding_model.max_input_length = (
            embedding_max_input_length
        )
        self.default_embedding_model.max_batch_size = embedding_max_batch_size

    async def start(self):
        """Start the memory manager and initialize services."""
        try:
            return await super().start()
        except Exception as e:
            logger.exception(f"Failed to start memory manager: {e}")
            raise

    async def close(self):
        """Close the memory manager and cleanup resources."""
        try:
            return await super().close()
        except Exception as e:
            logger.exception(f"Failed to close memory manager: {e}")
            raise

    async def compact_memory(
        self,
        messages_to_summarize: list[Msg] | None = None,
        turn_prefix_messages: list[Msg] | None = None,
        previous_summary: str = "",
    ) -> str:
        """Compact messages into a summary.

        Args:
            messages_to_summarize: Messages to summarize
            turn_prefix_messages: Messages to prepend to each turn
            previous_summary: Previous summary to build upon

        Returns:
            Compaction result from FsCompactor
        """
        self.update_emb_envs()

        formatter = TimestampedDashScopeChatFormatter(
            memory_compact_threshold=self._memory_compact_threshold,
        )
        if not messages_to_summarize and not turn_prefix_messages:
            return ""

        if messages_to_summarize:
            messages_to_summarize = await formatter.format(
                messages_to_summarize,
            )
        else:
            messages_to_summarize = []

        if turn_prefix_messages:
            turn_prefix_messages = await formatter.format(turn_prefix_messages)
        else:
            turn_prefix_messages = []

        try:
            prompt_dict: dict = await super().compact(
                messages_to_summarize=messages_to_summarize,
                turn_prefix_messages=turn_prefix_messages,
                previous_summary=previous_summary,
                language=self.language,
                return_prompt=True,
            )
        except Exception as e:
            logger.exception(f"Failed to generate compact prompt: {e}")
            return ""

        for key, value in prompt_dict.items():
            logger.info(f"Memory Compact Prompt={key}:\n{value}")

        system_prompt = prompt_dict["system"]
        history_user = prompt_dict.get("history_user", "")
        turn_prefix_user = prompt_dict.get("turn_prefix_user", "")

        if history_user:
            try:
                agent = ReActAgent(
                    name="history_summary",
                    model=self.chat_model,
                    sys_prompt=system_prompt,
                    formatter=self.formatter,
                )

                history_summary_msg: Msg = await agent.reply(
                    Msg(
                        name="reme",
                        content=history_user,
                        role="user",
                    ),
                )

                history_summary: str = history_summary_msg.get_text_content()
            except Exception as e:
                logger.exception(f"Failed to generate history summary: {e}")
                history_summary = ""

        else:
            history_summary = ""

        if turn_prefix_user:
            try:
                agent = ReActAgent(
                    name="turn_prefix_summary",
                    model=self.chat_model,
                    sys_prompt=system_prompt,
                    formatter=self.formatter,
                )

                turn_prefix_summary_msg: Msg = await agent.reply(
                    Msg(
                        name="reme",
                        content=turn_prefix_user,
                        role="user",
                    ),
                )

                turn_prefix_summary: str = (
                    turn_prefix_summary_msg.get_text_content()
                )
            except Exception as e:
                logger.exception(
                    f"Failed to generate turn prefix summary: {e}",
                )
                turn_prefix_summary = ""

        else:
            turn_prefix_summary = ""

        return "\n".join(
            [x for x in [history_summary, turn_prefix_summary] if x.strip()],
        )

    async def summary_memory(
        self,
        messages: list[Msg],
        date: str,
        version: str = "default",
    ) -> str:
        """Generate a summary of the given messages."""
        self.update_emb_envs()

        formatter = TimestampedDashScopeChatFormatter(
            memory_compact_threshold=self._memory_compact_threshold,
        )
        messages = await formatter.format(messages)

        try:
            result: dict = await super().summary(
                messages=messages,
                date=date,
                version=version,
                language=self.language,
                return_prompt=True,
            )
        except Exception as e:
            logger.exception(f"Failed to generate summary prompt: {e}")
            return ""

        prompt = result["prompt"]
        logger.info(f"Memory Summary Prompt:\n{prompt}")

        try:
            agent = ReActAgent(
                name="summary_memory",
                sys_prompt="You are a helpful assistant.",
                model=self.chat_model,
                formatter=self.formatter,
                toolkit=self.toolkit,
            )

            summary_msg: Msg = await agent.reply(
                Msg(
                    name="reme",
                    content=prompt,
                    role="user",
                ),
            )

            history_summary: str = summary_msg.get_text_content()
            logger.info(f"Memory Summary Result:\n{history_summary}")
            return history_summary
        except Exception as e:
            logger.exception(f"Failed to generate memory summary: {e}")
            return ""

    async def await_summary_tasks(self) -> str:
        """Wait for all summary tasks to complete."""
        result = ""
        for task in self.summary_tasks:
            if task.done():
                exc = task.exception()
                if exc is not None:
                    logger.exception(f"Summary task failed: {exc}")
                    result += f"Summary task failed: {exc}\n"

                else:
                    result = task.result()
                    logger.info(f"Summary task completed: {result}")
                    result += f"Summary task completed: {result}\n"

            else:
                try:
                    result = await task
                    logger.info(f"Summary task completed: {result}")
                    result += f"Summary task completed: {result}\n"

                except Exception as e:
                    logger.exception(f"Summary task failed: {e}")
                    result += f"Summary task failed: {e}\n"

        self.summary_tasks.clear()
        return result

    def add_async_summary_task(
        self,
        messages: list[Msg],
        date: str = "",
        version: str = "default",
    ):
        # Clean up completed summary tasks
        remaining_tasks = []
        for task in self.summary_tasks:
            if task.done():
                exc = task.exception()
                if exc is not None:
                    logger.exception(f"Summary task failed: {exc}")
                else:
                    result = task.result()
                    logger.info(f"Summary task completed: {result}")
            else:
                remaining_tasks.append(task)
        self.summary_tasks = remaining_tasks

        self.summary_tasks.append(
            asyncio.create_task(
                self.summary_memory(
                    messages=messages,
                    date=date or datetime.datetime.now().strftime("%Y-%m-%d"),
                    version=version,
                ),
            ),
        )

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0.1,
    ) -> ToolResponse:
        """
        Mandatory recall: semantically search MEMORY.md + memory/*.md
        (and optional session transcripts) before answering questions about
        prior work, decisions, dates, people, preferences, or todos;
        returns top snippets with path + lines.

        Args:
            query: The semantic search query to find relevant memory snippets
            max_results: Max search results to return (optional), default 5
            min_score: Min similarity score for results (optional), default 0.1

        Returns:
            Search results as formatted string
        """
        if not query:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text="Error: No query provided.",
                    ),
                ],
            )

        if isinstance(max_results, int):
            max_results = min(max(max_results, 1), 100)
        else:
            max_results = 5

        if isinstance(min_score, float):
            min_score = min(max(min_score, 0.001), 0.999)
        else:
            min_score = 0.1

        search_result: str = await super().memory_search(
            query=query,
            max_results=max_results,
            min_score=min_score,
        )
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=search_result,
                ),
            ],
        )

    async def memory_get(
        self,
        path: str,
        offset: int | None = None,
        limit: int | None = None,
    ) -> ToolResponse:
        """
        Safe snippet read from MEMORY.md, memory/*.md with optional
        offset/limit; use after memory_search to pull needed lines and
        keep context small.

        Args:
            path: Path to the memory file to read (relative or absolute)
            offset: Starting line number (1-indexed, optional)
            limit: Number of lines to read from the starting line (optional)

        Returns:
            Memory file content as string
        """
        get_result = await super().memory_get(
            path=path,
            offset=offset,
            limit=limit,
        )
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=get_result,
                ),
            ],
        )
