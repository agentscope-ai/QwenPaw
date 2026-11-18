# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,protected-access,unnecessary-lambda,useless-return

from __future__ import annotations

import asyncio
import base64
import io
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from agentscope.formatter import AnthropicChatFormatter, OpenAIChatFormatter
from agentscope.message import Msg
from PIL import Image

from models import vlm_model
from models.native_content import native_content_blocks
from utils.exceptions import ModelError

pytestmark = pytest.mark.unit

DASHSCOPE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _transport(part, model, base_url):
    coro = vlm_model._transport_local_media_part
    return asyncio.run(coro(part, "vlm-key", model, base_url))


def _formatted_media_blocks(parts):
    """Hand *parts* to the real SDK formatters and keep what they did not drop.

    Returns the non-text block types per formatter, because the interesting
    failure is silent: an unsupported media type is logged and skipped, so the
    request simply stops carrying the picture.
    """

    message = Msg(
        name="user",
        role="user",
        content=native_content_blocks(parts),
    )
    outcomes = {}
    for label, formatter in (
        ("openai", OpenAIChatFormatter()),
        ("anthropic", AnthropicChatFormatter()),
    ):
        formatted = asyncio.run(formatter.format([message]))
        outcomes[label] = [
            block["type"]
            for block in formatted[0]["content"]
            if block.get("type") != "text"
        ]
    return outcomes


def test_media_declaration_separates_three_levels_of_confidence():
    """A specific type, a placeholder, and a family are not the same claim.

    All three arrived at one ``mediaType`` field, and treating them alike is
    what let a placeholder outrank the family fallback: only the first is a
    declaration, the second says nothing about the bytes, and the third is the
    coarse guess every unnamed part is filed under.
    """

    assert (
        vlm_model._media_declaration(
            {"mediaType": "video/quicktime"},
            "video_url",
        )
        == "video/quicktime"
    )
    assert (
        vlm_model._media_declaration(
            {"mediaType": "application/octet-stream"},
            "video_url",
        )
        == "video/mp4"
    )
    assert vlm_model._media_declaration({}, "image_url") == "image/png"
    assert (
        vlm_model._media_declaration({"mediaType": "IMAGE/PNG"}, "image_url")
        == "IMAGE/PNG"
    )


def test_direct_protocol_entries_inherit_the_part_declaration(
    tmp_path,
    monkeypatch,
):
    """The Anthropic and Gemini inliners used to hardcode a family.

    Both sit behind the same OpenAI-shaped parts as the compatible transport,
    yet ignored ``mediaType`` entirely: a TIFF filed as ``frame.bin`` and a
    QuickTime clip filed as ``clip.bin`` went out as ``image/png`` and
    ``video/mp4``, labelling bytes their provider never described.
    """

    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_max_inline_bytes",
        lambda: 1024 * 1024,
    )

    captured: dict = {}

    class FakeResponse:
        status_code = 200
        headers: dict = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "content": [{"type": "text", "text": "ok"}],
                "max_tokens": 4096,
                "candidates": [
                    {
                        "content": {"parts": [{"text": "ok"}]},
                        "finishReason": "STOP",
                    },
                ],
            }

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, url, *, headers, json):
            del url, headers
            captured["body"] = json
            return FakeResponse()

        async def get(self, url, *, headers):
            # ``anthropic_output_limit`` resolves an unknown model through the
            # read-only Models API before it builds the request.
            del url, headers
            return FakeResponse()

    @asynccontextmanager
    async def fake_model_slot(_kind):
        yield

    monkeypatch.setattr(vlm_model.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(vlm_model, "model_slot", fake_model_slot)

    still = tmp_path / "frame.bin"
    still.write_bytes(b"\x00" * 64)
    clip = tmp_path / "clip.bin"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)

    asyncio.run(
        vlm_model._call_anthropic_vlm(
            [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": still.as_uri(),
                        "mediaType": "image/tiff",
                    },
                },
            ],
            system_prompt="",
            temperature=0.2,
            timeout=5.0,
            api_key="an-test-key",
            base_url="https://api.anthropic.com",
            model_name="claude-sonnet-4-20250514",
        ),
    )
    assert (
        captured["body"]["messages"][0]["content"][0]["source"]["media_type"]
        == "image/tiff"
    )

    asyncio.run(
        vlm_model._call_gemini_vlm(
            [
                {
                    "type": "video_url",
                    "video_url": {
                        "url": clip.as_uri(),
                        "mediaType": "video/quicktime",
                    },
                },
            ],
            system_prompt="",
            temperature=0.2,
            timeout=5.0,
            api_key="gm-test-key",
            base_url="https://generativelanguage.googleapis.com",
            model_name="gemini-2.5-pro",
        ),
    )
    assert (
        captured["body"]["contents"][0]["parts"][0]["inline_data"]["mime_type"]
        == "video/quicktime"
    )


