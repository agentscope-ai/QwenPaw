# -*- coding: utf-8 -*-
"""Cover the module-level media helpers of ``agents/model_factory.py``.

``tests/unit/agents/test_model_factory_message_normalization.py`` drives
the formatter-integration side (message normalization, video capping,
remote media download) and already pins the ``DataBlock`` file-URI
preservation rules of ``_fixup_media_list``.  What stayed uncovered are
the standalone helpers around it:

* ``_media_source_key`` — the dedup key derived from a media block.
* ``_fix_image_mime_types`` — the non-IANA ``image/jpg`` repair, in both
  the Chat Completions shape (``image_url`` is a dict) and the Responses
  API shape (``image_url`` is a plain string).
* ``_is_block_dropped_by_formatter`` — the assistant-survival predictor
  added for #5858.
* ``_stabilize_promoted_tool_result_media_identifiers`` — the workaround
  that replaces formatter-generated media labels with content-derived
  stable identifiers.
* the remaining ``_fixup_media_list`` branches: dict media blocks (the
  1.x shape), deleted-file placeholders, ``data`` blocks whose local file
  is gone, ``file`` blocks (always converted to text), and the
  ``tool_result`` recursion.

All five are pure or in-place list/dict rewriters, so they are exercised
directly with real files under ``tmp_path`` rather than with a patched
filesystem, except where a test says otherwise.
"""
# pylint: disable=protected-access,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

import pytest
from agentscope.message import TextBlock

from qwenpaw.agents import model_factory as mf


def _existing(tmp_path, name: str = "real.png") -> str:
    """Create a real file and return its absolute path."""
    path = tmp_path / name
    path.write_bytes(b"payload")
    return str(path)


def _gone(tmp_path, name: str = "gone.png") -> str:
    """Return an absolute path that does not exist."""
    return str(tmp_path / name)


def _data_block(media_type: str, url: str) -> SimpleNamespace:
    """A 2.0-shaped data block with attribute access on ``source``.

    ``DataBlock``/``URLSource`` from agentscope would work too, but the
    helpers only use ``getattr(block, "source")`` and
    ``getattr(source, ...)``; a plain namespace keeps the intent visible
    and avoids depending on pydantic validation of a file:// URL.
    """
    return SimpleNamespace(
        type="data",
        source=SimpleNamespace(type="url", url=url, media_type=media_type),
    )


class _Formatter:
    """Minimal stand-in exposing ``supported_input_media_types``."""

    def __init__(self, supported) -> None:
        self.supported_input_media_types = supported


# ---------------------------------------------------------------------------
# _media_source_key
# ---------------------------------------------------------------------------
def test_media_source_key_base64_has_nothing_to_compare() -> None:
    block = {"source": {"type": "base64", "data": "QUJD"}}
    assert mf._media_source_key(block) is None


def test_media_source_key_empty_url_is_none() -> None:
    assert mf._media_source_key({"source": {"type": "url", "url": ""}}) is None


def test_media_source_key_missing_source_is_none() -> None:
    assert mf._media_source_key({}) is None
    assert mf._media_source_key({"source": {}}) is None


def test_media_source_key_normalises_local_file_url(tmp_path) -> None:
    real = _existing(tmp_path)
    block = {"source": {"type": "url", "url": "file://" + real}}
    # file:// is resolved to a path, then normpath'ed (dots and duplicate
    # separators collapsed) so the same file yields the same dedup key.
    assert mf._media_source_key(block) == real

    doubled = {"source": {"type": "url", "url": "file:///tmp//a/../b.png"}}
    assert mf._media_source_key(doubled) == "/tmp/b.png"


def test_media_source_key_keeps_remote_url_verbatim() -> None:
    block = {"source": {"type": "url", "url": "http://host/a/../b.png"}}
    assert mf._media_source_key(block) == "http://host/a/../b.png"


def test_media_source_key_keeps_relative_url_verbatim() -> None:
    block = {"source": {"type": "url", "url": "relative/path.png"}}
    assert mf._media_source_key(block) == "relative/path.png"


# ---------------------------------------------------------------------------
# _fix_image_mime_types
# ---------------------------------------------------------------------------
def test_mime_fix_repairs_chat_completions_dict_shape() -> None:
    msgs = [
        {
            "content": [
                {"image_url": {"url": "data:image/jpg;base64,QUJD"}},
            ],
        },
    ]
    mf._fix_image_mime_types(msgs)
    assert msgs[0]["content"][0]["image_url"]["url"] == (
        "data:image/jpeg;base64,QUJD"
    )


