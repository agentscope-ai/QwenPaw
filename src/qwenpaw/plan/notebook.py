# -*- coding: utf-8 -*-
"""QwenPaw PlanNotebook: tolerate LLM tool calls that pass JSON strings."""

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


class QwenPawPlanNotebook(PlanNotebook):
    """PlanNotebook subclass; coerce JSON-string subtask tool arguments.

    Models sometimes pass subtask as a JSON string; we decode before
    AgentScope validates.

    When the user (or agent) revises the plan while every subtask is still
    *todo*, we require another explicit confirmation before execution; see
    :attr:`_qwenpaw_needs_reconfirmation` and plan hints.
    """

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
        self._qwenpaw_needs_reconfirmation = False
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
        if plan is not None and plan.subtasks:
            if all(st.state == "todo" for st in plan.subtasks):
                self._qwenpaw_needs_reconfirmation = True
        return resp

    async def update_subtask_state(
        self,
        subtask_idx: int,
        state: str,
    ) -> ToolResponse:
        resp = await super().update_subtask_state(subtask_idx, state)
        if state == "in_progress":
            self._qwenpaw_needs_reconfirmation = False
        return resp