def test_meaningless_extension_does_not_outrank_a_confirmed_media_type():
    """``.bin`` guesses ``application/octet-stream``, which says nothing.

    CPython's built-in mime table maps ``.bin`` to the generic placeholder, so
    an asset filed under a meaningless suffix used to lose the type its caller
    had already confirmed. A real suffix still wins: ``.jpg`` knows more than
    the coarse ``image/png`` family default that ``multimodal_media_part``
    leaves in place for a part that declares nothing.
    """

    assert (
        vlm_model._mime_for_path(Path("image.bin"), "image/png") == "image/png"
    )
    assert (
        vlm_model._mime_for_path(Path("clip.mp4"), "image/png") == "video/mp4"
    )
    assert (
        vlm_model._mime_for_path(Path("photo.jpg"), "image/png")
        == "image/jpeg"
    )
    assert (
        vlm_model._mime_for_path(Path("no-suffix"), "image/png") == "image/png"
    )
    # With nothing confirmed either, the placeholder remains the only answer.
    assert (
        vlm_model._mime_for_path(Path("image.bin"), "")
        == vlm_model._GENERIC_MIME
    )


def test_a_placeholder_media_type_does_not_defeat_the_family_fallback(
    tmp_path,
    monkeypatch,
):
    """``application/octet-stream`` is what an unnamed upload form submits.

    Treating it as a confirmed type left a suffixless clip inlined as
    ``data:application/octet-stream`` — the header both SDK formatters drop —
    while the same part declaring nothing at all correctly fell back to
    ``video/mp4``.  A placeholder cannot outrank a family guess, and a real
    declaration still wins.
    """

    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_max_inline_bytes",
        lambda: 1024 * 1024,
    )
    clip = tmp_path / "media-blob"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)

    def inline(media_type: str) -> str:
        part = {
            "type": "video_url",
            "video_url": {"url": clip.as_uri(), "mediaType": media_type},
        }
        transported, uses_temp_oss = _transport(
            part,
            "gpt-vision",
            "https://api.openai.example/v1",
        )
        assert uses_temp_oss is False
        return str(transported["video_url"]["url"]).split(";", maxsplit=1)[0]

    assert inline("application/octet-stream") == "data:video/mp4"
    assert inline("") == "data:video/mp4"
    assert inline("video/quicktime") == "data:video/quicktime"

    still_image = tmp_path / "frame-blob"
    Image.new("RGB", (8, 8), color="blue").save(still_image, format="PNG")
    part = {
        "type": "image_url",
        "image_url": {
            "url": still_image.as_uri(),
            "mediaType": "application/octet-stream",
        },
    }
    transported, _ = _transport(
        part,
        "gpt-vision",
        "https://api.openai.example/v1",
    )
    assert str(transported["image_url"]["url"]).startswith(
        "data:image/png;base64,",
    )


def test_inlined_media_keeps_its_type_through_the_sdk_formatters(
    tmp_path,
    monkeypatch,
):
    """The whole path, because the loss happened outside our own assertions.

    A PNG filed as ``image.bin`` used to leave the inline transport as
    ``data:application/octet-stream``, ``native_content_blocks`` then reads the
    media type off that header, and both pinned formatters drop a block whose
    type they do not list: the understanding request went out with text only.
    """

    source = tmp_path / "image.bin"
    Image.new("RGB", (8, 8), color="blue").save(source, format="PNG")
    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_max_inline_bytes",
        lambda: 1024 * 1024,
    )
    part = {
        "type": "image_url",
        "image_url": {"url": source.as_uri(), "mediaType": "image/png"},
    }

    transported, uses_temp_oss = _transport(
        part,
        "gpt-vision",
        "https://api.openai.example/v1",
    )
    assert uses_temp_oss is False
    assert str(transported["image_url"]["url"]).startswith(
        "data:image/png;base64,",
    )

    text = {"type": "text", "text": "look"}
    assert _formatted_media_blocks([transported, text]) == {
        "openai": ["image_url"],
        "anthropic": ["image"],
    }
    # The header the fix protects against, fed to the same formatters.
    placeholder = dict(
        transported,
        image_url={
            "url": transported["image_url"]["url"].replace(
                "data:image/png",
                "data:application/octet-stream",
            ),
        },
    )
    assert _formatted_media_blocks([placeholder, text]) == {
        "openai": [],
        "anthropic": [],
    }