def test_mime_fix_repairs_responses_api_string_shape() -> None:
    msgs = [{"content": [{"image_url": "data:image/jpg;base64,QUJD"}]}]
    mf._fix_image_mime_types(msgs)
    assert msgs[0]["content"][0]["image_url"] == "data:image/jpeg;base64,QUJD"


def test_mime_fix_leaves_valid_jpeg_alone() -> None:
    msgs = [
        {"content": [{"image_url": {"url": "data:image/jpeg;base64,QUJD"}}]},
    ]
    mf._fix_image_mime_types(msgs)
    assert msgs[0]["content"][0]["image_url"]["url"] == (
        "data:image/jpeg;base64,QUJD"
    )


def test_mime_fix_leaves_non_data_url_alone() -> None:
    msgs = [{"content": [{"image_url": {"url": "http://host/a.jpg"}}]}]
    mf._fix_image_mime_types(msgs)
    assert msgs[0]["content"][0]["image_url"]["url"] == "http://host/a.jpg"


def test_mime_fix_replaces_only_the_first_occurrence() -> None:
    url = "data:image/jpg;base64,data:image/jpg;"
    msgs = [{"content": [{"image_url": {"url": url}}]}]
    mf._fix_image_mime_types(msgs)
    assert msgs[0]["content"][0]["image_url"]["url"] == (
        "data:image/jpeg;base64,data:image/jpg;"
    )


def test_mime_fix_skips_blocks_without_a_usable_url() -> None:
    text_block: dict[str, Any] = {"type": "text", "text": "no image_url key"}
    none_block: dict[str, Any] = {"image_url": None}
    int_block: dict[str, Any] = {"image_url": 123}
    content: list[Any] = [
        text_block,
        none_block,
        int_block,
        "not-a-dict-block",
    ]
    msgs: list[dict[str, Any]] = [{"content": content}]
    mf._fix_image_mime_types(msgs)
    assert text_block["text"] == "no image_url key"
    assert none_block["image_url"] is None
    assert int_block["image_url"] == 123
    assert content[3] == "not-a-dict-block"


def test_mime_fix_skips_messages_without_list_content() -> None:
    msgs = [{"content": "plain string"}, {"role": "user"}]
    mf._fix_image_mime_types(msgs)
    assert msgs == [{"content": "plain string"}, {"role": "user"}]


def test_mime_fix_is_a_noop_on_empty_input() -> None:
    msgs: list = []
    mf._fix_image_mime_types(msgs)
    assert msgs == []


# ---------------------------------------------------------------------------
# _is_block_dropped_by_formatter
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("btype", ["text", "tool_use", "tool_call"])
def test_survivor_block_types_are_never_dropped(btype: str) -> None:
    fmt = _Formatter(["image/*"])
    assert mf._is_block_dropped_by_formatter({"type": btype}, fmt) is False
    obj = SimpleNamespace(type=btype)
    assert mf._is_block_dropped_by_formatter(obj, fmt) is False


@pytest.mark.parametrize("btype", ["thinking", "hint", "file"])
def test_always_dropped_types_are_dropped_for_both_shapes(btype: str) -> None:
    fmt = _Formatter(["image/*"])
    assert mf._is_block_dropped_by_formatter({"type": btype}, fmt) is True
    assert (
        mf._is_block_dropped_by_formatter(
            SimpleNamespace(type=btype),
            fmt,
        )
        is True
    )


def test_tool_result_is_dropped_for_assistant_survival() -> None:
    # A tool_result produces its own role="tool" message; it flushes the
    # current content but never contributes to assistant content_blocks.
    fmt = _Formatter(["image/*"])
    assert mf._is_block_dropped_by_formatter({"type": "tool_result"}, fmt) is (
        True
    )
    assert (
        mf._is_block_dropped_by_formatter(
            SimpleNamespace(type="tool_result"),
            fmt,
        )
        is True
    )


@pytest.mark.parametrize("block", [{"type": "mystery"}, {}, None])
def test_unknown_or_typeless_block_is_dropped(block) -> None:
    fmt = _Formatter(["image/*"])
    assert mf._is_block_dropped_by_formatter(block, fmt) is True


