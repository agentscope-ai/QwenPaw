# -*- coding: utf-8 -*-
"""on_acting middleware delegating tool execution to ToolCoordinator."""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, Any, AsyncGenerator, Callable

from agentscope.middleware import MiddlewareBase

if TYPE_CHECKING:
    from agentscope.agent import Agent

    from ._coordinator import BackgroundResultProcessor, ToolCoordinator

logger = logging.getLogger(__name__)

_EXECUTION_CONTEXT_KEYS = (
    "session_id",
    "agent_id",
    "root_session_id",
    "root_agent_id",
    "user_id",
    "approval_user_id",
    "conversation_id",
    "run_id",
    "channel",
    "actor_context",
    "source",
    "actor_type",
    "automation_kind",
    "cron_job_id",
    "authorized_by_user_id",
    "automation_authorization",
)


def _execution_context_snapshot(request_context: dict[str, Any]) -> dict[str, Any]:
    """复制后台生命周期所需的稳定标识，排除连接等运行时对象。"""
    snapshot = {
        key: request_context[key]
        for key in _EXECUTION_CONTEXT_KEYS
        if key in request_context
    }
    return copy.deepcopy(snapshot)


class ToolCoordinatorMiddleware(MiddlewareBase):
    """Thin on_acting middleware delegating to ToolCoordinator.

    Uses agentscope 2.0's official extension point — no Toolkit subclass.
    Direct access to agent.request_context (no ContextVar indirection).
    ``_execute_tool_call`` side effects work automatically.
    """

    def __init__(
        self,
        coordinator: "ToolCoordinator",
        background_result_processor: "BackgroundResultProcessor | None" = None,
    ) -> None:
        self._coordinator = coordinator
        self._background_result_processor = background_result_processor

    async def on_acting(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        tool_call = input_kwargs["tool_call"]

        request_context = getattr(agent, "_request_context", None) or {}
        session_id = request_context.get("session_id", "")
        agent_id = request_context.get("agent_id", "")
        root_session_id = request_context.get("root_session_id", "")
        execution_context = _execution_context_snapshot(request_context)

        async for item in self._coordinator.execute(
            tool_call=tool_call,
            next_handler=next_handler,
            session_id=session_id,
            agent_id=agent_id,
            root_session_id=root_session_id,
            execution_context=execution_context,
            background_result_processor=self._background_result_processor,
        ):
            yield item