def test_maas_host_uses_the_temporary_upload_like_dashscope(
    tmp_path,
    monkeypatch,
):
    """A MaaS deployment serves the DashScope API without naming it.

    Classifying it as a generic gateway would push local media onto the inline
    Base64 budget instead of the 1GB temporary OSS upload, and disagree with
    how the image backend already routes the same host.
    """

    maas = "https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1"
    assert vlm_model._is_dashscope_provider(maas) is True

    image = tmp_path / "reference.png"
    image.write_bytes(b"png")

    async def fake_upload(path, *, api_key, model_name, media_type):
        del path, api_key, model_name
        return f"oss://dashscope-instant/{media_type}"

    monkeypatch.setattr(
        vlm_model,
        "upload_local_file_to_dashscope_temp",
        fake_upload,
    )
    part = vlm_model.multimodal_media_part(image.as_uri(), "image")
    transported, uses_temp_oss = _transport(part, "qwen3-vl", maas)
    assert uses_temp_oss is True
    assert (
        transported["image_url"]["url"] == "oss://dashscope-instant/image/png"
    )

    # A lookalike must not be handed the DashScope bearer key.
    assert (
        vlm_model._is_dashscope_provider(
            "https://evil.example/.maas.aliyuncs.com",
        )
        is False
    )


def test_local_media_transport_dashscope_temp_and_data_url_fallback(
    tmp_path,
    monkeypatch,
):
    # Golden: max_frames is accepted but never forwarded; fps survives.
    assert vlm_model.multimodal_media_part(
        "https://cdn.example.com/clip.mp4",
        "video",
        fps=0.5,
        max_frames=12.9,
    ) == {
        "type": "video_url",
        "video_url": {"url": "https://cdn.example.com/clip.mp4"},
        "fps": 0.5,
    }

    image = tmp_path / "reference.png"
    image.write_bytes(b"png")
    observed = {}

    async def fake_upload(path, *, api_key, model_name, media_type):
        observed["call"] = (path, api_key, model_name, media_type)
        return "oss://dashscope-instant/reference.png"

    mc = vlm_model.model_config
    monkeypatch.setattr(mc, "get_vlm_base_url", lambda: DASHSCOPE)
    monkeypatch.setattr(
        vlm_model,
        "upload_local_file_to_dashscope_temp",
        fake_upload,
    )
    part = vlm_model.multimodal_media_part(image.as_uri(), "image")
    transported, uses_temp_oss = _transport(part, "qwen3-vl", DASHSCOPE)
    assert uses_temp_oss is True
    assert transported == {
        "type": "image_url",
        "image_url": {"url": "oss://dashscope-instant/reference.png"},
    }
    expected = (image.resolve(), "vlm-key", "qwen3-vl", "image/png")
    assert observed["call"] == expected

    # Off DashScope the transport inlines a bounded data URL instead.
    off = "https://api.openai.example/v1"
    monkeypatch.setattr(mc, "get_vlm_base_url", lambda: off)
    monkeypatch.setattr(mc, "get_vlm_max_inline_bytes", lambda: 1024)
    transported, uses_temp_oss = _transport(
        part,
        "gpt-vision",
        "https://api.openai.com/v1",
    )
    assert uses_temp_oss is False
    assert transported == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,cG5n"},
    }


def test_oversized_image_is_downscaled_instead_of_refused(
    tmp_path,
    monkeypatch,
):
    """An image over the inline budget is re-encoded, not refused.

    Providers bill vision tokens rather than request bytes, so a downscaled
    image still answers the question whereas a hard refusal leaves the
    understanding record silently empty.
    """

    image = tmp_path / "large.bmp"
    # BMP is uncompressed, so the byte size is predictable.
    Image.new("RGB", (1200, 1200), color="blue").save(image, format="BMP")
    assert image.stat().st_size > 64 * 1024

    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_max_inline_bytes",
        lambda: 64 * 1024,
    )
    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_model_name",
        lambda: "gpt-vision",
    )

    url = vlm_model._data_url(image, "image/png")

    assert url.startswith("data:image/jpeg;base64,")
    payload = base64.b64decode(url.split(",", 1)[1])
    assert len(payload) <= 64 * 1024
    # The re-encoded image is still decodable and carries real pixels.
    with Image.open(io.BytesIO(payload)) as decoded:
        assert decoded.size[0] > 0 and decoded.size[1] > 0