def test_data_block_matching_supported_media_survives() -> None:
    block = _data_block("image/png", "file:///tmp/a.png")
    assert (
        mf._is_block_dropped_by_formatter(
            block,
            _Formatter(["image/*"]),
        )
        is False
    )


def test_data_block_with_unsupported_media_is_dropped() -> None:
    block = _data_block("audio/mpeg", "file:///tmp/a.mp3")
    assert (
        mf._is_block_dropped_by_formatter(
            block,
            _Formatter(["image/*"]),
        )
        is True
    )


def test_data_block_is_dropped_when_formatter_supports_nothing() -> None:
    block = _data_block("image/png", "file:///tmp/a.png")
    assert mf._is_block_dropped_by_formatter(block, _Formatter([])) is True


def test_data_block_is_dropped_when_formatter_lacks_the_attribute() -> None:
    block = _data_block("image/png", "file:///tmp/a.png")
    assert mf._is_block_dropped_by_formatter(block, SimpleNamespace()) is True


def test_data_block_without_source_or_media_type_is_dropped() -> None:
    fmt = _Formatter(["image/*"])
    assert (
        mf._is_block_dropped_by_formatter(
            SimpleNamespace(type="data", source=None),
            fmt,
        )
        is True
    )
    assert (
        mf._is_block_dropped_by_formatter(
            SimpleNamespace(
                type="data",
                source=SimpleNamespace(media_type=None),
            ),
            fmt,
        )
        is True
    )


def test_dict_shaped_data_block_is_dropped() -> None:
    # The data branch reads the source with getattr, which a dict does not
    # answer, so a 1.x-shaped data block is predicted dropped.
    assert (
        mf._is_block_dropped_by_formatter(
            {"type": "data", "source": {"media_type": "image/png"}},
            _Formatter(["image/*"]),
        )
        is True
    )


# ---------------------------------------------------------------------------
# _stabilize_promoted_tool_result_media_identifiers
# ---------------------------------------------------------------------------
def _label(name: str, kind: str = "image/png") -> TextBlock:
    return TextBlock(type="text", text=f"- {name} ({kind})")


def _media(url: str, media_type: str = "image/png") -> SimpleNamespace:
    return SimpleNamespace(
        source=SimpleNamespace(media_type=media_type, url=url),
    )


def test_stabilize_rewrites_label_and_bracketed_reference() -> None:
    text, out = mf._stabilize_promoted_tool_result_media_identifiers(
        "Result:\n[shot.png]\nend",
        [_label("shot.png"), _media("http://host/shot.png")],
    )
    new_label = out[0].text.split(" ")[1]
    assert new_label.startswith("qwenpaw-media-")
    assert out[0].text == f"- {new_label} (image/png)"
    assert text == f"Result:\n[{new_label}]\nend"


def test_stabilize_identifier_is_12_hex_chars() -> None:
    _, out = mf._stabilize_promoted_tool_result_media_identifiers(
        "x",
        [_label("a.png"), _media("http://host/a.png")],
    )
    digest = out[0].text.split("qwenpaw-media-")[1].split(" ")[0]
    assert len(digest) == 12
    assert all(c in "0123456789abcdef" for c in digest)


def test_stabilize_is_deterministic_for_identical_input() -> None:
    args = ("[a.png]", [_label("a.png"), _media("http://host/a.png")])
    first = mf._stabilize_promoted_tool_result_media_identifiers(*args)
    second = mf._stabilize_promoted_tool_result_media_identifiers(*args)
    assert first[0] == second[0]
    assert first[1][0].text == second[1][0].text


def test_stabilize_digest_follows_index_media_type_and_value() -> None:
    # Same label text, different media payload -> different identifier,
    # because the digest is derived from index + media_type + value.
    _, a = mf._stabilize_promoted_tool_result_media_identifiers(
        "x",
        [_label("same.png"), _media("http://host/one.png")],
    )
    _, b = mf._stabilize_promoted_tool_result_media_identifiers(
        "x",
        [_label("same.png"), _media("http://host/two.png")],
    )
    _, c = mf._stabilize_promoted_tool_result_media_identifiers(
        "x",
        [_label("same.png"), _media("http://host/one.png", "image/jpeg")],
    )
    ids = {x[0].text for x in (a, b, c)}
    assert len(ids) == 3


