# -*- coding: utf-8 -*-

from copaw.agents.model_factory import _downgrade_text_only_message_content


def test_downgrade_text_only_content_blocks_to_string() -> None:
    payload = {
        "messages": [
            {
                "role": "system",
                "content": [
                    {"type": "text", "text": "line1"},
                    {"type": "text", "text": "\nline2"},
                ],
            },
        ],
    }

    out = _downgrade_text_only_message_content(payload)
    assert out is payload
    assert payload["messages"][0]["content"] == "line1\nline2"


def test_keep_multimodal_content_array_unchanged() -> None:
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look"},
                    {"type": "image_url", "image_url": "https://example.com/a.png"},
                ],
            },
        ],
    }

    out = _downgrade_text_only_message_content(payload)
    assert out is payload
    assert isinstance(payload["messages"][0]["content"], list)
    assert payload["messages"][0]["content"][1]["type"] == "image_url"
