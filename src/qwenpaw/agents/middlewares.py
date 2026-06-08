# -*- coding: utf-8 -*-
"""Native AgentScope 2.0 middleware implementations for QwenPaw.

Each middleware is passed via the ``Agent(middlewares=[...])`` constructor
parameter.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, AsyncGenerator, Callable

from agentscope.middleware import MiddlewareBase

if TYPE_CHECKING:
    from agentscope.agent import Agent

logger = logging.getLogger(__name__)


class BootstrapMiddleware(MiddlewareBase):
    """Run the bootstrap hook on the first user interaction.

    Checks for ``BOOTSTRAP.md`` in the workspace and prepends guidance
    to the first user message before reasoning begins.
    """

    def __init__(self, bootstrap_hook: Any) -> None:
        self._hook = bootstrap_hook

    async def on_reasoning(
        self,
        agent: Agent,
        input_kwargs: dict,
        next_handler: Callable[..., AsyncGenerator],
    ) -> AsyncGenerator:
        try:
            await self._hook(agent, input_kwargs)
        except Exception:
            logger.exception("Bootstrap middleware pre_reasoning raised")
        async for event in next_handler():
            yield event


class RequestSetupMiddleware(MiddlewareBase):
    """Per-reply pre-processing that both ``reply()`` and ``reply_stream()``
    need.

    Pre-migration this lived inside ``QwenPawAgent.reply()`` — the 1.x
    callable entry — but 2.0 splits user entry into ``reply()`` (drain to
    final Msg) and ``reply_stream()`` (async event generator).  Putting
    the setup on the agent's ``reply()`` override meant the streaming
    path silently lost every step.  A middleware fires for **both**
    paths automatically (agentscope's middleware chain wraps the inner
    ``_reply()`` generator regardless of how it's consumed), so this is
    the single source of truth for these eight steps:

    1. ``set_current_workspace_dir`` — workspace root for file tools
    2. ``set_current_session_id`` — required by ``delegate_external_agent``
       / ACP tools; missing => ``ValueError("requires session_id")``
    3. ``set_current_recent_max_bytes`` — tool-result truncation cap
    4. ``set_current_shell_command_timeout`` — exec_shell timeout
    5. ``set_current_shell_command_executable`` — Windows shell choice
    6. ``process_file_and_media_blocks_in_message`` — download uploads
       to ``media_dir``, rewrite blocks to ``file://`` URLs, inject
       sibling TextBlock with the local path so the model can ``send_file``
       it back
    7. ``apply_skill_config_env_overrides`` — push skill-declared env
       vars (e.g. MCP credentials) into ``os.environ`` for the LLM call
    8. (slash-command dispatch stays in ``stream_query`` — it needs to
       short-circuit the SSE event stream, not the middleware chain)
    """

    def __init__(
        self,
        workspace_dir: Any,
        agent_id: str,
        agent_config: Any,
        request_context: dict,
    ) -> None:
        self._workspace_dir = workspace_dir
        self._agent_id = agent_id
        self._agent_config = agent_config
        self._request_context = request_context or {}

    async def on_reply(
        self,
        agent: "Agent",  # pylint: disable=unused-argument
        input_kwargs: dict,
        next_handler: Callable[..., AsyncGenerator],
    ) -> AsyncGenerator:
        # --- Step 1-4: critical per-request ContextVars ---
        # These must succeed; a missing session_id causes hard failures
        # in downstream tools (e.g. delegate_external_agent).
        from ..config.context import (
            set_current_workspace_dir,
            set_current_session_id,
            set_current_recent_max_bytes,
            set_current_shell_command_timeout,
            set_current_shell_command_executable,
        )
        from ..app.agent_context import set_current_agent_id

        if self._workspace_dir is not None:
            set_current_workspace_dir(self._workspace_dir)
        set_current_agent_id(self._agent_id or "default")
        set_current_session_id(
            self._request_context.get("session_id") or None,
        )

        # --- Step 5: non-critical config-derived vars ---
        # Wrapped in try so a stale/broken config doesn't break the whole
        # turn — tools fall back to module defaults rather than failing.
        try:
            running = self._agent_config.running
            set_current_recent_max_bytes(
                running.light_context_config.tool_result_pruning_config.pruning_recent_msg_max_bytes,  # noqa  # pylint: disable=line-too-long
            )
            set_current_shell_command_timeout(running.shell_command_timeout)
            set_current_shell_command_executable(
                running.shell_command_executable or None,
            )
        except Exception:
            logger.warning(
                "RequestSetupMiddleware: config-derived ContextVar setup "
                "failed; tools may see defaults",
                exc_info=True,
            )

        # --- Step 6: process file / media blocks on user input ---
        # Inputs land in ``input_kwargs["inputs"]`` per 2.0 middleware
        # contract.  Tolerate any shape (single Msg, list[Msg], None).
        inputs = input_kwargs.get("inputs")
        if inputs is not None:
            try:
                from .utils import process_file_and_media_blocks_in_message

                await process_file_and_media_blocks_in_message(inputs)
            except Exception:
                logger.warning(
                    "RequestSetupMiddleware: process_file_and_media_blocks "
                    "failed; user uploads may not be visible to tools",
                    exc_info=True,
                )

        # --- Step 7: skill env-override scope wraps the whole reply ---
        from pathlib import Path
        from .skill_system import apply_skill_config_env_overrides
        from ..constant import WORKING_DIR

        skill_ws = Path(self._workspace_dir or WORKING_DIR)
        channel = self._request_context.get("channel", "console")
        with apply_skill_config_env_overrides(skill_ws, channel):
            async for event in next_handler():
                yield event
