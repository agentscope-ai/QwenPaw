# -*- coding: utf-8 -*-
"""Tests for video size capping in the model_factory video helpers.

Tool-result videos inline through ``_format_openai_video_block`` and
``_format_anthropic_video_data_block`` rather than the capping formatters
(which only intercept ``_format_*_source``), so the inline byte cap is
enforced inside those helpers.  These tests pin that behaviour for both
the local-file (``file://`` / ``url``) and in-memory (``base64``) source
shapes, for both wire formats.
"""

# pylint: disable=protected-access
from agentscope.message import DataBlock, URLSource

from qwenpaw.agents.model_factory import (
    MAX_INLINE_MEDIA_BYTES,
    _format_anthropic_video_data_block,
    _format_openai_video_block,
)


def _write_video(tmp_path, name: str, size: int) -> str:
    """Write a ``size``-byte file and return its ``file://`` URL."""
    path = tmp_path / name
    path.write_bytes(b"\x00" * size)
    return f"file://{path}"


# --------------------------------------------------------------------- OpenAI


def test_openai_url_video_under_cap_is_inlined(tmp_path) -> None:
    url = _write_video(tmp_path, "small.mp4", MAX_INLINE_MEDIA_BYTES)
    block = {"source": {"type": "url", "url": url}}
    out = _format_openai_video_block(block)
    assert out["type"] == "video_url"
    assert out["video_url"]["url"].startswith("data:video/mp4;base64,")


def test_openai_url_video_over_cap_is_placeholder(tmp_path) -> None:
    url = _write_video(tmp_path, "big.mp4", MAX_INLINE_MEDIA_BYTES + 1)
    block = {"source": {"type": "url", "url": url}}
    out = _format_openai_video_block(block)
    assert out["type"] == "text"
    assert "video omitted from model context" in out["text"]
    assert str(MAX_INLINE_MEDIA_BYTES + 1) in out["text"]


def test_openai_base64_video_over_cap_is_placeholder() -> None:
    # base64 of (cap+1) raw bytes -> length * 3//4 > cap.
    import base64

    data = base64.b64encode(b"\x00" * (MAX_INLINE_MEDIA_BYTES + 1)).decode()
    block = {
        "source": {
            "type": "base64",
            "media_type": "video/mp4",
            "data": data,
        },
    }
    out = _format_openai_video_block(block)
    assert out["type"] == "text"
    assert "video omitted from model context" in out["text"]


def test_openai_base64_video_under_cap_is_inlined() -> None:
    import base64

    data = base64.b64encode(b"\x00" * 16).decode()
    block = {
        "source": {
            "type": "base64",
            "media_type": "video/mp4",
            "data": data,
        },
    }
    out = _format_openai_video_block(block)
    assert out["type"] == "video_url"
    assert out["video_url"]["url"].startswith("data:video/mp4;base64,")


def test_openai_remote_url_video_is_passed_through() -> None:
    block = {"source": {"type": "url", "url": "https://example.com/v.mp4"}}
    out = _format_openai_video_block(block)
    # Remote URL is not read from disk; pass through unchanged (no cap).
    assert out["video_url"]["url"] == "https://example.com/v.mp4"


# ------------------------------------------------------------------ Anthropic


def test_anthropic_url_video_over_cap_is_placeholder(tmp_path) -> None:
    url = _write_video(tmp_path, "big.mp4", MAX_INLINE_MEDIA_BYTES + 1)
    block = DataBlock(source=URLSource(url=url, media_type="video/mp4"))
    out = _format_anthropic_video_data_block(block)
    assert out["type"] == "text"
    assert "video omitted from model context" in out["text"]


def test_anthropic_url_video_under_cap_is_inlined(tmp_path) -> None:
    url = _write_video(tmp_path, "small.mp4", MAX_INLINE_MEDIA_BYTES)
    block = DataBlock(source=URLSource(url=url, media_type="video/mp4"))
    out = _format_anthropic_video_data_block(block)
    assert out["type"] == "video"
    assert out["source"]["type"] == "base64"
    assert out["source"]["media_type"] == "video/mp4"


def test_anthropic_base64_video_over_cap_is_placeholder() -> None:
    from agentscope.message import Base64Source

    import base64

    data = base64.b64encode(b"\x00" * (MAX_INLINE_MEDIA_BYTES + 1)).decode()
    block = DataBlock(
        source=Base64Source(type="base64", media_type="video/mp4", data=data),
    )
    out = _format_anthropic_video_data_block(block)
    assert out["type"] == "text"
    assert "video omitted from model context" in out["text"]


def test_anthropic_base64_video_under_cap_is_inlined() -> None:
    from agentscope.message import Base64Source

    import base64

    data = base64.b64encode(b"\x00" * 16).decode()
    block = DataBlock(
        source=Base64Source(type="base64", media_type="video/mp4", data=data),
    )
    out = _format_anthropic_video_data_block(block)
    assert out["type"] == "video"
    assert out["source"]["data"] == data


def test_anthropic_missing_file_returns_none(tmp_path) -> None:
    block = DataBlock(
        source=URLSource(
            url=f"file://{tmp_path / 'nope.mp4'}",
            media_type="video/mp4",
        ),
    )
    assert _format_anthropic_video_data_block(block) is None
