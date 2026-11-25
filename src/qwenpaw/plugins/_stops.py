# -*- coding: utf-8 -*-
"""Translate finite SDK advice into the existing host stop-handler chain."""

import asyncio
from dataclasses import fields
import math

from ._identity import from_runtime
from ._messages import from_host
from .custody import stop_task
from .errors import SDKError, StaleContextError
from .stops import StopContext, StopResult


def register(plugin, spec):
    from ..loop.gates import StopAction, StopHandlerResult

    if not spec.name or not callable(spec.is_active):
        raise SDKError(
            "Stop handlers require a name and an active-mode predicate",
        )
    if not math.isfinite(spec.timeout) or spec.timeout <= 0:
        raise SDKError("Stop handler timeout must be finite and positive")

    async def handler(runtime):
        if getattr(handler, "_sdk_closed", False):
            raise StaleContextError("Stop handler has been released")
        agent = runtime["agent"]
        identity = from_runtime(agent)
        # The agent calls its stop chain before incrementing cur_iter. Expose
        # the completed reasoning turn as a one-based count to SDK authors.
        iteration = runtime["iteration"] + 1
        # Match the agent's actual hard iteration budget. A plugin cannot
        # reset it or continue after it is exhausted.
        config = getattr(agent, "react_config", None)
        limit = getattr(config, "max_iters", None)

        async def invoke():
            async with plugin._invocation(
                workspace_id=identity.workspace_id,
                session_id=identity.session_id,
                identity=identity,
                deadline=asyncio.get_running_loop().time() + spec.timeout,
            ) as base:
                base.check_cancelled()
                active = spec.is_active(identity)
                if not isinstance(active, bool):
                    if asyncio.iscoroutine(active):
                        active.close()
                    raise SDKError(
                        "Stop is_active must return bool synchronously",
                    )
                if not active:
                    return StopResult()
                if limit is not None and iteration >= limit:
                    return StopResult(
                        "stop",
                        reason="Host iteration limit reached",
                    )
                public = StopContext(
                    **{
                        item.name: getattr(base, item.name)
                        for item in fields(base)
                    },
                    iteration=iteration,
                    has_tool_calls=runtime["has_tool_calls"],
                    final_message=(
                        from_host(runtime["final_msg"])
                        if runtime["final_msg"] is not None
                        else None
                    ),
                )
                result = await plugin._call(spec.handler, public)
                base.check_cancelled()
                if not isinstance(result, StopResult) or result.action not in {
                    "bypass",
                    "continue",
                    "stop",
                }:
                    raise SDKError(
                        "Stop handler must return a valid StopResult",
                    )
                if result.action == "continue" and not result.message.strip():
                    raise SDKError(
                        "Continuing requires a nonempty instruction",
                    )
                return result

        task = plugin.resources.task(invoke(), f"stop:{spec.name}")
        try:
            _, pending = await asyncio.wait({task}, timeout=spec.timeout)
            if pending:
                raise SDKError("Stop handler exceeded its deadline")
            result = task.result()
        finally:
            if not task.done():
                await stop_task(task, f"stop:{spec.name}")
        return StopHandlerResult(
            {
                "bypass": StopAction.BYPASS,
                "continue": StopAction.INTERRUPT_AND_CONTINUE,
                "stop": StopAction.TERMINATE,
            }[result.action],
            continuation_message=result.message,
            reason=result.reason,
        )

    handle = plugin._register_contribution(
        plugin._api.register_agent_stop_handler,
        handler,
        priority=spec.priority,
        name=spec.name,
    )
    return plugin._with_admission(handle, handler)
