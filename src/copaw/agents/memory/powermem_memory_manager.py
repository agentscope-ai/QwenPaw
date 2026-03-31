# -*- coding: utf-8 -*-
"""powermem-backed memory manager for CoPaw agents."""

import logging
import os
from typing import Optional, TYPE_CHECKING

from agentscope.formatter import FormatterBase
from agentscope.message import Msg, TextBlock
from agentscope.model import ChatModelBase
from agentscope.tool import ToolResponse, Toolkit

from copaw.agents.memory.base_memory_manager import BaseMemoryManager
from copaw.agents.memory.powermem_in_memory import PowerMemInMemoryMemory
from copaw.agents.model_factory import create_model_and_formatter
from copaw.agents.tools import read_file, write_file, edit_file
from copaw.agents.utils import get_copaw_token_counter
from copaw.config.config import load_agent_config
from copaw.config.context import (
    set_current_workspace_dir,
    set_current_recent_max_bytes,
)

if TYPE_CHECKING:
    from powermem import AsyncMemory

logger = logging.getLogger(__name__)


class PowerMemMemoryManager(BaseMemoryManager):
    def __init__(self, working_dir: str, agent_id: str):
        super().__init__(working_dir=working_dir, agent_id=agent_id)
        self._powermem: Optional["AsyncMemory"] = None
        self._in_memory: Optional[PowerMemInMemoryMemory] = None
        self.chat_model: Optional[ChatModelBase] = None
        self.formatter: Optional[FormatterBase] = None
        logger.info(f"PowerMemMemoryManager init: agent_id={agent_id}")

    def _prepare_model_formatter(self) -> None:
        if self.chat_model is None or self.formatter is None:
            self.chat_model, self.formatter = create_model_and_formatter(
                self.agent_id,
            )

    def _get_embedding_config(self) -> dict:
        cfg = load_agent_config(self.agent_id).running.embedding_config
        return {
            "backend": cfg.backend,
            "api_key": cfg.api_key or os.getenv("EMBEDDING_API_KEY", ""),
            "base_url": cfg.base_url or os.getenv("EMBEDDING_BASE_URL", ""),
            "model_name": cfg.model_name
            or os.getenv("EMBEDDING_MODEL_NAME", ""),
            "dimensions": cfg.dimensions,
            "enable_cache": cfg.enable_cache,
            "use_dimensions": cfg.use_dimensions,
            "max_cache_size": cfg.max_cache_size,
            "max_input_length": cfg.max_input_length,
            "max_batch_size": cfg.max_batch_size,
        }

    async def start(self) -> None:
        from powermem import AsyncMemory, auto_config

        try:
            config = auto_config()
            config["vector_store"]["config"]["database_path"] = os.path.join(
                self.working_dir,
                "powermem.db",
            )
            config["logging"]["file"] = os.path.join(
                self.working_dir,
                "logs",
                "powermem.log",
            )

            emb_config = self._get_embedding_config()
            if emb_config["base_url"] and emb_config["model_name"]:
                config["embedder"] = {
                    "provider": emb_config["backend"] or "openai",
                    "config": {
                        "api_key": emb_config["api_key"],
                        "base_url": emb_config["base_url"],
                        "model": emb_config["model_name"],
                    },
                }

            self._powermem = AsyncMemory(config=config)
            await self._powermem.initialize()

            self._in_memory = PowerMemInMemoryMemory(
                powermem=self._powermem,
                agent_id=self.agent_id,
                working_dir=self.working_dir,
            )

            await self._in_memory.load_from_powermem()

            self.summary_toolkit = Toolkit()
            self.summary_toolkit.register_tool_function(read_file)
            self.summary_toolkit.register_tool_function(write_file)
            self.summary_toolkit.register_tool_function(edit_file)

            logger.info(f"PowerMem started for agent {self.agent_id}")

        except Exception as e:
            logger.error(f"Failed to start PowerMem: {e}")
            raise

    async def close(self) -> bool:
        logger.info(f"PowerMemMemoryManager closing: agent_id={self.agent_id}")
        if self._powermem is None:
            return True
        try:
            logger.info(f"PowerMem closed for agent {self.agent_id}")
            return True
        except Exception as e:
            logger.error(f"Error closing PowerMem: {e}")
            return False

    async def compact_tool_result(self, **kwargs) -> None:
        messages = kwargs.get("messages", [])
        recent_n = kwargs.get("recent_n", 3)
        old_max_bytes = kwargs.get("old_max_bytes", 1000)
        recent_max_bytes = kwargs.get("recent_max_bytes", 10000)

        if not messages:
            return

        recent_messages = (
            messages[-recent_n:] if len(messages) > recent_n else messages
        )
        old_messages = messages[:-recent_n] if len(messages) > recent_n else []

        for msg in old_messages:
            if len(msg.content) > old_max_bytes:
                msg.content = msg.content[:old_max_bytes] + "... [truncated]"

        for msg in recent_messages:
            if len(msg.content) > recent_max_bytes:
                msg.content = (
                    msg.content[:recent_max_bytes] + "... [truncated]"
                )

    async def check_context(self, **kwargs) -> tuple:
        messages = kwargs.get("messages", [])
        max_input_length = kwargs.get("max_input_length", 8000)

        if not messages:
            return [], [], True

        agent_config = load_agent_config(self.agent_id)
        token_counter = get_copaw_token_counter(agent_config)
        total_tokens = sum(token_counter(msg) for msg in messages)

        if total_tokens <= max_input_length:
            return [], messages, True

        tokens_to_remove = total_tokens - max_input_length
        messages_to_compact = []
        removed_tokens = 0

        for msg in messages:
            if msg.role == "system":
                continue
            msg_tokens = token_counter(msg)
            messages_to_compact.append(msg)
            removed_tokens += msg_tokens
            if removed_tokens >= tokens_to_remove:
                break

        remaining = [m for m in messages if m not in messages_to_compact]
        remaining_tokens = sum(token_counter(m) for m in remaining)
        is_valid = remaining_tokens <= max_input_length

        return messages_to_compact, remaining, is_valid

    async def compact_memory(
        self,
        messages: list[Msg],
        previous_summary: str = "",
        **kwargs,
    ) -> str:
        self._prepare_model_formatter()
        agent_config = load_agent_config(self.agent_id)
        cc = agent_config.running.context_compact

        prompt = self._build_compact_prompt(
            messages=messages,
            previous_summary=previous_summary,
            language=agent_config.language,
            compact_ratio=cc.memory_compact_ratio,
        )

        try:
            response = await self.chat_model.chat(
                messages=[Msg("system", prompt, "system")],
            )
            summary = response.content
            if not summary or len(summary) < 10:
                logger.warning(
                    "Generated summary is too short, returning empty",
                )
                return ""
            return summary
        except Exception as e:
            logger.error(f"Failed to compact memory: {e}")
            return ""

    def _build_compact_prompt(
        self,
        messages: list[Msg],
        previous_summary: str,
        language: str,
        compact_ratio: float,
    ) -> str:
        conversation = []
        for msg in messages:
            role_label = {
                "user": "User",
                "assistant": "Assistant",
                "system": "System",
            }.get(msg.role, msg.role)
            content = str(msg.content)
            if len(content) > 500:
                content = content[:500] + "..."
            conversation.append(f"{role_label}: {content}")

        conversation_text = "\n".join(conversation)

        lang_instruction = {
            "zh": "请用中文",
            "en": "Please respond in English",
            "ru": "Please respond in Russian",
        }.get(language, "Please respond in English")

        prompt = (
            f"You are a memory compression assistant. "
            f"Summarize the following conversation into a concise summary.\n\n"
            f"{lang_instruction}.\n\n"
            f"Previous summary (if any):\n"
            f"{previous_summary if previous_summary else '[None]'}\n\n"
            f"Conversation to summarize:\n"
            f"{conversation_text}\n\n"
            f"Instructions:\n"
            f"1. Create a concise summary capturing key points and context\n"
            f"2. Include important facts, decisions, and user preferences\n"
            f"3. The summary should be approximately "
            f"{int(compact_ratio * 100)}% of the original length\n"
            f"4. Write in narrative style, not bullet points\n"
            f"5. Focus on information useful for future conversations\n\n"
            f"Summary:"
        )
        return prompt

    async def summary_memory(self, messages: list[Msg], **kwargs) -> str:
        self._prepare_model_formatter()
        agent_config = load_agent_config(self.agent_id)
        cc = agent_config.running.context_compact

        set_current_workspace_dir(self.working_dir)
        recent_max_bytes = (
            agent_config.running.tool_result_compact.recent_max_bytes
        )
        set_current_recent_max_bytes(recent_max_bytes)

        prompt = self._build_summary_prompt(
            messages=messages,
            language=agent_config.language,
            _compact_ratio=cc.memory_compact_ratio,
        )

        try:
            response = await self.chat_model.chat(
                messages=[Msg("system", prompt, "system")],
            )
            return response.content
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            return ""

    def _build_summary_prompt(
        self,
        messages: list[Msg],
        language: str,
        _compact_ratio: float = 0.0,
    ) -> str:
        conversation = []
        for msg in messages:
            role_label = {
                "user": "User",
                "assistant": "Assistant",
                "system": "System",
            }.get(msg.role, msg.role)
            conversation.append(f"{role_label}: {msg.content}")

        conversation_text = "\n".join(conversation)

        lang_instruction = {
            "zh": "请用中文生成详细摘要",
            "en": "Provide a detailed summary in English",
            "ru": "Provide a detailed summary in Russian",
        }.get(language, "Provide a detailed summary in English")

        prompt = (
            f"You are a memory summarization assistant. "
            f"Create a comprehensive summary of this conversation.\n\n"
            f"{lang_instruction}.\n\n"
            f"Conversation:\n"
            f"{conversation_text}\n\n"
            f"Instructions:\n"
            f"1. Provide a detailed summary covering all important aspects\n"
            f"2. Include: topics, preferences, decisions, action items\n"
            f"3. Maintain chronological order where relevant\n"
            f"4. The summary should be comprehensive but concise\n"
            f"5. Format as a coherent narrative paragraph\n\n"
            f"Comprehensive Summary:"
        )
        return prompt

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        min_score: float = 0.1,
    ) -> ToolResponse:
        if self._powermem is None:
            return ToolResponse(
                content=[
                    TextBlock(type="text", text="PowerMem is not initialized"),
                ],
            )

        try:
            results = await self._powermem.search(
                query=query,
                agent_id=self.agent_id,
                limit=max_results,
                threshold=min_score,
            )

            memories = results.get("results", [])
            if not memories:
                return ToolResponse(
                    content=[
                        TextBlock(
                            type="text",
                            text="No relevant memories found.",
                        ),
                    ],
                )

            result_texts = []
            for i, mem in enumerate(memories, 1):
                content = mem.get("content", {})
                text = content.get("content", "")
                score = mem.get("score", 0)
                result_texts.append(f"{i}. [{score:.2f}] {text[:200]}...")

            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text="Relevant memories found:\n\n"
                        + "\n\n".join(result_texts),
                    ),
                ],
            )
        except Exception as e:
            logger.error(f"Memory search failed: {e}")
            return ToolResponse(
                content=[TextBlock(type="text", text=f"Search failed: {e}")],
            )

    def get_in_memory_memory(self, **kwargs) -> PowerMemInMemoryMemory:
        return self._in_memory
