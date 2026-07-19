# -*- coding: utf-8 -*-
"""AgentScope 2.0 middleware for parent subagent-result inboxes."""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Callable

from agentscope.agent import Agent
from agentscope.event import HintBlockEvent
from agentscope.message import AssistantMsg, HintBlock
from agentscope.middleware import MiddlewareBase

from .manager import SubagentLifecycleEvent, SubagentTaskManager


class SubagentInboxMiddleware(MiddlewareBase):
    """Inject child lifecycle events before parent reasoning."""

    def __init__(
        self,
        manager: SubagentTaskManager,
        parent_session_id: str,
    ) -> None:
        self._manager = manager
        self._parent_session_id = parent_session_id

    async def on_reasoning(
        self,
        agent: Agent,
        input_kwargs: dict,
        next_handler: Callable[..., AsyncGenerator],
    ) -> AsyncGenerator[Any, None]:
        claim_id = (
            f"{self._parent_session_id}:"
            f"{agent.state.reply_id}:subagent-events"
        )
        events = await self._manager.claim_events(
            self._parent_session_id,
            claim_id,
        )
        if events:
            claim_ids = list(
                getattr(agent, "_qwenpaw_subagent_event_claim_ids", []),
            )
            claim_ids.append(claim_id)
            setattr(agent, "_qwenpaw_subagent_event_claim_ids", claim_ids)
            setattr(agent, "_qwenpaw_subagent_event_claim_id", claim_id)
            hints = [self._to_hint(event) for event in events]
            if agent.state.context:
                last = agent.state.context[-1]
                if last.role == "assistant" and last.name == agent.name:
                    last.content.extend(hints)
                else:
                    agent.state.context.append(
                        AssistantMsg(
                            id=agent.state.reply_id,
                            name=agent.name,
                            content=hints,
                        ),
                    )
            else:
                agent.state.context.append(
                    AssistantMsg(
                        id=agent.state.reply_id,
                        name=agent.name,
                        content=hints,
                    ),
                )

            for hint in hints:
                yield HintBlockEvent(
                    reply_id=agent.state.reply_id,
                    block_id=hint.id,
                    source=hint.source,
                    hint=hint.hint,
                )

        async for event in next_handler(**input_kwargs):
            yield event

    @staticmethod
    def _to_hint(event: SubagentLifecycleEvent) -> HintBlock:
        source = json.dumps(
            {
                "label": "subagent",
                "sublabel": f"{event.task_id} · {event.status.value}",
            },
            ensure_ascii=False,
        )
        elapsed = (
            f" after {event.elapsed_seconds:.1f}s"
            if event.elapsed_seconds is not None
            else ""
        )
        lines = [
            "<system-notification>",
            "Background subagent "
            f"{event.task_id} {event.status.value}{elapsed}.",
            f"Original task: {event.prompt}",
        ]
        if event.result:
            lines.extend(["", "Result:", event.result])
        if event.error:
            lines.extend(["", "Error:", event.error])
        if event.worktree_branch:
            lines.extend(["", f"Fork branch: {event.worktree_branch}"])
        if event.status.value == "stale":
            lines.extend(
                [
                    "",
                    "The child stopped sending heartbeats and did not exit ",
                    "within the cancellation grace period. Do not poll it. ",
                    "You may report the stalled task or explicitly request ",
                    "cancellation again.",
                ],
            )
        else:
            lines.extend(
                [
                    "",
                    "Use this result now. Do not call a polling or waiting ",
                    "tool for this completed task.",
                ],
            )
        lines.append("</system-notification>")
        return HintBlock(hint="\n".join(lines), source=source)


__all__ = ["SubagentInboxMiddleware"]
