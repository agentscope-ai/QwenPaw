# -*- coding: utf-8 -*-
"""ChatModel router for local/cloud model selection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Literal, Type

from agentscope.formatter import FormatterBase
from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from pydantic import BaseModel

from ..config.config import AgentsLLMRoutingConfig

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
