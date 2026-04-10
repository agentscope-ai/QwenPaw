# -*- coding: utf-8 -*-
"""Agent-to-agent chat tool built on the shared agent chat service."""

import asyncio
import json
from typing import Optional

import httpx
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...app.services.agent_communicate import (
    AgentChatRequest,
    AgentChatTaskStatus,
    collect_agent_chat_final_response,
    get_agent_chat_task_status,
    prepare_agent_chat_request,
    submit_agent_chat_background_task,
)
from ...config.utils import read_last_api


DEFAULT_AGENT_CHAT_BASE_URL = "http://127.0.0.1:8088"


def _tool_response(text: str) -> ToolResponse:
    """Wrap text into a standard tool response."""
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _resolve_base_url(base_url: Optional[str]) -> str:
    """Resolve the API base URL for agent chat tool calls."""
    if base_url:
        return base_url.rstrip("/")

    last_api = read_last_api()
    if last_api is not None:
        host, port = last_api
        return f"http://{host}:{port}"

    return DEFAULT_AGENT_CHAT_BASE_URL


def _format_final_response(session_id: str, text: str) -> str:
    """Format a final chat response for tool output."""
    if text:
        return f"[SESSION: {session_id}]\n\n{text}"
    return f"[SESSION: {session_id}]\n\n(No text content in response)"


def _format_submission(task_id: str, session_id: str) -> str:
    """Format a background task submission response."""
    return (
        f"[TASK_ID: {task_id}]\n"
        f"[SESSION: {session_id}]\n\n"
        "Task submitted successfully.\n"
        "Check status later with agent_chat(background=true, task_id=...)."
    )


def _format_task_status(status_payload: AgentChatTaskStatus) -> str:
    """Format a background task status response."""
    lines = [
        f"[TASK_ID: {status_payload.task_id}]",
        f"[STATUS: {status_payload.status}]",
        "",
    ]

    if status_payload.status == "finished":
        if status_payload.task_status == "completed":
            lines.append("Task completed")
            if status_payload.text:
                lines.extend(["", status_payload.text])
        elif status_payload.task_status == "failed":
            result = status_payload.response_data.get("result", {})
            if isinstance(result, dict):
                error_info = result.get("error", {})
            else:
                error_info = {}
            error_msg = error_info.get("message", "Unknown error")
            lines.extend(["Task failed", "", f"Error: {error_msg}"])
        else:
            lines.append(f"Status: {status_payload.task_status}")
    elif status_payload.status == "running":
        created_at = status_payload.response_data.get("created_at", "N/A")
        lines.extend(
            [
                "Task is still running...",
                f"Started at: {created_at}",
            ]
        )
    elif status_payload.status == "pending":
        lines.append("Task is pending in queue...")
    elif status_payload.status == "submitted":
        lines.append("Task submitted, waiting to start...")
    else:
        lines.append(f"Unknown status: {status_payload.status}")

    return "\n".join(lines).strip()


async def agent_chat(
    to_agent: Optional[str] = None,
    text: Optional[str] = None,
    session_id: Optional[str] = None,
    new_session: bool = False,
    background: bool = False,
    task_id: Optional[str] = None,
    timeout: float = 600.0,
    base_url: Optional[str] = None,
    json_output: bool = False,
) -> ToolResponse:
    """Send a message to another agent or query an existing background task.

    Examples:
        Real-time request:
            agent_chat(to_agent="reviewer", text="Please review this plan")

        Continue an existing session:
            agent_chat(
                to_agent="reviewer",
                text="Please expand item 2",
                session_id="planner:to:reviewer:...",
            )

        Submit a background task:
            agent_chat(
                to_agent="data_analyst",
                text="Analyze the latest logs and summarize anomalies",
                background=True,
            )

        Query a background task:
            agent_chat(background=True, task_id="20802ea3-...")

    Args:
        to_agent: Target agent ID. Required for new chat requests and optional
            when querying an existing background task.
        text: Message text to send to the target agent. Required for new chat
            requests.
        session_id: Optional existing session ID for multi-turn continuation.
        new_session: Force a fresh session even if ``session_id`` is provided.
        background: Submit as a background task or query a background task.
        task_id: Existing background task ID to query. Requires
            ``background=True``.
        timeout: Request timeout in seconds.
        base_url: Optional API base URL, defaults to the local app endpoint.
        json_output: Return raw JSON payload instead of formatted text.

    Returns:
        ToolResponse with either formatted text or JSON.
    """
    from ...app.agent_context import get_current_agent_id

    resolved_base_url = _resolve_base_url(base_url)
    current_agent_id = get_current_agent_id()
    to_agent = to_agent.strip().strip("\"") if to_agent else None

    try:
        if task_id:
            if not background:
                return _tool_response(
                    "Error: task_id requires background=True."
                )

            status_payload = await asyncio.to_thread(
                get_agent_chat_task_status,
                resolved_base_url,
                task_id,
                to_agent,
                int(timeout),
            )
            if json_output:
                return _tool_response(
                    json.dumps(
                        status_payload.response_data,
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return _tool_response(_format_task_status(status_payload))

        if not to_agent:
            return _tool_response("Error: to_agent is required.")
        if not text:
            return _tool_response("Error: text is required.")
        if to_agent == current_agent_id:
            return _tool_response(
                "Error: agent_chat does not allow sending to the current "
                "agent."
            )

        prepared_request = prepare_agent_chat_request(
            AgentChatRequest(
                from_agent=current_agent_id,
                to_agent=to_agent,
                text=text,
                session_id=session_id,
                new_session=new_session,
            )
        )

        if background:
            submission = await asyncio.to_thread(
                submit_agent_chat_background_task,
                resolved_base_url,
                prepared_request,
                int(timeout),
            )
            if json_output:
                return _tool_response(
                    json.dumps(
                        submission.response_data,
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return _tool_response(
                _format_submission(submission.task_id, submission.session_id)
            )

        final_response = await asyncio.to_thread(
            collect_agent_chat_final_response,
            resolved_base_url,
            prepared_request,
            int(timeout),
        )
        if json_output:
            return _tool_response(
                json.dumps(
                    final_response.response_data,
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return _tool_response(
            _format_final_response(
                final_response.session_id,
                final_response.text,
            )
        )

    except ValueError as e:
        return _tool_response(f"Error: {e}")
    except httpx.HTTPError as e:
        return _tool_response(f"Error: agent chat request failed: {e}")
