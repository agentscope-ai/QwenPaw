# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-branches,too-many-nested-blocks,too-many-statements
"""AgentScope 2.0 chat-model boundary for the file Creator Runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import asyncio
import inspect
import json
import os
import re
from time import monotonic

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
from agentscope.model import ChatModelBase, DashScopeChatModel

from models import config as model_config
from models.concurrency import model_slot
from models.output_budget import anthropic_output_limit
from models.dashscope_multimodal import DashScopeNativeFormatter
from models.native_content import native_content_blocks
from services.media_files.transient_errors import is_transient_error_message
from utils.logger import setup_logger
from . import media_vault
from .tool_protocol import (
    NativeToolTextStream,
    NonNativeToolMarkupError,
)
from .model_context import (
    MODEL_INPUT_BYTES,
    MediaVault,
    ModelContextBudgetError,
    _TEXT_BYTES_PER_TOKEN,
    budget_diagnostics,
    context_window,
    demote_derived_inline_media,
    demote_human_inline_media,
    format_budget_failure,
    format_demotion_record,
    media_could_bridge_the_gap,
    media_observation_degrade_enabled,
    prepare_model_messages,
)

try:
    # The platform owns the recovery boundary (one attempt, one retry, and a
    # refusal to replay output the model already spoke).  The plugin imports
    # only that boundary; the marker list and the classifier that feeds it
    # stay on this side of the plugin boundary so enabling compression never
    # has to patch the host package.
    from qwenpaw.agents.context.overflow_recovery import (
        call_with_overflow_recovery,
    )

    _HOST_OVERFLOW_RECOVERY_AVAILABLE = True
except ImportError:  # pragma: no cover - standalone plugin installs
    _HOST_OVERFLOW_RECOVERY_AVAILABLE = False

    async def call_with_overflow_recovery(
        call_model: Callable[..., Awaitable[Any]],
        recover: Callable[[Exception], Awaitable[Any]],
        **kwargs: Any,
    ) -> Any:
        """Standalone stand-in for the platform's one-shot boundary.

        Creator consumes a stream inside ``complete()`` and hands back a
        finished turn, so there is no generator for the platform wrapper to
        own here; the retry shape is the part worth keeping identical.
        """
        try:
            return await call_model(**kwargs)
        except Exception as exc:
            return await recover(exc)


# Gateway streaming wrappers render the HTTP status inside brackets
# (``Streaming response failed: [400] ...``) instead of ``Error code: 400``.
# The host's ``extract_status_code`` matches this shape; the plugin-local
# fallback has to as well, or a standalone install silently misses the
# overflow signal on group-only phrases.
_STREAMING_ERROR_STATUS_RE = re.compile(
    r"Streaming response failed:\s*\[(\d{3})\]",
)


def _local_extract_status_code(exc: Exception) -> Any:
    """Plugin-local reader for the HTTP status the classifier gates on.

    Covers every provider refusal shape we've actually seen: SDK attribute
    lookups (int or digit string), ``response.status*``, streaming
    ``[NNN]`` wrappers, and the module's own body regex as last resort.
    """
    for attr in ("status_code", "status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    response = getattr(exc, "response", None)
    if response is not None:
        for attr in ("status_code", "status"):
            value = getattr(response, attr, None)
            if isinstance(value, int):
                return value
    streaming = _STREAMING_ERROR_STATUS_RE.search(str(exc))
    if streaming is not None:
        return int(streaming.group(1))
    return _provider_http_status(exc)


# ``providers.error_utils`` is a separate host module.  Keep its availability
# independent of ``overflow_recovery`` so a future rename on one side does
# not silently flip the other capability off.
try:
    from qwenpaw.providers.error_utils import (
        extract_status_code as _host_extract_status_code,
    )
except ImportError:
    _host_extract_status_code = _local_extract_status_code


# Plugin-owned classification of "the provider said this input was too
# long".  ``react_agent._is_context_overflow_error`` keeps the platform's
# own copy; this list is what the recovery boundary checks before it asks
# the host to retry.  The extra phrases (compared with the platform copy)
# cover gateway bodies that wrap the original refusal without a structured
# status code, which the host's inline path cannot see.
CONTEXT_OVERFLOW_MARKERS: tuple[str, ...] = (
    "range of input length",
    "context length exceeded",
    "context_length_exceeded",
    "maximum context length",
    "maximum context window",
    "context window exceeded",
    "max input length",
    "input length should be",
    "input is too long",
    "prompt is too long",
    "prompt too long",
    "too many input tokens",
)
_CONTEXT_OVERFLOW_MARKER_GROUPS: tuple[tuple[str, ...], ...] = (
    ("tokens", "exceeds the available context size"),
    (
        "input token count",
        "exceeds the maximum number of tokens allowed",
    ),
    (
        "input token count",
        "model only supports up to",
    ),
)


def _matches_overflow_markers(error_str: str) -> bool:
    """Whether *error_str* names an overflow by a marker or a marker group.

    The platform classifies some refusals with one phrase and others only
    with a group of phrases that must all appear. Both the bare-400
    classifier and the widened 413/422/text-only path scan through this one
    helper so neither can drift from the other.
    """
    if any(marker in error_str for marker in CONTEXT_OVERFLOW_MARKERS):
        return True
    return any(
        all(marker in error_str for marker in marker_group)
        for marker_group in _CONTEXT_OVERFLOW_MARKER_GROUPS
    )


def is_context_overflow_error(exc: Exception) -> bool:
    """Return whether *exc* is a provider refusal for an oversized input."""
    status = _host_extract_status_code(exc)
    error_str = str(exc).lower()
    if status != 400 and "error code: 400" not in error_str:
        return False
    return _matches_overflow_markers(error_str)


logger = setup_logger("creator.model_client")


class AgentModelError(RuntimeError):
    pass


class OverflowAfterOutputError(AgentModelError):
    """A provider overflow that arrived after the model already started reply.

    The recovery boundary degrades the input and calls again, which would say
    the same thing to the user twice. This is how a streamed turn tells the
    boundary to stop rather than retry.
    """


class AgentModelConfigurationError(AgentModelError):
    pass


class ModelContextUnfitError(AgentModelError):
    """The input was proven too large with nothing left to give up.

    Everything the recovery ladder can move has moved, so an automatic resume
    would re-send bytes the same window already refused and buy one error
    message at the price of a full model call. The run stops and waits for a
    human to shorten the input; every other ``AgentModelError`` describes a
    fault a retry can plausibly clear.
    """


class RateLimitExhaustedError(AgentModelError):
    """The provider kept rate-limiting the model after every retry.

    Carries the number of retry attempts so the Runtime can surface a
    user-facing notice (and a manual resume control) in AgentDock.
    """

    def __init__(self, message: str, *, retries: int) -> None:
        self.retries = retries
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RateLimitRetryNotice:
    """
    One real upcoming model retry; the legacy callback also carries recovery
    retries.
    """

    attempt: int
    max_attempts: int
    delay_seconds: float
    reason: str = "rate_limit"


AgentRateLimitRetryCallback = Callable[
    [RateLimitRetryNotice],
    Awaitable[None],
]

# Text is a fallback for SDKs that discard the structured HTTP response.
# A request ID can contain any digits, so bare status substrings are unsafe.
RATE_LIMIT_ERROR_SIGNATURES = (
    "throttl",
    "too many requests",
    "rate limit",
    "ratelimit",
)
_HTTP_STATUS_PATTERN = re.compile(
    r"(?:\b(?:http(?:/\d(?:\.\d)?)?|status(?:[_ -]?code)?|error code)"
    r"[\"']?\s*[:=]?\s*[\"']?|^\s*|<)([45]\d\d)(?=\b|>)",
    re.IGNORECASE,
)

MAX_RATE_LIMIT_RETRIES = 5
MAX_TRANSIENT_MODEL_RETRIES = 4


class _ThinkingDeltaBuffer:
    """Bound synchronous trace writes while keeping the full thinking text."""

    def __init__(self, callback: AgentTextDeltaCallback | None):
        self.callback = callback
        self.parts: list[str] = []
        self.size = 0
        self.last_flush: float | None = None

    async def feed(self, delta: str) -> None:
        self.parts.append(delta)
        self.size += len(delta)
        if (
            self.last_flush is None
            or self.size >= 1024
            or monotonic() - self.last_flush >= 0.5
        ):
            await self.flush()

    async def flush(self) -> None:
        if not self.parts:
            return
        delta = "".join(self.parts)
        # A callback failure must not replay the same delta or model request.
        self.parts.clear()
        self.size = 0
        if self.callback is not None:
            await self.callback(delta)
        self.last_flush = monotonic()


@asynccontextmanager
async def _buffered_thinking(callback: AgentTextDeltaCallback | None):
    buffer = _ThinkingDeltaBuffer(callback)
    try:
        yield buffer
    except (
        asyncio.CancelledError,
        AgentStreamCallbackError,
        AgentStreamCallbackPassthrough,
    ):
        # Cancellation and persistence failures remain immediate boundaries.
        raise
    except Exception:
        await buffer.flush()
        raise
    await buffer.flush()


def is_rate_limit_error_text(exc_text: str) -> bool:
    match = _HTTP_STATUS_PATTERN.search(exc_text)
    if match is not None:
        return int(match.group(1)) == 429
    lowered = exc_text.lower()
    return any(
        signature in lowered for signature in RATE_LIMIT_ERROR_SIGNATURES
    )


def _provider_http_status(exc: Exception) -> int | None:
    """Prefer transport facts to arbitrary text in a provider error body."""
    for source in (exc, getattr(exc, "response", None)):
        for name in ("status_code", "status"):
            value = getattr(source, name, None)
            if isinstance(value, (int, str)) and str(value).isdigit():
                status = int(value)
                if 400 <= status <= 599:
                    return status
    match = _HTTP_STATUS_PATTERN.search(str(exc))
    return int(match.group(1)) if match else None


def is_rate_limit_error(exc: Exception) -> bool:
    status = _provider_http_status(exc)
    if status is not None:
        return status == 429
    return is_rate_limit_error_text(str(exc))


def is_context_length_error(exc: Exception) -> bool:
    """Whether the provider refused this input for being too long.

    The plugin-owned classifier answers first so a refusal already on the
    marker list cannot be argued with here.  This plugin also has to
    survive gateways that answer 413/422 (or only leak text, no status at
    all) where the SDK path answers a bare 400, so those cases widen via
    the same marker list rather than a second list - and they scan the
    marker groups too, so a group-only refusal is not dropped just because
    its status is not a bare 400.
    """
    if is_context_overflow_error(exc):
        return True
    if _provider_http_status(exc) not in (None, 400, 413, 422):
        return False
    return _matches_overflow_markers(str(exc).casefold())


def _rate_limit_retry_delay(attempt: int) -> float:
    # 2s, 4s, 8s, 16s, 30s for attempts 0..4.
    return float(min(2 * (2**attempt), 30))


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
        """
        Serialize the call for the driver's provider-independent turn history.
        """

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
    # The request this turn actually answers. Compaction and the demotion
    # ladder can both leave a different shape than the caller handed over, and
    # a turn that hides which one the model read lets the next turn rebuild
    # the bytes that were already refused.
    sent_messages: list[dict[str, Any]] | None = field(
        default=None,
        compare=False,
        repr=False,
    )


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
        on_rate_limit_retry: AgentRateLimitRetryCallback | None = None,
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
        on_rate_limit_retry: AgentRateLimitRetryCallback | None = None,
    ) -> AgentModelTurn:
        del on_rate_limit_retry
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


# ── Protocol-aware model construction ────────────────────────────────────────
# Protocol classification lives in ``models.config`` so every module agrees
# on which gateway speaks which wire format.


def _build_chat_model(
    *,
    api_key: str,
    base_url: str,
    model_name: str,
    protocol: str,
    parameters: Any,
    stream: bool = True,
    formatter: Any = None,
    client_kwargs: dict[str, Any] | None = None,
) -> ChatModelBase:
    """Create the correct AgentScope ChatModel for the given protocol.

    Anthropic/MiniMax → `AnthropicChatModel` + `AnthropicCredential`
    Google Gemini     → `GeminiChatModel` + `GeminiCredential`
    Everything else   → `DashScopeChatModel` + `DashScopeCredential`
    """
    if model_config.is_anthropic_protocol(protocol):
        from agentscope.credential import AnthropicCredential
        from agentscope.model import AnthropicChatModel

        return AnthropicChatModel(
            credential=AnthropicCredential(
                api_key=api_key,
                base_url=base_url,
            ),
            model=model_name,
            parameters=parameters,
            stream=stream,
            formatter=formatter,
            client_kwargs=client_kwargs,
        )
    if model_config.is_gemini_protocol(protocol):
        from agentscope.credential import GeminiCredential
        from agentscope.model import GeminiChatModel

        # Google GenAI Client does not accept ``timeout`` in client_kwargs;
        # drop it to avoid TypeError at construction time.
        gemini_kwargs = (
            {k: v for k, v in client_kwargs.items() if k != "timeout"}
            if client_kwargs
            else None
        )
        return GeminiChatModel(
            credential=GeminiCredential(
                id="qwenpaw-creator",
                api_key=api_key,
            ),
            model=model_name,
            parameters=parameters,
            stream=stream,
            formatter=formatter,
            client_kwargs=gemini_kwargs,
        )
    # Drop the sampling temperature for models whose gateway rejects an
    # explicit value (e.g. DashScope ``kimi-k3``); AgentScope omits a
    # ``None`` temperature so the provider applies its own default. Only the
    # OpenAI-compatible/DashScope path reaches here: Anthropic and Gemini
    # return above and their ``Parameters`` differ.
    parameters = parameters.model_copy(
        update={
            "temperature": model_config.chat_temperature(
                model_name,
                parameters.temperature,
            ),
        },
    )
    return DashScopeChatModel(
        credential=DashScopeCredential(
            api_key=api_key,
            base_url=base_url,
        ),
        model=model_name,
        parameters=parameters,
        stream=stream,
        formatter=formatter,
        client_kwargs=client_kwargs,
    )


def default_model_turn_timeout_seconds() -> float:
    """Per-turn budget shared by the driver and the transport timeout.

    Planning turns that emit a full Element structure in one response
    legitimately exceed 300s on slower endpoints, so the floor is 600s;
    ``CREATOR_MODEL_TURN_TIMEOUT_SECONDS`` raises it per deployment.
    Invalid or non-positive overrides fall back to 600.
    """
    raw = os.environ.get("CREATOR_MODEL_TURN_TIMEOUT_SECONDS", "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            value = 0.0
        if value > 0:
            return value
    return 600.0


DEFAULT_MODEL_TURN_TIMEOUT_SECONDS = default_model_turn_timeout_seconds()


class AgentScopeAgentChatClient:
    """Direct AgentScope 2.0.4 model adapter for file Runtime turns.

    Supports DashScope (OpenAI-compatible), Anthropic/MiniMax, and
    Google Gemini protocols.  The protocol is read from the persisted
    ``llm`` section of ``model_config.json`` via
    ``model_config.get_text_protocol()``.
    """

    def __init__(
        self,
        model: ChatModelBase | None = None,
        *,
        # Shares default_model_turn_timeout_seconds with the driver turn
        # budget so the transport timeout never undercuts it.
        timeout_seconds: float = DEFAULT_MODEL_TURN_TIMEOUT_SECONDS,
        temperature: float = 0.2,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self._injected = model is not None
        self._configuration: tuple[str, str, str, str] | None = None
        self.model = model

    def _configured_model(self) -> ChatModelBase:
        if self._injected:
            assert self.model is not None
            return self.model
        api_key = model_config.get_text_api_key().strip()
        base_url = model_config.get_text_base_url().strip()
        model_name = model_config.get_text_model_name().strip()
        protocol = model_config.get_text_protocol().strip()
        # Anthropic and Gemini gateways always authenticate; OpenAI-compatible
        # gateways may serve free keyless models (e.g. OpenCode Zen), where
        # the openai client with an empty key simply omits the Authorization
        # header.
        required_fields: tuple[tuple[str, str], ...] = (
            ("base_url", base_url),
            ("model", model_name),
        )
        if model_config.protocol_requires_api_key(protocol):
            required_fields = (("api_key", api_key),) + required_fields
        missing = [name for name, value in required_fields if not value]
        if missing:
            raise AgentModelConfigurationError(
                "Creator text model configuration is incomplete: "
                + ", ".join(missing)
                + f" (protocol='{protocol}', "
                + f"base_url='{base_url or '<empty>'}', "
                + f"model='{model_name or '<empty>'}', "
                + "api_key="
                + ("'<set>'" if api_key else "'<empty>'")
                + "). Open the Creator model config dialog (or set the "
                + "creator text model fields) and retry. Protocols "
                + "'Anthropic'/'Gemini' always require an api_key; "
                + "OpenAI-compatible gateways may run keyless free models.",
            )
        configuration = (api_key, base_url, model_name, protocol)
        if self.model is None or self._configuration != configuration:
            if model_config.is_anthropic_protocol(protocol):
                from agentscope.model import AnthropicChatModel

                parameters = AnthropicChatModel.Parameters(
                    temperature=self.temperature,
                )
                self.model = _build_chat_model(
                    api_key=api_key,
                    base_url=base_url,
                    model_name=model_name,
                    protocol=protocol,
                    parameters=parameters,
                    client_kwargs={"timeout": self.timeout_seconds},
                )
            elif model_config.is_gemini_protocol(protocol):
                from agentscope.model import GeminiChatModel

                parameters = GeminiChatModel.Parameters(
                    temperature=self.temperature,
                )
                self.model = _build_chat_model(
                    api_key=api_key,
                    base_url=base_url,
                    model_name=model_name,
                    protocol=protocol,
                    parameters=parameters,
                    client_kwargs={"timeout": self.timeout_seconds},
                )
            else:
                parameters = DashScopeChatModel.Parameters(
                    temperature=self.temperature,
                    thinking_enable=True,
                    parallel_tool_calls=False,
                )
                self.model = _build_chat_model(
                    api_key=api_key,
                    base_url=base_url,
                    model_name=model_name,
                    protocol=protocol,
                    parameters=parameters,
                    formatter=DashScopeChatFormatter(),
                    client_kwargs={"timeout": self.timeout_seconds},
                )
            self._configuration = configuration
        return self.model

    def _budget_model_name(self) -> str:
        """Model name used to resolve the token window for this client.

        The base client issues requests through the text model, so the
        default is the text model name.  ``AgentScopeVlmChatClient``
        overrides this: VLM and text catalogs can carry different context
        windows, and pricing a VLM turn against the text window either
        demotes media that would have fitted or admits input the VLM
        actually cannot take.
        """
        return model_config.get_text_model_name()

    def _input_token_budget(self) -> int | None:
        """Input ceiling for this deployment's model context window.

        Resolves the window from the same host catalog the platform scroll
        reads, so the plugin never prices against a different ceiling.  The
        name is taken from ``_budget_model_name`` so a VLM turn is measured
        against the VLM window.  When no window is available the byte
        transport floor stays the sole limit.
        """
        context_size = context_window(
            self._budget_model_name(),
        )
        if context_size is None:
            return None
        # Match the platform scroll output reserve:
        #   min(_MAX_OUTPUT_RESERVE_TOKENS=4096, max(1, hard_limit * 0.05))
        reserve = min(4096, max(1, int(context_size * 0.05)))
        return max(1024, context_size - reserve)

    def _media_vault(self) -> MediaVault | None:
        """Durable home for demoted media, or ``None`` when there is none.

        The returned vault opens the store per block, so an unavailable data
        root is answered inside it (a pointer with no handle, which is what a
        machine without a resolved root can honestly promise). This guard only
        covers building the vault itself.
        """
        try:
            return media_vault.make_vault()
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "creator media vault unavailable; demoted pointers will carry "
                "no recall handle",
                exc_info=True,
            )
            return None

    def _fit_refused_request(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        *,
        max_bytes: int,
        failure: ModelContextBudgetError,
    ) -> tuple[list[dict[str, Any]], str]:
        """Rebuild a locally refused request in two pressure steps.

        First the runtime's own observations, which any tool can produce
        again. Only if the request still does not fit does a human attachment
        move, and only with a durable copy behind it. A refusal that survives
        both steps is reported with what was given up, because the input the
        caller sees failing is no longer the input it sent. The record comes
        back with the rebuilt request for the same reason: a provider refusal
        further along still describes this request.
        """
        if not media_observation_degrade_enabled():
            raise AgentModelError(format_budget_failure(failure)) from failure
        vault = self._media_vault()
        token_budget = self._input_token_budget()
        record: list[tuple[str, Mapping[str, Any]]] = []

        def prepare(
            candidate: Sequence[Mapping[str, Any]],
        ) -> tuple[
            list[dict[str, Any]] | None,
            ModelContextBudgetError | None,
        ]:
            try:
                return (
                    prepare_model_messages(
                        candidate,
                        tools,
                        max_bytes=max_bytes,
                        max_tokens=token_budget,
                    ),
                    None,
                )
            except ModelContextBudgetError as exc:
                return None, exc

        candidate: Sequence[Mapping[str, Any]] = messages
        demoted, receipt = demote_derived_inline_media(
            messages,
            budget_bytes=max_bytes,
            vault=vault,
        )
        record.append(("派生观察媒体", receipt))
        if receipt["demoted_blocks"]:
            candidate = demoted
            prepared, refused = prepare(demoted)
            if prepared is not None:
                return prepared, self._report_demotions(record, max_bytes)
            failure = refused or failure
        # Pressure has to be media-shaped before an upload moves. The very
        # accounting that refused the request says whether it is: when every
        # inline block together costs less than the overage, no amount of
        # demotion can fit, and the ladder would strip a person's attachments
        # one by one while heading for the identical failure.
        if not failure.diagnostics:
            # A provider refusal arrives without a local measurement, and an
            # empty reading opens that gate unconditionally: the ladder would
            # strip a person's uploads one by one on the promise that media is
            # what does not fit, while the request may be overflowing on
            # contract text no demotion can shrink. Measure the shape this step
            # aims at, through the same compaction its own success test
            # applies, so the gap the gate reads is the gap this request has to
            # close. What the caller was told keeps its own words: this probe
            # states a budget the ladder tightened, not the one that refused.
            probed, refused = prepare(candidate)
            reading = (
                refused.diagnostics
                if refused is not None and refused.diagnostics
                else budget_diagnostics(
                    probed if probed is not None else candidate,
                    tools,
                    max_bytes=max_bytes,
                    max_tokens=token_budget,
                )
            )
            failure = ModelContextBudgetError(
                str(failure),
                diagnostics=reading,
            )
        if not media_could_bridge_the_gap(failure.diagnostics):
            raise ModelContextUnfitError(
                "\n".join(
                    part
                    for part in (
                        format_budget_failure(failure),
                        "缺口不是媒体造成的，真人附件未移动。",
                        format_demotion_record(record),
                    )
                    if part
                ),
            ) from failure
        # Proven pressure is what earns this step, and it is paid one
        # attachment at a time: the most expensive upload moves, the request
        # is measured again, and the trade stops the moment it fits. Demoting
        # the whole batch instead would let one oversized screenshot cost every
        # other upload in the same conversation its bytes.
        current: list[dict[str, Any]] = demoted
        totals: dict[str, Any] = {
            "demoted_blocks": 0,
            "demoted_charge_bytes": 0,
            "stored_blocks": 0,
            "refused_blocks": 0,
            "handles": [],
        }
        while True:
            candidate, step = demote_human_inline_media(
                current,
                vault=vault,
                budget_bytes=max_bytes,
                one_step=True,
            )
            if not step["demoted_blocks"]:
                break
            for key in (
                "demoted_blocks",
                "demoted_charge_bytes",
                "stored_blocks",
                "refused_blocks",
            ):
                totals[key] += step[key]
            totals["handles"].extend(step["handles"])
            current = candidate
            prepared, refused = prepare(current)
            if prepared is not None:
                record.append(("真人附件媒体", totals))
                return prepared, self._report_demotions(record, max_bytes)
            failure = refused or failure
        record.append(("真人附件媒体", totals))
        logger.warning(
            "Model input exceeded the window and nothing left can be given "
            "up: %s",
            failure,
        )
        raise ModelContextUnfitError(
            "\n".join(
                part
                for part in (
                    format_budget_failure(failure),
                    format_demotion_record(record),
                )
                if part
            ),
        ) from failure

    @staticmethod
    def _report_demotions(
        record: list[tuple[str, Mapping[str, Any]]],
        max_bytes: int,
    ) -> str:
        """Log the demotion that let a refused request through, keep its text.

        The text outlives the log line: a request that fits now can still be
        refused by the provider, and that failure has to say what was already
        given up to produce it.
        """
        note = format_demotion_record(record)
        logger.warning(
            "creator context guard: fit %d bytes by demoting media; %s",
            max_bytes,
            note,
        )
        return note

    def _gentle_overflow_relief(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        *,
        max_bytes: int,
    ) -> tuple[list[dict[str, Any]], int, str] | None:
        """First recovery step: give up only what a tool can produce again.

        A provider refusing an input that is too long says the request cost
        more than the window, not that the conversation was wrong. The media
        the runtime observed itself is all this step may trade, and every
        traded block leaves a handle behind, so a person's upload keeps its
        bytes until the forced step proves they are what does not fit.

        ``None`` means there was nothing to trade here, which sends the caller
        to the one lever left: retiring older completed tool exchanges.
        """
        if not media_observation_degrade_enabled():
            return None
        demoted, receipt = demote_derived_inline_media(
            messages,
            budget_bytes=max_bytes,
            vault=self._media_vault(),
        )
        if not receipt["demoted_blocks"]:
            return None
        note = self._report_demotions(
            [("溢出恢复·派生观察媒体", receipt)],
            max_bytes,
        )
        try:
            prepared = prepare_model_messages(
                demoted,
                tools,
                max_bytes=max_bytes,
                max_tokens=self._input_token_budget(),
            )
        except ModelContextBudgetError:
            return None
        if prepared == list(messages):
            return None
        return prepared, max_bytes, note

    def _overflow_history_fallback(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        *,
        max_bytes: int,
    ) -> tuple[list[dict[str, Any]] | None, int]:
        """Rebuild at half the budget so compaction retires old tool exchanges.

        A provider that answers 400 on length knows a window this runtime did
        not assume; the request it refused is otherwise identical. Halving the
        budget is the only trade left that touches nothing a person uploaded:
        ``prepare_model_messages`` drops whole completed tool exchanges, which
        a healthy long session accumulates far faster than media.

        Returns ``(None, budget)`` when even that cannot produce a smaller
        request, so the caller stops rather than replaying the refusal.
        """
        smaller_budget = max(
            1024,
            min(
                max_bytes // 2,
                len(
                    json.dumps(
                        {"messages": messages, "tools": tools},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
                // 2,
            ),
        )
        try:
            smaller = prepare_model_messages(
                messages,
                tools,
                max_bytes=smaller_budget,
                max_tokens=self._input_token_budget(),
            )
        except ModelContextBudgetError:
            return None, smaller_budget
        if smaller == list(messages):
            return None, smaller_budget
        return smaller, smaller_budget

    async def _recover_forced_overflow(
        self,
        exc: Exception,
        *,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        max_bytes: int,
        retry_kwargs: Mapping[str, Any],
        demotion_notes: Sequence[str],
    ) -> AgentModelTurn:
        """Second recovery step, for a gentle request that overflowed too.

        Everything the demotion ladder can still move goes, including a human
        attachment with a durable copy behind it, and the byte budget tightens
        so compaction gives up old tool exchanges as well. Anything that is not
        an overflow propagates untouched: this boundary degrades input, it does
        not re-run work the provider already answered.
        """
        if isinstance(exc, OverflowAfterOutputError) or not (
            is_context_length_error(exc)
        ):
            raise exc
        if not media_observation_degrade_enabled():
            # With the ladder switched off this boundary stops where the
            # feature stops, and keeps the terminal the driver refuses to
            # resume: a reclassified retryable failure would spend another
            # call on bytes no longer allowed to move.
            raise ModelContextUnfitError(
                "\n".join((str(exc), *demotion_notes)),
            ) from exc
        # ``max_bytes`` is the caller's ``_context_budget_bytes``: the 384 KB
        # transport floor on a top-level turn, not the effective
        # token-window budget ``prepare_bytes`` may have derived. Halving the
        # floor therefore over-compresses a large window on purpose - a
        # strictly smaller request cannot re-trigger the refusal, and it
        # mirrors the host's forced-trigger semantics; the rebuilt request is
        # measured again by the byte and token gates before it is sent.
        forced_budget = max(1024, max_bytes // 2)
        rebuilt, forced_note = self._fit_refused_request(
            messages,
            tools,
            max_bytes=forced_budget,
            failure=ModelContextBudgetError(str(exc)),
        )
        logger.warning(
            "creator overflow recovery: forced demotion of the full ladder "
            "into %d bytes",
            forced_budget,
        )
        return await self.complete(
            messages=rebuilt,
            tools=tools,
            _context_budget_bytes=forced_budget,
            _demotion_notes=(*demotion_notes, forced_note),
            **retry_kwargs,
        )

    # Provider recovery paths return as soon as a complete turn is available.
    # pylint: disable-next=too-many-return-statements
    async def complete(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        on_text_delta: AgentTextDeltaCallback | None = None,
        on_thinking_delta: AgentTextDeltaCallback | None = None,
        on_tool_call_delta: AgentToolDeltaCallback | None = None,
        on_rate_limit_retry: AgentRateLimitRetryCallback | None = None,
        _empty_retries_remaining: int = 2,
        _rate_limit_retries_remaining: int = MAX_RATE_LIMIT_RETRIES,
        _transient_retries_remaining: int = MAX_TRANSIENT_MODEL_RETRIES,
        _markup_retries_remaining: int = 4,
        _context_retries_remaining: int = 1,
        _context_budget_bytes: int = MODEL_INPUT_BYTES,
        _demotion_notes: Sequence[str] = (),
    ) -> AgentModelTurn:
        token_budget = self._input_token_budget()
        # The byte budget prepare_model_messages checks can be two orders of
        # magnitude larger than the transport floor: a 1M-token window is
        # ~4 MB of plain text, so a 384 KB transport floor would refuse
        # every substantial request before the provider ever sees it.  Only
        # the top-level call derives this ceiling from the token window;
        # recovery paths already carry a tightened budget. Equality with the
        # transport floor is therefore the sentinel for "top-level call":
        # every recovery step halves its budget before it recurses, so a
        # recovery path never hands MODEL_INPUT_BYTES back in here.
        if token_budget is None or _context_budget_bytes != MODEL_INPUT_BYTES:
            prepare_bytes = _context_budget_bytes
        else:
            prepare_bytes = max(
                MODEL_INPUT_BYTES,
                int(token_budget * _TEXT_BYTES_PER_TOKEN),
            )
        try:
            messages = prepare_model_messages(
                messages,
                tools,
                max_bytes=prepare_bytes,
                max_tokens=token_budget,
            )
        except ModelContextBudgetError as exc:
            # This refusal happens locally, before a request goes out, so the
            # provider-side recovery below never gets to run. Compaction
            # stops at contract content, which leaves only demoted media as
            # relief; the ladder in _fit_refused_request decides how far to
            # go before handing the failure and its record back to the user.
            messages, note = self._fit_refused_request(
                messages,
                tools,
                max_bytes=prepare_bytes,
                failure=exc,
            )
            _demotion_notes = (*_demotion_notes, note)
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
        # Nothing the user can see has been streamed yet; the platform's
        # recovery boundary never replays output a model already spoke.
        emitted_model_output = False

        try:
            async with (
                model_slot("text"),
                _buffered_thinking(
                    guarded_thinking_delta,
                ) as thinking_buffer,
            ):
                configured = self._configured_model()
                if not self._injected and self._configuration is not None:
                    (
                        api_key,
                        base_url,
                        model_name,
                        protocol,
                    ) = self._configuration
                    if (
                        model_config.is_anthropic_protocol(protocol)
                        and configured.parameters.max_tokens is None
                    ):
                        configured.parameters.max_tokens = (
                            await anthropic_output_limit(
                                model_name,
                                base_url=base_url,
                                api_key=api_key,
                            )
                        )
                response = await configured(
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
                            if not isinstance(block, ThinkingBlock):
                                await thinking_buffer.flush()
                            if isinstance(block, TextBlock):
                                if block.text:
                                    await text_stream.feed(block.text)
                                    emitted_model_output = True
                            elif isinstance(block, ThinkingBlock):
                                if (
                                    block.thinking
                                    and guarded_thinking_delta is not None
                                ):
                                    await thinking_buffer.feed(
                                        block.thinking,
                                    )
                                    streamed_thinking = True
                                    emitted_model_output = True
                            elif isinstance(block, ToolCallBlock) and block.id:
                                raw_name = str(block.name or "").strip()
                                if raw_name in allowed_names:
                                    streamed_tool_names[block.id] = raw_name
                                effective_name = streamed_tool_names.get(
                                    block.id,
                                    raw_name,
                                )
                                if block.input:
                                    # A streamed tool-call argument is model
                                    # output the user can already see.
                                    emitted_model_output = True
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
                        # Unknown provider blocks cannot represent a tool call
                        # and
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
                if on_rate_limit_retry is not None:
                    await on_rate_limit_retry(
                        RateLimitRetryNotice(
                            attempt=5 - _markup_retries_remaining,
                            max_attempts=4,
                            delay_seconds=0,
                            reason="invalid_response",
                        ),
                    )
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
                    on_rate_limit_retry=on_rate_limit_retry,
                    _empty_retries_remaining=_empty_retries_remaining,
                    _rate_limit_retries_remaining=(
                        _rate_limit_retries_remaining
                    ),
                    _transient_retries_remaining=(
                        _transient_retries_remaining
                    ),
                    _markup_retries_remaining=_markup_retries_remaining - 1,
                    _context_retries_remaining=_context_retries_remaining,
                    _context_budget_bytes=_context_budget_bytes,
                    _demotion_notes=_demotion_notes,
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
            if model_config.is_temperature_unsupported_error(exc_text):
                # The AgentScope SDK path cannot cheaply re-issue the turn
                # here, so learn the refusal and drop the cached model. Its
                # parameters still carry the rejected temperature, and
                # _configured_model() rebuilds only when the configuration
                # tuple changes, which the capability flip does not do; the
                # next turn then rebuilds via _build_chat_model, which omits
                # the field via chat_temperature.
                model_config.learn_temperature_unsupported(
                    getattr(self.model, "model", "")
                    or model_config.get_text_model_name(),
                )
                if not self._injected:
                    self.model = None
                    self._configuration = None
            if is_context_length_error(exc):
                if emitted_model_output:
                    # Part of this answer is already on screen; degrading the
                    # input and calling again would repeat it.
                    raise OverflowAfterOutputError(
                        "\n".join(
                            (
                                "Creator model input overflowed after the "
                                f"model already streamed output: {exc}",
                                *_demotion_notes,
                            ),
                        ),
                    ) from exc
                if _context_retries_remaining:
                    # A provider overflow is deterministic, so it is answered
                    # by handing back a strictly smaller request and never by
                    # waiting. The platform boundary owns that one retry:
                    # gentle relief first, which gives up only what a tool can
                    # produce again; the forced step runs solely when the
                    # gentle request overflowed as well.
                    retry_kwargs: dict[str, Any] = {
                        "on_text_delta": on_text_delta,
                        "on_thinking_delta": on_thinking_delta,
                        "on_tool_call_delta": on_tool_call_delta,
                        "on_rate_limit_retry": on_rate_limit_retry,
                        "_empty_retries_remaining": _empty_retries_remaining,
                        "_rate_limit_retries_remaining": (
                            _rate_limit_retries_remaining
                        ),
                        "_transient_retries_remaining": (
                            _transient_retries_remaining
                        ),
                        "_markup_retries_remaining": _markup_retries_remaining,
                        "_context_retries_remaining": 0,
                    }
                    relief = self._gentle_overflow_relief(
                        messages,
                        tools,
                        max_bytes=_context_budget_bytes,
                    )
                    if relief is None:
                        # Nothing media-shaped can leave *the gentle step*. The
                        # lever still available retires older completed tool
                        # exchanges by re-running compaction against half the
                        # budget: the window the provider just refused is
                        # smaller than the one assumed here, and a text-only
                        # overflow has no media to demote. Without this step a
                        # long plain-text session fails on its first refusal.
                        smaller, half_budget = self._overflow_history_fallback(
                            messages,
                            tools,
                            max_bytes=_context_budget_bytes,
                        )
                        if smaller is None:
                            # Compaction having nothing to retire is not the
                            # same as the request having nothing to give up. A
                            # turn carrying only a person's uploads has no
                            # gentle relief to fail into, and this is the
                            # ordinary way the oversized input gets reported:
                            # the local byte guard prices inline media at a
                            # fraction of what a vision window charges, so the
                            # provider, not the guard, is the one that refuses.
                            # Ending here left every turn of an uploaded
                            # reference session paying one burned call before
                            # stopping as non-retryable, with the ladder that
                            # could have moved those bytes never entered.
                            # A notice promises a second request, and with the
                            # ladder switched off the boundary makes none.
                            if on_rate_limit_retry is not None and (
                                media_observation_degrade_enabled()
                            ):
                                await on_rate_limit_retry(
                                    RateLimitRetryNotice(
                                        attempt=1,
                                        max_attempts=2,
                                        delay_seconds=0,
                                        reason="context_recovery",
                                    ),
                                )
                            return await self._recover_forced_overflow(
                                exc,
                                messages=messages,
                                tools=tools,
                                max_bytes=_context_budget_bytes,
                                retry_kwargs=retry_kwargs,
                                demotion_notes=_demotion_notes,
                            )
                        logger.warning(
                            "creator overflow recovery: compacting history "
                            "into %d bytes after a provider refusal",
                            half_budget,
                        )
                        if on_rate_limit_retry is not None:
                            await on_rate_limit_retry(
                                RateLimitRetryNotice(
                                    attempt=1,
                                    max_attempts=2,
                                    delay_seconds=0,
                                    reason="context_recovery",
                                ),
                            )
                        # The compacted request is still this client's, so a
                        # second refusal has to reach the forced step the same
                        # way a gentle one does. Left unwrapped, a session that
                        # needed compaction could never trade a media block.
                        # The forced step rebuilds from what the provider just
                        # refused, not from the shape before compaction: handed
                        # the original, it re-retires every exchange a second
                        # time and measures them against the budget that was
                        # never in force for this retry.
                        return await call_with_overflow_recovery(
                            self.complete,
                            lambda retry_exc: self._recover_forced_overflow(
                                retry_exc,
                                messages=smaller,
                                tools=tools,
                                max_bytes=_context_budget_bytes,
                                retry_kwargs=retry_kwargs,
                                demotion_notes=_demotion_notes,
                            ),
                            messages=smaller,
                            tools=tools,
                            _context_budget_bytes=half_budget,
                            _demotion_notes=_demotion_notes,
                            **retry_kwargs,
                        )
                    smaller, smaller_budget, gentle_note = relief
                    notes = (*_demotion_notes, gentle_note)
                    if on_rate_limit_retry is not None:
                        await on_rate_limit_retry(
                            RateLimitRetryNotice(
                                attempt=1,
                                max_attempts=2,
                                delay_seconds=0,
                                reason="context_recovery",
                            ),
                        )
                    return await call_with_overflow_recovery(
                        self.complete,
                        lambda retry_exc: self._recover_forced_overflow(
                            retry_exc,
                            messages=smaller,
                            tools=tools,
                            max_bytes=_context_budget_bytes,
                            retry_kwargs=retry_kwargs,
                            demotion_notes=notes,
                        ),
                        messages=smaller,
                        tools=tools,
                        _context_budget_bytes=smaller_budget,
                        _demotion_notes=notes,
                        **retry_kwargs,
                    )
                # Reaching here means the ladder already ran: this call only
                # exists with its retry budget spent, so the provider has now
                # refused a request this client cannot make any smaller. The
                # notes name the media that already left, because the input it
                # refused is not the input the caller wrote.
                raise ModelContextUnfitError(
                    "\n".join((exc_text, *_demotion_notes)),
                ) from exc
            is_rate_limit = is_rate_limit_error(exc)
            if is_rate_limit and _rate_limit_retries_remaining > 0:
                attempt = (
                    MAX_RATE_LIMIT_RETRIES - _rate_limit_retries_remaining
                )
                delay = _rate_limit_retry_delay(attempt)
                model_name = (
                    getattr(self.model, "model", "")
                    or model_config.get_text_model_name()
                )
                logger.warning(
                    "Model request rate-limited [model=%s], retrying in %gs "
                    "(attempt %d/%d): %s",
                    model_name,
                    delay,
                    attempt + 1,
                    MAX_RATE_LIMIT_RETRIES,
                    exc_text,
                )
                if on_rate_limit_retry is not None:
                    await on_rate_limit_retry(
                        RateLimitRetryNotice(
                            attempt=attempt + 1,
                            max_attempts=MAX_RATE_LIMIT_RETRIES,
                            delay_seconds=delay,
                        ),
                    )
                await asyncio.sleep(delay)
                return await self.complete(
                    messages=messages,
                    tools=tools,
                    on_text_delta=on_text_delta,
                    on_thinking_delta=on_thinking_delta,
                    on_tool_call_delta=on_tool_call_delta,
                    on_rate_limit_retry=on_rate_limit_retry,
                    _empty_retries_remaining=_empty_retries_remaining,
                    _rate_limit_retries_remaining=(
                        _rate_limit_retries_remaining - 1
                    ),
                    _transient_retries_remaining=(
                        _transient_retries_remaining
                    ),
                    _markup_retries_remaining=_markup_retries_remaining,
                    _context_retries_remaining=_context_retries_remaining,
                    _context_budget_bytes=_context_budget_bytes,
                    _demotion_notes=_demotion_notes,
                )
            if is_rate_limit:
                model_name = (
                    getattr(self.model, "model", "")
                    or model_config.get_text_model_name()
                )
                logger.error(
                    "Model request still rate-limited after %d retries "
                    "[model=%s]: %s",
                    MAX_RATE_LIMIT_RETRIES,
                    model_name,
                    exc_text,
                )
                raise RateLimitExhaustedError(
                    f"Creator model still rate-limited after "
                    f"{MAX_RATE_LIMIT_RETRIES} retries: {exc_text}",
                    retries=MAX_RATE_LIMIT_RETRIES,
                ) from exc
            status = _provider_http_status(exc)
            is_transient = is_transient_error_message(exc_text) or any(
                marker in exc_text.casefold()
                for marker in (
                    "readerror",
                    "writeerror",
                    "connecterror",
                    "remoteprotocolerror",
                    "download multimodal file timed out",
                )
            )
            if status is not None:
                # Invalid input/auth errors cannot become retryable merely
                # because their response body mentions throttling/timeouts.
                is_transient = status == 408 or status >= 500
            if is_transient and _transient_retries_remaining > 0:
                attempt = (
                    MAX_TRANSIENT_MODEL_RETRIES - _transient_retries_remaining
                )
                delay = min(2**attempt, 8)
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
                if on_rate_limit_retry is not None:
                    await on_rate_limit_retry(
                        RateLimitRetryNotice(
                            attempt=attempt + 1,
                            max_attempts=MAX_TRANSIENT_MODEL_RETRIES,
                            delay_seconds=delay,
                            reason="transient",
                        ),
                    )
                await asyncio.sleep(delay)
                return await self.complete(
                    messages=messages,
                    tools=tools,
                    on_text_delta=on_text_delta,
                    on_thinking_delta=on_thinking_delta,
                    on_tool_call_delta=on_tool_call_delta,
                    on_rate_limit_retry=on_rate_limit_retry,
                    _empty_retries_remaining=_empty_retries_remaining,
                    _rate_limit_retries_remaining=_rate_limit_retries_remaining,
                    _transient_retries_remaining=(
                        _transient_retries_remaining - 1
                    ),
                    _markup_retries_remaining=_markup_retries_remaining,
                    _context_retries_remaining=_context_retries_remaining,
                    _context_budget_bytes=_context_budget_bytes,
                    _demotion_notes=_demotion_notes,
                )
            logger.error(
                "Model request failed with unexpected error: %s: %s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            raise AgentModelError(
                "\n".join(
                    (
                        f"Creator AgentScope model request failed: {exc}",
                        *_demotion_notes,
                    ),
                ),
            ) from exc

        finish_reason = str(
            getattr(
                getattr(response, "finished_reason", None),
                "value",
                getattr(response, "finished_reason", "completed"),
            ),
        )
        if finish_reason == "interrupted":
            # AgentScope catches CancelledError and returns its accumulated
            # stream. Restore cancellation so wait_for still enforces the
            # driver's deadline, and never repair/execute partial calls.
            current_task = asyncio.current_task()
            if current_task is not None and current_task.cancelling():
                raise asyncio.CancelledError
            raise AgentModelError(
                "Creator model response was interrupted; "
                "no tool calls from this response were executed. Retry "
                "with a smaller, complete project change.",
            )

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
                # Preserve an unknown native call as a normal tool call. The
                # execution layer returns a failed ToolResultBlock naming the
                # offered tools, which lets the model correct itself on the
                # next turn instead of aborting the complete Agent run here.
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
                if on_rate_limit_retry is not None:
                    await on_rate_limit_retry(
                        RateLimitRetryNotice(
                            attempt=5 - _markup_retries_remaining,
                            max_attempts=4,
                            delay_seconds=0,
                            reason="invalid_response",
                        ),
                    )
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
                    on_rate_limit_retry=on_rate_limit_retry,
                    _empty_retries_remaining=_empty_retries_remaining,
                    _rate_limit_retries_remaining=(
                        _rate_limit_retries_remaining
                    ),
                    _transient_retries_remaining=(
                        _transient_retries_remaining
                    ),
                    _markup_retries_remaining=_markup_retries_remaining - 1,
                    _context_retries_remaining=_context_retries_remaining,
                    _context_budget_bytes=_context_budget_bytes,
                    _demotion_notes=_demotion_notes,
                )
            raise AgentModelError(
                "Creator Agent returned textual tool-call markup instead of an "
                "AgentScope ToolCallBlock",
            ) from exc
        if not text and not calls:
            if _empty_retries_remaining > 0:
                if on_rate_limit_retry is not None:
                    await on_rate_limit_retry(
                        RateLimitRetryNotice(
                            attempt=3 - _empty_retries_remaining,
                            max_attempts=2,
                            delay_seconds=0,
                            reason="empty_response",
                        ),
                    )
                return await self.complete(
                    messages=messages,
                    tools=tools,
                    on_text_delta=on_text_delta,
                    on_thinking_delta=on_thinking_delta,
                    on_tool_call_delta=on_tool_call_delta,
                    on_rate_limit_retry=on_rate_limit_retry,
                    _empty_retries_remaining=_empty_retries_remaining - 1,
                    _rate_limit_retries_remaining=(
                        _rate_limit_retries_remaining
                    ),
                    _transient_retries_remaining=(
                        _transient_retries_remaining
                    ),
                    _markup_retries_remaining=_markup_retries_remaining,
                    _context_retries_remaining=_context_retries_remaining,
                    _context_budget_bytes=_context_budget_bytes,
                    _demotion_notes=_demotion_notes,
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
            finish_reason=finish_reason,
            usage=_usage_payload(getattr(response, "usage", None)),
            sent_messages=list(messages),
        )


class AgentScopeVlmChatClient(AgentScopeAgentChatClient):
    """Native multimodal client used for Source Intelligence turns.

    Supports DashScope (OpenAI-compatible), Anthropic/MiniMax, and
    Google Gemini protocols.  The protocol is read from the persisted
    ``vlm`` section of ``model_config.json`` via
    ``model_config.get_vlm_protocol()``.
    """

    def _budget_model_name(self) -> str:
        """Bind the token budget to the VLM catalog entry, not the text one.

        ``_configured_model`` picks up ``get_vlm_model_name()`` at request
        time; the budget has to read the same name or a wide-window VLM
        pays for a narrow text model (real case: 12 4K PNGs at 142k tokens
        against qwen-plus' 126,976 while qwen3.7-plus offers 1,000,000).
        """
        return (model_config.get_vlm_model_name() or "qwen3.7-plus").strip()

    def _configured_model(self) -> ChatModelBase:
        if self._injected:
            assert self.model is not None
            return self.model
        api_key = model_config.get_vlm_api_key().strip()
        base_url = model_config.get_vlm_base_url().strip()
        model_name = (
            model_config.get_vlm_model_name() or "qwen3.7-plus"
        ).strip()
        protocol = model_config.get_vlm_protocol().strip()
        timeout_seconds = model_config.get_vlm_timeout_seconds()
        # Anthropic and Gemini gateways always authenticate; OpenAI-compatible
        # gateways may serve free keyless models (e.g. OpenCode Zen), where
        # the openai client with an empty key simply omits the Authorization
        # header.
        required_fields: tuple[tuple[str, str], ...] = (
            ("base_url", base_url),
            ("model", model_name),
        )
        if model_config.protocol_requires_api_key(protocol):
            required_fields = (("api_key", api_key),) + required_fields
        missing = [name for name, value in required_fields if not value]
        if missing:
            raise AgentModelConfigurationError(
                "Creator VLM configuration is incomplete: "
                + ", ".join(missing)
                + f" (protocol='{protocol}', "
                + f"base_url='{base_url or '<empty>'}', "
                + f"model='{model_name or '<empty>'}', "
                + "api_key="
                + ("'<set>'" if api_key else "'<empty>'")
                + "). Open the Creator model config dialog (or set the "
                + "creator VLM fields) and retry. Protocols "
                + "'Anthropic'/'Gemini' always require an api_key; "
                + "OpenAI-compatible gateways may run keyless free models.",
            )
        configuration = (api_key, base_url, model_name, protocol)
        if self.model is None or self._configuration != configuration:
            if model_config.is_anthropic_protocol(protocol):
                from agentscope.model import AnthropicChatModel

                parameters = AnthropicChatModel.Parameters(
                    temperature=self.temperature,
                )
                self.model = _build_chat_model(
                    api_key=api_key,
                    base_url=base_url,
                    model_name=model_name,
                    protocol=protocol,
                    parameters=parameters,
                    client_kwargs={"timeout": timeout_seconds},
                )
            elif model_config.is_gemini_protocol(protocol):
                from agentscope.model import GeminiChatModel

                parameters = GeminiChatModel.Parameters(
                    temperature=self.temperature,
                )
                self.model = _build_chat_model(
                    api_key=api_key,
                    base_url=base_url,
                    model_name=model_name,
                    protocol=protocol,
                    parameters=parameters,
                    client_kwargs={"timeout": timeout_seconds},
                )
            else:
                parameters = DashScopeChatModel.Parameters(
                    temperature=self.temperature,
                    thinking_enable=True,
                    parallel_tool_calls=False,
                )
                self.model = _build_chat_model(
                    api_key=api_key,
                    base_url=base_url,
                    model_name=model_name,
                    protocol=protocol,
                    parameters=parameters,
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
    "AgentRateLimitRetryCallback",
    "AgentStreamCallbackError",
    "AgentStreamCallbackPassthrough",
    "AgentModelTurn",
    "AgentScopeAgentChatClient",
    "AgentScopeVlmChatClient",
    "AgentToolCall",
    "CallbackAgentChatClient",
    "MAX_RATE_LIMIT_RETRIES",
    "RateLimitExhaustedError",
    "RateLimitRetryNotice",
    "records_to_agentscope_messages",
]
