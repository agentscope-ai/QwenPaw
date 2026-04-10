# -*- coding: utf-8 -*-
"""Shared service helpers for agent discovery and communication."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional
from uuid import uuid4

import httpx


def normalize_api_base_url(base_url: str) -> str:
    """Ensure HTTP client base URL includes the ``/api`` prefix."""
    base = base_url.rstrip("/")
    if not base.endswith("/api"):
        base = f"{base}/api"
    return base


def _generate_unique_session_id(from_agent: str, to_agent: str) -> str:
    """Generate unique session_id (concurrency-safe)."""
    timestamp = int(time.time() * 1000)
    uuid_short = str(uuid4())[:8]
    return f"{from_agent}:to:{to_agent}:{timestamp}:{uuid_short}"


def _resolve_session_id(
    from_agent: str,
    to_agent: str,
    session_id: Optional[str],
) -> str:
    """Resolve final session_id, generating a new one when absent."""
    if not session_id:
        return _generate_unique_session_id(from_agent, to_agent)
    return session_id


def ensure_agent_identity_prefix(text: str, from_agent: str) -> str:
    """Ensure outgoing text starts with an agent identity prefix."""
    patterns = [
        r"^\[Agent\s+\w+",
        r"^\[来自智能体\s+\w+",
    ]
    stripped_text = text.strip()
    for pattern in patterns:
        if re.match(pattern, stripped_text):
            return text
    return f"[Agent {from_agent} requesting] {text}"


def parse_sse_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single SSE line and return JSON data if valid."""
    stripped = line.strip()
    if stripped.startswith("data: "):
        try:
            return json.loads(stripped[6:])
        except json.JSONDecodeError:
            return None
    return None


def extract_text_content(response_data: Dict[str, Any]) -> str:
    """Extract text content from an agent response payload."""
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


def filter_agents(
    agents: list[dict[str, Any]],
    enabled_only: bool = False,
) -> list[dict[str, Any]]:
    """Apply common filters to an agent list payload."""
    if not enabled_only:
        return list(agents)
    return [agent for agent in agents if agent.get("enabled", False)]


@dataclass(frozen=True)
class AgentListResult:
    """Validated agent list response."""

    response_data: Dict[str, Any]
    agents: list[dict[str, Any]]


@dataclass(frozen=True)
class AgentChatRequest:
    """Input model for agent-to-agent chat."""

    from_agent: str
    to_agent: str
    text: str
    session_id: Optional[str] = None


@dataclass(frozen=True)
class AgentChatPreparedRequest:
    """Prepared transport request and derived metadata."""

    from_agent: str
    to_agent: str
    raw_text: str
    final_text: str
    session_id: str
    request_payload: Dict[str, Any]
    headers: Dict[str, str]
    identity_prefix_added: bool


@dataclass(frozen=True)
class AgentChatFinalResponse:
    """Completed final-mode response."""

    session_id: str
    response_data: Dict[str, Any]
    text: str


@dataclass(frozen=True)
class AgentChatTaskSubmission:
    """Background task submission response."""

    task_id: str
    session_id: str
    response_data: Dict[str, Any]


@dataclass(frozen=True)
class AgentChatTaskStatus:
    """Background task status response."""

    task_id: str
    status: str
    response_data: Dict[str, Any]
    task_status: Optional[str]
    text: str