def test_stabilize_matches_the_documented_digest_recipe() -> None:
    media_type = "image/png"
    url = "http://host/shot.png"
    expected = hashlib.sha256(
        f"0\0{media_type}\0{url}".encode("utf-8"),
    ).hexdigest()[:12]
    _, out = mf._stabilize_promoted_tool_result_media_identifiers(
        "x",
        [_label("shot.png", media_type), _media(url, media_type)],
    )
    assert out[0].text == f"- qwenpaw-media-{expected} (image/png)"


def test_stabilize_falls_back_to_data_then_path_value() -> None:
    _, by_data = mf._stabilize_promoted_tool_result_media_identifiers(
        "x",
        [
            _label("d.png"),
            SimpleNamespace(
                source=SimpleNamespace(
                    media_type="image/png",
                    url=None,
                    data="QUJD",
                    path=None,
                ),
            ),
        ],
    )
    _, by_path = mf._stabilize_promoted_tool_result_media_identifiers(
        "x",
        [
            _label("p.png"),
            SimpleNamespace(
                source=SimpleNamespace(
                    media_type="",
                    url=None,
                    data=None,
                    path="/tmp/p.png",
                ),
            ),
        ],
    )
    expected_data = hashlib.sha256(b"0\0image/png\0QUJD").hexdigest()[:12]
    expected_path = hashlib.sha256(b"0\0\0/tmp/p.png").hexdigest()[:12]
    assert f"qwenpaw-media-{expected_data}" in by_data[0].text
    assert f"qwenpaw-media-{expected_path}" in by_path[0].text


def test_stabilize_leaves_unmatched_text_block_alone() -> None:
    block = TextBlock(type="text", text="no dash here")
    text, out = mf._stabilize_promoted_tool_result_media_identifiers(
        "plain",
        [block, _media("http://host/a.png")],
    )
    assert out[0] is block
    assert text == "plain"


def test_stabilize_skips_when_the_next_item_has_no_source() -> None:
    block = _label("f.png")
    _, out = mf._stabilize_promoted_tool_result_media_identifiers(
        "[f.png]",
        [block, SimpleNamespace(other=1)],
    )
    assert out[0] is block

    block2 = _label("g.png")
    _, out2 = mf._stabilize_promoted_tool_result_media_identifiers(
        "[g.png]",
        [block2, SimpleNamespace(source=None)],
    )
    assert out2[0] is block2


def test_stabilize_skips_non_text_items() -> None:
    media = _media("http://host/a.png")
    _, out = mf._stabilize_promoted_tool_result_media_identifiers(
        "x",
        [media, media],
    )
    assert out[0] is media
    assert out[1] is media


def test_stabilize_never_rewrites_the_last_item() -> None:
    # The loop walks rewritten[:-1]: a label needs a following media item
    # to derive an identifier from.
    only = _label("last.png")
    text, out = mf._stabilize_promoted_tool_result_media_identifiers(
        "[last.png]",
        [only],
    )
    assert out[0] is only
    assert text == "[last.png]"


def test_stabilize_handles_empty_promoted_list() -> None:
    text, out = mf._stabilize_promoted_tool_result_media_identifiers(
        "hello",
        [],
    )
    assert text == "hello"
    assert out == []


def test_stabilize_does_not_mutate_the_input_list() -> None:
    promoted = [_label("a.png"), _media("http://host/a.png")]
    mf._stabilize_promoted_tool_result_media_identifiers("[a.png]", promoted)
    assert promoted[0].text == "- a.png (image/png)"
    assert len(promoted) == 2


def test_stabilize_leaves_text_untouched_when_no_bracketed_form() -> None:
    # Only the "[label]" form is rewritten in the returned text; the block
    # text is rewritten either way.
    text, out = mf._stabilize_promoted_tool_result_media_identifiers(
        "mentions a.png without brackets",
        [_label("a.png"), _media("http://host/a.png")],
    )
    assert text == "mentions a.png without brackets"
    assert "qwenpaw-media-" in out[0].text


# ---------------------------------------------------------------------------
# _fixup_media_list — dict media blocks (1.x shape)
# ---------------------------------------------------------------------------
def test_fixup_strips_file_scheme_from_existing_local_media(
    tmp_path,
) -> None:
    real = _existing(tmp_path)
    items: list = [{"type": "image", "source": {"type": "url", "url": real}}]
    mf._fixup_media_list(items)
    assert items[0]["source"]["url"] == real


