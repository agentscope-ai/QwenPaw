# -*- coding: utf-8 -*-
"""Parse special tags from model-generated text.

Handles ``<think>...</think>`` (reasoning) and
``<tool_call>...</tool_call>`` (function calling) tags that local models
like Qwen3-Instruct embed in their raw text output.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

THINK_START = "<think>"
THINK_END = "</think>"

TOOL_CALL_START = "<tool_call>"
TOOL_CALL_END = "</tool_call>"

# Regex to find a complete <think>...</think> block (non-greedy).
_THINK_RE = re.compile(
    r"<think>(.*?)</think>",
    re.DOTALL,
)

# Regex to find complete <tool_call>...</tool_call> blocks (non-greedy).
_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>",
    re.DOTALL,
)

# Regex for XML-style tool call format:
#   <function=func_name>
#     <parameter=param_name>value</parameter>
#     ...
#   </function>
_XML_FUNC_RE = re.compile(
    r"<function=([^>]+)>(.*?)</function>",
    re.DOTALL,
)
_XML_PARAM_RE = re.compile(
    r"<parameter=([^>]+)>(.*?)</parameter>",
    re.DOTALL,
)

# Regex for lenient XML-style tool call format (no closing tags):
#   <function=func_name>
#     <parameter=param_name>value
#     <parameter=param_name2>value2
_XML_FUNC_LENIENT_RE = re.compile(
    r"<function=([^>]+)>(.*?)(?=<function=|</function>|\Z)",
    re.DOTALL,
)
# Each parameter value runs from after the tag to the next tag or end.
_XML_PARAM_LENIENT_RE = re.compile(
    r"<parameter=([^>]+)>(.*?)"
    r"(?=<parameter=|</parameter>|<function=|</function>|\Z)",
    re.DOTALL,
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TextWithThinking:
    """Result of extracting ``<think>`` tags from text."""

    # The thinking/reasoning content (between the tags).
    thinking: str = ""
    # The remaining text after removing the ``<think>...</think>`` block.
    remaining_text: str = ""
    # True when ``<think>`` has been opened but ``</think>`` not yet seen
    # (streaming scenario).
    has_open_tag: bool = False


@dataclass
class ParsedToolCall:
    """A single parsed tool call extracted from text."""

    id: str
    name: str
    arguments: dict
    raw_arguments: str


@dataclass
class TextWithToolCalls:
    """Result of parsing text that may contain tool-call tags."""

    # Text content before the first <tool_call> tag.
    text_before: str = ""
    # Text content after the last </tool_call> tag.
    text_after: str = ""
    # Successfully parsed tool calls.
    tool_calls: list[ParsedToolCall] = field(default_factory=list)
    # True when an opening <tool_call> has no matching </tool_call> yet
    # (streaming scenario).
    has_open_tag: bool = False
    # Raw text accumulated after the unclosed <tool_call> tag.
    partial_tool_text: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_call_id() -> str:
    return f"call_{uuid.uuid4().hex[:12]}"


def _extract_params_lenient(body: str) -> dict:
    """Extract parameters from *body* using lenient regex (no closing tags)."""
    arguments: dict = {}
    for param_match in _XML_PARAM_LENIENT_RE.finditer(body):
        param_name = param_match.group(1).strip()
        param_value = param_match.group(2).strip()
        if param_name:
            arguments[param_name] = param_value
    return arguments


# pylint: disable=too-many-return-statements
def _parse_xml_tool_call(raw_text: str) -> ParsedToolCall | None:
    """Parse an XML-style tool call block.

    Tries the strict format first (all closing tags present)::

        <function=func_name>
          <parameter=param1>value1</parameter>
          <parameter=param2>value2</parameter>
        </function>

    Falls back to a lenient format when closing tags are absent::

        <function=func_name>
          <parameter=param1>value1
          <parameter=param2>value2
    """
    func_match = _XML_FUNC_RE.search(raw_text)
    if func_match:
        name = func_match.group(1).strip()
        if not name:
            return None
        body = func_match.group(2)
        arguments: dict = {}
        for param_match in _XML_PARAM_RE.finditer(body):
            arguments[param_match.group(1).strip()] = param_match.group(
                2,
            ).strip()
        lenient_args = _extract_params_lenient(body)
        if len(lenient_args) > len(arguments):
            arguments = lenient_args
        if not arguments and "<parameter=" in body:
            # Body contains <parameter= tags but neither strict nor lenient
            # parsing could extract them — treat as a parse failure.
            return None
        return ParsedToolCall(
            id=_generate_call_id(),
            name=name,
            arguments=arguments,
            raw_arguments=json.dumps(arguments, ensure_ascii=False),
        )

    # Strict format failed — try lenient format (no closing tags).
    func_match_lenient = _XML_FUNC_LENIENT_RE.search(raw_text)
    if not func_match_lenient:
        return None

    name = func_match_lenient.group(1).strip()
    if not name:
        return None

    body = func_match_lenient.group(2)
    arguments = _extract_params_lenient(body)

    if not arguments:
        logger.debug(
            "Lenient XML parse found function '%s' but no parameters; "
            "discarding.",
            name,
        )
        return None

    logger.debug(
        "Parsed tool call via lenient XML format: name=%s, params=%s",
        name,
        list(arguments.keys()),
    )
    return ParsedToolCall(
        id=_generate_call_id(),
        name=name,
        arguments=arguments,
        raw_arguments=json.dumps(arguments, ensure_ascii=False),
    )


def _parse_single_tool_call(raw_text: str) -> ParsedToolCall | None:
    """Parse the content between a ``<tool_call>`` / ``</tool_call>`` pair.

    Tries JSON format first::

        {"name": "func_name", "arguments": {"key": "value"}}

    Falls back to strict XML format if JSON parsing fails::

        <function=func_name>
          <parameter=param1>value1</parameter>
        </function>

    Falls back further to lenient XML format (no closing tags) if needed::

        <function=func_name>
          <parameter=param1>value1
          <parameter=param2>value2
    """
    stripped = raw_text.strip()

    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        data = None

    if data is not None:
        name = data.get("name", "")
        if not name:
            logger.warning(
                "Tool call missing 'name' field: %s",
                stripped[:200],
            )
            return None

        arguments = data.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (json.JSONDecodeError, TypeError):
                arguments = {}

        return ParsedToolCall(
            id=_generate_call_id(),
            name=name,
            arguments=arguments,
            raw_arguments=json.dumps(arguments, ensure_ascii=False),
        )

    # JSON failed — try XML format.
    result = _parse_xml_tool_call(stripped)
    if result is None:
        logger.warning("Failed to parse tool call: %s", stripped[:200])
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def text_contains_think_tag(text: str) -> bool:
    """Fast substring check for a ``<think>`` tag."""
    return THINK_START in text


def extract_thinking_from_text(text: str) -> TextWithThinking:
    """Extract ``<think>...</think>`` content from *text*.

    Returns a :class:`TextWithThinking` with:

    * ``thinking``       – the reasoning content (empty if none found)
    * ``remaining_text`` – everything outside the think tags
    * ``has_open_tag``   – ``True`` if ``<think>`` opened but not closed yet
    """
    match = _THINK_RE.search(text)
    if match:
        thinking = match.group(1).strip()
        remaining = (text[: match.start()] + text[match.end() :]).strip()
        return TextWithThinking(
            thinking=thinking,
            remaining_text=remaining,
        )

    # No complete block — check for an unclosed <think>.
    open_idx = text.find(THINK_START)
    if open_idx != -1:
        remaining = text[:open_idx].strip()
        partial = text[open_idx + len(THINK_START) :]
        return TextWithThinking(
            thinking=partial.strip(),
            remaining_text=remaining,
            has_open_tag=True,
        )

    return TextWithThinking(remaining_text=text)


def text_contains_tool_call_tag(text: str) -> bool:
    """Fast substring check for a ``<tool_call>`` tag."""
    return TOOL_CALL_START in text


def parse_tool_calls_from_text(text: str) -> TextWithToolCalls:
    """Extract all ``<tool_call>...</tool_call>`` blocks from *text*.

    Returns a :class:`TextWithToolCalls` with:

    * ``text_before`` – all text before the first ``<tool_call>`` tag
    * ``text_after``  – all text after the last ``</tool_call>`` tag
    * ``tool_calls``  – successfully parsed tool calls
    * ``has_open_tag`` – whether there is an unclosed ``<tool_call>``
        (streaming)
    * ``partial_tool_text`` – content after the unclosed tag
    """
    matches = list(_TOOL_CALL_RE.finditer(text))

    if not matches:
        # No complete blocks.  Check for an unclosed opening tag.
        open_idx = text.rfind(TOOL_CALL_START)
        if open_idx != -1:
            return TextWithToolCalls(
                text_before=text[:open_idx].rstrip(),
                has_open_tag=True,
                partial_tool_text=text[open_idx + len(TOOL_CALL_START) :],
            )
        return TextWithToolCalls(text_before=text)

    # --- Text before the first match ---
    text_before = text[: matches[0].start()].rstrip()

    # --- Text after the last match ---
    remaining = text[matches[-1].end() :]
    open_idx = remaining.find(TOOL_CALL_START)
    if open_idx != -1:
        text_after = remaining[:open_idx].strip()
        has_open_tag = True
        partial_tool_text = remaining[open_idx + len(TOOL_CALL_START) :]
    else:
        text_after = remaining.strip()
        has_open_tag = False
        partial_tool_text = ""

    # --- Parse each complete block ---
    tool_calls: list[ParsedToolCall] = []
    for match in matches:
        parsed = _parse_single_tool_call(match.group(1))
        if parsed is not None:
            tool_calls.append(parsed)

    return TextWithToolCalls(
        text_before=text_before,
        text_after=text_after,
        tool_calls=tool_calls,
        has_open_tag=has_open_tag,
        partial_tool_text=partial_tool_text,
    )