def _validate_agent_list_payload(
    payload: Dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate and normalize the ``/agents`` response payload."""
    agents = payload.get("agents", [])
    if not isinstance(agents, list):
        raise ValueError(
            "Invalid agent list response: 'agents' must be a list.",
        )
    return [agent for agent in agents if isinstance(agent, dict)]


def fetch_agents(
    base_url: str,
    timeout: float = 30.0,
) -> AgentListResult:
    """Fetch the current list of configured agents."""
    with httpx.Client(base_url=normalize_api_base_url(base_url)) as client:
        response = client.get(
            "/agents",
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
        response.raise_for_status()
        response_data = response.json()

    return AgentListResult(
        response_data=response_data,
        agents=_validate_agent_list_payload(response_data),
    )


async def fetch_agents_async(
    base_url: str,
    timeout: float = 30.0,
) -> AgentListResult:
    """Fetch the current list of configured agents asynchronously."""
    async with httpx.AsyncClient(
        base_url=normalize_api_base_url(base_url),
    ) as client:
        response = await client.get(
            "/agents",
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
        response.raise_for_status()
        response_data = response.json()

    return AgentListResult(
        response_data=response_data,
        agents=_validate_agent_list_payload(response_data),
    )


def prepare_agent_chat_request(
    request: AgentChatRequest,
) -> AgentChatPreparedRequest:
    """Build request payload, headers, and metadata for agent chat."""
    final_session_id = _resolve_session_id(
        request.from_agent,
        request.to_agent,
        request.session_id,
    )
    final_text = ensure_agent_identity_prefix(request.text, request.from_agent)
    request_payload = {
        "session_id": final_session_id,
        "input": [
            {
                "role": "user",
                "content": [{"type": "text", "text": final_text}],
            },
        ],
    }
    return AgentChatPreparedRequest(
        from_agent=request.from_agent,
        to_agent=request.to_agent,
        raw_text=request.text,
        final_text=final_text,
        session_id=final_session_id,
        request_payload=request_payload,
        headers={"X-Agent-Id": request.to_agent},
        identity_prefix_added=final_text != request.text,
    )


def stream_agent_chat_lines(
    base_url: str,
    prepared_request: AgentChatPreparedRequest,
    timeout: int,
) -> Iterator[str]:
    """Yield raw SSE lines for stream mode."""
    with httpx.Client(base_url=normalize_api_base_url(base_url)) as client:
        with client.stream(
            "POST",
            "/agent/process",
            json=prepared_request.request_payload,
            headers=prepared_request.headers,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    yield line


def collect_agent_chat_final_response(
    base_url: str,
    prepared_request: AgentChatPreparedRequest,
    timeout: int,
) -> AgentChatFinalResponse:
    """Collect all SSE events and return the final parsed response."""
    response_data: Optional[Dict[str, Any]] = None

    with httpx.Client(base_url=normalize_api_base_url(base_url)) as client:
        with client.stream(
            "POST",
            "/agent/process",
            json=prepared_request.request_payload,
            headers=prepared_request.headers,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    parsed = parse_sse_line(line)
                    if parsed:
                        response_data = parsed

    if not response_data:
        raise ValueError("No response received")

    if "session_id" not in response_data:
        response_data["session_id"] = prepared_request.session_id

    return AgentChatFinalResponse(
        session_id=prepared_request.session_id,
        response_data=response_data,
        text=extract_text_content(response_data),
    )


def submit_agent_chat_background_task(
    base_url: str,
    prepared_request: AgentChatPreparedRequest,
    timeout: int,
) -> AgentChatTaskSubmission:
    """Submit an agent chat request as a background task."""
    with httpx.Client(base_url=normalize_api_base_url(base_url)) as client:
        response = client.post(
            "/agent/process/task",
            json=prepared_request.request_payload,
            headers=prepared_request.headers,
            timeout=timeout,
        )
        response.raise_for_status()
        response_data = response.json()

    task_id = response_data.get("task_id")
    if not task_id:
        raise ValueError("No task_id returned from server")

    return AgentChatTaskSubmission(
        task_id=task_id,
        session_id=prepared_request.session_id,
        response_data=response_data,
    )


def get_agent_chat_task_status(
    base_url: str,
    task_id: str,
    to_agent: Optional[str] = None,
    timeout: int = 10,
) -> AgentChatTaskStatus:
    """Fetch the current status of a background agent chat task."""
    headers = {"X-Agent-Id": to_agent} if to_agent else {}

    with httpx.Client(base_url=normalize_api_base_url(base_url)) as client:
        response = client.get(
            f"/agent/process/task/{task_id}",
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        response_data = response.json()

    status = response_data.get("status", "unknown")
    task_result = response_data.get("result", {})
    if isinstance(task_result, dict):
        task_status = task_result.get("status")
        text = extract_text_content(task_result)
    else:
        task_status = None
        text = ""

    return AgentChatTaskStatus(
        task_id=task_id,
        status=status,
        response_data=response_data,
        task_status=task_status,
        text=text,
    )
