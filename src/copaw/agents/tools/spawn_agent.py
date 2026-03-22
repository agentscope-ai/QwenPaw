# -*- coding: utf-8 -*-
"""Spawn agent tool for multi-agent orchestration.

Allows an agent to delegate tasks to other agents dynamically.
Uses context variables for spawn context (inspired by OpenClaw pattern).
"""

import asyncio
import logging
import uuid

from agentscope.message import Msg, TextBlock
from agentscope.tool import ToolResponse
from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest

logger = logging.getLogger(__name__)

# Reference to MultiAgentManager (set during app startup)
_multi_agent_manager = None


def set_multi_agent_manager(manager):
    """Set the global MultiAgentManager reference.

    Called during app startup to make the manager available to tools.
    """
    global _multi_agent_manager
    _multi_agent_manager = manager


def get_multi_agent_manager():
    """Get the MultiAgentManager reference.

    Returns:
        MultiAgentManager instance or None if not set.
    """
    return _multi_agent_manager


def _error_response(message: str) -> ToolResponse:
    """Create an error ToolResponse with proper format.

    Args:
        message: Error message text.

    Returns:
        ToolResponse with TextBlock containing the error.
    """
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=message,
            ),
        ],
    )


def _success_response(agent_id: str, text: str) -> ToolResponse:
    """Create a success ToolResponse with proper format.

    Args:
        agent_id: ID of the spawned agent.
        text: Response text from the spawned agent.

    Returns:
        ToolResponse with TextBlock containing the response.
    """
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=f"[Agent: {agent_id}]\n{text}",
            ),
        ],
    )


async def _collect_agent_response(
    runner,
    message: Msg,
    request: AgentRequest,
    timeout: int,
) -> Msg:
    """Collect response from agent's query_handler async generator.

    Args:
        runner: AgentRunner instance
        message: Message to send to the agent
        request: AgentRequest with session context
        timeout: Timeout in seconds

    Returns:
        Final response message

    Raises:
        asyncio.TimeoutError: If timeout exceeded
    """
    result_msg = None

    async def collect():
        nonlocal result_msg
        async for item in runner.query_handler([message], request):
            # The generator yields (Msg, is_last) tuples or just Msg
            if isinstance(item, tuple):
                msg, is_last = item
                if is_last:
                    result_msg = msg
                    return
                result_msg = msg
            else:
                result_msg = item

    await asyncio.wait_for(collect(), timeout=timeout)
    return result_msg


async def spawn_agent(
    agent_id: str,
    prompt: str,
    timeout: int = 300,
) -> ToolResponse:
    # pylint: disable=too-many-return-statements,too-many-branches
    """Spawn another agent to handle a task.

    This tool allows an agent to delegate work to another agent.
    The spawned agent will process the prompt and return its response.

    Permissions are checked based on the current agent's orchestration config:
    - can_spawn_agents must be True
    - agent_id must be in allowed_agents (if list is not empty)
    - max_spawn_depth must not be exceeded
    - Cannot spawn self (would cause infinite loop)

    Args:
        agent_id: ID of the agent to spawn (e.g., "researcher", "writer").
        prompt: The task or question to send to the spawned agent.
        timeout: Maximum time to wait for response in seconds (default: 300).
                 Must be positive.

    Returns:
        ToolResponse with the spawned agent's response or error message.
    """
    from ...app.agent_context import (
        get_current_agent_id,
        get_spawn_depth,
        SpawnDepthContext,
    )
    from ...config.config import load_agent_config, OrchestrationConfig

    # --- Input validation ---
    if not agent_id or not agent_id.strip():
        return _error_response("Error: agent_id cannot be empty.")

    if not prompt or not prompt.strip():
        return _error_response("Error: prompt cannot be empty.")

    if timeout <= 0:
        return _error_response(
            f"Error: timeout must be positive, got {timeout}.",
        )

    # --- Check manager availability ---
    if _multi_agent_manager is None:
        return _error_response(
            "Error: Multi-agent system not available. Cannot spawn agents.",
        )

    current_agent_id = get_current_agent_id()
    current_depth = get_spawn_depth()

    # --- Prevent self-spawning ---
    if agent_id == current_agent_id:
        return _error_response(
            f"Error: Agent '{agent_id}' cannot spawn itself. "
            f"This would cause an infinite loop.",
        )

    try:
        # Load current agent's config to get orchestration settings
        try:
            agent_config = load_agent_config(current_agent_id)
            orchestration = agent_config.orchestration
        except Exception as e:
            logger.warning(f"Failed to load agent config: {e}, using defaults")
            orchestration = OrchestrationConfig()

        # Check if spawning is enabled
        if not orchestration.can_spawn_agents:
            return _error_response(
                f"Error: Agent '{current_agent_id}' is not "
                f"allowed to spawn other agents. Enable "
                f"'can_spawn_agents' in agent configuration.",
            )

        # Check spawn depth
        if current_depth >= orchestration.max_spawn_depth:
            return _error_response(
                f"Error: Maximum spawn depth "
                f"({orchestration.max_spawn_depth}) exceeded. "
                f"Current depth: {current_depth}.",
            )

        # Check if target agent is allowed
        if (
            orchestration.allowed_agents
            and agent_id not in orchestration.allowed_agents
        ):
            return _error_response(
                f"Error: Agent '{agent_id}' is not in the allowed list. "
                f"Allowed agents: {orchestration.allowed_agents}.",
            )

        # Get the target agent workspace
        workspace = await _multi_agent_manager.get_agent(agent_id)
        if workspace is None:
            return _error_response(
                f"Error: Agent '{agent_id}' not found. "
                f"Check if the agent exists and is configured.",
            )

        # Check if runner is available
        if workspace.runner is None:
            return _error_response(
                f"Error: Agent '{agent_id}' is not running. "
                f"The agent may not have been started.",
            )

        # Create message for the spawned agent
        message = Msg(
            name="user",
            content=prompt,
            role="user",
        )

        # Create AgentRequest for the spawned agent
        spawn_session_id = (
            f"spawn-{current_agent_id}-{agent_id}-{uuid.uuid4().hex[:8]}"
        )
        spawn_request = AgentRequest(
            input=[{"content": [{"type": "text", "text": prompt}]}],
            session_id=spawn_session_id,
            user_id=f"spawned_by_{current_agent_id}",
            channel="spawn",
        )

        # Execute with increased spawn depth using context manager
        try:
            with SpawnDepthContext():
                result_msg = await _collect_agent_response(
                    workspace.runner,
                    message,
                    spawn_request,
                    timeout,
                )

            if result_msg is None:
                return _error_response(
                    f"Error: Agent '{agent_id}' returned no response.",
                )

        except asyncio.TimeoutError:
            return _error_response(
                f"Error: Agent '{agent_id}' timed out after "
                f"{timeout} seconds.",
            )

        # Extract text content from result
        response_text = _extract_text_from_result(result_msg)

        return _success_response(agent_id, response_text)

    except Exception as e:
        logger.exception(f"Failed to spawn agent '{agent_id}'")
        return _error_response(f"Error spawning agent '{agent_id}': {str(e)}")


def _extract_text_from_result(result) -> str:
    """Extract text content from a result message.

    Args:
        result: Result from agent execution (Msg or similar).

    Returns:
        Extracted text string.
    """
    if result is None:
        return ""

    if hasattr(result, "content"):
        content = result.content
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            # Extract text from content blocks
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif "text" in block:
                        text_parts.append(block["text"])
                elif isinstance(block, str):
                    text_parts.append(block)
            return "\n".join(text_parts)
        else:
            return str(content)

    return str(result)