def test_downscaled_image_is_rotated_to_match_exif_orientation(
    tmp_path,
    monkeypatch,
):
    """Re-encoding must not leave a portrait phone photo on its side.

    ``thumbnail`` + ``save`` drops the EXIF Orientation tag, so the pixels
    have to be rotated first: otherwise the VLM is handed a frame that no
    viewer would render the way the camera captured it.
    """

    image = tmp_path / "portrait.jpg"
    # 1200x400 pixels stored sideways, tagged "rotate 90 CW" like a phone.
    frame = Image.new("RGB", (1200, 400), color="blue")
    exif = frame.getexif()
    exif[0x0112] = 6
    frame.save(image, format="JPEG", exif=exif)
    assert image.stat().st_size > 4096

    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_max_inline_bytes",
        lambda: 4096,
    )
    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_model_name",
        lambda: "gpt-vision",
    )

    url = vlm_model._data_url(image, "image/jpeg")

    payload = base64.b64decode(url.split(",", 1)[1])
    assert len(payload) <= 4096
    with Image.open(io.BytesIO(payload)) as decoded:
        # Upright portrait, with no tag left to contradict the pixels.
        assert decoded.size[1] > decoded.size[0]
        assert decoded.getexif().get(0x0112) is None


def test_downscale_composites_transparency_onto_white(tmp_path):
    """A screenshot's transparent background must not come back black.

    Dropping the alpha channel keeps whatever the encoder stored under the
    transparent pixels, which for a UI capture is black: the page would
    reach the VLM as pale text on black. Opaque content keeps its colour.
    """

    image = tmp_path / "screenshot.png"
    # Fully transparent canvas whose stored RGB is black, plus dark "text".
    frame = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
    text = Image.new("RGBA", (32, 8), color=(20, 20, 20, 255))
    frame.paste(text, (16, 28))
    frame.save(image, format="PNG")

    payload = vlm_model._downscale_image_to_budget(image, 64 * 1024)

    assert payload is not None
    with Image.open(io.BytesIO(payload)) as decoded:
        assert decoded.mode == "RGB"
        # The transparent corner was composited onto white, not black.
        assert min(decoded.getpixel((0, 0))) > 180
        # The opaque text survived the composite instead of washing out.
        assert max(decoded.getpixel((32, 32))) < 120


def test_flatten_alpha_covers_every_mode_that_carries_transparency():
    """LA and palette transparency take the same white-composite path.

    A screenshot is RGBA, but a scanned page can arrive as LA and a legacy
    asset as a palette with a transparent index. All three must composite;
    an image without alpha is merely converted.
    """

    white = (255, 255, 255)
    rgba = Image.new("RGBA", (4, 4), color=(0, 0, 0, 0))
    assert vlm_model._flatten_alpha(rgba).getpixel((0, 0)) == white

    grey = Image.new("LA", (4, 4), color=(0, 0))
    assert vlm_model._flatten_alpha(grey).getpixel((0, 0)) == white

    palette = Image.new("P", (4, 4), color=0)
    palette.putpalette([0, 0, 0, 20, 20, 20] + [0] * (254 * 3))
    # Index 0 is the transparent one, and it stores black underneath.
    palette.info["transparency"] = 0
    assert vlm_model._flatten_alpha(palette).getpixel((0, 0)) == white

    opaque = Image.new("L", (4, 4), color=30)
    assert vlm_model._flatten_alpha(opaque).getpixel((0, 0)) == (30, 30, 30)

    # A palette without a transparent index has nothing to composite.
    solid = Image.new("P", (4, 4), color=1)
    solid.putpalette([0, 0, 0, 40, 40, 40] + [0] * (254 * 3))
    assert vlm_model._flatten_alpha(solid).getpixel((0, 0)) == (40, 40, 40)


