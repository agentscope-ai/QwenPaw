# -*- coding: utf-8 -*-
from __future__ import annotations

from qwenpaw.local_models import tag_parser


def test_extract_thinking_from_complete_tag() -> None:
    result = tag_parser.extract_thinking_from_text(
        "before <think>reasoning\nsteps</think> after",
    )

    assert result.thinking == "reasoning\nsteps"
    assert result.remaining_text == "before  after"
    assert result.has_open_tag is False


def test_extract_thinking_from_open_streaming_tag() -> None:
    result = tag_parser.extract_thinking_from_text(
        "answer prefix <think>still thinking",
    )

    assert result.thinking == "still thinking"
    assert result.remaining_text == "answer prefix"
    assert result.has_open_tag is True


def test_text_contains_tag_helpers() -> None:
    assert tag_parser.text_contains_think_tag("<think>x")
    assert not tag_parser.text_contains_think_tag("plain text")
    assert tag_parser.text_contains_tool_call_tag("<tool_call>{}</tool_call>")
    assert not tag_parser.text_contains_tool_call_tag("plain text")


def test_parse_json_tool_call() -> None:
    result = tag_parser.parse_tool_calls_from_text(
        'before <tool_call>{"name": "read_file", '
        '"arguments": {"path": "notes.md"}}</tool_call> after',
    )

    assert result.text_before == "before"
    assert result.text_after == "after"
    assert result.has_open_tag is False
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.id.startswith("call_")
    assert call.name == "read_file"
    assert call.arguments == {"path": "notes.md"}
    assert call.raw_arguments == '{"path": "notes.md"}'


def test_parse_json_tool_call_with_arguments_string() -> None:
    result = tag_parser.parse_tool_calls_from_text(
        '<tool_call>{"name": "write_file", '
        '"arguments": "{\\"path\\": \\"a.txt\\", \\"content\\": \\"ok\\"}"'
        "}</tool_call>",
    )

    assert result.tool_calls[0].name == "write_file"
    assert result.tool_calls[0].arguments == {
        "path": "a.txt",
        "content": "ok",
    }


def test_parse_strict_xml_tool_call() -> None:
    result = tag_parser.parse_tool_calls_from_text(
        "<tool_call>"
        "<function=read_file>"
        "<parameter=path>notes.md</parameter>"
        "<parameter=limit>20</parameter>"
        "</function>"
        "</tool_call>",
    )

    call = result.tool_calls[0]
    assert call.name == "read_file"
    assert call.arguments == {"path": "notes.md", "limit": "20"}


def test_parse_lenient_xml_tool_call_without_closing_parameter_tags() -> None:
    result = tag_parser.parse_tool_calls_from_text(
        "<tool_call>"
        "<function=grep_search>"
        "<parameter=pattern>TODO"
        "<parameter=path>src"
        "</tool_call>",
    )

    call = result.tool_calls[0]
    assert call.name == "grep_search"
    assert call.arguments == {"pattern": "TODO", "path": "src"}


def test_parse_multiple_tool_calls_and_trailing_partial() -> None:
    result = tag_parser.parse_tool_calls_from_text(
        'intro <tool_call>{"name": "read_file", '
        '"arguments": {"path": "a.md"}}</tool_call>'
        ' middle <tool_call>{"name": "write_file", '
        '"arguments": {"path": "b.md"}}</tool_call>'
        " outro <tool_call>partial",
    )

    assert result.text_before == "intro"
    assert result.text_after == "outro"
    assert result.has_open_tag is True
    assert result.partial_tool_text == "partial"
    assert [call.name for call in result.tool_calls] == [
        "read_file",
        "write_file",
    ]


def test_parse_only_open_tool_call_tag() -> None:
    result = tag_parser.parse_tool_calls_from_text(
        "lead text <tool_call>partial body",
    )

    assert result.text_before == "lead text"
    assert not result.tool_calls
    assert result.has_open_tag is True
    assert result.partial_tool_text == "partial body"


def test_invalid_tool_call_is_skipped_and_logged(monkeypatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        tag_parser.logger,
        "warning",
        lambda message, *args: warnings.append(message % args),
    )

    result = tag_parser.parse_tool_calls_from_text(
        "before <tool_call>{not-json}</tool_call> after",
    )

    assert result.text_before == "before"
    assert result.text_after == "after"
    assert not result.tool_calls
    assert any("Failed to parse tool call" in msg for msg in warnings)
