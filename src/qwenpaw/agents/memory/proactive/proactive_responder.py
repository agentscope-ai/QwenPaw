# -*- coding: utf-8 -*-
"""Responder logic for proactive conversation feature."""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Optional, List, Dict

import aiohttp
from agentscope.agent import ReActAgent
from agentscope.message import Msg
from agentscope.tool import Toolkit

from ....app.agent_context import get_current_agent_id
from ....app.workspace import Workspace
from ....config.config import load_agent_config
from ...prompt import get_active_model_supports_multimodal
from ...tools import (
    browser_use,
    execute_shell_command,
    read_file,
    desktop_screenshot,
)
from .proactive_prompts import (
    PROACTIVE_TASK_EXTRACTION_PROMPT,
    PROACTIVE_USER_FACING_MESSAGE_PROMPT,
)
from .proactive_types import ProactiveQueryResult, ProactiveTask
from .proactive_utils import (
    build_proactive_memory_context,
    load_json_safely,
    ensure_tz_aware,
    is_agent_busy,
)

logger = logging.getLogger(__name__)


async def generate_proactive_response(
    workspace: Workspace,
) -> Optional[Msg]:
    """Main function to generate proactive response based on memory."""
    baseline_timestamp = datetime.now(timezone.utc)  # Use UTC time directly
    active_agent_id = get_current_agent_id()

    agent = await _initialize_single_proactive_agent(
        active_agent_id,
    )

    memory_context_str = await build_proactive_memory_context(
        workspace=workspace,
        agent=agent,
    )

    if await _was_interrupted(
        baseline_timestamp,
        workspace,
    ):
        logger.info("Proactive response generation interrupted")
        return None

    tasks = await _extract_tasks_from_memory(memory_context_str, agent)

    results = []
    for task in tasks[:3]:
        if await _was_interrupted(
            baseline_timestamp,
            workspace,
        ):
            logger.info("Proactive response generation interrupted")
            return None

        result = await _execute_query(task.query, agent)
        results.append(result)

        if result.success and result.data:
            break
    if await _was_interrupted(
        baseline_timestamp,
        workspace,
    ):
        logger.info("Proactive response generation interrupted")
        return None

    if results:
        message_content = await _generate_final_message(
            results[-1],
            active_agent_id,
        )

        if message_content:
            return message_content

    return None


async def _initialize_single_proactive_agent(
    agent_id: str = "proactive",
) -> ReActAgent:
    """Initialize a single proactive agent instance."""
    agent_config = load_agent_config(agent_id)
    agent_config.running.max_iters = 50

    # Create model and formatter for the agent
    from ...model_factory import create_model_and_formatter

    model, formatter = create_model_and_formatter(agent_id=agent_config.id)

    # Create toolkit and register tools conditionally
    toolkit = Toolkit()
    toolkit.register_tool_function(browser_use)
    toolkit.register_tool_function(read_file)
    toolkit.register_tool_function(execute_shell_command)

    # Register desktop_screenshot only if the model supports multimodal
    if get_active_model_supports_multimodal():
        toolkit.register_tool_function(desktop_screenshot)

    agent = ReActAgent(
        name="ProactiveAssistant",
        model=model,
        sys_prompt="You are a helpful assistant.",
        toolkit=toolkit,
        formatter=formatter,
        memory=None,
        max_iters=agent_config.running.max_iters,
    )

    return agent


async def _extract_tasks_from_memory(
    memory_context: str,
    agent: ReActAgent,
) -> List[ProactiveTask]:
    """Extract likely user tasks from memory context."""
    prompt = f"{PROACTIVE_TASK_EXTRACTION_PROMPT}\n#Contexts: {memory_context}"
    response = await agent.reply(Msg(name="User", role="user", content=prompt))

    if not response or not response.content:
        return []

    text_content = response.get_text_content()
    parsed_data = load_json_safely(text_content)

    if parsed_data and "tasks" in parsed_data:
        return _create_tasks_from_data(parsed_data["tasks"])

    json_match = re.search(r"\{.*\}", text_content, re.DOTALL)
    if json_match:
        parsed_data = load_json_safely(json_match.group(0))
        if parsed_data and "tasks" in parsed_data:
            return _create_tasks_from_data(parsed_data["tasks"])

    return []


def _create_tasks_from_data(tasks_data: List[Dict]) -> List[ProactiveTask]:
    """Helper to create ProactiveTask instances from data."""
    tasks = []
    for i, task_data in enumerate(tasks_data):
        if "task" in task_data and "query" in task_data:
            tasks.append(
                ProactiveTask(
                    task=task_data["task"],
                    query=task_data["query"],
                    priority=i + 1,
                    reason=task_data.get("why", ""),
                ),
            )
    return tasks


