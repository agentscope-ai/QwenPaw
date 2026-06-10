# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import pytest

from qwenpaw.local_models.tag_parser import (
    extract_thinking_from_text,
    parse_tool_calls_from_text,
    text_contains_think_tag,
    text_contains_tool_call_tag,
)

# ---------------------------------------------------------------------------
# text_contains_think_tag
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("<think>hello</think>", True),
        ("no tags here", False),
        ("<think>", True),
        ("prefix<think>suffix", True),
        ("", False),
    ],
)
def test_text_contains_think_tag(text: str, expected: bool) -> None:
    assert text_contains_think_tag(text) is expected


# ---------------------------------------------------------------------------
# extract_thinking_from_text
# ---------------------------------------------------------------------------


def test_extract_thinking_complete_block() -> None:
    result = extract_thinking_from_text("before<think>reasoning</think>after")
    assert result.thinking == "reasoning"
    assert result.remaining_text == "beforeafter"
    assert result.has_open_tag is False


def test_extract_thinking_strips_whitespace() -> None:
    result = extract_thinking_from_text("<think>  spaced  </think>rest")
    assert result.thinking == "spaced"
    assert result.remaining_text == "rest"


def test_extract_thinking_open_tag_streaming() -> None:
    result = extract_thinking_from_text("hello<think>partial reasoning")
    assert result.has_open_tag is True
    assert result.thinking == "partial reasoning"
    assert result.remaining_text == "hello"


def test_extract_thinking_no_tag() -> None:
    result = extract_thinking_from_text("plain text")
    assert result.thinking == ""
    assert result.remaining_text == "plain text"
    assert result.has_open_tag is False


def test_extract_thinking_empty_block() -> None:
    result = extract_thinking_from_text("<think></think>content")
    assert result.thinking == ""
    assert result.remaining_text == "content"


def test_extract_thinking_multiline() -> None:
    text = "<think>\nline1\nline2\n</think>after"
    result = extract_thinking_from_text(text)
    assert "line1" in result.thinking
    assert "line2" in result.thinking
    assert result.remaining_text == "after"


# ---------------------------------------------------------------------------
# text_contains_tool_call_tag
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("<tool_call>{}</tool_call>", True),
        ("no tags", False),
        ("<tool_call>", True),
        ("", False),
    ],
)
def test_text_contains_tool_call_tag(text: str, expected: bool) -> None:
    assert text_contains_tool_call_tag(text) is expected


# ---------------------------------------------------------------------------
# parse_tool_calls_from_text — JSON format
# ---------------------------------------------------------------------------


def test_parse_json_tool_call() -> None:
    text = (
        "before<tool_call>\n"
        '{"name": "get_weather", "arguments": {"city": "NYC"}}\n'
        "</tool_call>after"
    )
    result = parse_tool_calls_from_text(text)
    assert result.text_before == "before"
    assert result.text_after == "after"
    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.name == "get_weather"
    assert tc.arguments == {"city": "NYC"}
    assert tc.id.startswith("call_")
    assert result.has_open_tag is False


def test_parse_json_tool_call_string_arguments() -> None:
    text = (
        "<tool_call>"
        '{"name": "func", "arguments": "{\\"key\\": \\"val\\"}"}'
        "</tool_call>"
    )
    result = parse_tool_calls_from_text(text)
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].arguments == {"key": "val"}


def test_parse_json_tool_call_missing_name() -> None:
    text = '<tool_call>{"arguments": {"a": 1}}</tool_call>'
    result = parse_tool_calls_from_text(text)
    assert len(result.tool_calls) == 0


def test_parse_multiple_tool_calls() -> None:
    text = (
        'text<tool_call>{"name":"a","arguments":{}}</tool_call>'
        'mid<tool_call>{"name":"b","arguments":{}}</tool_call>end'
    )
    result = parse_tool_calls_from_text(text)
    assert len(result.tool_calls) == 2
    assert result.tool_calls[0].name == "a"
    assert result.tool_calls[1].name == "b"
    assert result.text_before == "text"
    assert result.text_after == "end"


# ---------------------------------------------------------------------------
# parse_tool_calls_from_text — XML format
# ---------------------------------------------------------------------------


def test_parse_xml_tool_call_strict() -> None:
    xml_body = (
        "<function=search>\n"
        "<parameter=query>hello</parameter>\n"
        "<parameter=limit>10</parameter>\n"
        "</function>"
    )
    text = f"<tool_call>{xml_body}</tool_call>"
    result = parse_tool_calls_from_text(text)
    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.name == "search"
    assert tc.arguments == {"query": "hello", "limit": "10"}


def test_parse_xml_tool_call_lenient_no_closing() -> None:
    xml_body = (
        "<function=do_stuff>\n"
        "<parameter=arg1>value1\n"
        "<parameter=arg2>value2\n"
    )
    text = f"<tool_call>{xml_body}</tool_call>"
    result = parse_tool_calls_from_text(text)
    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.name == "do_stuff"
    assert tc.arguments["arg1"] == "value1"
    assert tc.arguments["arg2"] == "value2"


# ---------------------------------------------------------------------------
# parse_tool_calls_from_text — streaming / partial tags
# ---------------------------------------------------------------------------


def test_parse_open_tag_no_complete_blocks() -> None:
    text = "before<tool_call>partial content"
    result = parse_tool_calls_from_text(text)
    assert result.has_open_tag is True
    assert result.partial_tool_text == "partial content"
    assert result.text_before == "before"
    assert len(result.tool_calls) == 0


def test_parse_complete_blocks_plus_trailing_open() -> None:
    text = (
        '<tool_call>{"name":"a","arguments":{}}</tool_call>'
        "<tool_call>still streaming"
    )
    result = parse_tool_calls_from_text(text)
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "a"
    assert result.has_open_tag is True
    assert result.partial_tool_text == "still streaming"


def test_parse_no_tags() -> None:
    result = parse_tool_calls_from_text("plain text no tags")
    assert result.text_before == "plain text no tags"
    assert not result.tool_calls
    assert result.has_open_tag is False
    assert result.partial_tool_text == ""


def test_parse_invalid_json_falls_through() -> None:
    text = "<tool_call>not json at all</tool_call>"
    result = parse_tool_calls_from_text(text)
    assert len(result.tool_calls) == 0
