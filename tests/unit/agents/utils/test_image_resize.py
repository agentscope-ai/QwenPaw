# -*- coding: utf-8 -*-
"""Request copies downscale oversized images without losing information."""

import base64
from io import BytesIO

from agentscope.message import (
    Base64Source,
    DataBlock,
    Msg,
    TextBlock,
)
from PIL import Image

from qwenpaw.agents.utils.image_resize import (
    MAX_IMAGE_SIDE,
    downscale_image_bytes,
    downscale_oversized_images,
)
from qwenpaw.agents.utils.message_request_normalizer import (
    normalize_messages_for_model_request,
)


def _png(width: int, height: int, mode: str = "RGB") -> bytes:
    color = (30, 60, 90) if mode == "RGB" else (30, 60, 90, 255)
    image = Image.new(mode, (width, height), color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _webp(width: int, height: int, *, alpha: bool) -> bytes:
    mode = "RGBA" if alpha else "RGB"
    image = Image.new(mode, (width, height), (30, 60, 90, 128)[: len(mode)])
    buffer = BytesIO()
    image.save(buffer, format="WEBP", lossless=True)
    return buffer.getvalue()


def test_oversized_side_is_downscaled():
    raw = _png(9000, 60)

    scaled, media_type = downscale_image_bytes(raw, "image/png")

    assert media_type == "image/png"
    with Image.open(BytesIO(scaled)) as image:
        assert max(image.size) <= MAX_IMAGE_SIDE
        ratio = image.size[0] / image.size[1]
        assert abs(ratio / (9000 / 60) - 1) < 0.01


def test_transparent_webp_stays_webp():
    """Converting alpha to PNG can blow the payload up by an order of magnitude."""
    raw = _webp(9000, 60, alpha=True)

    scaled, media_type = downscale_image_bytes(raw, "image/webp")

    assert media_type == "image/webp"
    with Image.open(BytesIO(scaled)) as image:
        assert image.format == "WEBP"
        assert "A" in image.getbands()


def test_animated_webp_keeps_every_frame():
    """Pillow would keep only the first frame, so animations pass through."""
    frames = [
        Image.new("RGB", (9000, 60), color) for color in ((1, 2, 3), (4, 5, 6))
    ]
    buffer = BytesIO()
    frames[0].save(
        buffer,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
        lossless=True,
    )
    raw = buffer.getvalue()

    scaled, media_type = downscale_image_bytes(raw, "image/webp")

    assert media_type == "image/webp"
    assert scaled == raw
    with Image.open(BytesIO(scaled)) as image:
        assert getattr(image, "n_frames", 1) == 2


def test_apng_keeps_every_frame():
    frames = [
        Image.new("RGBA", (9000, 60), color)
        for color in ((1, 2, 3, 255), (4, 5, 6, 255))
    ]
    buffer = BytesIO()
    frames[0].save(
        buffer,
        format="PNG",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )
    raw = buffer.getvalue()

    scaled, media_type = downscale_image_bytes(raw, "image/png")

    assert media_type == "image/png"
    assert scaled == raw
    with Image.open(BytesIO(scaled)) as image:
        assert getattr(image, "n_frames", 1) == 2


def test_exif_orientation_is_applied_before_resizing():
    """A rotated JPEG must be scaled along its displayed axes."""
    image = Image.new("RGB", (60, 9000), (30, 60, 90))
    exif = Image.Exif()
    exif[274] = 6  # Rotate 90 CW on display
    buffer = BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    raw = buffer.getvalue()

    scaled, media_type = downscale_image_bytes(raw, "image/jpeg")

    assert media_type == "image/jpeg"
    with Image.open(BytesIO(scaled)) as resized:
        assert max(resized.size) <= MAX_IMAGE_SIDE
        assert resized.size[0] > resized.size[1]


def test_downscale_mutates_the_request_copy():
    """The helper edits the list it is given; callers pass a clone."""
    raw = _png(9000, 60)
    msg = Msg(
        name="user",
        role="user",
        content=[
            DataBlock(
                source=Base64Source(
                    data=base64.b64encode(raw).decode("ascii"),
                    media_type="image/png",
                ),
            ),
            TextBlock(text="what is this?"),
        ],
    )

    changed = downscale_oversized_images([msg])

    assert changed == 1
    with Image.open(BytesIO(raw)) as original:
        assert max(original.size) == 9000
    stored = base64.b64decode(msg.content[0].source.data)
    with Image.open(BytesIO(stored)) as shrunk:
        assert max(shrunk.size) <= MAX_IMAGE_SIDE

    # normalize_messages_for_model_request works on a clone, so a fresh
    # message keeps its bytes after normalization.
    fresh = Msg(
        name="user",
        role="user",
        content=[
            DataBlock(
                source=Base64Source(
                    data=base64.b64encode(raw).decode("ascii"),
                    media_type="image/png",
                ),
            ),
        ],
    )
    normalized = normalize_messages_for_model_request(
        [fresh],
        supports_multimodal=True,
    )
    assert base64.b64decode(fresh.content[0].source.data) == raw
    request_bytes = base64.b64decode(normalized[0].content[0].source.data)
    assert request_bytes != raw
    with Image.open(BytesIO(request_bytes)) as request_image:
        assert max(request_image.size) <= MAX_IMAGE_SIDE