def test_fixup_converts_file_uri_of_existing_media_to_path(tmp_path) -> None:
    real = _existing(tmp_path)
    items: list = [
        {
            "type": "image",
            "source": {"type": "url", "url": "file://" + real},
        },
    ]
    mf._fixup_media_list(items)
    assert items[0]["source"]["url"] == real


@pytest.mark.parametrize("kind", ["image", "audio", "video"])
def test_fixup_replaces_deleted_local_media_with_placeholder(
    kind: str,
    tmp_path,
) -> None:
    items: list = [
        {
            "type": kind,
            "source": {"type": "url", "url": _gone(tmp_path)},
        },
    ]
    mf._fixup_media_list(items)
    assert isinstance(items[0], TextBlock)
    assert items[0].text == (
        f"[{kind.title()} unavailable \u2014 file deleted from disk]"
    )


@pytest.mark.parametrize(
    "url",
    ["http://host/a.png", "https://host/a.png", "data:image/png;base64,QUJD"],
)
def test_fixup_never_touches_remote_or_inline_media(url: str) -> None:
    source: dict[str, Any] = {"type": "url", "url": url}
    block: dict[str, Any] = {"type": "image", "source": source}
    items: list[Any] = [block]
    mf._fixup_media_list(items)
    assert items[0] is block
    assert source["url"] == url


@pytest.mark.parametrize(
    "block",
    [
        {"type": "image"},
        {"type": "image", "source": {}},
        {"type": "image", "source": {"type": "base64", "data": "QUJD"}},
        {"type": "image", "source": "not-a-dict"},
        {"type": "image", "source": {"type": "url", "url": 42}},
        {"type": "image", "source": {"type": "url"}},
    ],
)
def test_fixup_leaves_media_blocks_without_a_url_source_alone(block) -> None:
    items: list = [block]
    mf._fixup_media_list(items)
    assert items[0] is block


def test_fixup_skips_pydantic_media_blocks() -> None:
    # The 2.0 formatter owns pydantic media blocks; the 1.x dict branch
    # must not rewrite them.
    block = SimpleNamespace(
        type="image",
        source=SimpleNamespace(type="url", url="/nonexistent/a.png"),
    )
    items: list = [block]
    mf._fixup_media_list(items)
    assert items[0] is block


def test_fixup_leaves_unrelated_blocks_alone() -> None:
    text = TextBlock(type="text", text="keep me")
    items: list = [text, {"type": "thinking", "thinking": "hmm"}]
    mf._fixup_media_list(items)
    assert items[0] is text
    assert items[1]["thinking"] == "hmm"


# ---------------------------------------------------------------------------
# _fixup_media_list — data blocks (2.0 shape)
# ---------------------------------------------------------------------------
def test_fixup_replaces_deleted_data_block_with_placeholder(tmp_path) -> None:
    items: list = [_data_block("image/png", "file://" + _gone(tmp_path))]
    mf._fixup_media_list(items)
    assert isinstance(items[0], TextBlock)
    assert items[0].text == "[Image unavailable \u2014 file deleted from disk]"


def test_fixup_placeholder_falls_back_to_media_for_empty_type(
    tmp_path,
) -> None:
    items: list = [_data_block("", "file://" + _gone(tmp_path))]
    mf._fixup_media_list(items)
    assert isinstance(items[0], TextBlock)
    assert items[0].text == "[Media unavailable \u2014 file deleted from disk]"


def test_fixup_keeps_data_block_whose_file_exists(tmp_path) -> None:
    real = _existing(tmp_path)
    block = _data_block("image/png", "file://" + real)
    items: list = [block]
    mf._fixup_media_list(items)
    assert items[0] is block
    assert block.source.url == "file://" + real


@pytest.mark.parametrize(
    "block",
    [
        SimpleNamespace(type="data", source=None),
        SimpleNamespace(
            type="data",
            source=SimpleNamespace(
                type="url",
                url="http://host/a.png",
                media_type="image/png",
            ),
        ),
        SimpleNamespace(
            type="data",
            source=SimpleNamespace(
                type="base64",
                url="",
                media_type="image/png",
            ),
        ),
    ],
)
def test_fixup_leaves_data_blocks_without_a_local_file_url(block) -> None:
    items: list = [block]
    mf._fixup_media_list(items)
    assert items[0] is block


