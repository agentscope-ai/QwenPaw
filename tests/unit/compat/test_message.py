# -*- coding: utf-8 -*-
from agentscope.message import DataBlock

from qwenpaw._compat.message import msg_from_dict


def _legacy_message(block: dict) -> dict:
    return {
        "name": "user",
        "role": "user",
        "content": [block],
    }


def test_msg_from_dict_accepts_legacy_string_source() -> None:
    msg = msg_from_dict(
        _legacy_message(
            {
                "type": "image",
                "source": "/home/user/.qwenpaw/workspaces/image.png",
            },
        ),
    )

    block = msg.content[0]
    assert isinstance(block, DataBlock)
    assert str(block.source.url) == (
        "file:///home/user/.qwenpaw/workspaces/image.png"
    )


def test_msg_from_dict_converts_legacy_local_url_path_to_file_url() -> None:
    msg = msg_from_dict(
        _legacy_message(
            {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": "/home/user/.qwenpaw/workspaces/image.png",
                },
            },
        ),
    )

    block = msg.content[0]
    assert isinstance(block, DataBlock)
    assert str(block.source.url) == (
        "file:///home/user/.qwenpaw/workspaces/image.png"
    )


def test_msg_from_dict_accepts_legacy_file_block() -> None:
    msg = msg_from_dict(
        _legacy_message(
            {
                "type": "file",
                "name": "report.pdf",
                "source": {
                    "type": "url",
                    "url": "file:///home/user/report.pdf",
                },
            },
        ),
    )

    block = msg.content[0]
    assert isinstance(block, DataBlock)
    assert block.name == "report.pdf"
    assert block.source.media_type == "application/pdf"
