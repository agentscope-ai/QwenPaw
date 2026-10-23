# -*- coding: utf-8 -*-
"""Preserved official artifact helpers; runtime behaviors use B147 workers.

No legacy channel class is retained.
"""
# pylint: disable=protected-access
import json
import re
from tests.fixtures.channel_plugins.c6_artifacts import artifact_module

_CJK_RE = re.compile(r"[\u3400-\u9fff]")


class TestExtractInteractiveText:
    """Unit tests for extract_interactive_text()."""

    def test_extracts_title_and_elements(self):
        extract_interactive_text = artifact_module(
            "feishu",
            "utils",
        ).extract_interactive_text

        payload = json.dumps(
            {
                "title": "Card Title",
                "elements": [
                    [{"tag": "text", "text": "Hello world"}],
                ],
            },
        )
        result = extract_interactive_text(payload)
        assert result is not None
        assert "Card Title" in result
        assert "Hello world" in result

    def test_cardkit_v2_body_elements(self):
        """CardKit v2 nests elements under body — must still extract."""
        extract_interactive_text = artifact_module(
            "feishu",
            "utils",
        ).extract_interactive_text

        payload = json.dumps(
            {
                "header": {"title": {"content": "V2 Card"}},
                "body": {
                    "elements": [
                        {"tag": "text", "text": "Body content here"},
                    ],
                },
            },
        )
        result = extract_interactive_text(payload)
        assert result is not None
        assert "V2 Card" in result
        assert "Body content here" in result

    def test_extracts_links_as_markdown(self):
        extract_interactive_text = artifact_module(
            "feishu",
            "utils",
        ).extract_interactive_text

        payload = json.dumps(
            {
                "elements": [
                    [
                        {
                            "tag": "a",
                            "text": "Click me",
                            "href": "https://example.com",
                        },
                    ],
                ],
            },
        )
        result = extract_interactive_text(payload)
        assert result is not None
        assert "[Click me](https://example.com)" in result

    def test_returns_none_for_empty_or_invalid(self):
        extract_interactive_text = artifact_module(
            "feishu",
            "utils",
        ).extract_interactive_text

        assert extract_interactive_text(None) is None
        assert extract_interactive_text("") is None
        assert extract_interactive_text("{broken") is None
        assert extract_interactive_text(json.dumps({"other": "data"})) is None

    def test_title_only(self):
        extract_interactive_text = artifact_module(
            "feishu",
            "utils",
        ).extract_interactive_text

        result = extract_interactive_text(json.dumps({"title": "Hello"}))
        assert result == "Hello"

    def test_header_title_content(self):
        extract_interactive_text = artifact_module(
            "feishu",
            "utils",
        ).extract_interactive_text

        payload = json.dumps(
            {
                "header": {"title": {"content": "Header Title"}},
            },
        )
        result = extract_interactive_text(payload)
        assert result == "Header Title"


class TestReasoningPanel:
    def test_reasoning_card_wraps_markdown_in_a_panel(self):
        build_streaming_card_json = artifact_module(
            "feishu",
            "card_templates",
        ).build_streaming_card_json
        FEISHU_REASONING_PANEL_ELEMENT_ID = artifact_module(
            "feishu",
            "constants",
        ).FEISHU_REASONING_PANEL_ELEMENT_ID
        FEISHU_REASONING_PANEL_ICON_TOKEN = artifact_module(
            "feishu",
            "constants",
        ).FEISHU_REASONING_PANEL_ICON_TOKEN
        FEISHU_STREAM_ELEMENT_ID = artifact_module(
            "feishu",
            "constants",
        ).FEISHU_STREAM_ELEMENT_ID
        body = build_streaming_card_json("...", collapsible=True)
        assert body["config"] == {"streaming_mode": True}
        (top,) = body["body"]["elements"]
        assert top["tag"] == "collapsible_panel"
        assert top["expanded"] is True
        assert top["element_id"] == FEISHU_REASONING_PANEL_ELEMENT_ID
        assert 0 < len(top["element_id"]) <= 20
        assert top["element_id"][0].isalpha()
        header = top["header"]
        assert header["title"] == {"tag": "plain_text", "content": "Thinking"}
        assert header["icon"]["token"] == FEISHU_REASONING_PANEL_ICON_TOKEN
        assert header["icon_position"] == "follow_text"
        assert header["icon_expanded_angle"] == 180
        (inner,) = top["elements"]
        assert inner["tag"] == "markdown"
        assert inner["element_id"] == FEISHU_STREAM_ELEMENT_ID
        assert inner["content"] == "..."

    def test_answer_card_stays_plain_markdown(self):
        build_streaming_card_json = artifact_module(
            "feishu",
            "card_templates",
        ).build_streaming_card_json
        body = build_streaming_card_json("...")
        (top,) = body["body"]["elements"]
        assert top["tag"] == "markdown"
        assert "collapsible_panel" not in json.dumps(body)

    def test_card_copy_contains_no_chinese(self):
        """Card copy must stay English for an international product."""
        build_streaming_card_json = artifact_module(
            "feishu",
            "card_templates",
        ).build_streaming_card_json
        payload = json.dumps(
            [
                build_streaming_card_json("...", collapsible=True),
                build_streaming_card_json("..."),
            ],
            ensure_ascii=False,
        )
        assert not _CJK_RE.search(payload)
