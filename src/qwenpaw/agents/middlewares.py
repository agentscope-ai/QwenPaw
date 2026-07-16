# -*- coding: utf-8 -*-
"""Native AgentScope 2.0 middleware implementations for QwenPaw.

Most per-request setup (ContextVars,
bootstrap injection, skill env overrides, file/media processing) is
handled by lifecycle hooks.

Middlewares in this module wrap the agent's inner reasoning loop via
agentscope's ``MiddlewareBase`` hooks.

Currently provided:

* :class:`ToolResultPruningMiddleware` — truncation of current and historical
  tool-call outputs so oversized results don't exhaust the context budget.
"""

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any, AsyncGenerator, Callable, Set

from agentscope.middleware import MiddlewareBase
from agentscope.message import Msg, TextBlock, ToolResultState
from agentscope.tool import ToolResponse
from json_repair import repair_json
import jsonschema

from .tools.utils import (
    DEFAULT_MAX_BYTES,
    ToolResultPruner,
)
from ..constant import (
    EXTERNAL_USER_QUERY_MESSAGE_TAG,
    QWENPAW_MESSAGE_TAG_KEY,
)

if TYPE_CHECKING:
    from agentscope.agent import Agent

logger = logging.getLogger(__name__)
MAX_AUTO_MEMORY_TURN_MARKERS = 1000
_AUTOMATION_MEMORY_SKIP_SOURCES = frozenset({"cron", "heartbeat"})

_EXECUTABLE_ARGUMENT_KEYS = frozenset(
    {"command", "script", "code", "content", "patch", "sql"},
)
_SHELL_ARGUMENT_KEYS = frozenset({"command", "shell_command"})
_HEREDOC_START_RE = re.compile(
    r"<<-?\s*(?P<quote>['\"]?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)(?P=quote)",
)


