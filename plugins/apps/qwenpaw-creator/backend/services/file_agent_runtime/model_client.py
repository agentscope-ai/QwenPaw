# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-branches,too-many-nested-blocks,too-many-statements
"""AgentScope 2.0 chat-model boundary for the file Creator Runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
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
from .tool_protocol import (
    NativeToolTextStream,
    NonNativeToolMarkupError,
)


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


_ARGS_PREVIEW_CHARS = 160


def _parse_tool_arguments(raw: str) -> tuple[dict[str, Any], str | None]:
    """Parse streamed tool-call arguments into a JSON object.

    Strict ``json.loads`` first; malformed payloads (truncated stream,
    unbalanced braces) go through ``json_repair`` exactly like AgentScope's
    own ``_json_loads_with_repair``. Returns ``(arguments, parse_error)``—
    an unrecoverable payload yields ``({}, message)`` so the tool call can
    fail individually while the run keeps going.
    """

    if not raw.strip():
        return {}, None
    decode_error: json.JSONDecodeError | None = None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        decode_error = error
    else:
        if isinstance(parsed, dict):
            return parsed, None
    try:
        repaired = repair_json(raw, stream_stable=True, return_objects=True)
    except Exception:
        repaired = None
    if isinstance(repaired, dict):
        return repaired, None
    if len(raw) > 2 * _ARGS_PREVIEW_CHARS:
        preview = (
            raw[:_ARGS_PREVIEW_CHARS]
            + "...[TRUNCATED]..."
            + raw[-_ARGS_PREVIEW_CHARS:]
        )
    else:
        preview = raw
    detail = (
        f"JSONDecodeError: {decode_error}"
        if decode_error is not None
        else "decoded into a non-object value"
    )
    return {}, (
        "工具调用参数不是合法的 JSON 对象且无法自动修复（" + detail + "）。常见原因：花括号遗漏/错位或输出被截断。"
        "请重新生成本次工具调用；若参数体量巨大，可拆分为少量几次较小的调用。"
        f"参数原文预览：{preview!r}"
    )


AgentTextDeltaCallback = Callable[[str], Awaitable[None]]
AgentToolDeltaCallback = Callable[[str, str, str], Awaitable[None]]


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


def _text_content(value: Any, *, field: str) -> str:
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
                    f"Creator Agent history {field} contains non-text content",
                )
            pieces.append(str(item.get("text") or ""))
        return "".join(pieces)
    raise AgentModelError(f"Creator Agent history {field} must be text")


def _message_content_blocks(value: Any, *, field: str) -> list[Any]:
    """Preserve native user media while keeping ordinary history compatible."""

    if value is None or isinstance(value, str):
        text = _text_content(value, field=field)
        return [TextBlock(text=text)] if text else []
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        parts: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, Mapping):
                raise AgentModelError(
                    f"Creator Agent history {field} contains an invalid content part",
                )
            parts.append(dict(item))
        try:
            return list(native_content_blocks(parts))
        except Exception as exc:
            raise AgentModelError(
                f"Creator Agent history {field} contains invalid native media: {exc}",
            ) from exc
    raise AgentModelError(
        f"Creator Agent history {field} must be text or content parts",
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
            _text_content(content_value, field=f"message[{index}].content")
            if role in {"system", "tool"}
            else ""
        )
        if role == "system":
            messages.append(SystemMsg("creator_agent", content))
            continue
        if role == "user":
            blocks = _message_content_blocks(
                content_value,
                field=f"message[{index}].content",
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
                field=f"message[{index}].content",
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
        _empty_retries_remaining: int = 1,
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
                                                await guarded_tool_delta(
                                                    block.id,
                                                    effective_name,
                                                    delta,
                                                )
                                            streamed_tool_call_ids.add(
                                                block.id,
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
        except (
            AgentModelError,
            AgentModelConfigurationError,
            AgentStreamCallbackError,
            AgentStreamCallbackPassthrough,
        ):
            raise
        except Exception as exc:
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
                arguments, parse_error = _parse_tool_arguments(
                    block.input or "",
                )
                calls.append(
                    AgentToolCall(
                        call_id=call_id,
                        name=name,
                        arguments=arguments,
                        parse_error=parse_error,
                    ),
                )

        text = "".join(text_parts)
        try:
            await text_stream.finalize(text)
        except NonNativeToolMarkupError as exc:
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
