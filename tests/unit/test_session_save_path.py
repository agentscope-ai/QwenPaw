# -*- coding: utf-8 -*-
"""Tests for _get_save_path() dedup guard and null session_id validation.

Covers the defensive logic added in fix/session-filename-duplication-4988-v3:
- user_id == session_id deduplication (prevents MAX_PATH overflow on Windows)
- null/empty session_id rejection
- channel subdirectory creation
"""
# pylint: disable=protected-access,redefined-outer-name
import os
import tempfile

import pytest

from qwenpaw.app.runner.session import SafeJSONSession


@pytest.fixture
def tmp_session_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sess(tmp_session_dir):
    return SafeJSONSession(save_dir=tmp_session_dir)


# ── uid == sid dedup guard ──────────────────────────────────────────


class TestUidSidDedup:
    """When user_id equals session_id, the uid prefix must be dropped."""

    def test_identical_uid_sid_drops_uid_prefix(self, sess):
        path = sess._get_save_path(
            session_id="same-token",
            user_id="same-token",
        )
        filename = os.path.basename(path)
        assert filename == "same-token.json"

    def test_different_uid_sid_keeps_both(self, sess):
        path = sess._get_save_path(
            session_id="session-abc",
            user_id="user-xyz",
        )
        filename = os.path.basename(path)
        assert filename == "user-xyz_session-abc.json"

    def test_sanitized_uid_sid_still_deduped(self, sess):
        """Dedup works even when sanitize_filename normalises both IDs
        to the same string (e.g. colons replaced with --)."""
        path = sess._get_save_path(
            session_id="agent:123",
            user_id="agent:123",
        )
        filename = os.path.basename(path)
        assert filename == "agent--123.json"

    def test_empty_uid_produces_sid_only(self, sess):
        path = sess._get_save_path(
            session_id="my-session",
            user_id="",
        )
        filename = os.path.basename(path)
        assert filename == "my-session.json"

    def test_none_uid_treated_as_empty(self, sess):
        path = sess._get_save_path(
            session_id="my-session",
            user_id=None,
        )
        filename = os.path.basename(path)
        assert filename == "my-session.json"


# ── null / empty session_id rejection ───────────────────────────────


class TestNullSessionId:
    """Empty or None session_id must raise ValueError."""

    def test_none_session_id_raises(self, sess):
        with pytest.raises(ValueError, match="session_id must not be"):
            sess._get_save_path(session_id=None, user_id="u")

    def test_empty_session_id_raises(self, sess):
        with pytest.raises(ValueError, match="session_id must not be"):
            sess._get_save_path(session_id="", user_id="u")


# ── channel subdirectory ────────────────────────────────────────────


class TestChannelSubdirectory:
    """Channel parameter creates subdirectory and applies dedup."""

    def test_channel_creates_subdir(self, sess, tmp_session_dir):
        path = sess._get_save_path(
            session_id="sid",
            user_id="uid",
            channel="console",
        )
        assert os.path.join(tmp_session_dir, "console") in path
        assert os.path.basename(path) == "uid_sid.json"

    def test_channel_with_dedup(self, sess, tmp_session_dir):
        _ = tmp_session_dir  # fixture needed for sess creation
        path = sess._get_save_path(
            session_id="dup-token",
            user_id="dup-token",
            channel="console",
        )
        assert os.path.basename(path) == "dup-token.json"


# ── long cross-agent session IDs ────────────────────────────────────


class TestLongSessionIds:
    """Realistic cross-agent session IDs should produce valid filenames."""

    def test_cross_agent_session_id_format(self, sess):
        long_sid = "default:to:QwenPaw_QA_Agent_0.2:1780975526576:4daf227e"
        path = sess._get_save_path(
            session_id=long_sid,
            user_id="default",
        )
        filename = os.path.basename(path)
        safe_sid = long_sid.replace(":", "--")
        assert filename == f"default_{safe_sid}.json"

    def test_cross_agent_sid_starting_with_uid_not_deduped(self, sess):
        """session_id starting with user_id as prefix is NOT a full match,
        so uid should be kept."""
        path = sess._get_save_path(
            session_id="default:to:qa:123",
            user_id="default",
        )
        filename = os.path.basename(path)
        assert filename.startswith("default_default--to--qa--123")
