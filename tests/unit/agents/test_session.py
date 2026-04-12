# -*- coding: utf-8 -*-
"""Tests for SafeJSONSession JSON corruption resilience."""
# pylint: disable=redefined-outer-name
import json
import os
import tempfile

import pytest

from copaw.app.runner.session import SafeJSONSession


@pytest.fixture
def tmp_session_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sess(tmp_session_dir):
    return SafeJSONSession(save_dir=tmp_session_dir)


def _corrupt_file(path, valid_json, tail_garbage):
    """Write a valid JSON object followed by garbage bytes."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(valid_json + tail_garbage)


class FakeModule:
    """Minimal state module mock for testing."""

    def __init__(self):
        self.data = None

    def state_dict(self):
        return self.data

    def load_state_dict(self, d):
        self.data = d


# ── load_session_state ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_valid_json(sess, tmp_session_dir):
    """Normal case: valid JSON loads without error."""
    path = os.path.join(tmp_session_dir, "test--session.json")
    data = {"memory": {"content": ["hello"], "_compressed_summary": ""}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    mod = FakeModule()
    await sess.load_session_state(
        "test:session",
        user_id="",
        memory=mod,
    )
    assert mod.data == data["memory"]


@pytest.mark.asyncio
async def test_load_corrupted_json_extra_data(sess, tmp_session_dir):
    """Corrupted file with extra data after valid JSON should recover."""
    path = os.path.join(tmp_session_dir, "test--session.json")
    valid = json.dumps(
        {"memory": {"content": [], "_compressed_summary": ""}},
        ensure_ascii=False,
    )
    garbage = '=============="}}'
    _corrupt_file(path, valid, garbage)

    mod = FakeModule()
    await sess.load_session_state(
        "test:session",
        user_id="",
        memory=mod,
    )
    assert mod.data == {"content": [], "_compressed_summary": ""}


@pytest.mark.asyncio
async def test_load_corrupted_json_real_world_tail(sess, tmp_session_dir):
    """Real-world corruption pattern from QQ session (203-char tail)."""
    path = os.path.join(tmp_session_dir, "test--session.json")
    valid = json.dumps(
        {
            "memory": {"content": [], "_compressed_summary": ""},
            "toolkit": {"active_groups": []},
        },
        ensure_ascii=False,
    )
    # Actual garbage observed in production
    garbage = (
        "perform actions. A response without a tool call indicates "
        "the task is complete. To continue a task, you must generate "
        "a tool call or provide useful feedback if you are blocked."
        '\\n\\n===================="}}'
    )
    _corrupt_file(path, valid, garbage)

    mod_mem = FakeModule()
    mod_tool = FakeModule()
    await sess.load_session_state(
        "test:session",
        user_id="",
        memory=mod_mem,
        toolkit=mod_tool,
    )
    assert mod_mem.data == {"content": [], "_compressed_summary": ""}
    assert mod_tool.data == {"active_groups": []}


# ── get_session_state_dict ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_corrupted_json(sess, tmp_session_dir):
    """get_session_state_dict should recover from corrupted files."""
    path = os.path.join(tmp_session_dir, "test--session.json")
    valid = json.dumps(
        {"memory": {"content": ["x"], "_compressed_summary": ""}},
        ensure_ascii=False,
    )
    _corrupt_file(path, valid, "GARBAGE}}")

    result = await sess.get_session_state_dict(
        "test:session",
        user_id="",
    )
    assert "memory" in result
    assert result["memory"]["content"] == ["x"]


# ── update_session_state ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_corrupted_json(sess, tmp_session_dir):
    """update_session_state should recover corrupted file then write clean."""
    path = os.path.join(tmp_session_dir, "test--session.json")
    valid = json.dumps(
        {"memory": {"content": [], "_compressed_summary": ""}},
        ensure_ascii=False,
    )
    _corrupt_file(path, valid, "EXTRA")

    await sess.update_session_state(
        "test:session",
        key="memory.content",
        value=["updated"],
        user_id="",
    )

    # Verify the file is now clean JSON
    with open(path, encoding="utf-8") as f:
        result = json.load(f)
    assert result["memory"]["content"] == ["updated"]


# ── non-existent session ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_nonexistent(sess):
    """Non-existent session should not raise when allow_not_exist=True."""
    await sess.load_session_state(
        "no:exist",
        user_id="",
        memory=FakeModule(),
    )


@pytest.mark.asyncio
async def test_get_nonexistent(sess):
    """Non-existent session should return empty dict."""
    result = await sess.get_session_state_dict(
        "no:exist",
        user_id="",
    )
    assert result == {}
