# -*- coding: utf-8 -*-
"""Runtime-safe agent configuration loading."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config.config import load_agent_config_async
from ..exceptions import (
    AGENT_CONFIG_UNAVAILABLE,
    AppBaseException,
    ConfigurationException,
)

if TYPE_CHECKING:
    from ..config.config import AgentProfileConfig

_READ_ONLY_MODEL_ARGS = {"", "help", "-h", "--help", "list", "info"}


def _request_last_user_text(request: Any) -> str:
    """Extract the last user text without requiring agent configuration."""
    raw_input = (
        request.get("input", [])
        if isinstance(request, dict)
        else getattr(request, "input", [])
    )
    if not isinstance(raw_input, list) or not raw_input:
        return ""
    message = raw_input[-1]
    content = (
        message.get("content", [])
        if isinstance(message, dict)
        else getattr(message, "content", [])
    )
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict):
            text = item.get("text")
        else:
            text = getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts).strip()


def is_config_independent_command(request: Any) -> bool:
    """Return whether a request can be answered without agent config.

    Only the read-only ``/model`` forms qualify: they report the global
    model, so a temporarily unreadable agent configuration is not a reason
    to refuse them.
    """
    text = _request_last_user_text(request)
    if not text.startswith("/"):
        return False
    command_parts = text[1:].split(None, 1)
    if not command_parts or command_parts[0].lower() != "model":
        return False
    if len(command_parts) < 2:
        return True
    normalized_args = command_parts[1].strip().lower()
    return (
        normalized_args in _READ_ONLY_MODEL_ARGS
        or normalized_args.startswith("info ")
    )


async def load_runtime_agent_config(agent_id: str) -> "AgentProfileConfig":
    """Load one agent configuration without blocking the event loop.

    A read failure carries a stable error code so clients can tell an
    unavailable configuration from a missing model selection. A failure
    that already has a code (for example a stale configuration) keeps it.
    """
    try:
        return await load_agent_config_async(agent_id)
    except ConfigurationException as exc:
        if exc.error_code:
            raise
        raise ConfigurationException(
            "Agent model configuration is temporarily unavailable",
            config_key=exc.config_key or "agent",
            error_code=AGENT_CONFIG_UNAVAILABLE,
        ) from exc
    except (OSError, TypeError, ValueError, AppBaseException) as exc:
        raise ConfigurationException(
            "Agent model configuration is temporarily unavailable",
            config_key="agent",
            error_code=AGENT_CONFIG_UNAVAILABLE,
        ) from exc
