# -*- coding: utf-8 -*-
"""Integration tests for the agent model factory media helpers.

Covers src/qwenpaw/agents/model_factory.py (466 uncovered lines):
media kind detection, source field access, base64 encoding, wire
media block counting, anthropic media dedup keys.
"""

from __future__ import annotations

import base64

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_media_kind_direct_media_types() -> None:
    """image/audio/video block types map to their kinds."""
    from qwenpaw.agents.model_factory import _media_kind

    for kind in ("image", "audio", "video"):
        assert _media_kind({"type": kind}) == kind


@pytest.mark.integration
@pytest.mark.p1
def test_media_kind_non_media_block() -> None:
    """Text and tool blocks have no media kind."""
    from qwenpaw.agents.model_factory import _media_kind

    assert _media_kind({"type": "text"}) is None
    assert _media_kind({"type": "tool_use"}) is None
    assert _media_kind({}) is None


@pytest.mark.integration
@pytest.mark.p1
def test_media_kind_data_block_with_media_type() -> None:
    """type=data blocks infer the kind from source media_type."""
    from qwenpaw.agents.model_factory import _media_kind

    block = {"type": "data", "source": {"media_type": "image/png"}}
    assert _media_kind(block) == "image"


@pytest.mark.integration
@pytest.mark.p1
def test_media_kind_data_block_unknown_media_type() -> None:
    """data blocks with non-media types yield None."""
    from qwenpaw.agents.model_factory import _media_kind

    block = {"type": "data", "source": {"media_type": "application/json"}}
    assert _media_kind(block) is None


@pytest.mark.integration
@pytest.mark.p1
def test_media_kind_object_block() -> None:
    """Object blocks with a type attribute are handled."""
    from qwenpaw.agents.model_factory import _media_kind

    class FakeBlock:
        type = "audio"

    assert _media_kind(FakeBlock()) == "audio"


@pytest.mark.integration
@pytest.mark.p1
def test_media_source_value_dict() -> None:
    """Dict sources read fields with defaults."""
    from qwenpaw.agents.model_factory import _media_source_value

    source = {"media_type": "image/png", "data": "abc"}
    assert _media_source_value(source, "media_type") == "image/png"
    assert _media_source_value(source, "missing", "d") == "d"


@pytest.mark.integration
@pytest.mark.p1
def test_media_source_value_object() -> None:
    """Pydantic-style sources read attributes."""
    from qwenpaw.agents.model_factory import _media_source_value

    class FakeSource:
        media_type = "audio/wav"

    assert _media_source_value(FakeSource(), "media_type") == "audio/wav"
    assert _media_source_value(FakeSource(), "nope", "d") == "d"


@pytest.mark.integration
@pytest.mark.p1
def test_encode_media_bytes() -> None:
    """Bytes are base64-encoded to UTF-8 text."""
    from qwenpaw.agents.model_factory import _encode_media_bytes

    encoded = _encode_media_bytes(b"hello media")
    assert base64.b64decode(encoded) == b"hello media"


@pytest.mark.integration
@pytest.mark.p1
def test_encode_media_bytes_empty() -> None:
    """Empty input encodes to an empty string."""
    from qwenpaw.agents.model_factory import _encode_media_bytes

    assert _encode_media_bytes(b"") == ""


@pytest.mark.integration
@pytest.mark.p1
def test_anthropic_media_dedup_key_url() -> None:
    """URL sources key on (url, media_type, url)."""
    from qwenpaw.agents.model_factory import _anthropic_media_dedup_key

    class Source:
        media_type = "image/png"
        url = "http://x/a.png"
        data = ""

    key = _anthropic_media_dedup_key(Source())
    assert key == ("url", "image/png", "http://x/a.png")


@pytest.mark.integration
@pytest.mark.p1
def test_anthropic_media_dedup_key_base64_data() -> None:
    """Inline base64 sources key on data content."""
    from qwenpaw.agents.model_factory import _anthropic_media_dedup_key

    class Source:
        media_type = "image/png"
        url = None
        data = "aGVsbG8="

    key = _anthropic_media_dedup_key(Source())
    assert key is not None
    assert key[0] != "url"


@pytest.mark.integration
@pytest.mark.p1
def test_anthropic_media_dedup_key_empty_source() -> None:
    """Sources without url or data yield None."""
    from qwenpaw.agents.model_factory import _anthropic_media_dedup_key

    class Source:
        media_type = ""
        url = None
        data = ""

    assert _anthropic_media_dedup_key(Source()) is None


@pytest.mark.integration
@pytest.mark.p1
def test_count_wire_media_blocks_flat() -> None:
    """Flat wire media block dicts count as one each."""
    from qwenpaw.agents.model_factory import _count_wire_media_blocks

    assert _count_wire_media_blocks({"type": "image"}) == 1
    assert _count_wire_media_blocks({"type": "input_audio"}) == 1
    assert _count_wire_media_blocks({"type": "text"}) == 0


@pytest.mark.integration
@pytest.mark.p1
def test_count_wire_media_blocks_nested() -> None:
    """Nested lists and dicts aggregate counts."""
    from qwenpaw.agents.model_factory import _count_wire_media_blocks

    payload = {
        "content": [
            {"type": "image"},
            {"type": "text"},
            {"inner": [{"type": "video"}]},
        ],
    }
    assert _count_wire_media_blocks(payload) == 2


@pytest.mark.integration
@pytest.mark.p1
def test_count_wire_media_blocks_container_keys() -> None:
    """file_data / inline_data container keys count as media."""
    from qwenpaw.agents.model_factory import _count_wire_media_blocks

    assert _count_wire_media_blocks({"file_data": {"x": 1}}) == 1
    assert _count_wire_media_blocks({"inline_data": "abc"}) == 1
    assert _count_wire_media_blocks({}) == 0


@pytest.mark.integration
@pytest.mark.p1
def test_count_wire_media_blocks_scalar() -> None:
    """Scalar payloads contain no media blocks."""
    from qwenpaw.agents.model_factory import _count_wire_media_blocks

    assert _count_wire_media_blocks("just text") == 0
    assert _count_wire_media_blocks(None) == 0
