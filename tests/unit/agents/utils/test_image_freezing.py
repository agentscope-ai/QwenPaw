# -*- coding: utf-8 -*-
"""Freezing keeps the original bytes; resizing happens on request copies."""

import base64
from io import BytesIO

from PIL import Image

from qwenpaw.agents.utils.image_freezing import freeze_image_bytes


def _png(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), (30, 60, 90))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_oversized_image_is_frozen_byte_identical():
    """Full resolution stays available for a later explicit request."""
    raw = _png(9000, 60)

    block, error = freeze_image_bytes(raw, "timeline_states_48h.png")

    assert error is None
    assert block is not None
    assert base64.b64decode(block.source.data) == raw


def test_normal_size_image_is_left_byte_identical():
    """Images inside the limit must not be re-encoded."""
    raw = _png(400, 300)

    block, error = freeze_image_bytes(raw, "small.png")

    assert error is None
    assert block is not None
    assert base64.b64decode(block.source.data) == raw
