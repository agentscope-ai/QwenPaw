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
import logging
import os
import platform
from pathlib import Path

from agentscope.agent import ReActAgent
from agentscope.formatter._formatter_base import FormatterBase
from agentscope.message import Msg
from agentscope.message import (
    TextBlock,
)
from agentscope.model import ChatModelBase
from agentscope.tool import ToolResponse, Toolkit

from . import prompt
from .memory_formatter import MemoryFormatter
from ..tools import (
    read_file,
    write_file,
    edit_file,
)
from ...config.utils import load_config
from ...constant import MEMORY_COMPACT_RATIO

logger = logging.getLogger(__name__)

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
            self.summary_prompt = prompt.SUMMARY_USER_ZH
            self.compact_system_prompt = prompt.COMPACT_SYSTEM_ZH
            self.compact_initial_prompt = prompt.INITIAL_USER_ZH
            self.compact_update_prompt = prompt.UPDATE_USER_ZH

        else:
            self.language = ""
            self.summary_prompt = prompt.SUMMARY_USER
            self.compact_system_prompt = prompt.COMPACT_SYSTEM
            self.compact_initial_prompt = prompt.INITIAL_USER
            self.compact_update_prompt = prompt.UPDATE_USER

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
            messages_to_summarize: list[Msg],
            previous_summary: str = "",
    ) -> str:
        """Compact messages into a summary.

        Args:
            messages_to_summarize: Messages to summarize
            previous_summary: Previous summary to build upon

        Returns:
            Compaction result from FsCompactor
        """
        self.update_emb_envs()

        formatter = MemoryFormatter(memory_compact_threshold=self._memory_compact_threshold)
        if not messages_to_summarize:
            return ""

        history_formatted_str: str = await formatter.format(messages_to_summarize)

        try:
            agent = ReActAgent(
                name="history_summary",
                model=self.chat_model,
                sys_prompt=self.compact_system_prompt,
                formatter=self.formatter,
            )

            if previous_summary:
                user_prompt = self.compact_update_prompt.format(previous_summary=previous_summary)
            else:
                user_prompt = self.compact_initial_prompt
            user_msg = f"<conversation>\n{history_formatted_str}\n</conversation>\n\n{user_prompt}"
            logger.info(f"user_msg={user_msg}")

            history_summary_msg: Msg = await agent.reply(
                Msg(
                    name="reme",
                    content=user_msg,
                    role="user",
                )
            )

            history_summary: str = history_summary_msg.get_text_content()
        except Exception as e:
            logger.exception(f"Failed to generate history summary: {e}")
            history_summary = ""

        return history_summary

    async def summary_memory(
            self,
            messages: list[Msg],
            date: str,
    ) -> str:
        """Generate a summary of the given messages."""
        self.update_emb_envs()

        formatter = MemoryFormatter(memory_compact_threshold=self._memory_compact_threshold)

        history_formatted_str: str = await formatter.format(messages)
        prompt = f"<conversation>\n{conversation}\n</conversation>\n" + self.summary_prompt.format(
            date=date,
            working_dir=self.working_dir,
            memory_dir=str(Path(self.working_dir) / "memory"),
        )
        logger.info(f"prompt={prompt}")

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
