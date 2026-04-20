# -*- coding: utf-8 -*-
"""MCP client for AgentMemory service using official MCP SDK.

This module provides a Python client for communicating with the AgentMemory
MCP server using the official mcp package SDK.
"""

import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Any, Optional

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

logger = logging.getLogger(__name__)


class AgentMemoryMCPClient:
    """Client for AgentMemory MCP server using official MCP SDK.
    
    This client wraps the MCP SDK's stdio client to communicate with
    the AgentMemory MCP server.
    
    Example:
        async with AgentMemoryMCPClient() as client:
            # Save memory
            result = await client.memory_save(
                content="User prefers dark theme",
                type="preference"
            )
            
            # Recall memories
            results = await client.memory_recall("theme preference")
    """
    
    def __init__(
        self,
        command: str = "npx",
        args: list = None,
        env: dict = None,
        cwd: str = None,
    ):
        """Initialize AgentMemory MCP client.
        
        Args:
            command: Command to start MCP server (default: npx)
            args: Arguments for the command
            env: Environment variables
            cwd: Working directory
        """
        self.server_params = StdioServerParameters(
            command=command,
            args=args or ["-y", "@agentmemory/mcp"],
            env=env,
            cwd=cwd,
        )
        
        self._stack: Optional[AsyncExitStack] = None
        self.session: Optional[ClientSession] = None
        self.is_connected = False
    
    async def __aenter__(self):
        """Start the MCP client as async context manager."""
        await self.start()
        return self
    
    async def __aexit__(self, *args):
        """Close the MCP client."""
        await self.close()
    
    async def start(self) -> None:
        """Start the MCP client and initialize session."""
        if self.is_connected:
            return
        
        self._stack = AsyncExitStack()
        
        # Start stdio client
        context = await self._stack.__aenter__()
        read_stream, write_stream = await self._stack.enter_async_context(
            stdio_client(self.server_params)
        )
        
        # Initialize session
        self.session = ClientSession(read_stream, write_stream)
        await self._stack.enter_async_context(self.session)
        await self.session.initialize()
        
        self.is_connected = True
        logger.info("AgentMemory MCP client started")
    
    async def close(self) -> None:
        """Close the MCP client."""
        if self._stack:
            await self._stack.__aexit__(None, None, None)
            self._stack = None
            self.session = None
            self.is_connected = False
            logger.info("AgentMemory MCP client closed")
    
    async def call_tool(self, name: str, arguments: dict = None) -> Any:
        """Call an MCP tool.
        
        Args:
            name: Tool name
            arguments: Tool arguments
            
        Returns:
            Tool result
        """
        if not self.session:
            raise RuntimeError("MCP client not started")
        
        result = await self.session.call_tool(name, arguments or {})
        
        # Extract text content
        if result.content:
            for item in result.content:
                if hasattr(item, "text"):
                    import json
                    try:
                        return json.loads(item.text)
                    except json.JSONDecodeError:
                        return item.text
        
        return result
    
    # ========================================
    # AgentMemory Tool Wrappers
    # ========================================
    
    async def memory_recall(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.1,
        format: str = "full",
    ) -> list:
        """Recall memories by semantic search.
        
        Args:
            query: Search query
            limit: Maximum results
            min_score: Minimum similarity score
            format: Output format
            
        Returns:
            List of memories
        """
        result = await self.call_tool("memory_recall", {
            "query": query,
            "limit": limit,
            "min_score": min_score,
            "format": format,
        })
        
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "results" in result:
            return result["results"]
        return []
    
    async def memory_save(
        self,
        content: str,
        type: str = "fact",
        concepts: str = "",
        files: str = "",
        metadata: dict = None,
    ) -> str:
        """Save a memory.
        
        Args:
            content: Memory content
            type: Memory type (pattern/preference/architecture/bug/workflow/fact)
            concepts: Comma-separated concepts
            files: Comma-separated file paths
            metadata: Optional metadata
            
        Returns:
            Memory ID or confirmation
        """
        args = {"content": content, "type": type}
        if concepts:
            args["concepts"] = concepts
        if files:
            args["files"] = files
        if metadata:
            args["metadata"] = metadata
        
        result = await self.call_tool("memory_save", args)
        return str(result)
    
    async def memory_patterns(self) -> list:
        """Get detected patterns."""
        result = await self.call_tool("memory_patterns", {})
        return result if isinstance(result, list) else []
    
    async def memory_relations(self, entity: str = "") -> list:
        """Get memory relations."""
        args = {"entity": entity} if entity else {}
        result = await self.call_tool("memory_relations", args)
        return result if isinstance(result, list) else []
    
    async def memory_sessions(self) -> list:
        """List recent sessions."""
        result = await self.call_tool("memory_sessions", {})
        return result if isinstance(result, list) else []
    
    async def memory_smart_search(
        self,
        query: str,
        limit: int = 10,
        expand_ids: str = "",
    ) -> list:
        """Hybrid semantic+keyword search."""
        args = {"query": query, "limit": limit}
        if expand_ids:
            args["expandIds"] = expand_ids
        
        result = await self.call_tool("memory_smart_search", args)
        return result if isinstance(result, list) else []
