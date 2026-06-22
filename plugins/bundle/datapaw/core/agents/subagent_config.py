# -*- coding: utf-8 -*-
"""Sub-agent factory and execution for DataPaw.

Extracted from ``base.py`` to keep ``DataPawAgent`` focused on the
core ReAct loop overrides.  Provides:

- ``build_spawn_subagent_fn(agent)`` — builds the ``spawn_subagent``
  closure that the parent agent registers as a tool.
- ``acting_spawn_subagent(agent, tool_call)`` — custom ``_acting``
  implementation that captures sub-agent trace metadata for SSE and
  session persistence.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from agentscope.message import Msg, ToolResultBlock

from .spawn_subagent import make_spawn_subagent_fn
from ..sse_metadata import SUBAGENT_ROUTING_BLOCK_TYPE

if TYPE_CHECKING:
    from .base import DataPawAgent

logger = logging.getLogger("qwenpaw.datapaw.subagent_config")

PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent

DATA_FETCHER_BUILTINS = frozenset({
    "execute_shell_command",
    "read_file",
    "write_file",
    "edit_file",
    "grep_search",
    "glob_search",
})

SKILL_DIRS = {
    "data_fetcher": [
        str(PLUGIN_DIR / "skills" / "fetch-data"),
    ],
}


def build_spawn_subagent_fn(agent: "DataPawAgent") -> Any:
    """Build the ``spawn_subagent`` closure with captured dependencies."""
    from qwenpaw.agents.model_factory import create_model_and_formatter

    from ..path_context import default_artifacts_root

    agent_id = agent._agent_config.id

    def _get_model_and_formatter():
        return create_model_and_formatter(agent_id=agent_id)

    def _get_builtin_tools() -> list:
        tools = []
        for name, registered in agent.toolkit.tools.items():
            if name in DATA_FETCHER_BUILTINS:
                fn = registered.original_func
                if fn is not None:
                    tools.append(fn)
        return tools

    def _get_mcp_clients() -> list:
        return agent._mcp_clients or []

    def _get_skill_dirs_for_role(role: str) -> list:
        return SKILL_DIRS.get(role, [])

    def _get_workspace_dir() -> Path | None:
        return getattr(agent, "_workspace_dir", None)

    def _get_artifacts_root() -> Path:
        return default_artifacts_root(
            agent_id,
            workspace_dir=_get_workspace_dir(),
        )

    def _get_session_id() -> str | None:
        return (getattr(agent, "_request_context", None) or {}).get(
            "session_id",
        )

    def _get_recent_max_bytes() -> int | None:
        running = getattr(agent._agent_config, "running", None)
        light_ctx = getattr(running, "light_context_config", None)
        pruning = getattr(light_ctx, "tool_result_pruning_config", None)
        return getattr(pruning, "pruning_recent_msg_max_bytes", None)

    def _get_shell_command_timeout() -> float | None:
        running = getattr(agent._agent_config, "running", None)
        return getattr(running, "shell_command_timeout", None)

    def _get_shell_command_executable() -> str | None:
        running = getattr(agent._agent_config, "running", None)
        return getattr(running, "shell_command_executable", None) or None

    return make_spawn_subagent_fn(
        runtime_state=agent.plan_notebook,
        get_model_and_formatter=_get_model_and_formatter,
        get_builtin_tools=_get_builtin_tools,
        get_mcp_clients=_get_mcp_clients,
        get_skill_dirs_for_role=_get_skill_dirs_for_role,
        get_workspace_dir=_get_workspace_dir,
        get_artifacts_root=_get_artifacts_root,
        get_session_id=_get_session_id,
        get_recent_max_bytes=_get_recent_max_bytes,
        get_shell_command_timeout=_get_shell_command_timeout,
        get_shell_command_executable=_get_shell_command_executable,
    )


async def acting_spawn_subagent(
    agent: "DataPawAgent",
    tool_call: dict,
) -> None:
    """Execute spawn_subagent and capture its trace metadata.

    Replicates the core of ``ReActAgent._acting`` but additionally
    reads ``ToolResponse.metadata`` from the final chunk and writes
    it into ``tool_res_msg.metadata["subagent_trace"]``, so the
    trace is persisted in session.json alongside the tool result.

    Each parallel ``spawn_subagent`` call runs its own instance of
    this function with its own ``tool_res_msg``, so there is no
    shared-state race.
    """
    tool_res_msg = Msg(
        "system",
        [
            ToolResultBlock(
                type="tool_result",
                id=tool_call["id"],
                name=tool_call["name"],
                output=[],
            ),
        ],
        "system",
    )
    try:
        tool_res = await agent.toolkit.call_tool_function(tool_call)

        last_metadata = None
        async for chunk in tool_res:
            event_meta: dict[str, Any] = {}
            if chunk.is_last:
                event_meta["subagent_event"] = "summary"
            elif chunk.metadata and chunk.metadata.get("type"):
                event_meta["subagent_event"] = chunk.metadata["type"]
                if chunk.metadata.get("tool_name"):
                    event_meta["subagent_tool_name"] = (
                        chunk.metadata["tool_name"]
                    )
            else:
                event_meta["subagent_event"] = "thinking"

            if chunk.is_last:
                tool_res_msg.content[0]["output"] = chunk.content  # type: ignore[index]
            else:
                output_blocks = list(chunk.content)
                routing = {
                    "type": SUBAGENT_ROUTING_BLOCK_TYPE,
                    "e": event_meta.get("subagent_event"),
                    "t": event_meta.get("subagent_tool_name"),
                }
                output_blocks.append(routing)
                tool_res_msg.content[0]["output"] = output_blocks  # type: ignore[index]

            tool_res_msg.metadata = event_meta
            await agent.print(tool_res_msg, chunk.is_last)
            if chunk.is_interrupted:
                raise asyncio.CancelledError()
            if chunk.is_last and chunk.metadata:
                last_metadata = chunk.metadata

        if last_metadata:
            msg_meta = dict(
                getattr(tool_res_msg, "metadata", None) or {},
            )
            msg_meta["subagent_trace"] = last_metadata
            tool_res_msg.metadata = msg_meta

        return None
    finally:
        await agent.memory.add(tool_res_msg)
