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
    """Select a route using deterministic request-shape heuristics first."""

    def __init__(self, cfg: AgentsLLMRoutingConfig):
        self.cfg = cfg

    def decide(
        self,
        *,
        text: str = "",
        channel: str = "",
        tools_available: bool = True,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        structured_output_requested: bool = False,
        has_non_text_user_content: bool = False,
        has_recent_tool_context: bool = False,
    ) -> RoutingDecision:
        del text, channel, tools_available

        if structured_output_requested:
            return RoutingDecision(
                route="cloud",
                reasons=["structured_output"],
            )

        if has_non_text_user_content:
            return RoutingDecision(
                route="cloud",
                reasons=["user_content:non_text"],
            )

        if tool_choice == "required":
            return RoutingDecision(
                route="cloud",
                reasons=["tool_choice:required"],
            )

        if has_recent_tool_context:
            return RoutingDecision(
                route="cloud",
                reasons=["recent_tool_context"],
            )

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
        text = _collect_user_text(messages)
        decision = self.policy.decide(
            text=text,
            tools_available=tools is not None,
            tool_choice=tool_choice,
            structured_output_requested=structured_model is not None,
            has_non_text_user_content=_has_non_text_user_content(messages),
            has_recent_tool_context=_has_recent_tool_context(messages),
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


def _collect_user_text(messages: list[dict]) -> str:
    parts: list[str] = []
    for message in messages:
        if message.get("role") != "user":
            continue
        parts.extend(_extract_text_segments(message.get("content")))
    return " ".join(part for part in parts if part).strip()


def _extract_text_segments(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]

    if not isinstance(content, list):
        return []

    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return parts


def _has_non_text_user_content(messages: list[dict]) -> bool:
    for message in messages:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if content in (None, ""):
            continue
        if isinstance(content, str):
            continue
        if isinstance(content, list):
            if any(_is_non_text_block(block) for block in content):
                return True
            continue
        return True
    return False


def _has_recent_tool_context(messages: list[dict]) -> bool:
    for message in reversed(messages):
        role = message.get("role")
        if role == "user":
            return False
        if role == "tool":
            return True
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            return True
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in {"tool_use", "tool_result"}:
                return True
    return False


def _is_non_text_block(block: Any) -> bool:
    if not isinstance(block, dict):
        return True
    return block.get("type") != "text"
