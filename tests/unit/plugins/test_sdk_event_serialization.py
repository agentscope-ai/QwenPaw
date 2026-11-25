# -*- coding: utf-8 -*-
"""Normalized JSON output retains multimedia data and owns its containers."""

import json

from qwenpaw.plugins._events import chat_event


def test_to_dict_preserves_nested_fields_and_zero_indices():
    original = {
        "object": "response",
        "id": "run",
        "status": "completed",
        "output": [
            {
                "id": "message",
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_call",
                        "id": "call",
                        "name": "tool",
                        "arguments": {"x": [1, 2]},
                    },
                    {
                        "type": "image",
                        "data": {"url": "https://example.test/image.png"},
                    },
                    {
                        "type": "text",
                        "text": "part",
                        "index": 0,
                        "delta": True,
                    },
                ],
                "metadata": {"nested": ["value"]},
            },
        ],
        "usage": {"input_tokens": 5},
    }
    event = chat_event(original)
    result = event.to_dict()
    assert json.loads(json.dumps(result)) == result
    content = result["output"][0]["content"]
    assert content[0]["arguments"] == {"x": [1, 2]}
    assert content[1]["data"]["url"] == "https://example.test/image.png"
    assert content[2]["index"] == 0 and content[2]["delta"] is True
    assert result["usage"] == {"input_tokens": 5}
    content[0]["arguments"]["x"].append(3)
    assert event.to_dict()["output"][0]["content"][0]["arguments"]["x"] == [
        1,
        2,
    ]
    assert original["output"][0]["content"][0]["arguments"]["x"] == [1, 2]


def test_content_event_roundtrip():
    event = chat_event(
        {
            "object": "content",
            "type": "text",
            "text": "token",
            "delta": True,
            "index": 0,
        },
    )
    result = event.to_dict()
    assert result["object"] == "content"
    assert result["text"] == "token"
    assert result["delta"] is True and result["index"] == 0
