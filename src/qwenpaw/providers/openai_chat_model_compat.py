# -*- coding: utf-8 -*-
"""OpenAI chat model compatibility wrappers."""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any, AsyncGenerator

from agentscope.model import OpenAIChatModel
from agentscope.model._model_response import ChatResponse

from qwenpaw.local_models.tag_parser import (
    parse_tool_calls_from_text,
    text_contains_tool_call_tag,
)


def _battr(block: Any, key: str, default: Any = None) -> Any:
    """Read an attribute from a dict *or* Pydantic block."""
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _bset(block: Any, key: str, value: Any) -> None:
    """Set an attribute on a dict *or* Pydantic block."""
    if isinstance(block, dict):
        block[key] = value
    else:
        setattr(block, key, value)


def _clone_with_overrides(obj: Any, **overrides: Any) -> Any:
    """Clone a stream object into a mutable namespace with overrides."""
    data = dict(getattr(obj, "__dict__", {}))
    data.update(overrides)
    return SimpleNamespace(**data)


def _sanitize_tool_call(tool_call: Any) -> Any | None:
    """Normalize a tool call for parser safety, or drop it if unusable."""
    if not hasattr(tool_call, "index"):
        return None

    function = getattr(tool_call, "function", None)
    if function is None:
        return None

    has_name = hasattr(function, "name")
    has_arguments = hasattr(function, "arguments")

    raw_name = getattr(function, "name", "")
    if isinstance(raw_name, str):
        safe_name = raw_name
    elif raw_name is None:
        safe_name = ""
    else:
        safe_name = str(raw_name)

    raw_arguments = getattr(function, "arguments", "")
    if isinstance(raw_arguments, str):
        safe_arguments = raw_arguments
    elif raw_arguments is None:
        safe_arguments = ""
    else:
        try:
            safe_arguments = json.dumps(raw_arguments, ensure_ascii=False)
        except (TypeError, ValueError):
            safe_arguments = str(raw_arguments)

    if (
        has_name
        and has_arguments
        and isinstance(raw_name, str)
        and isinstance(
            raw_arguments,
            str,
        )
    ):
        return tool_call

    safe_function = SimpleNamespace(
        name=safe_name,
        arguments=safe_arguments,
    )
    return _clone_with_overrides(tool_call, function=safe_function)


def _sanitize_chunk(chunk: Any) -> Any:
    """Drop/normalize malformed tool-calls in a streaming chunk."""
    choices = getattr(chunk, "choices", None)
    if not choices:
        return chunk

    sanitized_choices: list[Any] = []
    changed = False

    for choice in choices:
        delta = getattr(choice, "delta", None)
        if delta is None:
            sanitized_choices.append(choice)
            continue

        raw_tool_calls = getattr(delta, "tool_calls", None)
        if not raw_tool_calls:
            sanitized_choices.append(choice)
            continue

        choice_changed = False
        sanitized_tool_calls: list[Any] = []
        for tool_call in raw_tool_calls:
            sanitized = _sanitize_tool_call(tool_call)
            if sanitized is not tool_call:
                choice_changed = True
            if sanitized is not None:
                sanitized_tool_calls.append(sanitized)

        if choice_changed:
            changed = True
            sanitized_delta = _clone_with_overrides(
                delta,
                tool_calls=sanitized_tool_calls,
            )
            sanitized_choice = _clone_with_overrides(
                choice,
                delta=sanitized_delta,
            )
            sanitized_choices.append(sanitized_choice)
            continue

        sanitized_choices.append(choice)

    if not changed:
        return chunk
    return _clone_with_overrides(chunk, choices=sanitized_choices)


def _sanitize_stream_item(item: Any) -> Any:
    """Sanitize either plain stream chunks or structured stream items."""
    if hasattr(item, "chunk"):
        chunk = item.chunk
        sanitized_chunk = _sanitize_chunk(chunk)
        if sanitized_chunk is chunk:
            return item
        return _clone_with_overrides(item, chunk=sanitized_chunk)

    return _sanitize_chunk(item)


