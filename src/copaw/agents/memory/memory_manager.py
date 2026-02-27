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

from agentscope.agent import ReActAgent
from agentscope.formatter import DashScopeChatFormatter, FormatterBase
from agentscope.formatter._dashscope_formatter import (
    _format_dashscope_media_block,
    _reformat_messages,
)
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
from ...config.utils import load_config

logger = logging.getLogger(__name__)


class TimestampedDashScopeChatFormatter(DashScopeChatFormatter):
    """DashScope formatter that includes timestamp in formatted messages.

    Extends DashScopeChatFormatter to add the timestamp to each formatted
    message as a 'time_created' field. Also supports file blocks.
    """

    @staticmethod
    def convert_tool_result_to_string(
        output: str | list[dict],
    ) -> tuple[str, list[tuple[str, dict]]]:
        """Extend parent class to support file blocks."""
        if isinstance(output, str):
            return output, []

        # Try parent class method first
        try:
            return DashScopeChatFormatter.convert_tool_result_to_string(output)
        except ValueError as e:
            if "Unsupported block type: file" not in str(e):
                raise

            # Handle output containing file blocks
            textual_output = []
            multimodal_data = []

            for block in output:
                if not isinstance(block, dict) or "type" not in block:
                    raise ValueError(
                        f"Invalid block: {block}, "
                        "expected a dict with 'type' key",
                    ) from e

                if block["type"] == "file":
                    file_path = block.get("path", "") or block.get("url", "")
                    file_name = block.get("name", file_path)

                    textual_output.append(
                        f"The returned file '{file_name}' "
                        f"can be found at: {file_path}",
                    )
                    multimodal_data.append((file_path, block))
                else:
                    # Delegate other block types to parent class
                    (
                        text,
                        data,
                    ) = DashScopeChatFormatter.convert_tool_result_to_string(
                        [block],
                    )
                    textual_output.append(text)
                    multimodal_data.extend(data)

            if len(textual_output) == 0:
                return "", multimodal_data
            elif len(textual_output) == 1:
                return textual_output[0], multimodal_data
            else:
                return (
                    "\n".join("- " + _ for _ in textual_output),
                    multimodal_data,
                )

    async def _format(
        self,
        msgs: list[Msg],
    ) -> list[dict[str, Any]]:
        """Format message objects into DashScope API format with timestamps.

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

        i = 0
        while i < len(msgs):
            msg = msgs[i]
            content_blocks: list[dict[str, Any]] = []
            tool_calls = []

            for block in msg.get_content_blocks():
                typ = block.get("type")

                if typ == "text":
                    content_blocks.append(
                        {
                            "text": block.get("text"),
                        },
                    )

                elif typ in ["image", "audio", "video"]:
                    content_blocks.append(
                        _format_dashscope_media_block(
                            block,  # type: ignore[arg-type]
                        ),
                    )

                elif typ == "tool_use":
                    tool_calls.append(
                        {
                            "id": block.get("id"),
                            "type": "function",
                            "function": {
                                "name": block.get("name"),
                                "arguments": json.dumps(
                                    block.get("input", {}),
                                    ensure_ascii=False,
                                ),
                            },
                        },
                    )

                elif typ == "tool_result":
                    (
                        textual_output,
                        multimodal_data,
                    ) = self.convert_tool_result_to_string(block["output"])

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
                        # Insert promoted blocks as new user message(s)
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

                        msgs.insert(
                            i + 1,
                            Msg(
                                name="user",
                                content=promoted_blocks,
                                role="user",
                            ),
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

            if msg_dashscope["content"] or msg_dashscope.get("tool_calls"):
                formatted_msgs.append(msg_dashscope)

            # Move to next message
            i += 1

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

    def __init__(self, *args, working_dir: str, **kwargs):
        """Initialize MemoryManager with ReMeFs configuration."""
        if not _REME_AVAILABLE:
            raise RuntimeError("reme package not installed.")

        (
            embedding_api_key,
            embedding_base_url,
            embedding_model_name,
            embedding_dimensions,
            embedding_cache_enabled,
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
        embedding_dimensions = int(
            os.environ.get("EMBEDDING_DIMENSIONS", "1024"),
        )
        embedding_cache_enabled = (
            os.environ.get("EMBEDDING_CACHE_ENABLED", "true").lower() == "true"
        )
        return (
            embedding_api_key,
            embedding_base_url,
            embedding_model_name,
            embedding_dimensions,
            embedding_cache_enabled,
        )

    def update_emb_envs(self):
        (
            embedding_api_key,
            embedding_base_url,
            embedding_model_name,
            embedding_dimensions,
            embedding_cache_enabled,
        ) = self.get_emb_envs()

        if embedding_api_key:
            os.environ["REME_EMBEDDING_API_KEY"] = embedding_api_key

        if embedding_base_url:
            os.environ["REME_EMBEDDING_BASE_URL"] = embedding_base_url

        self.default_embedding_model.model_name = embedding_model_name
        self.default_embedding_model.dimensions = embedding_dimensions
        self.default_embedding_model.enable_cache = embedding_cache_enabled

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

        formatter = TimestampedDashScopeChatFormatter()
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

        formatter = TimestampedDashScopeChatFormatter()
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
