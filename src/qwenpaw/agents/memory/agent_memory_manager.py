# -*- coding: utf-8 -*-
"""AgentMemory-backed memory manager for QwenPaw.

This module provides a memory manager implementation that uses AgentMemory
MCP server as the backend, enabling high-precision triple retrieval
(vector + BM25 + knowledge graph).

Configuration:
    Set `memory_manager_backend: "agentmemory"` in config.json
    
Requirements:
    - Node.js >= 18
    - npm
    - npx @agentmemory/mcp
"""

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from agentscope.message import Msg

from qwenpaw.agents.memory.base_memory_manager import BaseMemoryManager

# Import MCP client - handle both installed and local import
try:
    from qwenpaw.agents.memory.agent_memory_mcp_client import AgentMemoryMCPClient
except ImportError:
    from agent_memory_mcp_client import AgentMemoryMCPClient

if TYPE_CHECKING:
    from reme.memory.file_based.reme_in_memory_memory import ReMeInMemoryMemory

logger = logging.getLogger(__name__)


class AgentMemoryManager(BaseMemoryManager):
    """Memory manager using AgentMemory MCP backend.
    
    Provides high-precision memory retrieval with:
    - Vector semantic search
    - BM25 full-text search
    - Knowledge graph relations
    - Automatic pattern detection
    
    This manager delegates most operations to the AgentMemory MCP server
    while implementing the BaseMemoryManager interface for seamless
    integration with QwenPaw.
    
    Attributes:
        working_dir: Working directory (for compatibility, primarily used for logs)
        agent_id: Agent identifier
        mcp_client: AgentMemory MCP client instance
    """
    
    def __init__(
        self,
        working_dir: str,
        agent_id: str,
        mcp_command: str = "npx",
        mcp_args: list = None,
        mcp_timeout: float = 30.0,
    ):
        """Initialize AgentMemory manager.
        
        Args:
            working_dir: Working directory for local cache/logs
            agent_id: Agent identifier
            mcp_command: Command to start MCP server (default: npx)
            mcp_args: Arguments for MCP command
            mcp_timeout: MCP request timeout in seconds
        """
        super().__init__(working_dir=working_dir, agent_id=agent_id)
        
        self.mcp_client = AgentMemoryMCPClient(
            command=mcp_command,
            args=mcp_args or ["-y", "@agentmemory/mcp"],
        )
        
        # Local context buffer for compaction
        self._context_buffer: list[Msg] = []
        self._max_buffer_size = 100
        
        logger.info(
            f"AgentMemoryManager initialized: agent_id={agent_id}, "
            f"working_dir={working_dir}"
        )
    
    # ========================================
    # Lifecycle Methods
    # ========================================
    
    async def start(self) -> None:
        """Start the memory manager and initialize MCP connection."""
        logger.info("Starting AgentMemoryManager...")
        
        try:
            await self.mcp_client.start()
            logger.info("AgentMemoryManager started successfully")
        except Exception as e:
            logger.error(f"Failed to start AgentMemory MCP client: {e}")
            raise
    
    async def close(self) -> bool:
        """Close the memory manager and cleanup resources.
        
        Returns:
            True if closed successfully, False otherwise
        """
        logger.info("Closing AgentMemoryManager...")
        
        try:
            await self.mcp_client.close()
            logger.info("AgentMemoryManager closed successfully")
            return True
        except Exception as e:
            logger.error(f"Error closing AgentMemoryManager: {e}")
            return False
    
    # ========================================
    # Memory Operations
    # ========================================
    
    async def memory_search(
        self,
        query: str,
        top_k: int = 5,
        **kwargs,
    ) -> list:
        """Search memories using semantic and keyword matching.
        
        Args:
            query: Search query
            top_k: Maximum number of results
            
        Returns:
            List of matching memories with scores
        """
        logger.debug(f"memory_search: query='{query[:50]}...', top_k={top_k}")
        
        try:
            results = await self.mcp_client.memory_recall(
                query=query,
                limit=top_k,
                min_score=kwargs.get("min_score", 0.1),
            )
            
            logger.debug(f"memory_search: found {len(results)} results")
            return results
            
        except Exception as e:
            logger.error(f"memory_search failed: {e}")
            return []
    
    async def summary_memory(
        self,
        messages: list[Msg],
        **kwargs,
    ) -> str:
        """Generate and save a summary of messages.
        
        Args:
            messages: List of messages to summarize
            
        Returns:
            Summary text
        """
        if not messages:
            return ""
        
        logger.info(f"summary_memory: summarizing {len(messages)} messages")
        
        # Generate summary using chat model if available
        summary = ""
        if self.chat_model and self.formatter:
            try:
                summary = await self._generate_summary(messages)
            except Exception as e:
                logger.warning(f"Failed to generate summary with LLM: {e}")
                summary = self._generate_simple_summary(messages)
        else:
            summary = self._generate_simple_summary(messages)
        
        # Save summary to AgentMemory
        if summary:
            try:
                await self.mcp_client.memory_save(
                    content=summary,
                    type="fact",
                    concepts="conversation,summary",
                )
            except Exception as e:
                logger.error(f"Failed to save summary to AgentMemory: {e}")
        
        return summary
    
    async def compact_memory(
        self,
        messages: list[Msg],
        previous_summary: str = "",
        extra_instruction: str = "",
        **kwargs,
    ) -> str:
        """Compact messages into a condensed format.
        
        Args:
            messages: Messages to compact
            previous_summary: Previous summary to incorporate
            extra_instruction: Additional instructions for compaction
            
        Returns:
            Compacted summary
        """
        if not messages:
            return previous_summary
        
        logger.info(f"compact_memory: compacting {len(messages)} messages")
        
        # Use LLM for compaction if available
        compacted = ""
        if self.chat_model and self.formatter:
            try:
                compacted = await self._compact_with_llm(
                    messages, previous_summary, extra_instruction
                )
            except Exception as e:
                logger.warning(f"LLM compaction failed: {e}")
                compacted = self._generate_simple_summary(messages)
        else:
            compacted = self._generate_simple_summary(messages)
        
        # Save compacted memory to AgentMemory
        if compacted:
            try:
                await self.mcp_client.memory_save(
                    content=compacted,
                    type="fact",
                    concepts="compacted,memory",
                )
            except Exception as e:
                logger.error(f"Failed to save compacted memory: {e}")
        
        return compacted
    
    async def dream_memory(self, **kwargs) -> str:
        """Perform background memory optimization.
        
        This method:
        1. Identifies patterns in stored memories
        2. Creates relations between related memories
        3. Consolidates duplicate or similar memories
        
        Returns:
            Summary of dream operations
        """
        logger.info("dream_memory: starting memory optimization")
        
        results = []
        
        # Get detected patterns
        try:
            patterns = await self.mcp_client.memory_patterns()
            if patterns:
                results.append(f"Detected {len(patterns)} patterns")
                logger.info(f"Dream: detected {len(patterns)} patterns")
        except Exception as e:
            logger.warning(f"Failed to get patterns: {e}")
        
        # Get memory relations
        try:
            relations = await self.mcp_client.memory_relations()
            if relations:
                results.append(f"Found {len(relations)} relations")
                logger.info(f"Dream: found {len(relations)} relations")
        except Exception as e:
            logger.warning(f"Failed to get relations: {e}")
        
        return "; ".join(results) if results else "No optimization performed"
    
    # ========================================
    # Context Management
    # ========================================
    
    async def check_context(self, **kwargs) -> tuple:
        """Check context size and determine if compaction is needed.
        
        Args:
            **kwargs: Context check parameters
            
        Returns:
            Tuple of (messages_to_compact, remaining_messages, is_valid)
        """
        messages = kwargs.get("messages", [])
        max_tokens = kwargs.get("max_tokens", 100000)
        
        if not messages:
            return ([], [], True)
        
        # Estimate token count
        total_tokens = sum(
            len(str(m.content)) // 4  # Rough estimate
            for m in messages
        )
        
        if total_tokens > max_tokens:
            # Compact oldest 50% of messages
            split_idx = len(messages) // 2
            return (messages[:split_idx], messages[split_idx:], False)
        
        return ([], messages, True)
    
    async def compact_tool_result(self, **kwargs) -> None:
        """Compact tool results by truncating large outputs.
        
        Args:
            **kwargs: Compaction parameters
        """
        messages = kwargs.get("messages", [])
        max_bytes = kwargs.get("max_bytes", 50000)
        
        for msg in messages:
            if hasattr(msg, "content") and isinstance(msg.content, str):
                if len(msg.content) > max_bytes:
                    msg.content = msg.content[:max_bytes] + "\n...[truncated]"
    
    # ========================================
    # Compatibility Methods
    # ========================================
    
    def get_in_memory_memory(self) -> Optional["ReMeInMemoryMemory"]:
        """Get in-memory memory object for compatibility.
        
        Note: AgentMemory doesn't use ReMeInMemoryMemory.
        This returns None for compatibility.
        
        Returns:
            None (AgentMemory uses MCP server)
        """
        return None
    
    def get_embedding_config(self) -> dict:
        """Get embedding configuration.
        
        AgentMemory handles embedding internally, so this returns
        an empty dict for compatibility.
        
        Returns:
            Empty dict
        """
        return {}
    
    async def restart_embedding_model(self) -> bool:
        """Restart embedding model.
        
        AgentMemory manages its own embedding model.
        This is a no-op for compatibility.
        
        Returns:
            True (always succeeds)
        """
        return True
    
    # ========================================
    # AgentMemory-specific Methods
    # ========================================
    
    async def get_patterns(self) -> list:
        """Get detected user behavior patterns.
        
        Returns:
            List of patterns
        """
        return await self.mcp_client.memory_patterns()
    
    async def get_relations(self, entity: str = "") -> list:
        """Get memory relations graph.
        
        Args:
            entity: Optional entity to filter relations
            
        Returns:
            List of relations
        """
        return await self.mcp_client.memory_relations(entity)
    
    async def smart_search(
        self,
        query: str,
        limit: int = 10,
    ) -> list:
        """Hybrid semantic+keyword search.
        
        Args:
            query: Search query
            limit: Max results
            
        Returns:
            Search results
        """
        return await self.mcp_client.memory_smart_search(query, limit=limit)
    
    # ========================================
    # Private Helper Methods
    # ========================================
    
    async def _generate_summary(self, messages: list[Msg]) -> str:
        """Generate a summary using the chat model."""
        if not self.chat_model or not self.formatter:
            return self._generate_simple_summary(messages)
        
        # Format messages for summarization
        text = "\n".join(
            f"{m.name}: {m.content}"
            for m in messages[-20:]  # Last 20 messages
        )
        
        prompt = f"""请总结以下对话的关键内容：

{text}

总结要点："""

        try:
            response = await self.chat_model.achat(
                self.formatter.format([Msg(role="user", content=prompt)])
            )
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.warning(f"Summary generation failed: {e}")
            return self._generate_simple_summary(messages)
    
    def _generate_simple_summary(self, messages: list[Msg]) -> str:
        """Generate a simple summary without LLM."""
        if not messages:
            return ""
        
        # Count message types
        roles = {}
        for m in messages:
            role = m.name or "unknown"
            roles[role] = roles.get(role, 0) + 1
        
        # Generate basic summary
        summary_parts = [
            f"共 {len(messages)} 条消息",
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ]
        
        if roles:
            role_strs = [f"{k}: {v}条" for k, v in roles.items()]
            summary_parts.append("参与者: " + ", ".join(role_strs))
        
        return " | ".join(summary_parts)
    
    async def _compact_with_llm(
        self,
        messages: list[Msg],
        previous_summary: str,
        extra_instruction: str,
    ) -> str:
        """Compact messages using LLM."""
        if not self.chat_model:
            return previous_summary
        
        # Build compaction prompt
        text = "\n".join(
            f"{m.name}: {str(m.content)[:500]}"
            for m in messages
        )
        
        prompt = f"""请压缩以下对话内容，保留关键信息：

{text}

{f"之前的摘要: {previous_summary}" if previous_summary else ""}
{extra_instruction}

压缩后的内容："""

        try:
            response = await self.chat_model.achat(
                self.formatter.format([Msg(role="user", content=prompt)])
            )
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.warning(f"Compaction failed: {e}")
            return previous_summary