class _SanitizedStream:
    """Proxy OpenAI async stream that sanitizes each emitted item and
    captures ``extra_content`` from tool-call chunks (used by Gemini
    thinking models to carry ``thought_signature``)."""

    def __init__(self, stream: Any):
        self._stream = stream
        self._ctx_stream: Any | None = None
        self.extra_contents: dict[str, Any] = {}

    async def __aenter__(self) -> "_SanitizedStream":
        self._ctx_stream = await self._stream.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc: Any,
        tb: Any,
    ) -> bool | None:
        return await self._stream.__aexit__(exc_type, exc, tb)

    def __aiter__(self) -> "_SanitizedStream":
        return self

    async def __anext__(self) -> Any:
        if self._ctx_stream is None:
            raise StopAsyncIteration
        item = await self._ctx_stream.__anext__()
        self._capture_extra_content(item)
        return _sanitize_stream_item(item)

    def _capture_extra_content(self, item: Any) -> None:
        """Store ``extra_content`` keyed by tool-call id."""
        chunk = getattr(item, "chunk", item)
        choices = getattr(chunk, "choices", None) or []
        for choice in choices:
            delta = getattr(choice, "delta", None)
            if not delta:
                continue
            for tc in getattr(delta, "tool_calls", None) or []:
                tc_id = getattr(tc, "id", None)
                if not tc_id:
                    continue
                extra = getattr(tc, "extra_content", None)
                if extra is None:
                    model_extra = getattr(tc, "model_extra", None)
                    if isinstance(model_extra, dict):
                        extra = model_extra.get("extra_content")
                if extra:
                    self.extra_contents[tc_id] = extra


# JSON Schema keywords whose value is itself a schema.
_SINGLE_SCHEMA_KEYWORDS = frozenset(
    {
        "items",
        "additionalProperties",
        "additionalItems",
        "unevaluatedProperties",
        "unevaluatedItems",
        "contains",
        "propertyNames",
        "not",
        "if",
        "then",
        "else",
        "contentSchema",
    },
)
# Keywords whose value is an array of schemas.
_ARRAY_SCHEMA_KEYWORDS = frozenset(
    {"allOf", "anyOf", "oneOf", "prefixItems"},
)
# Keywords whose value is an object whose values are schemas.
_MAP_SCHEMA_KEYWORDS = frozenset(
    {
        "properties",
        "patternProperties",
        "$defs",
        "definitions",
        "dependentSchemas",
    },
)


# pylint: disable=too-many-branches
def _sanitize_boolean_schemas(schema: Any) -> Any:
    """Position-aware sanitizer for boolean JSON Schema values.

    JSON Schema uses booleans in two distinct ways:

    1. **Boolean schemas** — at a position where a schema is expected,
       ``true`` means "accept anything" and ``false`` means "reject
       everything".  Legal per spec but rejected by strict LLM providers
       (DeepSeek V4, OpenAI) that require an object schema.  We convert::

           true  → {}
           false → {"not": {}}

    2. **Boolean-valued keywords** — annotations like ``nullable``,
       ``deprecated``, ``readOnly``, ``writeOnly``, ``uniqueItems``,
       draft-04 ``exclusiveMinimum`` / ``exclusiveMaximum``.  These MUST
       remain booleans; providers validate them as ``type: boolean``.

    This walker recurses only into known schema-positions, so boolean
    annotations on ordinary keywords pass through unchanged.

    Special-cases retained:
    - ``additionalProperties: true``  → removed (JSON Schema default;
      explicit form rejected by some strict validators).
    - ``required: <bool>`` inside a property definition → removed
      (malformed; real JSON Schema uses ``required: ["field"]`` on the
      parent object).
    """
    if schema is True:
        return {}
    if schema is False:
        return {"not": {}}
    if not isinstance(schema, dict):
        return schema

    result: dict[str, Any] = {}
    for key, value in schema.items():
        # Strip special-cases intercepted before the keyword dispatch:
        # `additionalProperties: False` / `: <object>` still fall through
        # to the `_SINGLE_SCHEMA_KEYWORDS` branch below.
        if key == "additionalProperties" and value is True:
            continue
        if key == "required" and isinstance(value, bool):
            continue

        if key in _SINGLE_SCHEMA_KEYWORDS:
            if key == "items" and isinstance(value, list):
                # draft-07 tuple form
                result[key] = [_sanitize_boolean_schemas(v) for v in value]
            else:
                result[key] = _sanitize_boolean_schemas(value)
        elif key in _ARRAY_SCHEMA_KEYWORDS:
            if isinstance(value, list):
                result[key] = [_sanitize_boolean_schemas(v) for v in value]
            else:
                result[key] = value
        elif key in _MAP_SCHEMA_KEYWORDS:
            if isinstance(value, dict):
                result[key] = {
                    k: _sanitize_boolean_schemas(v) for k, v in value.items()
                }
            else:
                result[key] = value
        elif key == "dependencies" and isinstance(value, dict):
            # draft-07: value per key may be a schema or a string array.
            result[key] = {
                k: (
                    _sanitize_boolean_schemas(v)
                    if isinstance(v, (dict, bool))
                    else v
                )
                for k, v in value.items()
            }
        else:
            result[key] = value
    return result


