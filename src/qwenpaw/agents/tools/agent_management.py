# -*- coding: utf-8 -*-
"""Tools and shared helpers for agent discovery and inter-agent chat."""

import asyncio
import json
import logging
import math
import re
import time
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

import httpx
from agentscope.message import TextBlock
from agentscope.tool import ToolChunk
from agentscope.message import ToolResultState

from ...config.utils import read_last_api
from ...runtime.tool_registry import tool_descriptor
from ...utils.http import trust_env_for_url

logger = logging.getLogger(__name__)

DEFAULT_AGENT_API_BASE_URL = "http://127.0.0.1:8088"
DEFAULT_AGENT_API_TIMEOUT = 30.0
MAX_SPAWN_BATCH_SIZE = 10
MAX_SPAWN_BATCH_CONCURRENCY = 3


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


def _tool_text_response(text: str) -> ToolChunk:
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=text)],
    )


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
    normalized = _normalize_api_base_url(base_url)
    return httpx.Client(
        base_url=normalized,
        timeout=default_timeout,
        trust_env=trust_env_for_url(normalized),
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
    """Parse a single SSE line emitted by /console/chat."""
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
    root_session_id: Optional[str] = None,
) -> tuple[str, Dict[str, Any], bool]:
    """Build the inter-agent chat payload and resolve the final session ID.

    Args:
        to_agent: Target agent ID
        text: Message text
        session_id: Optional session ID override
        from_agent: Calling agent ID (for identity prefix)
        root_session_id: Root session ID for cross-session approval routing

    Returns:
        Tuple of (final_session_id, request_payload, text_was_prefixed)
    """
    caller_agent_id = resolve_calling_agent_id(from_agent)
    final_session_id = resolve_agent_session_id(
        caller_agent_id,
        to_agent,
        session_id,
    )
    final_text = ensure_agent_identity_prefix(text, caller_agent_id)
    request_payload = {
        "session_id": final_session_id,
        "user_id": caller_agent_id,
        "input": [
            {
                "role": "user",
                "content": [{"type": "text", "text": final_text}],
            },
        ],
        "request_context": {
            "root_agent_id": caller_agent_id,
        },
    }

    # Add root_session_id as top-level field for approval routing
    if root_session_id:
        request_payload["root_session_id"] = root_session_id

    return final_session_id, request_payload, final_text != text