# ---------------------------------------------------------------------------
# _fixup_media_list — file blocks
# ---------------------------------------------------------------------------
def test_fixup_converts_dict_file_block_to_text_with_path(tmp_path) -> None:
    real = _existing(tmp_path)
    items: list = [
        {
            "type": "file",
            "source": {"type": "url", "url": "file://" + real},
        },
    ]
    mf._fixup_media_list(items)
    assert isinstance(items[0], TextBlock)
    assert items[0].text == f"File 'real.png' is available at: {real}"


@pytest.mark.parametrize("hint_key", ["filename", "name"])
def test_fixup_prefers_the_explicit_filename_hint(
    hint_key: str,
    tmp_path,
) -> None:
    real = _existing(tmp_path)
    items: list = [
        {
            "type": "file",
            "source": {"url": real},
            hint_key: "report.pdf",
        },
    ]
    mf._fixup_media_list(items)
    assert items[0].text == (f"File 'report.pdf' is available at: {real}")


@pytest.mark.parametrize(
    "block",
    [
        {"type": "file"},
        {"type": "file", "source": "not-a-dict"},
        {"type": "file", "source": {"url": ""}},
    ],
)
def test_fixup_file_block_without_a_path_reports_only_the_name(block) -> None:
    items: list = [block]
    mf._fixup_media_list(items)
    assert isinstance(items[0], TextBlock)
    assert items[0].text == "File 'file'"


def test_fixup_converts_object_file_block_to_text(tmp_path) -> None:
    real = _existing(tmp_path)
    block = SimpleNamespace(
        type="file",
        source=SimpleNamespace(type="url", url="file://" + real),
        filename="py.pdf",
        name=None,
    )
    items: list = [block]
    mf._fixup_media_list(items)
    assert isinstance(items[0], TextBlock)
    assert items[0].text == f"File 'py.pdf' is available at: {real}"


def test_fixup_object_file_block_falls_back_to_name(tmp_path) -> None:
    real = _existing(tmp_path)
    block = SimpleNamespace(
        type="file",
        source=SimpleNamespace(type="url", url=real),
        filename=None,
        name="byname.pdf",
    )
    items: list = [block]
    mf._fixup_media_list(items)
    assert items[0].text == f"File 'byname.pdf' is available at: {real}"


def test_fixup_object_file_block_without_source(tmp_path) -> None:
    del tmp_path  # unused: no filesystem access happens on this path
    block = SimpleNamespace(
        type="file",
        source=None,
        filename=None,
        name=None,
    )
    items: list = [block]
    mf._fixup_media_list(items)
    assert items[0].text == "File 'file'"


# ---------------------------------------------------------------------------
# _fixup_media_list — tool_result recursion and whole-list behaviour
# ---------------------------------------------------------------------------
def test_fixup_recurses_into_dict_tool_result_output(tmp_path) -> None:
    gone = _gone(tmp_path)
    items: list = [
        {
            "type": "tool_result",
            "output": [
                {"type": "image", "source": {"type": "url", "url": gone}},
            ],
        },
    ]
    mf._fixup_media_list(items)
    assert isinstance(items[0]["output"][0], TextBlock)
    assert items[0]["output"][0].text == (
        "[Image unavailable \u2014 file deleted from disk]"
    )


def test_fixup_recurses_into_object_tool_result_output(tmp_path) -> None:
    gone = _gone(tmp_path)
    block = SimpleNamespace(
        type="tool_result",
        output=[{"type": "video", "source": {"type": "url", "url": gone}}],
    )
    items: list = [block]
    mf._fixup_media_list(items)
    assert isinstance(block.output[0], TextBlock)
    assert block.output[0].text == (
        "[Video unavailable \u2014 file deleted from disk]"
    )


def test_fixup_ignores_tool_result_output_that_is_not_a_list() -> None:
    block = {"type": "tool_result", "output": "plain text"}
    items: list = [block]
    mf._fixup_media_list(items)
    assert items[0]["output"] == "plain text"


def test_fixup_on_empty_list_is_a_noop() -> None:
    items: list = []
    mf._fixup_media_list(items)
    assert items == []


def test_fixup_rewrites_only_the_affected_position(tmp_path) -> None:
    real = _existing(tmp_path, "keep.png")
    gone = _gone(tmp_path)
    keep = {"type": "image", "source": {"type": "url", "url": real}}
    items: list = [
        keep,
        {"type": "image", "source": {"type": "url", "url": gone}},
    ]
    mf._fixup_media_list(items)
    assert items[0] is keep
    assert isinstance(items[1], TextBlock)
