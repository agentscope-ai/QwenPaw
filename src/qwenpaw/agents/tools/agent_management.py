# -*- coding: utf-8 -*-
"""Tools and shared helpers for agent discovery and inter-agent chat."""

import asyncio
import json
import re
import time
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

import httpx
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config.utils import read_last_api


DEFAULT_AGENT_API_BASE_URL = "http://127.0.0.1:8088"
DEFAULT_AGENT_API_TIMEOUT = 30.0


def resolve_agent_api_base_url(base_url: Optional[str] = None) -> str:
    """Resolve the agent API base URL.

    Priority:
    1. Explicit ``base_url`` argument
    2. Last recorded API host/port from config
    3. Built-in localhost fallback
    """
    if base_url:
        return base_url.rstrip("/")

    last_api = read_last_api()
    if last_api:
        host, port = last_api
        return f"http://{host}:{port}"

    return DEFAULT_AGENT_API_BASE_URL


def _normalize_api_base_url(base_url: Optional[str]) -> str:
    base = resolve_agent_api_base_url(base_url).rstrip("/")
    if not base.endswith("/api"):
        base = f"{base}/api"
    return base


def _tool_text_response(text: str) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def normalize_id(id_to_normalize: Optional[str]) -> Optional[str]:
    """Trim surrounding whitespace and quotes from an ID."""
    if id_to_normalize is None:
        return None
    return id_to_normalize.strip().strip("\"'").strip()


def create_agent_api_client(
    base_url: Optional[str],
    default_timeout: float = DEFAULT_AGENT_API_TIMEOUT,
) -> httpx.Client:
    """Create an HTTP client targeting the local agent API."""
    return httpx.Client(
        base_url=_normalize_api_base_url(base_url),
        timeout=default_timeout,
    )


def generate_unique_session_id(from_agent: str, to_agent: str) -> str:
    """Generate a concurrency-safe session ID for inter-agent chat."""
    timestamp = int(time.time() * 1000)
    uuid_short = str(uuid4())[:8]
    return f"{from_agent}:to:{to_agent}:{timestamp}:{uuid_short}"


def resolve_calling_agent_id(from_agent: Optional[str] = None) -> str:
    """Resolve the calling agent ID.

    Priority:
    1. Explicit ``from_agent`` argument
    2. Current runtime agent context
    """
    if from_agent:
        return from_agent
    from ...app.agent_context import get_current_agent_id

    return get_current_agent_id()


def resolve_agent_session_id(
    from_agent: Optional[str],
    to_agent: str,
    session_id: Optional[str],
) -> str:
    """Resolve the effective session ID based on session reuse semantics."""
    caller_agent_id = resolve_calling_agent_id(from_agent)
    if not session_id:
        return generate_unique_session_id(caller_agent_id, to_agent)
    return session_id


def ensure_agent_identity_prefix(
    text: str,
    from_agent: Optional[str] = None,
) -> str:
    """Prefix inter-agent prompts so the target knows the message source."""
    caller_agent_id = resolve_calling_agent_id(from_agent)
    patterns = [
        r"^\[Agent\s+\w+",
        r"^\[来自智能体\s+\w+",
    ]
    stripped = text.strip()
    for pattern in patterns:
        if re.match(pattern, stripped):
            return text
    return f"[Agent {caller_agent_id} requesting] {text}"


def parse_agent_sse_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single SSE line emitted by /agent/process."""
    stripped = line.strip()
    if stripped.startswith("data: "):
        try:
            return json.loads(stripped[6:])
        except json.JSONDecodeError:
            return None
    return None


def extract_agent_text_content(response_data: Dict[str, Any]) -> str:
    """Extract concatenated text blocks from an agent response payload."""
    try:
        output = response_data.get("output", [])
        if not output:
            return ""

        last_msg = output[-1]
        content = last_msg.get("content", [])

        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))

        return "\n".join(text_parts).strip()
    except (KeyError, IndexError, TypeError):
        return ""


def list_agents_data(
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch the configured agent list from the local API."""
    with create_agent_api_client(base_url) as client:
        response = client.get("/agents")
        response.raise_for_status()
        return response.json()


def extract_agent_ids(agent_list_data: Dict[str, Any]) -> set[str]:
    """Extract configured agent IDs from the /agents payload."""
    agents = agent_list_data.get("agents", [])
    if not isinstance(agents, list):
        return set()

    agent_ids = set()
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        agent_id = agent.get("id")
        if isinstance(agent_id, str) and agent_id:
            agent_ids.add(agent_id)
    return agent_ids


def agent_exists(
    to_agent: str,
    base_url: Optional[str] = None,
) -> bool:
    """Check whether the target agent exists in the configured agent list."""
    return to_agent in extract_agent_ids(list_agents_data(base_url))