def _contains_executable_argument(value: Any) -> bool:
    """Return whether repaired arguments contain executable/large payloads."""
    if isinstance(value, dict):
        return any(
            str(key).lower() in _EXECUTABLE_ARGUMENT_KEYS
            or _contains_executable_argument(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_executable_argument(item) for item in value)
    return False


def _incomplete_heredoc(  # pylint: disable=too-many-return-statements
    value: Any,
    inspect_string: bool = False,
) -> str | None:
    """Return a missing heredoc terminator found in nested arguments."""
    if isinstance(value, dict):
        for key, item in value.items():
            missing = _incomplete_heredoc(
                item,
                str(key).lower() in _SHELL_ARGUMENT_KEYS,
            )
            if missing:
                return missing
        return None
    if isinstance(value, list):
        for item in value:
            missing = _incomplete_heredoc(item, inspect_string)
            if missing:
                return missing
        return None
    if not inspect_string or not isinstance(value, str):
        return None
    for match in _HEREDOC_START_RE.finditer(value):
        tag = match.group("tag")
        remaining_lines = value[match.end() :].splitlines()
        if not any(line.strip() == tag for line in remaining_lines):
            return tag
    return None


def _repair_tool_call_input(
    raw: str,
    schema: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Parse and safely repair tool input, returning an error when unsafe."""
    decode_error: json.JSONDecodeError | None = None
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return None, "tool arguments must decode to a JSON object"
    except json.JSONDecodeError as exc:
        decode_error = exc

        try:
            parsed = repair_json(
                raw,
                return_objects=True,
                stream_stable=True,
                schema=schema,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            parsed = None
        if not isinstance(parsed, dict):
            return None, (
                f"{decode_error.msg} at character {decode_error.pos}; "
                "automatic repair did not produce a JSON object"
            )

    # json_repair deliberately closes unterminated strings.  For commands,
    # source code and file bodies that can turn a truncated stream into a
    # different, executable payload.  Keep repair for ordinary syntax errors,
    # but reject this one ambiguity instead of executing partial content.
    if (
        decode_error is not None
        and "unterminated string" in decode_error.msg.lower()
        and _contains_executable_argument(parsed)
    ):
        return None, (
            f"{decode_error.msg} at character {decode_error.pos}; "
            "an executable or file-content argument may be truncated"
        )

    missing_tag = _incomplete_heredoc(parsed)
    if missing_tag:
        return None, (
            "repaired command contains an unterminated heredoc "
            f"({missing_tag})"
        )
    return parsed, ""


class ToolCallInputRepairMiddleware(MiddlewareBase):
    """Repair model tool JSON before execution and persist canonical input."""

    async def on_acting(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        tool_call = input_kwargs.get("tool_call")
        raw = getattr(tool_call, "input", None)
        if not isinstance(raw, str):
            async for event in next_handler(**input_kwargs):
                yield event
            return

        schema = None
        toolkit = getattr(agent, "toolkit", None)
        if toolkit is not None:
            activated_groups = getattr(
                getattr(getattr(agent, "state", None), "tool_context", None),
                "activated_groups",
                None,
            )
            tool = await toolkit.check_tool_available(
                getattr(tool_call, "name", ""),
                activated_groups,
            )
            schema = tool.input_schema

        parsed, error = _repair_tool_call_input(raw, schema)
        if parsed is not None and schema:
            try:
                jsonschema.validate(parsed, schema)
            except jsonschema.ValidationError as exc:
                parsed = None
                error = (
                    "repaired arguments failed schema validation: "
                    f"{exc.message}"
                )
        if parsed is None:
            tool_name = str(getattr(tool_call, "name", "unknown"))
            # Keep the rejected call/result pair valid for history formatters.
            tool_call.input = "{}"
            logger.warning(
                "Rejected unsafe repaired tool input: tool=%r id=%r "
                "input_length=%d reason=%s",
                tool_name,
                getattr(tool_call, "id", None),
                len(raw),
                error,
            )
            yield ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Tool call `{tool_name}` was not executed: "
                            f"{error}. Retry with complete JSON arguments; "
                            "split large payloads into smaller calls."
                        ),
                    ),
                ],
                state=ToolResultState.ERROR,
                metadata={"tool_input_validation": "rejected"},
            )
            return

        canonical = json.dumps(parsed, ensure_ascii=False)
        if canonical != raw:
            logger.info(
                "Repaired tool-call JSON before execution: tool=%r id=%r "
                "input_length=%d repaired_length=%d",
                getattr(tool_call, "name", None),
                getattr(tool_call, "id", None),
                len(raw),
                len(canonical),
            )
            tool_call.input = canonical

        async for event in next_handler(**input_kwargs):
            yield event


class MemoryMiddleware(MiddlewareBase):
    """Attach long-term memory behavior to AgentScope 2.0 agents.

    The middleware owns lifecycle-level memory behavior only:

    * system prompt guidance injection
    * temporary auto-memory-search context injection for model calls
    * post-reply auto-memory scheduling

    Tool registration remains part of toolkit construction.
    """

    def __init__(self, *, memory_manager: Any) -> None:
        self._memory_manager = memory_manager

    async def on_system_prompt(
        self,
        # pylint: disable=unused-argument
        agent: "Agent",
        current_prompt: str,
    ) -> str:
        prompt = self._memory_manager.get_memory_prompt()
        if not prompt or prompt in current_prompt:
            return current_prompt
        if current_prompt.strip():
            return f"{current_prompt.rstrip()}\n\n{prompt.strip()}"
        return prompt.strip()

    async def on_model_call(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., Any],
    ) -> Any:
        if self._is_automation_request(agent):
            return await next_handler(**input_kwargs)

        query_msg = self._latest_external_user_query(agent.state.context)
        turn_marker = query_msg.id if query_msg is not None else ""
        turn_state = self._auto_memory_turn_state(agent)
        if turn_marker and turn_marker != turn_state.get("searched_turn"):
            turn_state["searched_turn"] = turn_marker
            try:
                result = await self._memory_manager.auto_memory_search(
                    query_msg,
                    agent_name=agent.name,
                    session_id=agent.state.session_id,
                    user_turn_id=turn_marker,
                )
            except Exception:
                logger.exception(
                    "MemoryMiddleware auto_memory_search failed",
                )
            else:
                messages = list(input_kwargs.get("messages") or [])
                memory_msgs = self._extract_memory_messages(
                    result,
                    context_len=len(agent.state.context),
                )
                if memory_msgs:
                    messages.extend(memory_msgs)
                    input_kwargs["messages"] = messages
                    agent.state.context.extend(memory_msgs)
        return await next_handler(**input_kwargs)

    # pylint: disable=stop-iteration-return
    async def on_reply(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        async for item in next_handler(**input_kwargs):
            yield item

        if self._is_automation_request(agent):
            return

        turn_state = self._auto_memory_turn_state(agent)
        pending_markers = turn_state["pending"]
        seen_markers = turn_state["seen"]
        turn_marker = self._latest_user_turn_marker(agent.state.context)
        if not turn_marker or turn_marker in seen_markers:
            return

        seen_markers[turn_marker] = None
        if len(seen_markers) > MAX_AUTO_MEMORY_TURN_MARKERS:
            oldest_key = next(iter(seen_markers))
            seen_markers.pop(oldest_key)
        pending_markers.append(turn_marker)

        interval = self._auto_memory_interval()
        if interval <= 0:
            pending_markers.clear()
            return
        if len(pending_markers) < interval:
            return

        await self._flush_auto_memory(
            agent,
            count=interval,
        )

    async def on_compress_context(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., Any],
    ) -> None:
        if self._is_automation_request(agent):
            await next_handler(**input_kwargs)
            return

        cfg = self._memory_config()
        pending_markers = self._auto_memory_turn_state(agent)["pending"]
        if (
            getattr(cfg, "summarize_when_compact", False)
            and pending_markers
            and await self._will_compress_context(agent, input_kwargs)
        ):
            await self._flush_auto_memory(agent)

        await next_handler(**input_kwargs)

    async def _flush_auto_memory(
        self,
        agent: "Agent",
        *,
        count: int | None = None,
    ) -> None:
        if self._is_automation_request(agent):
            logger.debug(
                "MemoryMiddleware auto_memory skipped for automation source: "
                "agent=%s",
                agent.name,
            )
            # Defensive: clear in case on_reply guard was bypassed
            self._auto_memory_turn_state(agent)["pending"].clear()
            return

        pending_markers = self._auto_memory_turn_state(agent)["pending"]
        if not pending_markers:
            return

        if count is None:
            turn_markers = list(pending_markers)
            pending_markers.clear()
        else:
            turn_markers = pending_markers[:count]
            del pending_markers[:count]

        messages = self._messages_for_user_turns(
            list(agent.state.context),
            turn_markers=turn_markers,
        )
        if not messages:
            return

        try:
            await self._memory_manager.auto_memory(
                messages,
                session_id=self._agent_session_id(agent),
            )
        except Exception:
            logger.exception("MemoryMiddleware auto_memory failed")

    @staticmethod
    def _agent_session_id(agent: "Agent") -> str:
        session_id = str(getattr(agent.state, "session_id", "") or "")
        if session_id:
            return session_id
        request_context = getattr(agent, "_request_context", None) or {}
        if isinstance(request_context, dict):
            return str(request_context.get("session_id") or "")
        return ""

    @staticmethod
    def _is_automation_request(agent: "Agent") -> bool:
        """Return True when the request originates from non-user automation."""
        request_context = getattr(agent, "_request_context", None) or {}
        if not isinstance(request_context, dict):
            return False
        source = str(request_context.get("source") or "").strip().lower()
        return source in _AUTOMATION_MEMORY_SKIP_SOURCES

    @staticmethod
    async def _will_compress_context(
        agent: "Agent",
        input_kwargs: dict[str, Any],
    ) -> bool:
        cfg = input_kwargs.get("context_config") or agent.context_config
        # pylint: disable=protected-access
        kwargs = await agent._prepare_model_input()
        estimated_tokens = await agent.model.count_tokens(**kwargs)
        threshold = cfg.trigger_ratio * agent.model.context_size
        return estimated_tokens >= threshold

    @staticmethod
    def _extract_memory_messages(
        result: Any,
        *,
        context_len: int,
    ) -> list["Msg"]:
        if not isinstance(result, dict):
            return []
        msgs = result.get("msg") or result.get("messages")
        if not isinstance(msgs, list):
            return []

        injected = msgs[context_len:] if len(msgs) > context_len else msgs
        return [
            msg
            for msg in injected
            if hasattr(msg, "has_content_blocks")
            and (
                msg.has_content_blocks("tool_call")
                or msg.has_content_blocks("tool_result")
            )
        ]

    def _auto_memory_interval(self) -> int:
        return int(self._memory_manager.get_auto_memory_interval())

    def _memory_config(self) -> Any:
        return self._memory_manager.get_memory_config()

    def _auto_memory_turn_state(self, agent: "Agent") -> dict[str, Any]:
        return self._memory_manager.get_auto_memory_turn_state(
            self._agent_session_id(agent),
        )

    @staticmethod
    def _message_tag(msg: "Msg") -> str:
        metadata = getattr(msg, "metadata", None)
        if not isinstance(metadata, dict):
            return ""
        return str(metadata.get(QWENPAW_MESSAGE_TAG_KEY) or "")

    @classmethod
    def _is_external_user_query(cls, msg: "Msg") -> bool:
        return (
            msg.role == "user"
            and cls._message_tag(msg) == EXTERNAL_USER_QUERY_MESSAGE_TAG
        )

    @classmethod
    def _latest_external_user_query(
        cls,
        messages: list["Msg"],
    ) -> "Msg | None":
        for msg in reversed(messages):
            if cls._is_external_user_query(msg):
                return msg
        return None

    @classmethod
    def _latest_user_turn_marker(cls, messages: list["Msg"]) -> str:
        for idx in range(len(messages) - 1, -1, -1):
            msg = messages[idx]
            if not cls._is_external_user_query(msg):
                continue
            return msg.id
        return ""

    @classmethod
    def _messages_for_user_turns(
        cls,
        messages: list["Msg"],
        *,
        turn_markers: list[str],
    ) -> list["Msg"]:
        targets = set(turn_markers)
        if not targets:
            return []

        first_idx: int | None = None
        last_idx: int | None = None
        for idx, msg in enumerate(messages):
            if cls._is_external_user_query(msg) and msg.id in targets:
                if first_idx is None:
                    first_idx = idx
                last_idx = idx

        if first_idx is None or last_idx is None:
            return []

        end_idx = len(messages)
        for idx in range(last_idx + 1, len(messages)):
            if cls._is_external_user_query(messages[idx]):
                end_idx = idx
                break

        return [
            msg
            for msg in messages[first_idx:end_idx]
            if msg.role != "user" or cls._is_external_user_query(msg)
        ]


class ToolResultPruningMiddleware(MiddlewareBase):
    """Truncate oversized tool-call results around each acting step.

    Implements the ``on_acting`` hook: each ``ToolResponse`` is capped before
    it is yielded into the agent context, then every historical ``tool_result``
    block in the agent's context is scanned and pruned according to tiered byte
    thresholds.

    * **Recent** tool results (the last ``recent_n`` tool-bearing messages)
      are capped at ``recent_max_bytes``.
    * **Older** tool results are shrunk to ``old_max_bytes``.
    * Tools whose name appears in ``exempt_tool_names``, or whose
      ``read_file`` input references an extension in
      ``exempt_file_extensions``, always use the larger
      ``recent_max_bytes`` limit.

    Full tool outputs are saved to ``{tool_results_dir}/{uuid}.txt``
    before truncation so they remain recoverable.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        recent_n: int = 2,
        old_max_bytes: int = 3000,
        recent_max_bytes: int = DEFAULT_MAX_BYTES,
        exempt_file_extensions: set[str] | None = None,
        exempt_tool_names: set[str] | None = None,
        tool_results_dir: str = "",
        agent_id: str = "default",
    ) -> None:
        self._enabled = enabled
        self._recent_n = recent_n
        self._old_max_bytes = old_max_bytes
        self._recent_max_bytes = recent_max_bytes
        self._exempt_extensions = exempt_file_extensions or set()
        self._exempt_tools = exempt_tool_names or set()
        self._pruner = ToolResultPruner(tool_results_dir)
        self._agent_id = agent_id

    async def on_acting(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],  # pylint: disable=unused-argument
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        events: list[Any] = []
        async for event in next_handler():
            if isinstance(event, ToolResponse):
                event = await self.prune_tool_response_async(event)
            events.append(event)
            yield event

        if not self._enabled or not events:
            return

        try:
            messages = list(agent.state.context)
            await asyncio.to_thread(self._prune_tool_results, messages)
        except Exception:
            logger.exception("ToolResultPruningMiddleware failed")

    # ------------------------------------------------------------------
    # Core pruning logic (ported from LightContextManager)
    # ------------------------------------------------------------------

    def prune_tool_response(
        self,
        response: ToolResponse,
    ) -> ToolResponse:
        """Cap the current ToolResponse before it enters agent context."""
        if not self._enabled:
            return response

        # Current responses are pruned per text block, not by aggregate
        # ToolResponse byte size. Multi-block truncation metadata is kept by
        # content index so one block cannot influence another block's retry
        # location or cached file path.
        self._pruner.prune_output(
            response.content or [],
            max_bytes=self._recent_max_bytes,
            metadata=response.metadata,
        )

        return response

    async def prune_tool_response_async(
        self,
        response: ToolResponse,
    ) -> ToolResponse:
        """Prune a response without blocking the asyncio event loop."""
        return await asyncio.to_thread(self.prune_tool_response, response)

    def _prune_tool_results(self, messages: list["Msg"]) -> None:
        if not messages:
            return

        recent_count = 0
        for msg in reversed(messages):
            if not isinstance(msg.content, list) or not any(
                self._block_type(b) == "tool_result" for b in msg.content
            ):
                break
            recent_count += 1
        split_index = max(
            0,
            len(messages) - max(recent_count, self._recent_n),
        )

        exempt_tool_ids = self._detect_exempt_tool_ids(messages)

        for idx, msg in enumerate(messages):
            if not isinstance(msg.content, list):
                continue
            is_recent = idx >= split_index
            max_bytes = (
                self._recent_max_bytes if is_recent else self._old_max_bytes
            )

            for block in msg.content:
                if self._block_type(block) != "tool_result":
                    continue

                tool_id = (
                    block.get("id", "")
                    if isinstance(block, dict)
                    else getattr(block, "id", "")
                )
                output = (
                    block.get("output")
                    if isinstance(block, dict)
                    else getattr(block, "output", None)
                )
                if not output:
                    continue

                effective_max = (
                    self._recent_max_bytes
                    if tool_id in exempt_tool_ids
                    else max_bytes
                )
                block_metadata = (
                    block.setdefault("metadata", {})
                    if isinstance(block, dict)
                    else block.metadata
                )
                pruned, _ = self._pruner.prune_output(
                    output,
                    max_bytes=effective_max,
                    metadata=block_metadata,
                )
                if isinstance(block, dict):
                    block["output"] = pruned
                else:
                    block.output = pruned

    def _detect_exempt_tool_ids(self, messages: list["Msg"]) -> Set[str]:
        exempt_ids: Set[str] = set()
        for msg in messages:
            if not isinstance(msg.content, list):
                continue
            for block in msg.content:
                if self._block_type(block) not in ("tool_use", "tool_call"):
                    continue

                tool_id = (
                    block.get("id", "")
                    if isinstance(block, dict)
                    else getattr(block, "id", "")
                )
                if not tool_id:
                    continue

                tool_name = (
                    (
                        block.get("name", "")
                        if isinstance(block, dict)
                        else getattr(block, "name", "")
                    )
                    or ""
                ).lower()
                raw_input = (
                    block.get("raw_input")
                    if isinstance(block, dict)
                    else getattr(block, "raw_input", None)
                ) or ""
                if isinstance(raw_input, dict):
                    raw_input = str(raw_input)
                raw_input = raw_input.lower()

                if tool_name in self._exempt_tools:
                    exempt_ids.add(tool_id)
                    continue

                if tool_name == "read_file":
                    for ext in self._exempt_extensions:
                        if ext in raw_input:
                            exempt_ids.add(tool_id)
                            break

        return exempt_ids

    @staticmethod
    def _block_type(block: Any) -> str | None:
        if isinstance(block, dict):
            return block.get("type")
        return getattr(block, "type", None)


class LangfuseToolSpanMiddleware(MiddlewareBase):
    """Record each tool execution as a Langfuse tool observation.

    Yields ``None`` from ``tool_span`` when Langfuse is disabled or the
    client is unavailable; the ``observation is not None`` guard handles
    this gracefully.
    """

    async def on_acting(
        self,
        agent: "Agent",  # pylint: disable=unused-argument
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        from ..observability.langfuse import get_current_trace, tool_span

        if get_current_trace() is None:
            async for event in next_handler():
                yield event
            return

        tool_call = input_kwargs.get("tool_call")
        tool_name = getattr(tool_call, "name", "unknown")
        tool_input = getattr(tool_call, "input", None)

        async with tool_span(
            name=tool_name,
            input=tool_input,
            metadata={"tool_call_id": getattr(tool_call, "id", None)},
        ) as observation:
            final_response = None
            async for event in next_handler():
                if isinstance(event, ToolResponse):
                    final_response = event
                yield event
            if observation is not None and final_response is not None:
                observation.update(
                    output={
                        "content": [
                            getattr(b, "text", str(b))
                            for b in (final_response.content or [])
                        ],
                    },
                )