def _request_headers(
    to_agent: Optional[str],
) -> Dict[str, str]:
    """Build HTTP headers for agent chat requests.

    Args:
        to_agent: Target agent ID

    Returns:
        Dictionary of HTTP headers
    """
    headers = {}
    if to_agent:
        headers["X-Agent-Id"] = to_agent
    return headers


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
            "/console/chat",
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
    """Collect the last non-metadata SSE payload from inter-agent chat.

    Skips trailing ``turn_usage`` events so the caller receives
    the actual agent response instead of usage telemetry.
    """
    response_data: Optional[Dict[str, Any]] = None
    with create_agent_api_client(base_url) as client:
        with client.stream(
            "POST",
            "/console/chat",
            json=request_payload,
            headers=_request_headers(to_agent),
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    parsed = parse_agent_sse_line(line)
                    if parsed and parsed.get("type") != "turn_usage":
                        response_data = parsed
    return response_data


def submit_agent_chat_task(
    base_url: Optional[str],
    request_payload: Dict[str, Any],
    to_agent: str,
    timeout: int,
    task_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Submit an inter-agent chat task for background execution."""
    payload = dict(request_payload)
    if task_timeout is not None:
        payload["timeout"] = task_timeout
    with create_agent_api_client(base_url) as client:
        response = client.post(
            "/console/chat/task",
            json=payload,
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
            f"/console/chat/task/{task_id}",
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
            "The subagent is working autonomously"
            " \u2014 do NOT poll immediately.",
            "Wait at least 30 seconds, then check with:",
            f"  check_agent_task(task_id='{task_id}')",
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
        parts.append("")
        parts.append(
            "Do NOT poll again immediately."
            " Wait at least 30 seconds before next check.",
        )
    elif status == "pending":
        parts.append("Task is pending in queue...")
    elif status == "submitted":
        parts.append("Task submitted, waiting to start...")
    else:
        parts.append(_json_text(result))
    return "\n".join(parts)


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    policy_name="ListAgents",
    ui_description="List configured agents from the local API",
    ui_icon="🤖",
)
async def list_agents(
    base_url: Optional[str] = None,
) -> ToolChunk:
    """List all configured agents from the QwenPaw service.

    Returns:
        `ToolChunk`:
            A tool response containing the agent list as json text. Each agent
            has its id, name, description and workspace directory.
    """
    result = await asyncio.to_thread(list_agents_data, base_url)
    return _tool_text_response(_json_text(result))


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    target_param="to_agent",
    policy_name="ChatWithAgent",
    ui_description=(
        "Send a message to another configured agent and wait for "
        "the response"
    ),
    ui_icon="💬",
)
async def chat_with_agent(
    to_agent: str,
    text: str,
    session_id: Optional[str] = None,
    timeout: int = 300,
) -> ToolChunk:
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
        `ToolChunk`:
            A text response containing the final agent reply. Successful
            responses include a ``[SESSION: ...]`` header followed by the reply
            text so the caller can reuse the same session in later turns.
    """
    normalized_to_agent = normalize_id(to_agent)
    normalized_session_id = normalize_id(session_id)
    if not normalized_to_agent:
        return _tool_text_response("ERROR: 'to_agent' is required for chat")
    if not text:
        return _tool_text_response("ERROR: 'text' is required for chat")

    target_exists = await asyncio.to_thread(
        agent_exists,
        normalized_to_agent,
        None,
    )
    if not target_exists:
        return _tool_text_response(
            f"Agent [{normalized_to_agent}] not exists",
        )

    # Get root_session_id from current context for cross-session approval
    from ...app.agent_context import (
        get_current_session_id,
        get_current_root_session_id,
    )

    caller_session_id = get_current_session_id() or ""
    caller_root_session = get_current_root_session_id()
    final_root_session = caller_root_session or caller_session_id

    final_session_id, request_payload, _ = build_agent_chat_request(
        normalized_to_agent,
        text,
        session_id=normalized_session_id,
        from_agent=None,
        root_session_id=final_root_session,
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


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    target_param="to_agent",
    policy_name="SubmitToAgent",
    ui_description="Submit a background task to another configured agent",
    ui_icon="📨",
)
async def submit_to_agent(
    to_agent: str,
    text: str,
    session_id: Optional[str] = None,
    task_timeout: Optional[float] = None,
) -> ToolChunk:
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
        task_timeout (`float`, optional):
            Task execution timeout in seconds. Overrides the server-side
            default stream_task_timeout for this specific task.

    Returns:
        `ToolChunk`:
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
    if not text:
        return _tool_text_response(
            "ERROR: 'text' is required for submission",
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

    # Get root_session_id from current context for cross-session approval
    from ...app.agent_context import (
        get_current_session_id,
        get_current_root_session_id,
    )

    caller_session_id = get_current_session_id() or ""
    caller_root_session = get_current_root_session_id()
    final_root_session = caller_root_session or caller_session_id

    final_session_id, request_payload, _ = build_agent_chat_request(
        normalized_to_agent,
        text,
        session_id=normalized_session_id,
        from_agent=None,
        root_session_id=final_root_session,
    )

    result = await asyncio.to_thread(
        submit_agent_chat_task,
        None,
        request_payload,
        normalized_to_agent,
        int(DEFAULT_AGENT_API_TIMEOUT),
        task_timeout,
    )
    return _tool_text_response(
        format_background_submission_text(result, final_session_id),
    )


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    target_param="task_id",
    policy_name="CheckAgentTask",
    ui_description="Check the status of a background agent task",
    ui_icon="⏳",
)
async def check_agent_task(
    task_id: str,
) -> ToolChunk:
    """Check the status of a background inter-agent task.

    This tool queries a previously submitted background task by its task ID.
    If the task is still in progress, it returns the current lifecycle state.
    If the task has finished, it returns either the final agent response or a
    failure message.

    Args:
        task_id (`str`):
            The background task ID returned by ``submit_to_agent``.

    Returns:
        `ToolChunk`:
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
    # Background fork workers: commit on success, mark failed otherwise.
    if isinstance(result, dict) and result.get("status") == "finished":
        task_result = result.get("result")
        if isinstance(task_result, dict):
            try:
                from ..fork_project import (
                    finalize_fork_for_task,
                    mark_fork_failed_for_task,
                )
                from ...config.context import get_current_workspace_dir

                ws = get_current_workspace_dir()
                if task_result.get("status") == "completed":
                    await asyncio.to_thread(
                        finalize_fork_for_task,
                        normalized_task_id,
                        workspace_dir=ws,
                    )
                else:
                    err = task_result.get("error") or {}
                    reason = (
                        err.get("message", "background task failed")
                        if isinstance(err, dict)
                        else "background task failed"
                    )
                    await asyncio.to_thread(
                        mark_fork_failed_for_task,
                        normalized_task_id,
                        workspace_dir=ws,
                        reason=str(reason),
                    )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Fork finalize/fail on check_agent_task failed for %s",
                    normalized_task_id,
                    exc_info=True,
                )
    return _tool_text_response(
        format_background_status_text(normalized_task_id, result),
    )


def _generate_subagent_session_id() -> str:
    """Generate a short session ID for a spawned subagent."""
    return f"sub-{str(uuid4())[:8]}"


def _json_safe_channel_meta(value: Any) -> Any:
    """Keep channel routing metadata safe to include in an HTTP payload."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, raw_value in value.items():
            safe_value = _json_safe_channel_meta(raw_value)
            if safe_value is not None:
                safe[str(key)] = safe_value
        return safe
    if isinstance(value, (list, tuple)):
        safe_list = []
        for raw_value in value:
            safe_value = _json_safe_channel_meta(raw_value)
            if safe_value is not None:
                safe_list.append(safe_value)
        return safe_list
    return None


def _build_spawn_request_context(current_agent_id: str) -> dict[str, Any]:
    """Build approval routing metadata without changing child identity."""
    from ...app.agent_context import (
        get_current_approval_route,
        get_current_channel,
        get_current_root_session_id,
        get_current_session_id,
        get_current_user_id,
    )

    inherited = get_current_approval_route() or {}
    context: dict[str, Any] = {
        "root_session_id": (
            inherited.get("root_session_id")
            or get_current_root_session_id()
            or get_current_session_id()
            or ""
        ),
        "root_agent_id": current_agent_id,
        "user_id": inherited.get("user_id") or get_current_user_id() or "",
        "channel": inherited.get("channel") or get_current_channel() or "",
        "_spawn_subagent": True,
    }
    safe_meta = _json_safe_channel_meta(inherited.get("channel_meta") or {})
    if isinstance(safe_meta, dict) and safe_meta:
        context["channel_meta"] = safe_meta
    return context


def _coerce_json_list(value: Any, field_name: str) -> Optional[list[Any]]:
    """Coerce a tool arg to ``list``; accept JSON-array strings from LLMs.

    Returns ``None`` when *value* is ``None``.  Raises ``ValueError`` for
    non-list values (after optional JSON decode of strings).
    """
    if value is None:
        return None
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(
                f"'{field_name}' must be a list or a JSON array string",
            )
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(
                f"'{field_name}' must be a list or a JSON array string",
            ) from exc
        if not isinstance(parsed, list):
            raise ValueError(
                f"'{field_name}' JSON value must be an array, "
                f"got {type(parsed).__name__}",
            )
        return parsed
    raise ValueError(
        f"'{field_name}' must be a list or a JSON array string",
    )


def _normalize_str_list(
    value: Any,
    field_name: str,
) -> Optional[list[str]]:
    """Validate an optional list[str] tool argument.

    Accepts a real ``list[str]`` or a JSON array string (common LLM
    mis-serialization).  Returns ``None`` when *value* is ``None``.
    Raises ``ValueError`` when the value is not a list of strings
    (prevents ``list("abc")`` character-splitting on mistaken string
    inputs that are not JSON arrays).
    """
    if value is None:
        return None
    coerced = _coerce_json_list(value, field_name)
    assert coerced is not None
    if not all(isinstance(item, str) for item in coerced):
        raise ValueError(
            f"'{field_name}' must be a list of strings or null",
        )
    return list(coerced)


def _coerce_bool(
    value: Any,
    default: bool = False,
    *,
    field_name: str = "value",
) -> bool:
    """Parse a bool tool field; reject ambiguous truthiness.

    ``bool("false")`` / ``bool("null")`` are ``True`` in Python — only
    accept explicit bool / ``0|1`` / known true/false strings.  Anything
    else raises ``ValueError`` (no ``bool(value)`` fallthrough).
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off"):
            return False
    raise ValueError(
        f"'{field_name}' must be a boolean "
        f"(or 0/1 / true/false / yes/no / on/off)",
    )


def _coerce_timeout(
    value: Any,
    default: int = 600,
    *,
    field_name: str = "timeout",
) -> int:
    """Parse a timeout tool field to ``int`` seconds.

    Accepts ``int`` / ``float`` / numeric strings (LLM mis-serialization).
    Rejects bools, non-numeric values, and non-positive timeouts.
    """
    if value is None:
        return default
    # bool is an int subclass — do not treat True/False as 1/0 seconds.
    if isinstance(value, bool):
        raise ValueError(
            f"'{field_name}' must be a positive number (seconds)",
        )
    if isinstance(value, (int, float)):
        as_float = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(
                f"'{field_name}' must be a positive number (seconds)",
            )
        try:
            as_float = float(text)
        except ValueError as exc:
            raise ValueError(
                f"'{field_name}' must be a positive number (seconds)",
            ) from exc
    else:
        raise ValueError(
            f"'{field_name}' must be a positive number (seconds)",
        )
    if not math.isfinite(as_float):
        raise ValueError(
            f"'{field_name}' must be a positive number (seconds)",
        )
    # Truncation can turn (0, 1) into 0 — reject after int(), not before.
    as_int = int(as_float)
    if as_int <= 0:
        raise ValueError(
            f"'{field_name}' must be a positive number (seconds)",
        )
    return as_int


def _normalize_batch(
    value: Any,
) -> Optional[list[Dict[str, Any]]]:
    """Normalize ``batch`` to ``list[dict]`` or ``None``.

    Accepts a real list or a JSON array string.  Structural checks
    (non-empty, per-item ``task``) remain in :func:`_spawn_batch`.
    """
    if value is None:
        return None
    coerced = _coerce_json_list(value, "batch")
    assert coerced is not None
    return coerced  # type: ignore[return-value]


def _build_subagent_request_context(
    current_agent_id: str,
    allowed_tools: Optional[list[str]] = None,
    skills: Optional[list[str]] = None,
    extra: Optional[dict] = None,
) -> dict[str, Any]:
    """Build request_context with approval routing + tool/skill filters."""
    rc = _build_spawn_request_context(current_agent_id)
    if extra:
        rc.update(extra)
    if allowed_tools is not None:
        rc["subagent_allowed_tools"] = list(allowed_tools)
    if skills is not None:
        rc["subagent_skills"] = list(skills)
    return rc


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    policy_name="SpawnSubagent",
    ui_description="Spawn an ephemeral sub-task within the current workspace",
    ui_icon="🔀",
)
async def spawn_subagent(  # pylint: disable=too-many-return-statements
    task: str,
    fork: bool | str | int = False,
    background: bool | str | int = False,
    timeout: int | float | str = 600,
    allowed_tools: Optional[list[str] | str] = None,
    skills: Optional[list[str] | str] = None,
    batch: Optional[list[Dict[str, Any]] | str] = None,
) -> ToolChunk:
    """Spawn an ephemeral subagent within the CURRENT workspace.

    The subagent starts a **fresh conversation context** — it does NOT
    inherit the parent agent's dialogue history, accumulated state, or
    in-progress tool calls.  It shares the same agent identity,
    workspace, and (by default) the full set of available tools and
    skills.  Use ``allowed_tools`` / ``skills`` to restrict what a
    subagent can access.

    Unlike ``chat_with_agent`` (which targets a *different* configured
    agent), this tool creates a disposable one-shot worker under the
    current agent's identity.

    Args:
        task: Description of the sub-task.  This becomes the sole user
            message in the subagent's conversation.  Always required by
            the signature; pass an empty string when using ``batch``.
        fork: Controls two independent features:
            1. **Session state inheritance** — the subagent receives a
               copy of the parent's persisted session state.
            2. **Git worktree isolation** — if the project directory is
               a git repository, the subagent works in a dedicated
               worktree so its file changes cannot conflict with the
               parent or other subagents.
            When False (default), the subagent starts with an empty
            session and works in the original project directory.
            A JSON/string boolean (e.g. ``"false"``) is also accepted
            for LLM mis-serialization; ambiguous values return ERROR.
        background: If True, submit as a background task and return
            immediately with a task_id.  The subagent typically runs for
            **minutes, not seconds** — do NOT poll immediately.  Wait at
            least 30 seconds before the first ``check_agent_task`` call,
            and use 30-60 second intervals between subsequent polls.
            Prefer ``background=False`` (foreground) when only spawning
            a single subagent — it blocks until completion, eliminating
            the need to poll entirely.  String booleans are accepted
            like ``fork``; ambiguous values return ERROR.
        timeout: Foreground wait timeout in seconds (default 600).
            Ignored when ``background=True``.  Numeric strings (e.g.
            ``"600"``) are accepted for LLM mis-serialization; invalid
            values return ERROR.  Ignored entirely in batch mode.
        allowed_tools: Tool-name whitelist.  Only the listed tools are
            available to the subagent.  ``None`` (default) inherits the
            parent's full tool set.  An empty list denies all tools.
            A JSON array string is also accepted (LLM mis-serialization).
            Ignored in batch mode (use per-item ``allowed_tools``).
        skills: Skill-name whitelist.  Only the listed SKILL.md files
            are loaded for the subagent.  ``None`` (default) inherits
            all skills resolved for this workspace.  A JSON array
            string is also accepted.  Ignored in batch mode (use
            per-item ``skills``).
        batch: List of task specs for batch mode.  When provided,
            ``task`` must be an empty string.  Each dict must contain a
            ``task`` key; optional keys: ``fork``, ``timeout``,
            ``allowed_tools``, ``skills`` (top-level ``fork`` /
            ``timeout`` / ``allowed_tools`` / ``skills`` /
            ``background`` are ignored in batch mode).
            A JSON array string is also accepted so schema validation
            does not reject common LLM stringification.  All subagents
            run as background tasks.  Maximum length is
            ``MAX_SPAWN_BATCH_SIZE`` (10); concurrent dispatches are
            capped at ``MAX_SPAWN_BATCH_CONCURRENCY`` (3).

    Returns:
        Foreground (single): subagent result text with [SESSION: <id>].
        Background (single): [TASK_ID: <id>] + [SESSION: <id>].
        Fork foreground: also [FORK_BRANCH: <branch>] if changes.
        Batch: per-subagent [TASK_ID: ...] + [SESSION: ...].
    """
    try:
        batch = _normalize_batch(batch)
    except ValueError as exc:
        return _tool_text_response(f"ERROR: {exc}")

    if batch is not None:
        if task and task.strip():
            return _tool_text_response(
                "ERROR: 'task' and 'batch' are mutually exclusive. "
                "Pass task='' with 'batch' for multiple subagents.",
            )
        # Top-level fork/background/timeout/allowed_tools/skills are
        # ignored in batch mode — do not normalize/coerce them here or
        # LLM placeholder strings would block dispatch.
        return await _spawn_batch(batch)

    if not task or not task.strip():
        return _tool_text_response(
            "ERROR: 'task' is required for spawn_subagent "
            "(use task='' only with batch=...)",
        )

    try:
        allowed_tools = _normalize_str_list(
            allowed_tools,
            "allowed_tools",
        )
        skills = _normalize_str_list(skills, "skills")
        fork = _coerce_bool(fork, default=False, field_name="fork")
        background = _coerce_bool(
            background,
            default=False,
            field_name="background",
        )
        timeout = _coerce_timeout(timeout, default=600, field_name="timeout")
    except ValueError as exc:
        return _tool_text_response(f"ERROR: {exc}")

    from ...app.agent_context import get_current_agent_id

    current_agent_id = get_current_agent_id()
    if not current_agent_id:
        return _tool_text_response(
            "ERROR: unable to resolve current agent ID",
        )

    subagent_session_id = _generate_subagent_session_id()

    if fork:
        return await _spawn_forked_subagent(
            task=task,
            current_agent_id=current_agent_id,
            subagent_session_id=subagent_session_id,
            background=background,
            timeout=timeout,
            allowed_tools=allowed_tools,
            skills=skills,
        )

    request_context = _build_subagent_request_context(
        current_agent_id,
        allowed_tools=allowed_tools,
        skills=skills,
    )
    request_payload = {
        "session_id": subagent_session_id,
        "input": [
            {
                "role": "user",
                "content": [{"type": "text", "text": task}],
            },
        ],
        "request_context": request_context,
    }

    if background:
        result = await asyncio.to_thread(
            submit_agent_chat_task,
            None,
            request_payload,
            current_agent_id,
            int(DEFAULT_AGENT_API_TIMEOUT),
            float(timeout),
        )
        return _tool_text_response(
            format_background_submission_text(
                result,
                subagent_session_id,
            ),
        )

    response_data = await asyncio.to_thread(
        collect_final_agent_chat_response,
        None,
        request_payload,
        current_agent_id,
        timeout,
    )
    if not response_data:
        return _tool_text_response(
            "(No response received from subagent)",
        )

    return _tool_text_response(
        format_agent_chat_text(
            response_data,
            session_id=subagent_session_id,
        ),
    )


def _chunk_text(chunk: ToolChunk) -> str:
    """Extract plain text from a ToolChunk, if present."""
    if not chunk.content:
        return ""
    block = chunk.content[0]
    text = getattr(block, "text", None)
    return text if isinstance(text, str) else str(block)


async def _spawn_batch(
    specs: list[Dict[str, Any]],
) -> ToolChunk:
    """Dispatch multiple subagents in parallel as background tasks."""
    if not isinstance(specs, list) or not specs:
        return _tool_text_response(
            "ERROR: 'batch' must be a non-empty list",
        )
    if len(specs) > MAX_SPAWN_BATCH_SIZE:
        return _tool_text_response(
            f"ERROR: batch size {len(specs)} exceeds "
            f"maximum of {MAX_SPAWN_BATCH_SIZE}",
        )
    normalized: list[Dict[str, Any]] = []
    for i, spec in enumerate(specs):
        if (
            not isinstance(spec, dict)
            or not str(
                spec.get("task", ""),
            ).strip()
        ):
            return _tool_text_response(
                f"ERROR: batch[{i}] must be a dict with a "
                f"non-empty 'task' field",
            )
        try:
            normalized.append(
                {
                    **spec,
                    "allowed_tools": _normalize_str_list(
                        spec.get("allowed_tools"),
                        f"batch[{i}].allowed_tools",
                    ),
                    "skills": _normalize_str_list(
                        spec.get("skills"),
                        f"batch[{i}].skills",
                    ),
                    # Validate fork/timeout before any dispatch so a bad
                    # value cannot partially spawn siblings (gather).
                    "fork": _coerce_bool(
                        spec.get("fork"),
                        default=False,
                        field_name=f"batch[{i}].fork",
                    ),
                    "timeout": _coerce_timeout(
                        spec.get("timeout"),
                        default=600,
                        field_name=f"batch[{i}].timeout",
                    ),
                },
            )
        except ValueError as exc:
            return _tool_text_response(f"ERROR: {exc}")

    from ...app.agent_context import get_current_agent_id

    current_agent_id = get_current_agent_id()
    if not current_agent_id:
        return _tool_text_response(
            "ERROR: unable to resolve current agent ID",
        )

    sem = asyncio.Semaphore(MAX_SPAWN_BATCH_CONCURRENCY)

    async def _dispatch_one(spec: Dict[str, Any]) -> str:
        session_id = _generate_subagent_session_id()
        task_text = spec["task"]
        spec_fork = bool(spec["fork"])
        spec_timeout = int(spec["timeout"])
        spec_allowed = spec.get("allowed_tools")
        spec_skills = spec.get("skills")

        async with sem:
            if spec_fork:
                chunk = await _spawn_forked_subagent(
                    task=task_text,
                    current_agent_id=current_agent_id,
                    subagent_session_id=session_id,
                    background=True,
                    timeout=spec_timeout,
                    allowed_tools=spec_allowed,
                    skills=spec_skills,
                )
                return _chunk_text(chunk)

            rc = _build_subagent_request_context(
                current_agent_id,
                allowed_tools=spec_allowed,
                skills=spec_skills,
            )
            payload = {
                "session_id": session_id,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": task_text},
                        ],
                    },
                ],
                "request_context": rc,
            }
            result = await asyncio.to_thread(
                submit_agent_chat_task,
                None,
                payload,
                current_agent_id,
                int(DEFAULT_AGENT_API_TIMEOUT),
                float(spec_timeout),
            )
            return format_background_submission_text(result, session_id)

    results = await asyncio.gather(
        *[_dispatch_one(s) for s in normalized],
        return_exceptions=True,
    )

    lines: list[str] = []
    for i, r in enumerate(results):
        prefix = f"[{i + 1}/{len(specs)}]"
        if isinstance(r, Exception):
            lines.append(f"{prefix} ERROR: {r}")
        else:
            lines.append(f"{prefix} {r}")

    return _tool_text_response("\n\n".join(lines))


async def _call_fork_api(
    agent_id: str,
    parent_session_id: str,
    user_id: Optional[str] = None,
    channel: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Call POST /api/fork/agent to prepare fork session + worktree."""
    url = (
        _normalize_api_base_url(base_url).removesuffix("/api")
        + "/api/fork/agent"
    )
    payload = {
        "agent_id": agent_id,
        "parent_session_id": parent_session_id,
        "user_id": user_id,
        "channel": channel,
    }
    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            trust_env=trust_env_for_url(url),
        ) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


async def _spawn_forked_subagent(
    task: str,
    current_agent_id: str,
    subagent_session_id: str,
    background: bool,
    timeout: int,
    allowed_tools: Optional[list[str]] = None,
    skills: Optional[list[str]] = None,
) -> ToolChunk:
    """Fork path: call /api/fork/agent then dispatch subagent."""
    # pylint: disable=too-many-branches,too-many-statements
    from ...app.agent_context import (
        get_current_session_id,
        get_current_user_id,
        get_current_channel,
    )

    parent_session_id = get_current_session_id() or ""
    user_id = get_current_user_id() or ""
    channel = get_current_channel() or ""

    fork_result = await _call_fork_api(
        agent_id=current_agent_id,
        parent_session_id=parent_session_id,
        user_id=user_id,
        channel=channel,
    )
    if not fork_result or "error" in fork_result:
        err = (fork_result or {}).get("error", "unknown error")
        return _tool_text_response(
            f"ERROR: fork API failed: {err}",
        )

    fork_session_id = fork_result.get(
        "fork_session_id",
        subagent_session_id,
    )
    worktree_path = fork_result.get("worktree_path", "")
    worktree_branch = fork_result.get("worktree_branch", "")

    from ..fork_project import (
        FORK_WORKER_COMMIT_PROTOCOL,
        bind_fork_task,
        finalize_fork_worktree_or_fail,
        get_active_fork_scope,
        register_fork,
    )
    from ...config.context import get_current_workspace_dir

    # Workers must commit; inject protocol even when the caller forgot.
    worker_task = task
    if worktree_path and FORK_WORKER_COMMIT_PROTOCOL not in task:
        worker_task = f"{FORK_WORKER_COMMIT_PROTOCOL}\n\n{task}"

    fork_extra: dict[str, Any] | None = None
    fork_scope_id = ""
    if worktree_path:
        # ``fork_project_dir`` is the spawn-level key; also set the ACP
        # coding-project meta key so AgentBuilder / ContextVars rebind
        # tools/cwd to the worktree.
        from ..acp.meta import ACP_CODING_PROJECT_META_KEY

        workspace_dir = get_current_workspace_dir()
        registered = await asyncio.to_thread(
            register_fork,
            worktree_path,
            worktree_branch,
            session_id=fork_session_id,
            workspace_dir=workspace_dir,
        )
        if not registered:
            return _tool_text_response(
                "ERROR: failed to register fork for merge verification "
                f"(branch={worktree_branch or '?'}). Aborting spawn so "
                "the merge gate cannot be bypassed.",
            )
        fork_scope_id = get_active_fork_scope(workspace_dir)
        fork_extra = {
            "fork_project_dir": worktree_path,
            ACP_CODING_PROJECT_META_KEY: worktree_path,
            "fork_worktree_branch": worktree_branch,
            "fork_scope_id": fork_scope_id,
        }
    request_context = _build_subagent_request_context(
        current_agent_id,
        allowed_tools=allowed_tools,
        skills=skills,
        extra=fork_extra,
    )

    request_payload: dict = {
        "session_id": fork_session_id,
        "user_id": user_id,
        "channel": channel,
        "input": [
            {
                "role": "user",
                "content": [{"type": "text", "text": worker_task}],
            },
        ],
        "request_context": request_context,
    }

    if background:
        result = await asyncio.to_thread(
            submit_agent_chat_task,
            None,
            request_payload,
            current_agent_id,
            int(DEFAULT_AGENT_API_TIMEOUT),
            # Align console cancel with spawn timeout / fork watchdog.
            float(timeout),
        )
        task_id = result.get("task_id") if isinstance(result, dict) else None
        if worktree_path and task_id:
            await asyncio.to_thread(
                bind_fork_task,
                worktree_path,
                worktree_branch,
                str(task_id),
                expected_scope=fork_scope_id or None,
            )
            # Poller fallback if the console completion hook is unavailable.
            # finalize_fork_worktree is claim/idempotent so overlapping
            # console-hook / check_agent_task paths are safe.
            asyncio.create_task(
                _watch_background_fork_finalize(
                    str(task_id),
                    worktree_path,
                    worktree_branch,
                    timeout=timeout,
                    expected_scope=fork_scope_id or None,
                ),
            )
        submission_text = format_background_submission_text(
            result,
            fork_session_id,
        )
        if worktree_path:
            submission_text += (
                f"\n\n[FORK_BRANCH: {worktree_branch}]"
                "\nWorktree cleanup is not automatic in "
                "background mode."
            )
        return _tool_text_response(submission_text)

    response_data = await asyncio.to_thread(
        collect_final_agent_chat_response,
        None,
        request_payload,
        current_agent_id,
        timeout,
    )

    # Only commit on a successful worker response (avoid half-baked commits).
    finalize_ok = False
    if worktree_path and response_data:
        finalize_ok = await asyncio.to_thread(
            finalize_fork_worktree_or_fail,
            worktree_path,
            worktree_branch,
            message=f"fork worker {worktree_branch or fork_session_id}",
            expected_scope=fork_scope_id or None,
        )
    elif worktree_path:
        from ..fork_project import mark_fork_failed

        await asyncio.to_thread(
            mark_fork_failed,
            worktree_path,
            worktree_branch,
            reason="No response from forked subagent",
            expected_scope=fork_scope_id or None,
        )

    # Do not auto-remove the worktree on the sync path: the controller
    # needs [FORK_BRANCH:] to merge, and cleanup would hide that signal.
    if not response_data:
        return _tool_text_response(
            "(No response received from forked subagent)",
        )

    result_text = format_agent_chat_text(
        response_data,
        session_id=fork_session_id,
    )

    # Only advertise [FORK_BRANCH:] when finalize succeeded; a failed
    # finalize is marked in the registry and must not look merge-ready.
    if worktree_path and finalize_ok:
        result_text += (
            f"\n\n[FORK_BRANCH: {worktree_branch}]"
            "\nForked worktree retained for merge; clean up after "
            "`git merge` succeeds."
        )
    elif worktree_path:
        result_text += (
            f"\n\n[FORK_FINALIZE_FAILED: {worktree_branch}]"
            "\nFork was marked failed; do not merge until re-run succeeds."
        )

    return _tool_text_response(result_text)


async def _watch_background_fork_finalize(
    task_id: str,
    worktree_path: str,
    worktree_branch: str,
    *,
    timeout: int = 600,
    expected_scope: str | None = None,
) -> None:
    """Poll until the background task finishes or *timeout* elapses."""
    from ..fork_project import (
        finalize_fork_worktree_or_fail,
        mark_fork_failed,
    )

    # Align with worker timeout (default 600s); console hook remains primary.
    deadline = time.time() + max(30, int(timeout) + 30)
    delay = 2.0
    while time.time() < deadline:
        await asyncio.sleep(delay)
        delay = min(delay * 1.5, 30.0)
        try:
            status = await asyncio.to_thread(
                get_agent_chat_task_status,
                None,
                task_id,
                to_agent=None,
                timeout=10,
            )
        except Exception:  # noqa: BLE001
            continue
        if status.get("status") != "finished":
            continue
        result = status.get("result") or {}
        if result.get("status") == "completed":
            await asyncio.to_thread(
                finalize_fork_worktree_or_fail,
                worktree_path,
                worktree_branch,
                message=f"fork worker {worktree_branch}",
                expected_scope=expected_scope,
            )
        else:
            err = result.get("error") or {}
            reason = (
                err.get("message", "background task failed")
                if isinstance(err, dict)
                else "background task failed"
            )
            await asyncio.to_thread(
                mark_fork_failed,
                worktree_path,
                worktree_branch,
                reason=str(reason),
                expected_scope=expected_scope,
            )
        return

    await asyncio.to_thread(
        mark_fork_failed,
        worktree_path,
        worktree_branch,
        reason="finalize watchdog timeout",
        expected_scope=expected_scope,
    )
