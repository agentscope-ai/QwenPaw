# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-branches,too-many-nested-blocks,too-many-statements
"""AgentScope 2.0 chat-model boundary for the file Creator Runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
import asyncio
import inspect
import json

from typing import Any, Protocol

from json_repair import repair_json

from agentscope.credential import DashScopeCredential
from agentscope.formatter import DashScopeChatFormatter
from agentscope.message import (
    AssistantMsg,
    Msg,
    SystemMsg,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolResultState,
    UserMsg,
)
from agentscope.model import DashScopeChatModel

from models import config as model_config
from models.concurrency import model_slot
from models.dashscope_multimodal import DashScopeNativeFormatter
from models.native_content import native_content_blocks
from utils.logger import setup_logger
from .tool_protocol import (
    NativeToolTextStream,
    NonNativeToolMarkupError,
)

logger = setup_logger("creator.model_client")


class AgentModelError(RuntimeError):
    pass


class AgentModelConfigurationError(AgentModelError):
    pass


class AgentStreamCallbackError(RuntimeError):
    """A consumer callback failed while the provider stream was healthy."""

    def __init__(self, cause: Exception) -> None:
        self.cause = cause
        super().__init__(
            f"Creator stream callback failed: {type(cause).__name__}: {cause}",
        )


class AgentStreamCallbackPassthrough(RuntimeError):
    """Marker for callback control flow that must retain its original type."""


@dataclass(frozen=True, slots=True)
class AgentToolCall:
    """Runtime-neutral projection of one validated AgentScope ToolCallBlock."""

    call_id: str
    name: str
    arguments: dict[str, Any]
    # Set when the streamed arguments could not be recovered into a JSON
    # object even after repair. The driver must surface this back to the
    # model as a failed tool result instead of failing the whole run.
    parse_error: str | None = None
    # Transport diagnostics are intentionally excluded from equality, repr,
    # and provider history. They let the Runtime distinguish strict provider
    # JSON from syntax-repaired JSON without leaking malformed payloads back
    # into the conversation or changing tool semantics.
    raw_arguments_bytes: int = field(default=0, compare=False, repr=False)
    arguments_repaired: bool = field(default=False, compare=False, repr=False)
    strict_json_error: str | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    # Retain the provider payload only until the Runtime persists the completed
    # turn. Raw fragments are deliberately not durable events anymore.
    raw_arguments: str = field(default="", compare=False, repr=False)
    provider_chunk_count: int = field(default=0, compare=False, repr=False)

    def history_dict(self) -> dict[str, Any]:
        """Serialize the call for the driver's provider-independent turn history."""

        return {
            "id": self.call_id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(
                    self.arguments,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        }


@dataclass(frozen=True, slots=True)
class AgentModelTurn:
    content: str | None = None
    thinking: str = ""
    tool_calls: tuple[AgentToolCall, ...] = ()
    provider_message_id: str | None = None
    finish_reason: str = "completed"
    usage: dict[str, Any] | None = field(default=None, compare=False)


_ARGS_PREVIEW_CHARS = 160


def _usage_payload(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    payload: dict[str, Any] = {}
    for name in (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_input_tokens",
        "time",
    ):
        value = getattr(usage, name, None)
        if isinstance(value, (int, float)):
            payload[name] = value
    metadata = getattr(usage, "metadata", None)
    if isinstance(metadata, Mapping) and metadata:
        payload["metadata"] = dict(metadata)
    return payload or None


def _parse_tool_arguments(
    raw: str,
) -> tuple[dict[str, Any], str | None, bool, str | None]:
    """Parse streamed tool-call arguments into a JSON object.

    Strict ``json.loads`` first; malformed payloads (truncated stream,
    unbalanced braces) go through ``json_repair`` exactly like AgentScope's
    own ``_json_loads_with_repair``. Returns ``(arguments, parse_error,
    repaired, strict_error)``—an unrecoverable payload yields a
    ``parse_error`` message so the tool call can fail individually while the
    run keeps going, and ``repaired``/``strict_error`` let the Runtime tell
    strict provider JSON from syntax-repaired JSON.
    """

    if not raw.strip():
        return {}, None, False, None
    decode_error: json.JSONDecodeError | None = None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        decode_error = error
    else:
        if isinstance(parsed, dict):
            return parsed, None, False, None
    benign = _parse_with_benign_trailing_closers(raw, decode_error)
    if benign is not None:
        return benign, None, False, None
    strict_error = (
        f"JSONDecodeError: {decode_error}"
        if decode_error is not None
        else "decoded into a non-object value"
    )
    try:
        repaired = repair_json(raw, stream_stable=True, return_objects=True)
    except Exception:
        repaired = None
    if isinstance(repaired, dict):
        return repaired, None, True, strict_error
    if len(raw) > 2 * _ARGS_PREVIEW_CHARS:
        preview = (
            raw[:_ARGS_PREVIEW_CHARS]
            + "...[TRUNCATED]..."
            + raw[-_ARGS_PREVIEW_CHARS:]
        )
    else:
        preview = raw
    parse_error = (
        "工具调用参数不是合法的 JSON 对象且无法自动修复（" + strict_error + "）。常见原因：花括号遗漏/错位或输出被截断。"
        "请重新生成本次工具调用；若参数体量巨大，可拆分为少量几次较小的调用。"
        f"参数原文预览：{preview!r}"
    )
    return {}, parse_error, False, strict_error


AgentTextDeltaCallback = Callable[[str], Awaitable[None]]
AgentToolDeltaCallback = Callable[[str, str, str], Awaitable[None]]


def _parse_with_benign_trailing_closers(
    raw: str,
    decode_error: json.JSONDecodeError | None,
) -> dict[str, Any] | None:
    """Accept a complete JSON object followed only by stray closers.

    Long streamed tool arguments sometimes end with one surplus ``}`` or
    ``]`` (a bracket-count slip, not truncation). When the prefix before
    the decode error parses to a complete object and the remainder holds
    zero information — nothing but closers and whitespace — executing the
    prefix is provably lossless, so the call must not pay a repair-and-
    retry turn. Any other trailing content means real payload was cut off
    and keeps the strict failure path.
    """

    if decode_error is None or "Extra data" not in decode_error.msg:
        return None
    boundary = decode_error.pos
    remainder = raw[boundary:].strip()
    if remainder and set(remainder) - {"}", "]", " ", "\t", "\r", "\n"}:
        return None
    try:
        parsed = json.loads(raw[:boundary])
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _guard_text_callback(
    callback: AgentTextDeltaCallback | None,
) -> AgentTextDeltaCallback | None:
    if callback is None:
        return None

    async def guarded(delta: str) -> None:
        try:
            await callback(delta)
        except (AgentStreamCallbackError, AgentStreamCallbackPassthrough):
            raise
        except Exception as exc:
            raise AgentStreamCallbackError(exc) from exc

    return guarded


def _guard_tool_callback(
    callback: AgentToolDeltaCallback | None,
) -> AgentToolDeltaCallback | None:
    if callback is None:
        return None

    async def guarded(call_id: str, name: str, arguments_delta: str) -> None:
        try:
            await callback(call_id, name, arguments_delta)
        except (AgentStreamCallbackError, AgentStreamCallbackPassthrough):
            raise
        except Exception as exc:
            raise AgentStreamCallbackError(exc) from exc

    return guarded


class AgentChatClient(Protocol):
    async def complete(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        on_text_delta: AgentTextDeltaCallback | None = None,
        on_thinking_delta: AgentTextDeltaCallback | None = None,
        on_tool_call_delta: AgentToolDeltaCallback | None = None,
    ) -> AgentModelTurn:
        ...


AgentModelCallback = Callable[
    [Sequence[Mapping[str, Any]], Sequence[Mapping[str, Any]]],
    Awaitable[AgentModelTurn],
]


class CallbackAgentChatClient:
    """Small test/embedding adapter without any provider dependency."""

    def __init__(self, callback: AgentModelCallback) -> None:
        self.callback = callback

    async def complete(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        on_text_delta: AgentTextDeltaCallback | None = None,
        on_thinking_delta: AgentTextDeltaCallback | None = None,
        on_tool_call_delta: AgentToolDeltaCallback | None = None,
    ) -> AgentModelTurn:
        turn = await self.callback(messages, tools)
        await _replay_complete_turn(
            turn,
            on_text_delta=_guard_text_callback(on_text_delta),
            on_thinking_delta=_guard_text_callback(on_thinking_delta),
            on_tool_call_delta=_guard_tool_callback(on_tool_call_delta),
        )
        return turn


def _text_content(value: Any, *, field_name: str) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        pieces: list[str] = []
        for item in value:
            if not isinstance(item, Mapping) or item.get("type") not in {
                None,
                "text",
            }:
                raise AgentModelError(
                    f"Creator Agent history {field_name} contains non-text content",
                )
            pieces.append(str(item.get("text") or ""))
        return "".join(pieces)
    raise AgentModelError(f"Creator Agent history {field_name} must be text")


def _message_content_blocks(value: Any, *, field_name: str) -> list[Any]:
    """Preserve native user media while keeping ordinary history compatible."""

    if value is None or isinstance(value, str):
        text = _text_content(value, field_name=field_name)
        return [TextBlock(text=text)] if text else []
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        parts: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, Mapping):
                raise AgentModelError(
                    f"Creator Agent history {field_name} contains an invalid content part",
                )
            parts.append(dict(item))
        try:
            return list(native_content_blocks(parts))
        except Exception as exc:
            raise AgentModelError(
                f"Creator Agent history {field_name} contains invalid native media: {exc}",
            ) from exc
    raise AgentModelError(
        f"Creator Agent history {field_name} must be text or content parts",
    )


def _history_tool_call(value: Any) -> AgentToolCall:
    if not isinstance(value, Mapping):
        raise AgentModelError(
            "Creator Agent history contains an invalid tool call",
        )
    function = value.get("function")
    if not isinstance(function, Mapping):
        raise AgentModelError(
            "Creator Agent history tool call has no function",
        )
    call_id = value.get("id")
    name = function.get("name")
    raw_arguments = function.get("arguments", "{}")
    if not isinstance(call_id, str) or not call_id.strip():
        raise AgentModelError("Creator Agent history tool call has no id")
    if not isinstance(name, str) or not name.strip():
        raise AgentModelError("Creator Agent history tool call has no name")
    if isinstance(raw_arguments, str):
        try:
            arguments = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError as exc:
            raise AgentModelError(
                "Creator Agent history tool arguments are invalid JSON",
            ) from exc
    else:
        arguments = raw_arguments
    if not isinstance(arguments, dict):
        raise AgentModelError(
            "Creator Agent history tool arguments must be an object",
        )
    return AgentToolCall(
        call_id=call_id.strip(),
        name=name.strip(),
        arguments=arguments,
    )


def records_to_agentscope_messages(
    records: Sequence[Mapping[str, Any]],
) -> list[Msg]:
    """Rehydrate driver history as native AgentScope 2.0 message blocks."""

    messages: list[Msg] = []
    for index, record in enumerate(records):
        role = str(record.get("role") or "").strip()
        content_value = record.get("content")
        content = (
            _text_content(
                content_value,
                field_name=f"message[{index}].content",
            )
            if role in {"system", "tool"}
            else ""
        )
        if role == "system":
            messages.append(SystemMsg("creator_agent", content))
            continue
        if role == "user":
            blocks = _message_content_blocks(
                content_value,
                field_name=f"message[{index}].content",
            )
            if not blocks:
                raise AgentModelError(
                    "Creator Agent history contains an empty user turn",
                )
            messages.append(UserMsg("user", blocks))
            continue
        if role == "assistant":
            blocks = _message_content_blocks(
                content_value,
                field_name=f"message[{index}].content",
            )
            raw_calls = record.get("tool_calls") or []
            if not isinstance(raw_calls, Sequence) or isinstance(
                raw_calls,
                (str, bytes, bytearray),
            ):
                raise AgentModelError(
                    "Creator Agent history tool_calls must be a list",
                )
            for raw_call in raw_calls:
                call = _history_tool_call(raw_call)
                blocks.append(
                    ToolCallBlock(
                        id=call.call_id,
                        name=call.name,
                        input=json.dumps(
                            call.arguments,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    ),
                )
            if not blocks:
                raise AgentModelError(
                    "Creator Agent history contains an empty assistant turn",
                )
            messages.append(AssistantMsg("creator_agent", blocks))
            continue
        if role == "tool":
            call_id = str(record.get("tool_call_id") or "").strip()
            name = str(record.get("name") or "").strip()
            if not call_id or not name:
                raise AgentModelError(
                    "Creator Agent history tool result has no id/name",
                )
            messages.append(
                AssistantMsg(
                    "creator_runtime",
                    [
                        ToolResultBlock(
                            id=call_id,
                            name=name,
                            output=content,
                            state=(
                                ToolResultState.ERROR
                                if record.get("failed") is True
                                else ToolResultState.SUCCESS
                            ),
                        ),
                    ],
                ),
            )
            continue
        raise AgentModelError(
            f"Creator Agent history has unsupported role: {role!r}",
        )
    return messages


class AgentScopeAgentChatClient:
    """Direct AgentScope 2.0.4 DashScope model adapter for file Runtime turns."""

    def __init__(
        self,
        model: DashScopeChatModel | None = None,
        *,
        timeout_seconds: float = 180.0,
        # ``None`` omits the parameter entirely so the provider/model keeps
        # control over its own output budget.
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._injected = model is not None
        self._configuration: tuple[str, str, str] | None = None
        self.model = model

    def _configured_model(self) -> DashScopeChatModel:
        if self._injected:
            assert self.model is not None
            return self.model
        api_key = model_config.get_text_api_key().strip()
        base_url = model_config.get_text_base_url().strip()
        model_name = model_config.get_text_model_name().strip()
        missing = [
            name
            for name, value in (
                ("api_key", api_key),
                ("base_url", base_url),
                ("model", model_name),
            )
            if not value
        ]
        if missing:
            raise AgentModelConfigurationError(
                "Creator text model configuration is incomplete: "
                + ", ".join(missing)
                + ". Configure creator_text_model before retrying.",
            )
        configuration = (api_key, base_url, model_name)
        if self.model is None or self._configuration != configuration:
            self.model = DashScopeChatModel(
                credential=DashScopeCredential(
                    api_key=api_key,
                    base_url=base_url,
                ),
                model=model_name,
                parameters=DashScopeChatModel.Parameters(
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    thinking_enable=True,
                    parallel_tool_calls=False,
                ),
                stream=True,
                formatter=DashScopeChatFormatter(),
                client_kwargs={"timeout": self.timeout_seconds},
            )
            self._configuration = configuration
        return self.model

    async def complete(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        on_text_delta: AgentTextDeltaCallback | None = None,
        on_thinking_delta: AgentTextDeltaCallback | None = None,
        on_tool_call_delta: AgentToolDeltaCallback | None = None,
        _empty_retries_remaining: int = 2,
        _rate_limit_retries_remaining: int = 3,
        _transient_retries_remaining: int = 2,
        _markup_retries_remaining: int = 2,
    ) -> AgentModelTurn:
        native_messages = records_to_agentscope_messages(messages)
        allowed_names = {
            str((item.get("function") or {}).get("name") or "")
            for item in tools
            if isinstance(item, Mapping)
            and isinstance(item.get("function"), Mapping)
        }
        allowed_names.discard("")
        guarded_text_delta = _guard_text_callback(on_text_delta)
        guarded_thinking_delta = _guard_text_callback(on_thinking_delta)
        guarded_tool_delta = _guard_tool_callback(on_tool_call_delta)
        text_stream = NativeToolTextStream(guarded_text_delta)
        streamed_thinking = False
        streamed_tool_call_ids: set[str] = set()
        streamed_tool_names: dict[str, str] = {}
        pending_tool_inputs: dict[str, list[str]] = {}
        provider_tool_chunk_counts: dict[str, int] = {}

        try:
            async with model_slot("text"):
                response = await self._configured_model()(
                    native_messages,
                    tools=[dict(item) for item in tools] or None,
                )
                if inspect.isasyncgen(response):
                    final = None
                    async for item in response:
                        if item.is_last:
                            final = item
                            continue
                        for block in item.content:
                            if isinstance(block, TextBlock):
                                if block.text:
                                    await text_stream.feed(block.text)
                            elif isinstance(block, ThinkingBlock):
                                if (
                                    block.thinking
                                    and guarded_thinking_delta is not None
                                ):
                                    await guarded_thinking_delta(
                                        block.thinking,
                                    )
                                    streamed_thinking = True
                            elif isinstance(block, ToolCallBlock) and block.id:
                                raw_name = str(block.name or "").strip()
                                if raw_name in allowed_names:
                                    streamed_tool_names[block.id] = raw_name
                                effective_name = streamed_tool_names.get(
                                    block.id,
                                    raw_name,
                                )
                                if block.input:
                                    if effective_name in allowed_names:
                                        deltas = [
                                            *pending_tool_inputs.pop(
                                                block.id,
                                                [],
                                            ),
                                            block.input,
                                        ]
                                        if guarded_tool_delta is not None:
                                            for delta in deltas:
                                                provider_tool_chunk_counts[
                                                    block.id
                                                ] = (
                                                    provider_tool_chunk_counts.get(
                                                        block.id,
                                                        0,
                                                    )
                                                    + 1
                                                )
                                                await guarded_tool_delta(
                                                    block.id,
                                                    effective_name,
                                                    delta,
                                                )
                                            streamed_tool_call_ids.add(
                                                block.id,
                                            )
                                        else:
                                            provider_tool_chunk_counts[
                                                block.id
                                            ] = provider_tool_chunk_counts.get(
                                                block.id,
                                                0,
                                            ) + len(
                                                deltas,
                                            )
                                    else:
                                        pending_tool_inputs.setdefault(
                                            block.id,
                                            [],
                                        ).append(
                                            block.input,
                                        )
                        # Unknown provider blocks cannot represent a tool call and
                        # are intentionally ignored at this transport boundary.
                    if final is None:
                        raise AgentModelError(
                            "AgentScope Creator stream is missing its final response",
                        )
                    response = final
        except NonNativeToolMarkupError as exc:
            # Same class of stochastic stream degradation as an empty
            # response: the model narrates its tool call as XML-ish text.
            # A fresh turn usually recovers; killing the run must be the
            # last resort, not the first response.
            if _markup_retries_remaining > 0:
                logger.warning(
                    "Model emitted textual tool-call markup in a TextBlock, "
                    "retrying (%d retries remaining)",
                    _markup_retries_remaining,
                )
                return await self.complete(
                    messages=messages,
                    tools=tools,
                    on_text_delta=on_text_delta,
                    on_thinking_delta=on_thinking_delta,
                    on_tool_call_delta=on_tool_call_delta,
                    _empty_retries_remaining=_empty_retries_remaining,
                    _rate_limit_retries_remaining=(
                        _rate_limit_retries_remaining
                    ),
                    _transient_retries_remaining=(
                        _transient_retries_remaining
                    ),
                    _markup_retries_remaining=_markup_retries_remaining - 1,
                )
            raise AgentModelError(
                "Creator Agent returned textual tool-call markup instead of "
                "an AgentScope ToolCallBlock",
            ) from exc
        except (
            AgentModelError,
            AgentModelConfigurationError,
            AgentStreamCallbackError,
            AgentStreamCallbackPassthrough,
        ) as exc:
            logger.error(
                "Model request failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            raise
        except Exception as exc:
            exc_text = str(exc)
            is_rate_limit = (
                "<503>" in exc_text
                or "ServiceUnavailable" in exc_text
                or "Too many requests" in exc_text
            )
            if is_rate_limit and _rate_limit_retries_remaining > 0:
                delay = 2 ** (3 - _rate_limit_retries_remaining)
                model_name = (
                    getattr(self.model, "model", "")
                    or model_config.get_text_model_name()
                )
                logger.warning(
                    "Model request rate-limited (503) [model=%s], retrying in %ds "
                    "(%d retries remaining): %s",
                    model_name,
                    delay,
                    _rate_limit_retries_remaining,
                    exc_text,
                )
                await asyncio.sleep(delay)
                return await self.complete(
                    messages=messages,
                    tools=tools,
                    on_text_delta=on_text_delta,
                    on_thinking_delta=on_thinking_delta,
                    on_tool_call_delta=on_tool_call_delta,
                    _empty_retries_remaining=_empty_retries_remaining,
                    _rate_limit_retries_remaining=(
                        _rate_limit_retries_remaining - 1
                    ),
                )
            is_transient = (
                "Download multimodal file timed out" in exc_text
                or "ReadTimeout" in exc_text
                or "ConnectTimeout" in exc_text
                or "WriteTimeout" in exc_text
            )
            if is_transient and _transient_retries_remaining > 0:
                delay = 2 ** (3 - _transient_retries_remaining)
                model_name = (
                    getattr(self.model, "model", "")
                    or model_config.get_text_model_name()
                )
                logger.warning(
                    "Model request transient error [model=%s], retrying in %ds "
                    "(%d retries remaining): %s: %s",
                    model_name,
                    delay,
                    _transient_retries_remaining,
                    type(exc).__name__,
                    exc_text,
                )
                await asyncio.sleep(delay)
                return await self.complete(
                    messages=messages,
                    tools=tools,
                    on_text_delta=on_text_delta,
                    on_thinking_delta=on_thinking_delta,
                    on_tool_call_delta=on_tool_call_delta,
                    _empty_retries_remaining=_empty_retries_remaining,
                    _rate_limit_retries_remaining=_rate_limit_retries_remaining,
                    _transient_retries_remaining=(
                        _transient_retries_remaining - 1
                    ),
                )
            logger.error(
                "Model request failed with unexpected error: %s: %s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            raise AgentModelError(
                f"Creator AgentScope model request failed: {exc}",
            ) from exc

        text_parts: list[str] = []
        thinking_parts: list[str] = []
        calls: list[AgentToolCall] = []
        for block in response.content:
            if isinstance(block, TextBlock):
                text_parts.append(block.text)
            elif isinstance(block, ThinkingBlock):
                thinking_parts.append(block.thinking)
            elif isinstance(block, ToolCallBlock):
                call_id = str(block.id or "").strip()
                raw_name = str(block.name or "").strip()
                name = (
                    raw_name
                    if raw_name in allowed_names
                    else streamed_tool_names.get(call_id, raw_name)
                )
                if not call_id or not name:
                    raise AgentModelError(
                        "Creator AgentScope ToolCallBlock has no id/name",
                    )
                if name not in allowed_names:
                    raise AgentModelError(
                        f"Creator AgentScope returned a tool not offered this turn: {name}",
                    )
                raw_arguments = block.input or ""
                (
                    arguments,
                    parse_error,
                    repaired,
                    strict_error,
                ) = _parse_tool_arguments(raw_arguments)
                calls.append(
                    AgentToolCall(
                        call_id=call_id,
                        name=name,
                        arguments=arguments,
                        parse_error=parse_error,
                        raw_arguments_bytes=len(
                            raw_arguments.encode("utf-8"),
                        ),
                        arguments_repaired=repaired,
                        strict_json_error=strict_error,
                        raw_arguments=raw_arguments,
                        provider_chunk_count=(
                            provider_tool_chunk_counts.get(call_id, 0)
                            or (1 if raw_arguments else 0)
                        ),
                    ),
                )

        text = "".join(text_parts)
        try:
            await text_stream.finalize(text)
        except NonNativeToolMarkupError as exc:
            if _markup_retries_remaining > 0:
                logger.warning(
                    "Model emitted textual tool-call markup in final text, "
                    "retrying (%d retries remaining)",
                    _markup_retries_remaining,
                )
                return await self.complete(
                    messages=messages,
                    tools=tools,
                    on_text_delta=on_text_delta,
                    on_thinking_delta=on_thinking_delta,
                    on_tool_call_delta=on_tool_call_delta,
                    _empty_retries_remaining=_empty_retries_remaining,
                    _rate_limit_retries_remaining=(
                        _rate_limit_retries_remaining
                    ),
                    _transient_retries_remaining=(
                        _transient_retries_remaining
                    ),
                    _markup_retries_remaining=_markup_retries_remaining - 1,
                )
            raise AgentModelError(
                "Creator Agent returned textual tool-call markup instead of an "
                "AgentScope ToolCallBlock",
            ) from exc
        if not text and not calls:
            if _empty_retries_remaining > 0:
                return await self.complete(
                    messages=messages,
                    tools=tools,
                    on_text_delta=on_text_delta,
                    on_thinking_delta=on_thinking_delta,
                    on_tool_call_delta=on_tool_call_delta,
                    _empty_retries_remaining=_empty_retries_remaining - 1,
                )
            raise AgentModelError(
                "Creator AgentScope model returned empty text and no ToolCallBlock",
            )

        thinking = "".join(thinking_parts)
        if (
            thinking
            and on_thinking_delta is not None
            and not streamed_thinking
        ):
            await on_thinking_delta(thinking)
        if on_tool_call_delta is not None:
            for call in calls:
                if call.call_id in streamed_tool_call_ids:
                    continue
                await on_tool_call_delta(
                    call.call_id,
                    call.name,
                    json.dumps(
                        call.arguments,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
        return AgentModelTurn(
            content=text or None,
            thinking=thinking,
            tool_calls=tuple(calls),
            provider_message_id=(
                str(response.id) if getattr(response, "id", None) else None
            ),
            finish_reason=str(
                getattr(
                    getattr(response, "finished_reason", None),
                    "value",
                    getattr(response, "finished_reason", "completed"),
                ),
            ),
            usage=_usage_payload(getattr(response, "usage", None)),
        )


class AgentScopeVlmChatClient(AgentScopeAgentChatClient):
    """Native multimodal client used for Source Intelligence turns."""

    def _configured_model(self) -> DashScopeChatModel:
        if self._injected:
            assert self.model is not None
            return self.model
        api_key = model_config.get_vlm_api_key().strip()
        base_url = model_config.get_vlm_base_url().strip()
        model_name = (
            model_config.get_vlm_model_name() or "qwen3.7-plus"
        ).strip()
        timeout_seconds = model_config.get_vlm_timeout_seconds()
        missing = [
            name
            for name, value in (
                ("api_key", api_key),
                ("base_url", base_url),
                ("model", model_name),
            )
            if not value
        ]
        if missing:
            raise AgentModelConfigurationError(
                "Creator VLM configuration is incomplete: "
                + ", ".join(missing)
                + ". Configure creator_vlm before retrying.",
            )
        configuration = (api_key, base_url, model_name)
        if self.model is None or self._configuration != configuration:
            self.model = DashScopeChatModel(
                credential=DashScopeCredential(
                    api_key=api_key,
                    base_url=base_url,
                ),
                model=model_name,
                parameters=DashScopeChatModel.Parameters(
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    thinking_enable=True,
                    parallel_tool_calls=False,
                ),
                stream=True,
                formatter=DashScopeNativeFormatter(),
                client_kwargs={
                    "timeout": timeout_seconds,
                    "default_headers": {
                        "X-DashScope-OssResourceResolve": "enable",
                    },
                },
            )
            self._configuration = configuration
        return self.model


async def _replay_complete_turn(
    turn: AgentModelTurn,
    *,
    on_text_delta: AgentTextDeltaCallback | None,
    on_thinking_delta: AgentTextDeltaCallback | None,
    on_tool_call_delta: AgentToolDeltaCallback | None,
) -> None:
    if turn.content:
        stream = NativeToolTextStream(on_text_delta)
        try:
            await stream.finalize(turn.content)
        except NonNativeToolMarkupError as exc:
            raise AgentModelError(
                "Creator Agent returned textual tool-call markup instead of an "
                "AgentScope ToolCallBlock",
            ) from exc
    if turn.thinking and on_thinking_delta is not None:
        await on_thinking_delta(turn.thinking)
    if on_tool_call_delta is not None:
        for call in turn.tool_calls:
            await on_tool_call_delta(
                call.call_id,
                call.name,
                json.dumps(
                    call.arguments,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )


__all__ = [
    "AgentChatClient",
    "AgentModelConfigurationError",
    "AgentModelError",
    "AgentStreamCallbackError",
    "AgentStreamCallbackPassthrough",
    "AgentModelTurn",
    "AgentScopeAgentChatClient",
    "AgentScopeVlmChatClient",
    "AgentToolCall",
    "CallbackAgentChatClient",
    "records_to_agentscope_messages",
]
