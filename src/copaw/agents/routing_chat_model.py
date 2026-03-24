# -*- coding: utf-8 -*-
"""ChatModel router for local/cloud model selection."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, AsyncGenerator, Callable, Literal, Type, cast

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

JUDGE_SYSTEM_PROMPT = """You are a routing judge for a chat assistant.
Choose exactly one route:
- local: normal requests that a local model can answer safely
- cloud: requests that likely need stronger capabilities

Use the provided context packet and heuristic signals. Heuristic signals are
inputs, not hard rules.

Respond with exactly two lines:
route=<local|cloud>
reason=<short_reason>
"""

JUDGE_ROUTE_PATTERN = re.compile(
    r"(?im)^route\s*[:=]\s*(local|cloud)\s*$",
)
JUDGE_REASON_PATTERN = re.compile(
    r"(?im)^reason\s*[:=]\s*(.+?)\s*$",
)


@dataclass
class RoutingDecision:
    route: Route
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RoutingRequestContext:
    latest_user_text: str = ""
    prompt_chars: int = 0
    message_count: int = 0
    tool_choice: Literal["auto", "none", "required"] | str | None = None
    structured_output_requested: bool = False
    has_non_text_user_content: bool = False
    has_recent_tool_context: bool = False
    freshness_sensitive: bool = False
    strict_format_requested: bool = False

    def to_judge_packet(
        self,
        *,
        default_route: Route,
        signals: list[str],
    ) -> str:
        latest_user_text = self.latest_user_text.strip() or "<empty>"
        signal_lines = (
            "\n".join(f"- {signal}" for signal in signals) or "- none"
        )
        return (
            f"default_route: {default_route}\n"
            f"latest_user_text:\n{latest_user_text}\n"
            f"prompt_chars: {self.prompt_chars}\n"
            f"message_count: {self.message_count}\n"
            f"tool_choice: {self.tool_choice or 'none'}\n"
            "structured_output_requested: "
            f"{self.structured_output_requested}\n"
            f"has_non_text_user_content: {self.has_non_text_user_content}\n"
            f"has_recent_tool_context: {self.has_recent_tool_context}\n"
            f"freshness_sensitive: {self.freshness_sensitive}\n"
            f"strict_format_requested: {self.strict_format_requested}\n"
            "signals:\n"
            f"{signal_lines}\n"
        )


class RoutingPolicy:
    """Collect heuristic routing signals and a default route."""

    def __init__(self, cfg: AgentsLLMRoutingConfig):
        self.cfg = cfg

    def default_route(self) -> Route:
        if getattr(self.cfg, "mode", "local_first") == "cloud_first":
            return "cloud"
        return "local"

    def collect_signals(
        self,
        context: RoutingRequestContext,
    ) -> list[str]:
        signals: list[str] = []

        if context.structured_output_requested:
            signals.append("structured_output")

        if context.strict_format_requested:
            signals.append("prompt:strict_format")

        if context.freshness_sensitive:
            signals.append("prompt:freshness_sensitive")

        if context.has_non_text_user_content:
            signals.append("user_content:non_text")

        if context.tool_choice == "required":
            signals.append("tool_choice:required")

        if context.has_recent_tool_context:
            signals.append("recent_tool_context")

        if context.prompt_chars >= LONG_PROMPT_CHAR_THRESHOLD:
            signals.append(f"prompt_chars>={LONG_PROMPT_CHAR_THRESHOLD}")

        if context.message_count >= LONG_CONVERSATION_MESSAGE_THRESHOLD:
            signals.append(
                f"message_count>={LONG_CONVERSATION_MESSAGE_THRESHOLD}",
            )

        signals.append(f"mode:{self.default_route()}_first")
        return signals


def _new_lock() -> Lock:
    return Lock()


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
    _load_lock: Lock = field(
        default_factory=_new_lock,
        init=False,
        repr=False,
        compare=False,
    )

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._formatter is not None:
            return

        with self._load_lock:
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
        context = _build_routing_request_context(
            messages,
            tool_choice=tool_choice,
            structured_model=structured_model,
        )
        signals = self.policy.collect_signals(context)
        decision = await self._judge_route(context, signals)
        endpoint = self._load_endpoint(decision.route)

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
        except Exception as exc:
            raise RuntimeError(
                "Selected routed model invocation failed "
                f"(route={decision.route}, provider={endpoint.provider_id}, "
                f"model={endpoint.model_name}).",
            ) from exc

    async def _judge_route(
        self,
        context: RoutingRequestContext,
        signals: list[str],
    ) -> RoutingDecision:
        judge_messages = [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": context.to_judge_packet(
                    default_route=self.policy.default_route(),
                    signals=signals,
                ),
            },
        ]

        try:
            result = await self.local_endpoint.model(
                messages=judge_messages,
                tools=None,
                tool_choice="none",
            )
        except Exception as exc:
            raise RuntimeError(
                "Routing judge invocation failed on local endpoint.",
            ) from exc

        output_text = await _extract_text_from_result(result)
        try:
            return _parse_judge_output(output_text, signals=signals)
        except ValueError as exc:
            raise RuntimeError(
                "Routing judge returned an invalid decision payload: "
                f"{output_text!r}",
            ) from exc

    def _load_endpoint(self, route: Route) -> RoutingEndpoint:
        endpoint = self._primary_endpoint(route)
        try:
            _ = endpoint.model
        except Exception as exc:
            raise RuntimeError(
                "Selected routed model failed to load "
                f"(route={route}, provider={endpoint.provider_id}, "
                f"model={endpoint.model_name}).",
            ) from exc
        return endpoint

    def _primary_endpoint(self, route: Route) -> RoutingEndpoint:
        return self.local_endpoint if route == "local" else self.cloud_endpoint


def _build_routing_request_context(
    messages: list[dict],
    *,
    tool_choice: Literal["auto", "none", "required"] | str | None,
    structured_model: Type[BaseModel] | None,
) -> RoutingRequestContext:
    latest_user_message = _get_latest_user_message(messages)
    latest_user_text = ""
    has_non_text_user_content = False

    if latest_user_message is not None:
        content = latest_user_message.get("content")
        if isinstance(content, str):
            latest_user_text = content
        elif content not in (None, ""):
            has_non_text_user_content = True

    return RoutingRequestContext(
        latest_user_text=latest_user_text,
        prompt_chars=len(latest_user_text),
        message_count=len(messages),
        tool_choice=tool_choice,
        structured_output_requested=structured_model is not None,
        has_non_text_user_content=has_non_text_user_content,
        has_recent_tool_context=_has_recent_tool_context(messages),
        freshness_sensitive=_looks_freshness_sensitive(latest_user_text),
        strict_format_requested=_looks_strict_format_request(latest_user_text),
    )


def _normalize_reason(reason: str) -> str:
    normalized = re.sub(r"[^a-z0-9_./:-]+", "_", reason.lower()).strip("_")
    return normalized or "judge"


def _parse_judge_output(
    output_text: str,
    *,
    signals: list[str],
) -> RoutingDecision:
    route_match = JUDGE_ROUTE_PATTERN.search(output_text)
    if route_match is None:
        raise ValueError(
            "Routing judge response did not include a valid route line.",
        )

    route = cast(Route, route_match.group(1).lower())
    reason_match = JUDGE_REASON_PATTERN.search(output_text)
    if reason_match is not None:
        reason = f"judge:{_normalize_reason(reason_match.group(1))}"
    else:
        reason = "judge"

    return RoutingDecision(
        route=route,
        reasons=[*signals, reason],
    )


def _extract_text_from_response(response: Any) -> str:
    if isinstance(response, str):
        return response

    content = None
    if hasattr(response, "get"):
        content = response.get("content")
    if content is None:
        content = getattr(response, "content", None)

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and isinstance(
                    block.get("text"),
                    str,
                ):
                    parts.append(block["text"])
                continue

            if getattr(block, "type", None) == "text" and isinstance(
                getattr(block, "text", None),
                str,
            ):
                parts.append(block.text)

        if parts:
            return "\n".join(parts)

    for attr in ("text", "output_text"):
        value = getattr(response, attr, None)
        if isinstance(value, str):
            return value

    raise ValueError("Unable to extract text from routing judge response.")


async def _extract_text_from_result(
    result: ChatResponse | AsyncGenerator[ChatResponse, None],
) -> str:
    if hasattr(result, "__aiter__"):
        parts: list[str] = []
        async for chunk in cast(AsyncGenerator[ChatResponse, None], result):
            chunk_text = _extract_text_from_response(chunk)
            if chunk_text:
                parts.append(chunk_text)
        return "".join(parts)
    return _extract_text_from_response(result)


def _get_latest_user_message(messages: list[dict]) -> dict | None:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message
    return None


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