def _sanitize_tool_schemas(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Sanitize tool function schemas to be compatible with strict providers.

    Walks the ``parameters`` of each tool's function definition and replaces
    boolean JSON Schema values that providers like DeepSeek V4 reject.
    """
    sanitized = []
    for tool in tools:
        if not isinstance(tool, dict):
            sanitized.append(tool)
            continue
        func = tool.get("function")
        if not isinstance(func, dict):
            sanitized.append(tool)
            continue
        params = func.get("parameters")
        if not isinstance(params, dict):
            sanitized.append(tool)
            continue
        sanitized_params = _sanitize_boolean_schemas(params)
        sanitized.append(
            {**tool, "function": {**func, "parameters": sanitized_params}},
        )
    return sanitized


class OpenAIChatModelCompat(OpenAIChatModel):
    """OpenAIChatModel with robust parsing for malformed tool-call chunks
    and transparent ``extra_content`` (Gemini thought_signature) relay.

    Accepts two extra constructor kwargs that ``OpenAIChatModel`` does not:

    * ``default_headers`` — injected as ``extra_headers`` on every API call
      (used for DashScope tracking headers, etc.).
    * ``extra_generate_kwargs`` — merged into every ``_call_api`` invocation
      (provider-level ``generate_kwargs`` that don't map to ``Parameters``).
    """

    def __init__(
        self,
        *,
        default_headers: dict[str, str] | None = None,
        extra_generate_kwargs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._default_headers = default_headers
        self._extra_generate_kwargs = extra_generate_kwargs or {}
        super().__init__(**kwargs)

    async def _call_api(
        self,
        model_name: str,
        messages: Any,
        tools: list[dict] | None = None,
        tool_choice: Any | None = None,
        **generate_kwargs: Any,
    ) -> Any:
        merged = {**self._extra_generate_kwargs, **generate_kwargs}
        if self._default_headers:
            existing = merged.get("extra_headers") or {}
            merged["extra_headers"] = {**self._default_headers, **existing}
        return await super()._call_api(
            model_name,
            messages,
            tools,
            tool_choice,
            **merged,
        )

    def _format_tools(
        self,
        tools: list[dict] | None,
        tool_choice: Any | None,
    ) -> tuple[list[dict] | None, Any]:
        """Sanitize boolean sub-schemas before forwarding to base.

        Some MCP servers declare parameters using JSON Schema boolean values
        (e.g. ``additionalProperties: true``, ``items: true``) which are valid
        per spec but rejected by strict providers such as DeepSeek V4.
        """
        if tools:
            tools = _sanitize_tool_schemas(tools)
        return super()._format_tools(tools, tool_choice)

    # pylint: disable=too-many-branches, too-many-statements
    async def _parse_stream_response(
        self,
        start_datetime: datetime,
        response: Any,
        audio_format: str = "wav",
    ) -> AsyncGenerator[ChatResponse, None]:
        sanitized_response = _SanitizedStream(response)

        _think_tool_calls: dict[str, dict] = {}
        _text_tool_calls: dict[str, dict] = {}

        async for parsed in super()._parse_stream_response(
            start_datetime=start_datetime,
            response=sanitized_response,
            audio_format=audio_format,
        ):
            # Filter out malformed tool_use blocks (null id or empty name)
            # emitted by some OpenAI-compatible models, to prevent bad entries
            # from being persisted into session history (issue #4185).
            _tool_types = ("tool_use", "tool_call")

            parsed.content = [
                b
                for b in parsed.content
                if not (
                    (
                        b.get("type")
                        if isinstance(b, dict)
                        else getattr(b, "type", None)
                    )
                    in _tool_types
                    and (
                        not isinstance(
                            b.get("id")
                            if isinstance(b, dict)
                            else getattr(b, "id", None),
                            str,
                        )
                        or not (
                            b.get("name")
                            if isinstance(b, dict)
                            else getattr(b, "name", None)
                        )
                    )
                )
            ]

            if sanitized_response.extra_contents:
                for block in parsed.content:
                    btype = (
                        block.get("type")
                        if isinstance(block, dict)
                        else getattr(block, "type", None)
                    )
                    if btype not in _tool_types:
                        continue
                    tool_id = (
                        block.get("id")
                        if isinstance(block, dict)
                        else getattr(block, "id", None)
                    )
                    if not isinstance(tool_id, str):
                        continue
                    ec = sanitized_response.extra_contents.get(tool_id)
                    if ec:
                        if isinstance(block, dict):
                            block["extra_content"] = ec
                        else:
                            block.extra_content = ec

            has_tool_use = any(
                (
                    b.get("type")
                    if isinstance(b, dict)
                    else getattr(b, "type", None)
                )
                in _tool_types
                for b in parsed.content
            )

            if has_tool_use:
                _think_tool_calls.clear()
                _text_tool_calls.clear()
            else:
                # --- 1. Scan thinking blocks ---
                for block in parsed.content:
                    btype = _battr(block, "type")
                    if btype != "thinking":
                        continue
                    thinking_text = _battr(block, "thinking") or ""
                    if not text_contains_tool_call_tag(thinking_text):
                        continue

                    think_parsed = parse_tool_calls_from_text(thinking_text)
                    if not think_parsed.tool_calls:
                        continue

                    _bset(block, "thinking", think_parsed.text_before.strip())

                    _think_tool_calls = {
                        f"thinking_{i}": {
                            "type": "tool_use",
                            "id": f"think_call_{i}",
                            "name": ptc.name,
                            "input": ptc.arguments,
                            "raw_input": ptc.raw_arguments,
                        }
                        for i, ptc in enumerate(think_parsed.tool_calls)
                    }

                # --- 2. Scan text/content blocks ---
                new_content: list | None = None
                for i, block in enumerate(parsed.content):
                    if _battr(block, "type") != "text":
                        continue
                    text = _battr(block, "text") or ""
                    if not text_contains_tool_call_tag(text):
                        continue

                    text_parsed = parse_tool_calls_from_text(text)
                    clean_text = text_parsed.text_before.strip()
                    _bset(block, "text", clean_text)

                    if text_parsed.tool_calls:
                        _text_tool_calls = {
                            f"text_{j}": {
                                "type": "tool_use",
                                "id": f"text_call_{j}",
                                "name": ptc.name,
                                "input": ptc.arguments,
                                "raw_input": ptc.raw_arguments,
                            }
                            for j, ptc in enumerate(text_parsed.tool_calls)
                        }

                    # If the text block is now empty, mark it for removal.
                    if not clean_text:
                        if new_content is None:
                            new_content = list(parsed.content)
                        new_content[i] = None  # type: ignore[index]

                if new_content is not None:
                    parsed.content = [b for b in new_content if b is not None]

                extra = list(_think_tool_calls.values()) + list(
                    _text_tool_calls.values(),
                )
                if extra:
                    parsed.content = list(parsed.content) + extra

            yield parsed