def test_trns_colour_key_takes_the_white_composite_path(tmp_path):
    """RGB and L PNGs carry transparency as a colour key, not as alpha.

    Saving with ``transparency=(0, 0, 0)`` writes a ``tRNS`` chunk and leaves
    the mode at RGB, so the mode alone cannot answer "is this transparent?".
    Measured on Pillow 10.0.1 — the declared floor — and on 13.0.0:
    ``convert("RGBA")`` applies the key, yielding alpha 0 on the keyed pixels
    and alpha 255 where the key matches nothing.
    """

    keyed = tmp_path / "keyed.png"
    Image.new("RGB", (4, 4), color=(0, 0, 0)).save(
        keyed,
        format="PNG",
        transparency=(0, 0, 0),
    )
    with Image.open(keyed) as opened:
        assert opened.mode == "RGB"
        assert "transparency" in opened.info
        assert vlm_model._flatten_alpha(opened).getpixel((0, 0)) == (
            255,
            255,
            255,
        )

    grey = tmp_path / "grey-key.png"
    Image.new("L", (4, 4), color=0).save(grey, format="PNG", transparency=0)
    with Image.open(grey) as opened:
        assert opened.mode == "L"
        assert vlm_model._flatten_alpha(opened).getpixel((0, 0)) == (
            255,
            255,
            255,
        )

    # A key that matches no pixel makes nothing transparent: colour survives.
    unmatched = tmp_path / "unmatched.png"
    Image.new("RGB", (4, 4), color=(9, 9, 9)).save(
        unmatched,
        format="PNG",
        transparency=(0, 0, 0),
    )
    with Image.open(unmatched) as opened:
        assert vlm_model._flatten_alpha(opened).getpixel((0, 0)) == (9, 9, 9)

    # A PNG with no key at all still takes the RGB fast path unchanged.
    plain = Image.new("RGB", (4, 4), color=(0, 0, 0))
    assert vlm_model._flatten_alpha(plain) is plain


def test_reencoded_keyed_png_composites_to_white(tmp_path):
    """The reported symptom, asserted on pixels rather than on metadata.

    A keyed RGB PNG over the inline budget used to re-encode as solid black,
    because the fast path never looked for the key, so the VLM saw a filled
    background where the asset has none. The keyed half is transparent and the
    pasted half is real content, which is the pair the composite has to get
    right in both directions.
    """

    source = tmp_path / "keyed.png"
    frame = Image.new("RGB", (64, 64), color=(0, 0, 0))
    frame.paste(Image.new("RGB", (32, 8), color=(20, 20, 20)), (16, 28))
    frame.save(source, format="PNG", transparency=(0, 0, 0))

    payload = vlm_model._downscale_image_to_budget(source, 64 * 1024)

    assert payload is not None
    with Image.open(io.BytesIO(payload)) as decoded:
        assert decoded.format == "JPEG"
        assert decoded.mode == "RGB"
        # The keyed corner became the documented white, not stored black.
        assert min(decoded.getpixel((0, 0))) > 180
        # Pixels the key does not match kept their own colour.
        assert max(decoded.getpixel((32, 32))) < 120


def test_oversized_non_image_media_still_refused_with_guidance(
    tmp_path,
    monkeypatch,
):
    """A clip cannot be downscaled here, so the refusal must say what to do."""

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00" * 4096)

    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_max_inline_bytes",
        lambda: 1024,
    )
    monkeypatch.setattr(
        vlm_model.model_config,
        "get_vlm_model_name",
        lambda: "gpt-vision",
    )

    with pytest.raises(ModelError, match="VLM_MAX_INLINE_BYTES"):
        vlm_model._data_url(clip, "video/mp4")


