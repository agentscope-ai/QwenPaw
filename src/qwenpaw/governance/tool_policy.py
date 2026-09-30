# -*- coding: utf-8 -*-
"""Escalation-only plugin hints for the pre-tool-call governance gate."""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import math
from dataclasses import dataclass, replace
from typing import Any, Callable, Coroutine, Literal

from .policy import GovernanceAction, GovernanceDecision, ToolCallSpec


@dataclass(frozen=True)
class PolicyHint:
    """A plugin verdict with a nullable action and JSON-compatible metadata."""

    action: Literal["allow", "deny", "ask"] | None = None
    reason: str = ""
    metadata: dict | None = None


@dataclass(frozen=True)
class ToolPolicyHookRegistration:
    """Plugin-owned callback with a host-enforced timeout and failure mode."""

    plugin_id: str
    hook_name: str
    callback: Callable[[ToolCallSpec], Coroutine[Any, Any, PolicyHint | None]]
    priority: int = 100
    fail: str = "open"
    timeout_s: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.hook_name, str) or not self.hook_name.strip():
            raise ValueError("hook_name must be a non-empty string")
        if not (
            inspect.iscoroutinefunction(self.callback)
            or inspect.iscoroutinefunction(
                getattr(self.callback, "__call__", None),
            )
        ):
            raise TypeError("tool policy callbacks must be async functions")
        if not isinstance(self.priority, int) or isinstance(
            self.priority,
            bool,
        ):
            raise ValueError("priority must be an integer")
        if self.fail not in ("open", "closed"):
            raise ValueError("fail must be 'open' or 'closed'")
        if (
            not isinstance(self.timeout_s, (int, float))
            or isinstance(self.timeout_s, bool)
            or not math.isfinite(self.timeout_s)
            or self.timeout_s <= 0
        ):
            raise ValueError("timeout_s must be finite and greater than zero")


def _consume_result(task: asyncio.Task) -> None:
    """Retrieve late failures when a timed-out callback delays cancellation."""
    if not task.cancelled():
        task.exception()


async def _invoke_hook(
    hook: ToolPolicyHookRegistration,
    tc_spec: ToolCallSpec,
) -> dict:
    record: dict[str, Any] = {
        "plugin_id": hook.plugin_id,
        "hook_name": hook.hook_name,
    }
    task = None
    try:
        # A hook must not rewrite already-checked arguments, or another hook's
        # view of them. The callback owns only this per-invocation snapshot.
        task = asyncio.create_task(hook.callback(copy.deepcopy(tc_spec)))
        done, _ = await asyncio.wait({task}, timeout=hook.timeout_s)
        if not done:
            raise TimeoutError("tool policy hook timed out")
        if task.cancelled():
            raise RuntimeError("tool policy hook cancelled itself")
        hint = task.result()
        if hint is None:
            hint = PolicyHint()
        if not isinstance(hint, PolicyHint):
            raise TypeError("callback must return PolicyHint or None")
        if hint.action not in (None, "allow", "ask", "deny"):
            raise ValueError("invalid policy hint action")
        if not isinstance(hint.reason, str):
            raise TypeError("policy hint reason must be a string")
        if hint.metadata is not None and not isinstance(hint.metadata, dict):
            raise TypeError("policy hint metadata must be a dict or None")
        # Validate and detach metadata before it enters the shared audit log.
        metadata = json.loads(json.dumps(hint.metadata, allow_nan=False))
        record.update(
            status="ok",
            action=hint.action,
            reason=hint.reason,
            metadata=metadata,
        )
    except Exception as exc:
        # Do not persist exception text: clients may include credentials or
        # request bodies in their errors. Keep the failure type observable.
        record.update(
            status="timeout" if isinstance(exc, TimeoutError) else "error",
            action="deny" if hook.fail == "closed" else None,
            reason=f"Tool policy hook failed ({type(exc).__name__})",
            metadata=None,
        )
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            task.add_done_callback(_consume_result)
    return record


async def apply_tool_policy_hooks(
    tc_spec: ToolCallSpec,
    decision: GovernanceDecision,
    hooks: list[ToolPolicyHookRegistration],
) -> GovernanceDecision:
    """Run hints in priority order without relaxing the static decision.

    The first DENY ends the chain. Otherwise the first ASK wins. Static
    DENY/unknown decisions bypass callbacks; OFF bypasses this gate entirely.
    """
    if not hooks or decision.action not in (
        GovernanceAction.ALLOW,
        GovernanceAction.ASK,
        GovernanceAction.SANDBOX_FALLBACK,
    ):
        return decision

    records = []
    selected = None
    for hook in sorted(hooks, key=lambda item: item.priority):
        record = await _invoke_hook(hook, tc_spec)
        records.append(record)
        if record["action"] == "deny":
            selected = record
            break
        if record["action"] == "ask" and selected is None:
            selected = record

    result = replace(
        decision,
        extra={
            **decision.extra,
            "tool_policy": {
                "static_action": decision.action.value,
                "static_source": decision.source,
                "static_reason": decision.reason,
                "hooks": records,
            },
        },
    )
    if selected is not None:
        action = GovernanceAction(selected["action"])
        if decision.action is not GovernanceAction.ASK or (
            action is GovernanceAction.DENY
        ):
            result.action = action
            result.source = (
                f"plugin:{selected['plugin_id']}/{selected['hook_name']}"
            )
            result.reason = selected["reason"] or "Plugin policy approval"
    return result