def build_agent_chat_request(
    to_agent: str,
    text: str,
    session_id: Optional[str] = None,
    from_agent: Optional[str] = None,
) -> tuple[str, Dict[str, Any], bool]:
    """Build the inter-agent chat payload and resolve the final session ID."""
    caller_agent_id = resolve_calling_agent_id(from_agent)
    final_session_id = resolve_agent_session_id(
        caller_agent_id,
        to_agent,
        session_id,
    )
    final_text = ensure_agent_identity_prefix(text, caller_agent_id)
    request_payload = {
        "session_id": final_session_id,
        "input": [
            {
                "role": "user",
                "content": [{"type": "text", "text": final_text}],
            },
        ],
    }
    return final_session_id, request_payload, final_text != text


def _request_headers(to_agent: Optional[str]) -> Dict[str, str]:
    return {"X-Agent-Id": to_agent} if to_agent else {}


def stream_agent_chat(
    base_url: Optional[str],
    request_payload: Dict[str, Any],
    to_agent: str,
    timeout: int,
    line_handler: Callable[[str], None] | None = None,
) -> list[str]:
    """Stream SSE lines from inter-agent chat."""
    lines: list[str] = []
    with create_agent_api_client(base_url, default_timeout=timeout) as client:
        with client.stream(
            "POST",
            "/agent/process",
            json=request_payload,
            headers=_request_headers(to_agent),
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    lines.append(line)
                    if line_handler is not None:
                        line_handler(line)
    return lines


def collect_final_agent_chat_response(
    base_url: Optional[str],
    request_payload: Dict[str, Any],
    to_agent: str,
    timeout: int,
) -> Optional[Dict[str, Any]]:
    """Collect the last SSE payload from inter-agent chat."""
    response_data: Optional[Dict[str, Any]] = None
    with create_agent_api_client(base_url) as client:
        with client.stream(
            "POST",
            "/agent/process",
            json=request_payload,
            headers=_request_headers(to_agent),
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    parsed = parse_agent_sse_line(line)
                    if parsed:
                        response_data = parsed
    return response_data


def submit_agent_chat_task(
    base_url: Optional[str],
    request_payload: Dict[str, Any],
    to_agent: str,
    timeout: int,
) -> Dict[str, Any]:
    """Submit an inter-agent chat task for background execution."""
    with create_agent_api_client(base_url) as client:
        response = client.post(
            "/agent/process/task",
            json=request_payload,
            headers=_request_headers(to_agent),
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()


def get_agent_chat_task_status(
    base_url: Optional[str],
    task_id: str,
    to_agent: Optional[str] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """Get the current status for a background inter-agent chat task."""
    with create_agent_api_client(base_url) as client:
        response = client.get(
            f"/agent/process/task/{task_id}",
            headers=_request_headers(to_agent),
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()


def format_agent_chat_text(
    response_data: Dict[str, Any],
    session_id: Optional[str] = None,
) -> str:
    """Format agent chat output as plain text for tool consumption."""
    text = extract_agent_text_content(response_data)
    parts: list[str] = []
    if session_id:
        parts.append(f"[SESSION: {session_id}]")
        parts.append("")
    parts.append(text or "(No text content in response)")
    return "\n".join(parts)


def format_background_submission_text(
    task_result: Dict[str, Any],
    session_id: str,
) -> str:
    """Format background submission result as plain text."""
    task_id = task_result.get("task_id")
    if not task_id:
        return "ERROR: No task_id returned from server"

    return "\n".join(
        [
            f"[TASK_ID: {task_id}]",
            f"[SESSION: {session_id}]",
            "",
            "Task submitted successfully.",
            "Check status with: check_agent_task(" f"task_id='{task_id}')",
        ],
    )


def format_background_status_text(
    task_id: str,
    result: Dict[str, Any],
) -> str:
    """Format background task status as plain text."""
    status = result.get("status", "unknown")
    parts = [f"[TASK_ID: {task_id}]", f"[STATUS: {status}]", ""]

    if status == "finished":
        task_result = result.get("result", {})
        task_status = task_result.get("status")
        if task_status == "completed":
            parts.append("Task completed.")
            parts.append("")
            parts.append(
                format_agent_chat_text(
                    task_result,
                    session_id=task_result.get("session_id"),
                ),
            )
        elif task_status == "failed":
            error_info = task_result.get("error", {})
            error_msg = error_info.get("message", "Unknown error")
            parts.append("Task failed.")
            parts.append("")
            parts.append(f"Error: {error_msg}")
        else:
            parts.append(_json_text(result))
        return "\n".join(parts)

    if status == "running":
        started_at = result.get("started_at", "N/A")
        parts.append("Task is still running...")
        parts.append(f"Started at: {started_at}")
    elif status == "pending":
        parts.append("Task is pending in queue...")
    elif status == "submitted":
        parts.append("Task submitted, waiting to start...")
    else:
        parts.append(_json_text(result))
    return "\n".join(parts)


async def list_agents(
    base_url: Optional[str] = None,
) -> ToolResponse:
    """List all configured agents from the QwenPaw service.

    Returns:
        `ToolResponse`:
            A tool response containing the agent list as json text. Each agent
            has its id, name, description and workspace directory.
    """
    result = await asyncio.to_thread(list_agents_data, base_url)
    return _tool_text_response(_json_text(result))


async def chat_with_agent(
    to_agent: str,
    text: str,
    session_id: Optional[str] = None,
    timeout: int = 300,
) -> ToolResponse:
    """Send a foreground message to another configured agent.

    This tool waits for the target agent to finish and returns the final text
    response in a single tool result. It is intended for direct inter-agent
    consultation where the caller expects an immediate reply rather than a
    background task handle.

    Args:
        to_agent (`str`):
            The target agent ID to send the message to. This must be an agent
            ID returned by ``list_agents``.
        text (`str`):
            The message text to send to the target agent.
        session_id (`str`, optional):
            Existing session ID to continue a previous conversation. If not
            provided, a new session ID is generated automatically.
        timeout (`int`, optional):
            Foreground wait timeout in seconds. Callers should estimate how
            long the target agent may need to finish to reduce avoidable
            timeout failures.

    Returns:
        `ToolResponse`:
            A text response containing the final agent reply. Successful
            responses include a ``[SESSION: ...]`` header followed by the reply
            text so the caller can reuse the same session in later turns.
    """
    normalized_to_agent = normalize_id(to_agent)
    normalized_session_id = normalize_id(session_id)
    if not normalized_to_agent:
        return _tool_text_response("ERROR: 'to_agent' is required for chat")

    target_exists = await asyncio.to_thread(
        agent_exists,
        normalized_to_agent,
        None,
    )
    if not target_exists:
        return _tool_text_response(
            f"Agent [{normalized_to_agent}] not exists",
        )

    final_session_id, request_payload, _ = build_agent_chat_request(
        normalized_to_agent,
        text,
        session_id=normalized_session_id,
        from_agent=None,
    )

    response_data = await asyncio.to_thread(
        collect_final_agent_chat_response,
        None,
        request_payload,
        normalized_to_agent,
        timeout,
    )
    if not response_data:
        return _tool_text_response("(No response received)")

    return _tool_text_response(
        format_agent_chat_text(response_data, session_id=final_session_id),
    )


async def submit_to_agent(
    to_agent: str,
    text: str,
    session_id: Optional[str] = None,
) -> ToolResponse:
    """Submit a background message to another configured agent.

    This tool is the background-task counterpart to ``chat_with_agent``. It
    submits the request and returns immediately with task metadata instead of
    waiting for the target agent to finish.

    Args:
        to_agent (`str`):
            The target agent ID to send the message to. This must be an agent
            ID returned by ``list_agents``.
        text (`str`):
            The message text to execute as a background task.
        session_id (`str`, optional):
            Existing session ID to continue a previous conversation in the
            background. If not provided, a new session ID is generated.

    Returns:
        `ToolResponse`:
            A text response containing ``[TASK_ID: ...]`` and
            ``[SESSION: ...]`` headers. The returned task ID can be passed to
            ``check_agent_task`` to inspect progress or fetch the final result.
    """
    normalized_to_agent = normalize_id(to_agent)
    normalized_session_id = normalize_id(session_id)
    if not normalized_to_agent:
        return _tool_text_response(
            "ERROR: 'to_agent' is required for submission",
        )

    target_exists = await asyncio.to_thread(
        agent_exists,
        normalized_to_agent,
        None,
    )
    if not target_exists:
        return _tool_text_response(
            f"Agent [{normalized_to_agent}] not exists",
        )

    final_session_id, request_payload, _ = build_agent_chat_request(
        normalized_to_agent,
        text,
        session_id=normalized_session_id,
        from_agent=None,
    )
    result = await asyncio.to_thread(
        submit_agent_chat_task,
        None,
        request_payload,
        normalized_to_agent,
        int(DEFAULT_AGENT_API_TIMEOUT),
    )
    return _tool_text_response(
        format_background_submission_text(result, final_session_id),
    )


async def check_agent_task(
    task_id: str,
) -> ToolResponse:
    """Check the status of a background inter-agent task.

    This tool queries a previously submitted background task by its task ID.
    If the task is still in progress, it returns the current lifecycle state.
    If the task has finished, it returns either the final agent response or a
    failure message.

    Args:
        task_id (`str`):
            The background task ID returned by ``submit_to_agent``.

    Returns:
        `ToolResponse`:
            A text response containing a ``[TASK_ID: ...]`` header and current
            task status. Completed tasks also include the resolved session ID
            and final agent text when available.
    """
    normalized_task_id = normalize_id(task_id)
    if not normalized_task_id:
        return _tool_text_response(
            "ERROR: 'task_id' is required to check task status",
        )

    result = await asyncio.to_thread(
        get_agent_chat_task_status,
        None,
        normalized_task_id,
        to_agent=None,
        timeout=10,
    )
    return _tool_text_response(
        format_background_status_text(normalized_task_id, result),
    )