async def _execute_query(
    query: str,
    agent: ReActAgent,
) -> ProactiveQueryResult:
    """Execute a query using available tools."""
    prompt = (
        f"Task: Answer: {query} using tools -- "
        "`browser_use` primary, `execute_shell_command`/`read_file` "
        "only if essential.\n"
        "Self-check: Did you retrieve new, query-relevant data or "
        "complete given task?\n"
        "Output: Query answer and end strictly with `[SUCCESS]` "
        "(yes) or `[FAILURE]` (no).\n"
        "⚠️ CRITICAL: The flag MUST be the absolute last token. "
        "No trailing text."
    )

    response = await agent.reply(Msg(name="User", role="user", content=prompt))

    success = False
    response_content = response.get_text_content()
    if response_content:
        match = re.search(r"\[(SUCCESS)\]\s*$", response_content.strip())
        if match:
            success = True

    return ProactiveQueryResult(
        query=query,
        success=success,
        data=response_content,
    )


async def _generate_final_message(
    result: ProactiveQueryResult,
    active_agent_id: str,
) -> Optional[Msg]:
    """Generate the final proactive message for the user."""
    if not result.data:
        return None

    gathered_info = f"Query: {result.query}\nResult: {result.data}\n\n"

    agent_language = load_agent_config(active_agent_id).language
    proactive_content = PROACTIVE_USER_FACING_MESSAGE_PROMPT.format(
        gathered_info=gathered_info,
        language=agent_language,
    )

    await send_proactive_message_via_http(
        active_agent_id=active_agent_id,
        proactive_content=proactive_content,
        timeout_seconds=300,
    )

    return None


async def send_proactive_message_via_http(
    active_agent_id: str,
    proactive_content: str,
    timeout_seconds: int = 60,
) -> str:
    """Send a proactive message by directly calling the QwenPaw API."""

    from ...tools.agent_management import resolve_agent_api_base_url

    session_id = f"proactive_mode:{active_agent_id}"

    request_payload = {
        "session_id": session_id,
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "[Agent proactive_helper requesting] "
                            f"{proactive_content}"
                        ),
                    },
                ],
            },
        ],
    }

    headers = {"X-Agent-Id": active_agent_id}
    timeout_config = aiohttp.ClientTimeout(total=timeout_seconds)

    base_url = resolve_agent_api_base_url()
    clean_base = base_url.rstrip("/")
    api_base_url = (
        f"{clean_base}/api" if not clean_base.endswith("/api") else clean_base
    )

    try:
        async with aiohttp.ClientSession() as session:
            url = f"{api_base_url.rstrip('/')}/agent/process"
            async with session.post(
                url,
                json=request_payload,
                headers=headers,
                timeout=timeout_config,
            ) as resp:
                resp.raise_for_status()
                last_data = None
                async for line_bytes in resp.content:
                    line = line_bytes.decode("utf-8").strip()
                    if line.startswith("data: "):
                        try:
                            last_data = line[6:]
                        except Exception:
                            continue

                if last_data:
                    logger.info("Proactive message sent successfully via HTTP")
                else:
                    logger.warning("No valid SSE data received from agent")

    except asyncio.TimeoutError:
        logger.error(
            "Timeout (%ds) calling QwenPaw API for proactive message",
            timeout_seconds,
        )
    except Exception as e:
        logger.error("Error calling QwenPaw API for proactive message: %s", e)

    return None


async def _was_interrupted(
    baseline_timestamp: datetime,
    workspace: Optional[Workspace] = None,
) -> bool:
    """Check if the proactive process was interrupted by new user activity.

    This enhanced version combines:
    Active task checking - if agent is busy with user requests
    Timestamp comparison - if session was updated since baseline
    """
    # Check if the agent has active tasks (busy with user messages)
    if workspace:
        try:
            is_busy = await is_agent_busy(workspace)
            if is_busy:
                return True
        except Exception as e:
            logger.warning(f"Error checking if agent is busy: {e}")

    # Check if any chat was updated since the baseline timestamp
    if workspace and hasattr(workspace, "chat_manager"):
        try:
            chats = await workspace.chat_manager.list_chats()
            baseline_tz_aware = ensure_tz_aware(baseline_timestamp)

            for chat in chats:
                chat_updated_tz_aware = ensure_tz_aware(chat.updated_at)
                if chat_updated_tz_aware > baseline_tz_aware:
                    logger.info(f"Interrupt detected: chat {chat.id}")
                    return True

        except Exception as e:
            logger.warning(f"Error checking chat updates: {e}")

    return False
