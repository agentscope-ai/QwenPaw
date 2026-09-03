# -*- coding: utf-8 -*-
"""Tests for contextvars hook project-dir resolution helpers.

Covers _entry_path_strings (raw path extraction without normalization),
_validated_dir_entries (existing-directory filtering), and the
request-context readers (_trusted_request_project_dir,
_inherited_project_dirs, _pending_project_dirs), which were previously
untested.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

from pathlib import Path


from qwenpaw.hooks.request_setup import contextvars_hook as cvh


# ---------------------------------------------------------------------------
# _entry_path_strings
# ---------------------------------------------------------------------------


class TestEntryPathStrings:
    def test_none_returns_empty(self):
        assert cvh._entry_path_strings(None) == []

    def test_empty_list_returns_empty(self):
        assert cvh._entry_path_strings([]) == []

    def test_plain_strings_collected(self):
        assert cvh._entry_path_strings(["/a", "/b"]) == ["/a", "/b"]

    def test_dict_entries_use_path_key(self):
        entries = [{"path": "/x", "label": "X"}, {"label": "no path"}]
        assert cvh._entry_path_strings(entries) == ["/x"]

    def test_tuple_entries_use_first(self):
        assert cvh._entry_path_strings([("/a", "label"), ()]) == ["/a"]

    def test_path_objects_stringified(self):
        result = cvh._entry_path_strings([Path("/a/b")])
        assert result == ["/a/b"]

    def test_blank_entries_dropped(self):
        assert cvh._entry_path_strings(["  ", "", 42, None]) == []

    def test_mixed_entries(self):
        entries = ["/plain", {"path": "/dict"}, ("/tuple", "l"), {"x": 1}]
        assert cvh._entry_path_strings(entries) == [
            "/plain",
            "/dict",
            "/tuple",
        ]


# ---------------------------------------------------------------------------
# _validated_dir_entries
# ---------------------------------------------------------------------------


class TestValidatedDirEntries:
    def test_existing_dirs_kept(self, tmp_path):
        a = tmp_path / "a"
        a.mkdir()
        result = cvh._validated_dir_entries([str(a)], kind="test")
        assert result == [{"path": str(a), "label": None}]

    def test_nonexistent_dir_dropped(self, tmp_path):
        result = cvh._validated_dir_entries(
            [str(tmp_path / "ghost")],
            kind="test",
        )
        assert result is None

    def test_file_dropped(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        result = cvh._validated_dir_entries([str(f)], kind="test")
        assert result is None

    def test_empty_input_returns_none(self):
        assert cvh._validated_dir_entries([], kind="test") is None

    def test_mixed_keeps_only_dirs(self, tmp_path):
        a = tmp_path / "a"
        a.mkdir()
        result = cvh._validated_dir_entries(
            [str(a), str(tmp_path / "missing")],
            kind="test",
        )
        assert result == [{"path": str(a), "label": None}]

    def test_label_preserved(self, tmp_path):
        a = tmp_path / "a"
        a.mkdir()
        result = cvh._validated_dir_entries(
            [{"path": str(a), "label": "My Project"}],
            kind="test",
        )
        assert result is not None
        assert result == [{"path": str(a), "label": "My Project"}]


# ---------------------------------------------------------------------------
# _trusted_request_project_dir
# ---------------------------------------------------------------------------


class TestTrustedRequestProjectDir:
    def test_no_override_returns_none(self):
        assert cvh._trusted_request_project_dir({}) is None

    def test_project_dir_key_used(self):
        ctx = {"project_dir": "/tmp/proj"}
        assert cvh._trusted_request_project_dir(ctx) == "/tmp/proj"

    def test_project_dir_stripped(self):
        ctx = {"project_dir": "  /tmp/proj  "}
        assert cvh._trusted_request_project_dir(ctx) == "/tmp/proj"

    def test_blank_value_returns_none(self):
        ctx = {"project_dir": "   "}
        assert cvh._trusted_request_project_dir(ctx) is None

    def test_non_string_returns_none(self):
        ctx = {"project_dir": 123}
        assert cvh._trusted_request_project_dir(ctx) is None

    def test_acp_meta_key_takes_priority(self):
        from qwenpaw.agents.acp.meta import ACP_PROJECT_DIR_META_KEY

        ctx = {
            ACP_PROJECT_DIR_META_KEY: "/acp/proj",
            "project_dir": "/other",
        }
        assert cvh._trusted_request_project_dir(ctx) == "/acp/proj"


# ---------------------------------------------------------------------------
# _inherited_project_dirs
# ---------------------------------------------------------------------------


class TestInheritedProjectDirs:
    def test_missing_key_returns_none(self):
        assert cvh._inherited_project_dirs({}) is None

    def test_empty_list_returns_none(self):
        assert (
            cvh._inherited_project_dirs({"inherited_project_dirs": []}) is None
        )

    def test_non_list_returns_none(self):
        ctx = {"inherited_project_dirs": "not a list"}
        assert cvh._inherited_project_dirs(ctx) is None

    def test_valid_dirs_returned(self, tmp_path):
        a = tmp_path / "a"
        a.mkdir()
        ctx = {"inherited_project_dirs": [str(a)]}
        result = cvh._inherited_project_dirs(ctx)
        assert result == [{"path": str(a), "label": None}]

    def test_invalid_dirs_dropped_to_none(self, tmp_path):
        ctx = {"inherited_project_dirs": [str(tmp_path / "ghost")]}
        assert cvh._inherited_project_dirs(ctx) is None


# ---------------------------------------------------------------------------
# _pending_project_dirs
# ---------------------------------------------------------------------------


class TestPendingProjectDirs:
    def test_no_pending_returns_none(self):
        assert cvh._pending_project_dirs({}) is None

    def test_session_project_dirs_list(self, tmp_path):
        a = tmp_path / "a"
        a.mkdir()
        ctx = {"session_project_dirs": [str(a)]}
        result = cvh._pending_project_dirs(ctx)
        assert result == [{"path": str(a), "label": None}]

    def test_legacy_singular_key(self, tmp_path):
        a = tmp_path / "a"
        a.mkdir()
        ctx = {"session_project_dir": str(a)}
        result = cvh._pending_project_dirs(ctx)
        assert result == [{"path": str(a), "label": None}]

    def test_plural_key_preferred_over_singular(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        ctx = {
            "session_project_dirs": [str(a)],
            "session_project_dir": str(b),
        }
        result = cvh._pending_project_dirs(ctx)
        assert result == [{"path": str(a), "label": None}]

    def test_empty_list_falls_to_singular(self, tmp_path):
        a = tmp_path / "a"
        a.mkdir()
        ctx = {
            "session_project_dirs": [],
            "session_project_dir": str(a),
        }
        result = cvh._pending_project_dirs(ctx)
        assert result == [{"path": str(a), "label": None}]

    def test_non_directory_singular_dropped(self, tmp_path):
        ctx = {"session_project_dir": str(tmp_path / "ghost")}
        assert cvh._pending_project_dirs(ctx) is None


# ---------------------------------------------------------------------------
# _project_dirs_unavailable_msg
# ---------------------------------------------------------------------------


class TestProjectDirsUnavailableMsg:
    def test_returns_system_message(self):
        msg = cvh._project_dirs_unavailable_msg()
        assert msg.role == "system"
        assert msg.name == "system"
        text = msg.content[0].text
        assert "project directories could not be read" in text
        assert "turn was stopped" in text
