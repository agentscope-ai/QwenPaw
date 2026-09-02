# -*- coding: utf-8 -*-
"""The advisor model, resolved through QwenPaw's model factory.

By default Advisor Mode reuses the agent's existing model settings: the
*main* model (``active_model``) is the advisor and the cheaper
``subagent_model`` — when configured — runs the agent itself (the worker).
Both can be overridden per agent
in ``advisor_mode.advisor_model`` / ``advisor_mode.worker_model`` (the
Advisor tab of Agent Loop Settings).
Going through :func:`create_model_and_formatter_async` means the advisor
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


def resolve_advisor_slot(agent_config: Any) -> tuple[Any, str]:
    """The model slot that answers as the advisor, and where it comes from.

    Precedence: the ``advisor_mode.advisor_model`` override
    (``"override"``), the agent's own ``active_model`` (``"main_model"``),
    then the global active model from :class:`ProviderManager`
    (``"global"``) — the same fallback the model factory applies when
    building the agent's main model.
    """
    override = _override(agent_config, "advisor_model")
    if override is not None:
        return override, "override"
    slot = getattr(agent_config, "active_model", None)
    if slot_to_dict(slot) is not None:
        return slot, "main_model"
    try:
        from ...providers import ProviderManager

        return ProviderManager.get_instance().get_active_model(), "global"
    except Exception:
        logger.debug("AdvisorClient: no global active model", exc_info=True)
        return None, "global"


def resolve_worker_slot(agent_config: Any) -> tuple[Any, str]:
    """The model slot the agent itself runs on, and where it comes from.

    Precedence: the ``advisor_mode.worker_model`` override
    (``"override"``), then ``subagent_model`` (``"subagent_model"``).
    ``(None, "main_model")`` means the agent keeps its main model, i.e. it
    shares the advisor's model and Advisor Mode saves no tokens.
    """
    override = _override(agent_config, "worker_model")
    if override is not None:
        return override, "override"
    slot = getattr(agent_config, "subagent_model", None)
    if slot_to_dict(slot) is not None:
        return slot, "subagent_model"
    return None, "main_model"


def _with_thinking(agent_config: Any, thinking: str) -> Any:
    """``agent_config`` as seen with the advisor's thinking level.

    The model factory reads ``thinking_level`` off the config it is given,
    so a detached copy carries the override without touching the agent.
    """
    if not thinking or thinking == "inherit" or agent_config is None:
        return agent_config
    copy = getattr(agent_config, "model_copy", None)
    if callable(copy):
        try:
            return copy(update={"thinking_level": thinking})
        except Exception:
            logger.debug(
                "AdvisorClient: could not copy config",
                exc_info=True,
            )
    return agent_config


def effective_advisor_slot(agent_config: Any) -> Any:
    """The model slot that answers as the advisor."""
    return resolve_advisor_slot(agent_config)[0]


def effective_worker_slot(agent_config: Any) -> Any:
    """The model slot the agent runs on, or ``None`` for the main model."""
    return resolve_worker_slot(agent_config)[0]


class AdvisorClient:
    """Lazily build the advisor model and answer chat-style requests."""

    def __init__(
        self,
        *,
        agent_id: str,
        agent_config: Any = None,
        model_slot: Any = None,
        thinking: str = "inherit",
    ) -> None:
        self._agent_id = agent_id
        self._agent_config = agent_config
        self._model_slot = model_slot
        # ``advisor_mode.advisor_thinking``: the advisor's own thinking
        # level. A long think before a short plan is most of the wait the
        # user sees, so it is separate from the agent's level.
        self._thinking = thinking or "inherit"
        self._model: Any = None

    @property
    def label(self) -> str:
        """Which model answers as the advisor."""
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
                agent_config=_with_thinking(
                    self._agent_config,
                    self._thinking,
                ),
            )
            self._model = model
            logger.info(
                "AdvisorClient: using %s for agent %s",
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
    "AdvisorClient",
    "effective_worker_slot",
    "effective_advisor_slot",
    "resolve_worker_slot",
    "resolve_advisor_slot",
    "slot_label",
    "slot_to_dict",
]
