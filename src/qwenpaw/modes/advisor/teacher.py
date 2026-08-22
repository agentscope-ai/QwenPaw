# -*- coding: utf-8 -*-
"""The advisor ("teacher") model, resolved through QwenPaw's model factory.

Advisor Mode reuses the agent's existing model settings instead of adding
new ones: the *main* model (``active_model``) is the teacher and the
cheaper ``subagent_model`` — when configured — runs the agent itself.
Going through :func:`create_model_and_formatter_async` means the teacher
inherits provider routing, retries, rate limiting and token accounting
exactly like every other model call in QwenPaw.
"""
from __future__ import annotations

import logging
from typing import Any

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


def effective_teacher_slot(agent_config: Any) -> Any:
    """The model slot that answers as the teacher.

    The agent's own ``active_model`` when it is set; otherwise the global
    active model from :class:`ProviderManager` — the same fallback the
    model factory applies when building the agent's main model.
    """
    slot = getattr(agent_config, "active_model", None)
    if slot_to_dict(slot) is not None:
        return slot
    try:
        from ...providers import ProviderManager

        return ProviderManager.get_instance().get_active_model()
    except Exception:
        logger.debug("AdvisorTeacher: no global active model", exc_info=True)
        return None


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

    async def ask(self, messages: list[dict[str, str]]) -> str:
        """Send ``messages`` (``{"role", "content"}`` dicts) and return the
        reply text."""
        model = await self._get_model()
        msgs = [
            Msg(
                name=m["role"],
                role=m["role"],
                content=[TextBlock(type="text", text=m["content"])],
            )
            for m in messages
        ]
        return await consume_model_response(model, msgs)


__all__ = [
    "AdvisorTeacher",
    "effective_teacher_slot",
    "slot_label",
    "slot_to_dict",
]
