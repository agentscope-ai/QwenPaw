# -*- coding: utf-8 -*-
"""PlanNotebook subclass: tolerate LLM tool calls that pass JSON strings."""

import json
import logging
from typing import Any, Literal

from agentscope.plan import PlanNotebook, SubTask
from agentscope.tool import ToolResponse

# Do NOT use ``from __future__ import annotations`` here: AgentScope builds
# tool JSON schema via ``inspect.signature`` + Pydantic ``create_model``;
# postponed annotations stringify ``Literal`` / ``SubTask`` and trigger
# PydanticUserError: class not fully defined (breaks all channels).

logger = logging.getLogger(__name__)

# Cap JSON string size before ``json.loads`` to limit CPU / memory from
# pathological tool arguments (defense in depth; SubTask text is small).
_MAX_SUBTASK_JSON_CHARS = 512_000


def _normalize_subtask_payload(subtask: Any) -> Any:
    """Decode JSON string payloads so ``SubTask.model_validate`` succeeds.

    Some chat models emit ``subtask`` as a serialized JSON object string
    instead of a structured argument; AgentScope only coerces ``dict``,
    not ``str``, which caused repeated validation failures and retry loops.
    """
    if subtask is None or not isinstance(subtask, str):
        return subtask
    raw = subtask.strip()
    if len(raw) > _MAX_SUBTASK_JSON_CHARS:
        logger.warning(
            "subtask JSON string exceeds %s chars; rejecting parse",
            _MAX_SUBTASK_JSON_CHARS,
        )
        return subtask
    if len(raw) < 2 or raw[0] not in "{[":
        return subtask
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug(
            "subtask string is not valid JSON; passing through unchanged",
        )
        return subtask
    return parsed


class JsonSubtaskPlanNotebook(PlanNotebook):
    """PlanNotebook subclass; coerce JSON-string subtask tool arguments.

    Models sometimes pass subtask as a JSON string; we decode before
    AgentScope validates.

    When the user (or agent) revises the plan while every subtask is still
    *todo*, we require another explicit confirmation before execution; see
    :attr:`_plan_needs_reconfirmation` and plan hints.
    """

    def state_dict(self) -> dict[str, Any]:
        """Persist notebook state plus one-shot post-finish guard marker."""
        payload = super().state_dict()
        payload["_plan_recently_finished"] = bool(
            getattr(self, "_plan_recently_finished", False),
        )
        return payload

    def load_state_dict(self, state_dict: dict[str, Any]) -> None:
        """Load notebook state and restore one-shot post-finish marker."""
        payload = dict(state_dict or {})
        marker = bool(payload.pop("_plan_recently_finished", False))
        super().load_state_dict(payload)
        self._plan_recently_finished = marker

    async def create_plan(
        self,
        name: str,
        description: str,
        expected_outcome: str,
        subtasks: list[SubTask],
    ) -> ToolResponse:
        if isinstance(subtasks, list):
            subtasks = [
                _normalize_subtask_payload(st) if isinstance(st, str) else st
                for st in subtasks
            ]
        resp = await super().create_plan(
            name,
            description,
            expected_outcome,
            subtasks,
        )
        self._plan_needs_reconfirmation = False
        self._plan_just_mutated = True
        self._plan_recently_finished = False
        # Fresh plan supersedes any pending panel-revised notice.
        self._plan_panel_revised_pending = False
        return resp

    async def revise_current_plan(
        self,
        subtask_idx: int,
        action: Literal["add", "revise", "delete"],
        subtask: SubTask | None = None,
    ) -> ToolResponse:
        normalized = _normalize_subtask_payload(subtask)
        resp = await super().revise_current_plan(
            subtask_idx,
            action,
            normalized,
        )
        plan = self.current_plan
        if plan is not None:
            # Auto-abandon when all subtasks removed (empty plan)
            if not plan.subtasks:
                logger.info(
                    "revise_current_plan: all subtasks removed; "
                    "auto-abandoning plan",
                )
                await self.finish_plan(
                    state="abandoned",
                    outcome="All subtasks removed by user",
                )
                # Reset gate so next turn doesn't force create_plan
                from .hints import set_plan_gate

                set_plan_gate(self, False)
            elif all(st.state == "todo" for st in plan.subtasks):
                # All remaining subtasks are still todo → need reconfirmation
                self._plan_needs_reconfirmation = True
                self._plan_just_mutated = True
        # Mid-execution edits (some subtask already in_progress / done) do
        # not satisfy the all-todo branch above, so neither flag fires for
        # them. Mark a one-shot panel-revised notice so the next reasoning
        # hint reminds the model to follow the updated plan structure
        # rather than the original user message. Consumed in
        # ``hints.ExtendedPlanToHint._pick_hint``.
        self._plan_panel_revised_pending = True
        return resp

    async def update_subtask_state(
        self,
        subtask_idx: int,
        state: str,
    ) -> ToolResponse:
        resp = await super().update_subtask_state(subtask_idx, state)
        if state == "in_progress":
            self._plan_needs_reconfirmation = False
        return resp

    async def finish_plan(
        self,
        state: Literal["done", "abandoned"],
        outcome: str,
    ) -> ToolResponse:
        """Finish plan and set one-shot guard for the next no-plan turn."""
        resp = await super().finish_plan(state=state, outcome=outcome)
        self._plan_needs_reconfirmation = False
        self._plan_just_mutated = False
        self._plan_recently_finished = True
        # No active plan → drop any pending panel-revised notice.
        self._plan_panel_revised_pending = False
        return resp
