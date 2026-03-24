# -*- coding: utf-8 -*-
"""ChatModel router for local/cloud model selection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Literal, Type

from agentscope.formatter import FormatterBase
from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from pydantic import BaseModel

from ..config.config import AgentsLLMRoutingConfig

logger = logging.getLogger(__name__)


Route = Literal["local", "cloud"]

LONG_PROMPT_CHAR_THRESHOLD = 6000
LONG_CONVERSATION_MESSAGE_THRESHOLD = 24

FRESHNESS_KEYWORDS = (
    "latest",
    "current price",
    "current prices",
    "today",
    "this week",
    "right now",
    "as of ",
    "stock price",
    "stock prices",
    "market price",
    "market prices",
    "breaking news",
    "news today",
    "weather",
    "live score",
    "schedule today",
)

STRICT_FORMAT_KEYWORDS = (
    "json object",
    "valid json",
    "return json",
    "return only json",
    "respond with json",
    "only json",
    "output json",
)


@dataclass
class RoutingDecision:
    route: Route
    reasons: list[str] = field(default_factory=list)


class RoutingPolicy:
    """Phase-1 routing policy: use request shape first, mode as fallback."""

    def __init__(self, cfg: AgentsLLMRoutingConfig):
        self.cfg = cfg

    # pylint: disable=too-many-return-statements
    def decide(
        self,
        *,
        text: str = "",
        channel: str = "",
        tools_available: bool = True,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        structured_output_requested: bool = False,
        message_count: int = 0,
        has_non_text_user_content: bool = False,
        has_recent_tool_context: bool = False,
        freshness_sensitive: bool = False,
        strict_format_requested: bool = False,
    ) -> RoutingDecision:
        del channel, tools_available

        if structured_output_requested:
            return RoutingDecision(
                route="cloud",
                reasons=["structured_output"],
            )

        if strict_format_requested:
            return RoutingDecision(
                route="cloud",
                reasons=["prompt:strict_format"],
            )

        if freshness_sensitive:
            return RoutingDecision(
                route="cloud",
                reasons=["prompt:freshness_sensitive"],
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

        if len(text) >= LONG_PROMPT_CHAR_THRESHOLD:
            return RoutingDecision(
                route="cloud",
                reasons=[f"prompt_chars>={LONG_PROMPT_CHAR_THRESHOLD}"],
            )

        if message_count >= LONG_CONVERSATION_MESSAGE_THRESHOLD:
            return RoutingDecision(
                route="cloud",
                reasons=[
                    f"message_count>={LONG_CONVERSATION_MESSAGE_THRESHOLD}",
                ],
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
    formatter_family: Type[FormatterBase]
    loader: Callable[[], tuple[ChatModelBase, FormatterBase]]
    _model: ChatModelBase | None = field(default=None, init=False, repr=False)
    _formatter: FormatterBase | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._formatter is not None:
            return
        model, formatter = self.loader()
        object.__setattr__(self, "_model", model)
        object.__setattr__(self, "_formatter", formatter)

    @property
    def model(self) -> ChatModelBase:
        self._ensure_loaded()
        assert self._model is not None
        return self._model

    @property
    def formatter(self) -> FormatterBase:
        self._ensure_loaded()
        assert self._formatter is not None
        return self._formatter


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
            stream=True,
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
        has_non_text_user_content = any(
            message.get("role") == "user"
            and message.get("content") not in (None, "")
            and not isinstance(message.get("content"), str)
            for message in messages
        )
        freshness_sensitive = _looks_freshness_sensitive(text)
        strict_format_requested = _looks_strict_format_request(text)
        decision = self.policy.decide(
            text=text,
            tools_available=tools is not None,
            tool_choice=tool_choice,
            structured_output_requested=structured_model is not None,
            message_count=len(messages),
            has_non_text_user_content=has_non_text_user_content,
            has_recent_tool_context=_has_recent_tool_context(messages),
            freshness_sensitive=freshness_sensitive,
            strict_format_requested=strict_format_requested,
        )
        endpoint, decision = self._load_endpoint_with_fallback(decision)

        logger.debug(
            "LLM routing decision: route=%s provider=%s model=%s reasons=%s",
            decision.route,
            endpoint.provider_id,
            endpoint.model_name,
            ",".join(decision.reasons),
        )

        try:
            return await endpoint.model(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                structured_model=structured_model,
                **kwargs,
            )
        except Exception:
            fallback = self._secondary_endpoint(decision.route)
            if fallback is None:
                raise

            logger.warning(
                "Primary routed model invocation failed; retrying with %s "
                "(provider=%s, model=%s).",
                "cloud" if decision.route == "local" else "local",
                fallback.provider_id,
                fallback.model_name,
                exc_info=True,
            )
            return await fallback.model(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                structured_model=structured_model,
                **kwargs,
            )

    def _primary_endpoint(self, route: Route) -> RoutingEndpoint:
        return self.local_endpoint if route == "local" else self.cloud_endpoint

    def _secondary_endpoint(self, route: Route) -> RoutingEndpoint | None:
        fallback_route: Route = "cloud" if route == "local" else "local"
        fallback = self._primary_endpoint(fallback_route)
        primary = self._primary_endpoint(route)
        if (
            fallback.provider_id == primary.provider_id
            and fallback.model_name == primary.model_name
        ):
            return None
        return fallback

    def _load_endpoint_with_fallback(
        self,
        decision: RoutingDecision,
    ) -> tuple[RoutingEndpoint, RoutingDecision]:
        endpoint = self._primary_endpoint(decision.route)
        try:
            _ = endpoint.model
            return endpoint, decision
        except Exception:
            fallback = self._secondary_endpoint(decision.route)
            if fallback is None:
                raise

            fallback_route: Route = (
                "cloud" if decision.route == "local" else "local"
            )
            logger.warning(
                "Primary routed model load failed; falling back to %s "
                "(provider=%s, model=%s).",
                fallback_route,
                fallback.provider_id,
                fallback.model_name,
                exc_info=True,
            )
            _ = fallback.model
            return fallback, RoutingDecision(
                route=fallback_route,
                reasons=[
                    *decision.reasons,
                    f"fallback:{decision.route}_load_error",
                ],
            )


def _has_recent_tool_context(messages: list[dict]) -> bool:
    """Detect whether the current turn is in the middle of tool execution."""
    non_system_messages = [
        message for message in messages if message.get("role") != "system"
    ]
    if not non_system_messages:
        return False

    last_message = non_system_messages[-1]
    if last_message.get("role") == "tool":
        return True
    if last_message.get("role") == "assistant" and last_message.get(
        "tool_calls",
    ):
        return True

    if len(non_system_messages) < 2:
        return False

    previous_message = non_system_messages[-2]
    return bool(
        previous_message.get("role") == "assistant"
        and previous_message.get("tool_calls")
        and last_message.get("role") == "tool",
    )


def _looks_freshness_sensitive(text: str) -> bool:
    normalized = text.lower()
    return any(keyword in normalized for keyword in FRESHNESS_KEYWORDS)


def _looks_strict_format_request(text: str) -> bool:
    normalized = text.lower()
    return any(keyword in normalized for keyword in STRICT_FORMAT_KEYWORDS)
