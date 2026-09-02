# -*- coding: utf-8 -*-
"""The advisor ("teacher") model, resolved through QwenPaw's model factory.

By default Advisor Mode reuses the agent's existing model settings: the
*main* model (``active_model``) is the teacher and the cheaper
``subagent_model`` — when configured — runs the agent itself. Both can be
overridden per agent in ``advisor_mode.teacher_model`` /
``advisor_mode.student_model`` (the Advisor tab of Agent Loop Settings).
Going through :func:`create_model_and_formatter_async` means the teacher
inherits provider routing, retries, rate limiting and token accounting
exactly like every other model call in QwenPaw.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from agentscope.message import Msg, TextBlock

from ...utils.model_response import consume_model_response

logger = logging.getLogger(__name__)


def slot_to_dict(slot: Any) -> dict[str, str] | None:
    """Return ``{"provider_id", "model"}`` for a configured model slot."""
    if slot is None:
        return None
    provider_id = getattr(slot, "provider_id", None) or ""
    model = getattr(slot, "model", None) or ""
    if isinstance(slot, dict):
        provider_id = slot.get("provider_id") or ""
        model = slot.get("model") or ""
    if not provider_id or not model:
        return None
    return {"provider_id": str(provider_id), "model": str(model)}


def slot_label(slot: Any) -> str:
    """Human-readable ``provider:model`` label for logs and status."""
    data = slot_to_dict(slot)
    if data is None:
        return "active model"
    return f"{data['provider_id']}:{data['model']}"


def _override(agent_config: Any, field: str) -> Any:
    """The ``advisor_mode.<field>`` slot when it names a model."""
    am = getattr(agent_config, "advisor_mode", None)
    slot = getattr(am, field, None) if am is not None else None
    return slot if slot_to_dict(slot) is not None else None


def resolve_teacher_slot(agent_config: Any) -> tuple[Any, str]:
    """The model slot that answers as the teacher, and where it comes from.

    Precedence: the ``advisor_mode.teacher_model`` override
    (``"override"``), the agent's own ``active_model`` (``"main_model"``),
    then the global active model from :class:`ProviderManager`
    (``"global"``) — the same fallback the model factory applies when
    building the agent's main model.
    """
    override = _override(agent_config, "teacher_model")
    if override is not None:
        return override, "override"
    slot = getattr(agent_config, "active_model", None)
    if slot_to_dict(slot) is not None:
        return slot, "main_model"
    try:
        from ...providers import ProviderManager

        return ProviderManager.get_instance().get_active_model(), "global"
    except Exception:
        logger.debug("AdvisorTeacher: no global active model", exc_info=True)
        return None, "global"


def resolve_student_slot(agent_config: Any) -> tuple[Any, str]:
    """The model slot the agent itself runs on, and where it comes from.

    Precedence: the ``advisor_mode.student_model`` override
    (``"override"``), then ``subagent_model`` (``"subagent_model"``).
    ``(None, "main_model")`` means the agent keeps its main model, i.e. it
    shares the teacher's model and Advisor Mode saves no tokens.
    """
    override = _override(agent_config, "student_model")
    if override is not None:
        return override, "override"
    slot = getattr(agent_config, "subagent_model", None)
    if slot_to_dict(slot) is not None:
        return slot, "subagent_model"
    return None, "main_model"


def effective_teacher_slot(agent_config: Any) -> Any:
    """The model slot that answers as the teacher."""
    return resolve_teacher_slot(agent_config)[0]


def effective_student_slot(agent_config: Any) -> Any:
    """The model slot the agent runs on, or ``None`` for the main model."""
    return resolve_student_slot(agent_config)[0]


class AdvisorTeacher:
    """Lazily build the teacher model and answer chat-style requests."""

    def __init__(
        self,
        *,
        agent_id: str,
        agent_config: Any = None,
        model_slot: Any = None,
    ) -> None:
        self._agent_id = agent_id
        self._agent_config = agent_config
        self._model_slot = model_slot
        self._model: Any = None

    @property
    def label(self) -> str:
        """Which model answers as the teacher."""
        return slot_label(self._model_slot)

    async def _get_model(self) -> Any:
        if self._model is None:
            # Local import keeps ``qwenpaw.modes`` importable without
            # pulling the whole model factory at module load.
            from ...agents.model_factory import (
                create_model_and_formatter_async,
            )

            model, _formatter = await create_model_and_formatter_async(
                agent_id=self._agent_id,
                model_slot_override=self._model_slot,
                agent_config=self._agent_config,
            )
            self._model = model
            logger.info(
                "AdvisorTeacher: using %s for agent %s",
                self.label,
                self._agent_id,
            )
        return self._model

    async def ask(
        self,
        messages: list[dict[str, str]],
        *,
        on_text: Callable[[str], None] | None = None,
    ) -> str:
        """Send ``messages`` (``{"role", "content"}`` dicts) and return the
        reply text. ``on_text`` receives the cumulative reply text as it
        streams in, so the caller can show it before it is complete."""
        model = await self._get_model()
        msgs = [
            Msg(
                name=m["role"],
                role=m["role"],
                content=[TextBlock(type="text", text=m["content"])],
            )
            for m in messages
        ]
        return await consume_model_response(model, msgs, on_text=on_text)


__all__ = [
    "AdvisorTeacher",
    "effective_student_slot",
    "effective_teacher_slot",
    "resolve_student_slot",
    "resolve_teacher_slot",
    "slot_label",
    "slot_to_dict",
]
