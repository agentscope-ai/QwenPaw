# -*- coding: utf-8 -*-
"""Tests for media block compaction in MemoryCompactionHook."""

import os

import pytest
from agentscope.message import Msg, TextBlock, ImageBlock, VideoBlock

from copaw.agents.hooks.memory_compaction import MemoryCompactionHook


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_text_msg(role, text):
    return Msg(name=role, role=role, content=[TextBlock(type="text", text=text)])


def _make_video_msg(role, path):
    return Msg(
        name=role, role="assistant",
        content=[
            TextBlock(type="text", text=f"Video loaded: {os.path.basename(path)}"),
            VideoBlock(type="video", source={"type": "url", "url": path}),
        ],
    )


def _make_image_msg(role, path):
    return Msg(
        name=role, role="assistant",
        content=[
            TextBlock(type="text", text=f"Image loaded: {os.path.basename(path)}"),
            ImageBlock(type="image", source={"type": "url", "url": path}),
        ],
    )


def _make_mixed_msg(role, text, video_path):
    return Msg(
        name=role, role="assistant",
        content=[
            TextBlock(type="text", text=text),
            VideoBlock(type="video", source={"type": "url", "url": video_path}),
            TextBlock(type="text", text="some follow-up text"),
        ],
    )


def _has_media_block(msg):
    if not isinstance(msg.content, list):
        return False
    return any(
        isinstance(b, dict) and b.get("type") in ("video", "image")
        for b in msg.content
    )


def _count_media_blocks(messages):
    return sum(1 for m in messages if _has_media_block(m))


def _get_placeholder_texts(msg):
    if not isinstance(msg.content, list):
        return []
    return [
        b.get("text", "")
        for b in msg.content
        if isinstance(b, dict) and b.get("type") == "text"
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCompactMediaBlocks:

    def test_no_messages(self):
        assert MemoryCompactionHook._compact_media_blocks([], recent_n=2) == 0

    def test_no_media_blocks(self):
        msgs = [_make_text_msg("user", "hello"), _make_text_msg("assistant", "hi")]
        assert MemoryCompactionHook._compact_media_blocks(msgs, recent_n=1) == 0

    def test_video_compacted_in_old_messages(self):
        msgs = [
            _make_text_msg("user", "show me the video"),
            _make_video_msg("assistant", "/tmp/big_video.mp4"),
            _make_text_msg("user", "thanks"),
            _make_text_msg("assistant", "no problem"),
        ]
        result = MemoryCompactionHook._compact_media_blocks(msgs, recent_n=2)
        assert result == 1
        assert not _has_media_block(msgs[1])
        texts = _get_placeholder_texts(msgs[1])
        assert any("/tmp/big_video.mp4" in t for t in texts)
        assert any("removed from context" in t for t in texts)

    def test_image_compacted_in_old_messages(self):
        msgs = [
            _make_image_msg("assistant", "/tmp/screenshot.png"),
            _make_text_msg("user", "nice"),
            _make_text_msg("assistant", "thanks"),
        ]
        result = MemoryCompactionHook._compact_media_blocks(msgs, recent_n=2)
        assert result == 1
        assert not _has_media_block(msgs[0])
        texts = _get_placeholder_texts(msgs[0])
        assert any("/tmp/screenshot.png" in t for t in texts)

    def test_recent_media_preserved(self):
        msgs = [
            _make_text_msg("user", "old"),
            _make_video_msg("assistant", "/tmp/old.mp4"),
            _make_text_msg("user", "new"),
            _make_video_msg("assistant", "/tmp/new.mp4"),
        ]
        result = MemoryCompactionHook._compact_media_blocks(msgs, recent_n=2)
        assert result == 1
        assert not _has_media_block(msgs[1])
        assert _has_media_block(msgs[3])

    def test_all_recent_nothing_compacted(self):
        msgs = [_make_video_msg("a", "/tmp/a.mp4"), _make_video_msg("a", "/tmp/b.mp4")]
        assert MemoryCompactionHook._compact_media_blocks(msgs, recent_n=5) == 0
        assert _count_media_blocks(msgs) == 2

    def test_mixed_content_only_media_removed(self):
        msgs = [
            _make_mixed_msg("assistant", "here is the analysis", "/tmp/vid.mp4"),
            _make_text_msg("user", "recent"),
        ]
        result = MemoryCompactionHook._compact_media_blocks(msgs, recent_n=1)
        assert result == 1
        assert not _has_media_block(msgs[0])
        texts = _get_placeholder_texts(msgs[0])
        assert any("here is the analysis" in t for t in texts)
        assert any("some follow-up text" in t for t in texts)
        assert any("/tmp/vid.mp4" in t for t in texts)

    def test_multiple_media_blocks_compacted(self):
        msgs = [
            _make_video_msg("a", "/tmp/v1.mp4"),
            _make_image_msg("a", "/tmp/img1.png"),
            _make_video_msg("a", "/tmp/v2.mp4"),
            _make_text_msg("user", "recent"),
        ]
        result = MemoryCompactionHook._compact_media_blocks(msgs, recent_n=1)
        assert result == 3
        assert _count_media_blocks(msgs) == 0

    def test_placeholder_contains_full_path(self):
        long_path = "/home/joe/.copaw/workspaces/default/media/downloads/very_long_video_name.mp4"
        msgs = [_make_video_msg("a", long_path), _make_text_msg("user", "recent")]
        MemoryCompactionHook._compact_media_blocks(msgs, recent_n=1)
        texts = _get_placeholder_texts(msgs[0])
        assert any(long_path in t for t in texts)

    def test_dict_style_video_block(self):
        msg = Msg(
            name="assistant", role="assistant",
            content=[
                {"type": "text", "text": "here"},
                {"type": "video", "source": {"type": "url", "url": "/tmp/dict_vid.mp4"}},
            ],
        )
        msgs = [msg, _make_text_msg("user", "recent")]
        assert MemoryCompactionHook._compact_media_blocks(msgs, recent_n=1) == 1

    def test_recent_n_zero_compacts_everything(self):
        msgs = [_make_video_msg("a", "/tmp/a.mp4"), _make_video_msg("a", "/tmp/b.mp4")]
        assert MemoryCompactionHook._compact_media_blocks(msgs, recent_n=0) == 2
        assert _count_media_blocks(msgs) == 0

    def test_idempotent(self):
        msgs = [_make_video_msg("a", "/tmp/v.mp4"), _make_text_msg("user", "recent")]
        first = MemoryCompactionHook._compact_media_blocks(msgs, recent_n=1)
        assert first == 1
        second = MemoryCompactionHook._compact_media_blocks(msgs, recent_n=1)
        assert second == 0
