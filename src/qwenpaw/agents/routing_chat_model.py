# -*- coding: utf-8 -*-
"""ChatModel router for local/cloud model selection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Literal, Optional, Type

from agentscope.formatter import FormatterBase
from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from pydantic import BaseModel

from ..config.config import (
    AgentsLLMRoutingConfig,
    has_configured_model_slot,
    ModelSlotConfig,
    routing_has_explicit_override,
)
from ..providers import ProviderManager

logger = logging.getLogger(__name__)


Route = Literal["local", "cloud"]


@dataclass
class RoutingDecision:
    route: Route
    reasons: list[str] = field(default_factory=list)


class RoutingPolicy:
    """Select a route using the configured default mode."""

    def __init__(self, cfg: AgentsLLMRoutingConfig):
        self.cfg = cfg

    def decide(
        self,
        *,
        text: str = "",
        channel: str = "",
        tools_available: bool = True,
    ) -> RoutingDecision:
        del text, channel, tools_available

        if getattr(self.cfg, "mode", "local_first") == "cloud_first":
            return RoutingDecision(
                route="cloud",
                reasons=["mode:cloud_first"],
            )

        return RoutingDecision(
            route="local",
            reasons=["mode:local_first"],
        )


@dataclass(frozen=True)
class RoutingEndpoint:
    provider_id: str
    model_name: str
    model: ChatModelBase
    formatter: FormatterBase
    formatter_family: Type[FormatterBase]


class RoutingChatModel(ChatModelBase):
    """A ChatModelBase that routes between local and cloud slots."""

    def __init__(
        self,
        *,
        local_endpoint: RoutingEndpoint,
        cloud_endpoint: RoutingEndpoint,
        routing_cfg: AgentsLLMRoutingConfig,
    ) -> None:
        super().__init__(
            model_name="routing",
            stream=bool(getattr(local_endpoint.model, "stream", True)),
        )
        self.local_endpoint = local_endpoint
        self.cloud_endpoint = cloud_endpoint
        self.routing_cfg = routing_cfg
        self.policy = RoutingPolicy(routing_cfg)

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        text = " ".join(
            message["content"]
            for message in messages
            if message.get("role") == "user"
            and isinstance(message.get("content"), str)
        )
        decision = self.policy.decide(
            text=text,
            tools_available=tools is not None,
        )
        endpoint = (
            self.local_endpoint
            if decision.route == "local"
            else self.cloud_endpoint
        )

        logger.debug(
            "LLM routing decision: route=%s provider=%s model=%s reasons=%s",
            decision.route,
            endpoint.provider_id,
            endpoint.model_name,
            ",".join(decision.reasons),
        )

        return await endpoint.model(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            structured_model=structured_model,
            **kwargs,
        )


def _routing_enabled(routing_cfg) -> bool:
    return bool(routing_cfg and getattr(routing_cfg, "enabled", False))


def _select_scoped_model_config(
    *,
    agent_model_slot: ModelSlotConfig | None,
    agent_routing_cfg,
    global_model_slot: ModelSlotConfig | None,
    global_routing_cfg,
) -> tuple[ModelSlotConfig | None, object | None]:
    agent_has_selection = has_configured_model_slot(
        agent_model_slot,
    )
    agent_has_routing_override = routing_has_explicit_override(
        agent_routing_cfg,
    )
    if agent_has_selection or agent_has_routing_override:
        return (
            agent_model_slot or global_model_slot,
            agent_routing_cfg,
        )
    return global_model_slot, global_routing_cfg


def _resolve_routed_model_slot(
    routing_cfg,
) -> ModelSlotConfig | None:
    if not _routing_enabled(routing_cfg):
        return None

    decision = RoutingPolicy(routing_cfg).decide()
    if decision.route == "local":
        return routing_cfg.local
    return routing_cfg.cloud


def _load_global_routing_config():
    from ..config.utils import load_config

    try:
        return load_config().agents.llm_routing
    except Exception:
        return None


def resolve_effective_model_slot(
    agent_id: Optional[str] = None,
) -> ModelSlotConfig | None:
    """Resolve the concrete model slot for the current scope."""
    from ..config.config import load_agent_config

    if agent_id is None:
        from ..app.agent_context import get_current_agent_id

        try:
            agent_id = get_current_agent_id()
        except Exception:
            pass

    agent_model_slot = None
    agent_routing_cfg = None
    if agent_id:
        try:
            agent_config = load_agent_config(agent_id)
            agent_model_slot = agent_config.active_model
            agent_routing_cfg = getattr(agent_config, "llm_routing", None)
        except Exception:
            pass
    manager = ProviderManager.get_instance()
    global_model_slot = manager.get_active_model()
    global_routing_cfg = _load_global_routing_config()
    scoped_fallback_slot, scoped_routing_cfg = _select_scoped_model_config(
        agent_model_slot=agent_model_slot,
        agent_routing_cfg=agent_routing_cfg,
        global_model_slot=global_model_slot,
        global_routing_cfg=global_routing_cfg,
    )
    model_slot = _resolve_routed_model_slot(
        scoped_routing_cfg,
    )
    if has_configured_model_slot(model_slot):
        return model_slot
    if _routing_enabled(scoped_routing_cfg):
        return None
    return scoped_fallback_slot
