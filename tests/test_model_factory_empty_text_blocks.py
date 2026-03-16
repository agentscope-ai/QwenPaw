# -*- coding: utf-8 -*-

from __future__ import annotations

from agentscope.formatter import AnthropicChatFormatter
from agentscope.message import Msg

from copaw.agents.model_factory import _create_file_block_support_formatter


async def test_formatter_wrapper_strips_empty_text_blocks() -> None:
    formatter_cls = _create_file_block_support_formatter(
        AnthropicChatFormatter,
    )
    formatter = formatter_cls()
    msg = Msg(
        name="user",
        role="user",
        content=[
            {"type": "text", "text": ""},
            {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": "https://example.com/demo.png",
                },
            },
            {"type": "text", "text": "后续文字"},
        ],
    )

    messages = await formatter.format([msg])

    assert messages == [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "url",
                        "url": "https://example.com/demo.png",
                    },
                },
                {"type": "text", "text": "后续文字"},
            ],
        },
    ]