def test_chat_completion_preserves_mixed_content_parts_in_request(monkeypatch):
    captured: dict[str, object] = {}
    content = [
        {
            "type": "image_url",
            "image_url": {"url": "https://cdn.example.com/reference.png"},
        },
        {
            "type": "video_url",
            "video_url": {"url": "https://cdn.example.com/clip.mp4"},
            "fps": 1.0,
            "max_frames": 24,
        },
        {"type": "text", "text": "请比较图像和视频。"},
    ]

    class FakeCapabilityCache:
        def get(self, model, capability):
            captured["capability_get"] = (model, capability)
            return None

        def learn(self, model, capability, value):
            captured["capability_learn"] = (model, capability, value)

    class FakeResponse:
        text = ""
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            message = {
                "content": [
                    {"type": "text", "text": "看到了图像"},
                    {"type": "text", "text": "也看到了完整视频"},
                ],
            }
            return {
                "choices": [{"finish_reason": "stop", "message": message}],
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

        async def post(self, url, *, headers, json):
            captured.update(url=url, headers=headers, body=json)
            return FakeResponse()

    @asynccontextmanager
    async def fake_model_slot(_kind):
        yield

    monkeypatch.setattr(
        vlm_model,
        "get_capability_cache",
        lambda: FakeCapabilityCache(),
    )
    monkeypatch.setattr(vlm_model, "model_slot", fake_model_slot)
    monkeypatch.setattr(vlm_model.httpx, "AsyncClient", FakeAsyncClient)
    config = {
        "get_vlm_api_key": "test-vlm-key",
        "get_vlm_model_name": "qwen3.7-plus",
        "get_vlm_chat_url": "https://provider.example/v1/chat/completions",
        "get_vlm_timeout_seconds": 31.0,
    }
    for name, value in config.items():
        monkeypatch.setattr(vlm_model.model_config, name, lambda v=value: v)

    result = asyncio.run(
        vlm_model.chat_completion(
            content,
            system_prompt="  仅分析提供的素材。  ",
            temperature=0.1,
        ),
    )

    assert result == "看到了图像\n也看到了完整视频"
    assert captured["capability_get"] == ("vlm:qwen3.7-plus", "rejects_media")
    video_part = {
        "type": "video_url",
        "video_url": {"url": "https://cdn.example.com/clip.mp4"},
        "fps": 1.0,
    }
    assert captured["body"] == {
        "model": "qwen3.7-plus",
        "messages": [
            {"role": "system", "content": "仅分析提供的素材。"},
            {"role": "user", "content": [content[0], video_part, content[2]]},
        ],
        "temperature": 0.1,
        "enable_thinking": False,
    }
    assert content[1]["max_frames"] == 24
    assert captured["headers"]["Authorization"] == "Bearer test-vlm-key"


def test_invalid_media_payload_does_not_poison_capability_cache() -> None:
    dims_error = (
        "The image length and width do not meet the model restrictions; "
        "width must be larger than 10"
    )
    assert not vlm_model._is_media_related_error(dims_error)
    assert vlm_model._is_media_related_error(
        "This model does not support multimodal input",
    )


def test_anthropic_caller_rejects_video_before_io_or_http(
    monkeypatch,
) -> None:
    def unexpected_inline(*_args, **_kwargs):
        raise AssertionError("video bytes must not be read")

    class UnexpectedClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("provider must not be called")

    monkeypatch.setattr(vlm_model, "_inline_base64", unexpected_inline)
    monkeypatch.setattr(vlm_model.httpx, "AsyncClient", UnexpectedClient)

    with pytest.raises(ModelError, match="does not support video") as caught:
        asyncio.run(
            vlm_model._call_anthropic_vlm(
                [
                    {
                        "type": "video_url",
                        "video_url": {"url": "file:///tmp/clip.mp4"},
                    },
                    {"type": "text", "text": "What happens in this video?"},
                ],
                system_prompt="",
                temperature=0.2,
                timeout=5.0,
                api_key="test-key",
                base_url="https://api.anthropic.com",
                model_name="claude-test",
            ),
        )

    assert caught.value.retryable is False


def test_image_bytes_settle_a_label_the_file_name_gets_wrong(tmp_path):
    """A suffix can be wrong in the other direction, and the bytes decide.

    Whatever ``_mime_for_path`` returns ends up in the data URL header that
    ``native_content`` reads, so a converter that wrote a GIF under a ``.png``
    suffix used to cost the block its real type — and the review's counter-
    case showed a confirmed declaration losing to a wrong-but-specific
    extension. Sniffing the payload settles both.
    """

    gif = tmp_path / "sticker.png"
    gif.write_bytes(b"GIF89a" + b"\x00" * 24)
    assert vlm_model._mime_for_path(gif, "image/png") == "image/gif"

    png = tmp_path / "frame.jpg"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)
    assert vlm_model._mime_for_path(png, "") == "image/png"

    webp = tmp_path / "icon.png"
    webp.write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
    assert vlm_model._mime_for_path(webp, "image/png") == "image/webp"

    # Video is not sniffed, so the suffix still answers for it.
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 8)
    assert vlm_model._mime_for_path(clip, "image/png") == "video/mp4"
