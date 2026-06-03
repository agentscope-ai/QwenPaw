# -*- coding: utf-8 -*-
"""The ACP server surfaces files an agent sends (``send_file_to_user``) as a
``resource_link`` tool-call content block, so clients (e.g. the paw TUI) can
offer a clickable link instead of a raw dict repr."""

from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.agents.acp.server import (
    _extract_tool_output,
    _media_block_url,
    _msg_to_updates,
    _tool_result_content,
)


def _tool_result_msg(output):
    return SimpleNamespace(
        metadata={},
        content=[
            {
                "type": "tool_result",
                "id": "t1",
                "name": "send_file_to_user",
                "output": output,
            },
        ],
        role="system",
    )


def test_media_block_url_extracts_file_blocks():
    assert _media_block_url(
        {
            "type": "file",
            "source": {"type": "url", "url": "file:///tmp/a.pdf"},
            "filename": "a.pdf",
        },
    ) == ("file:///tmp/a.pdf", "a.pdf", None)

    # Name falls back to the URL basename when no filename is given.
    url, name, _mime = _media_block_url(
        {"type": "image", "source": {"type": "url", "url": "file:///x/c.png"}},
    )
    assert (url, name) == ("file:///x/c.png", "c.png")

    # Non-media / text blocks are ignored.
    assert _media_block_url({"type": "text", "text": "hi"}) is None


def test_tool_result_content_appends_resource_link():
    output = [
        {
            "type": "file",
            "source": {"type": "url", "url": "file:///tmp/report.pdf"},
            "filename": "report.pdf",
        },
        {"type": "text", "text": "File sent successfully."},
    ]
    contents = _tool_result_content(output)

    text_blocks = [c for c in contents if c.content.type == "text"]
    assert "File sent successfully." in text_blocks[0].content.text
    # The file block renders as a readable filename line, not a dict repr.
    assert "📎 report.pdf" in text_blocks[0].content.text
    assert "{'type'" not in text_blocks[0].content.text

    links = [c for c in contents if c.content.type == "resource_link"]
    assert len(links) == 1
    assert links[0].content.uri == "file:///tmp/report.pdf"
    assert links[0].content.name == "report.pdf"


def test_plain_text_output_has_no_resource_link():
    contents = _tool_result_content([{"type": "text", "text": "done"}])
    assert [c.content.type for c in contents] == ["text"]


def test_remote_url_media_gets_no_resource_link():
    # Only local file:// media becomes a clickable resource_link; remote
    # URLs are not turned into openable resources, but still show as text.
    output = [
        {
            "type": "image",
            "source": {"type": "url", "url": "https://example.com/a.png"},
            "filename": "a.png",
        },
        {"type": "text", "text": "File sent successfully."},
    ]
    contents = _tool_result_content(output)
    assert [c.content.type for c in contents] == ["text"]
    text = contents[0].content.text
    assert "📎 a.png" in text


def test_extract_tool_output_handles_block_objects():
    # Object-style blocks (not dicts), e.g. agentscope ImageBlock/TextBlock.
    output = [
        SimpleNamespace(
            type="file",
            source={"type": "url", "url": "file:///tmp/r.pdf"},
            filename="r.pdf",
        ),
        SimpleNamespace(type="text", text="File sent successfully."),
    ]
    text = _extract_tool_output(output)
    assert "📎 r.pdf" in text
    assert "File sent successfully." in text
    assert "namespace(" not in text  # no raw repr fallback


def test_tool_result_update_carries_link_end_to_end():
    output = [
        {
            "type": "image",
            "source": {"type": "url", "url": "file:///tmp/cat.png"},
        },
        {"type": "text", "text": "File sent successfully."},
    ]
    [update] = _msg_to_updates(_tool_result_msg(output))
    assert update.session_update == "tool_call_update"
    types = [c.content.type for c in update.content]
    assert "resource_link" in types
    link = next(c for c in update.content if c.content.type == "resource_link")
    assert link.content.uri == "file:///tmp/cat.png"
    assert link.content.name == "cat.png"
