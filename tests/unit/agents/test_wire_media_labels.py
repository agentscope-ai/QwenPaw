# -*- coding: utf-8 -*-
"""Labels that let a provider rejection name the image it rejected."""

from __future__ import annotations

from qwenpaw.agents.model_factory import _describe_wire_media_blocks

_PAYLOAD = "A" * 1398104  # ~1 MiB once decoded


def test_labels_anthropic_source_blocks() -> None:
    labels = _describe_wire_media_blocks(
        [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": _PAYLOAD,
                        },
                    },
                ],
            },
        ],
    )

    assert len(labels) == 1
    assert labels[0] == "#1 image/png 1.0 MiB"


def test_labels_openai_data_url_blocks() -> None:
    labels = _describe_wire_media_blocks(
        [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{_PAYLOAD}",
                        },
                    },
                ],
            },
        ],
    )

    assert len(labels) == 1
    assert labels[0] == "#1 image/jpeg 1.0 MiB"


def test_labels_gemini_inline_data_blocks() -> None:
    labels = _describe_wire_media_blocks(
        [
            {
                "role": "user",
                "content": [
                    {
                        "inline_data": {
                            "mime_type": "image/webp",
                            "data": _PAYLOAD,
                        },
                    },
                ],
            },
        ],
    )

    assert len(labels) == 1
    assert labels[0] == "#1 image/webp 1.0 MiB"


def test_numbers_follow_wire_order_and_skip_non_media() -> None:
    labels = _describe_wire_media_blocks(
        [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {
                "role": "tool",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": _PAYLOAD,
                        },
                    },
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/gif",
                            "data": _PAYLOAD,
                        },
                    },
                ],
            },
        ],
    )

    assert [label.split()[0] for label in labels] == ["#1", "#2"]
    assert "image/gif" in labels[1]


def test_blocks_without_a_known_shape_are_ignored() -> None:
    assert _describe_wire_media_blocks([{"role": "user", "content": []}]) == []
    assert _describe_wire_media_blocks({"type": "text", "text": "hi"}) == []
