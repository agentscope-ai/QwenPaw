# -*- coding: utf-8 -*-
"""Gap-path tests for project_directory pure helpers.

Complements ``test_project_directory.py`` by covering the lexical
containment / identity helpers, entry coercion, and the normalize-list
dedupe & cap logic. All helpers are filesystem-free by design.
"""
# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path


from qwenpaw.services import project_directory as pd
from qwenpaw.services.fs_name_rules import NameRules


CASE_SENSITIVE = NameRules(case_sensitive=True, normalization_sensitive=True)
CASE_INSENSITIVE = NameRules(
    case_sensitive=False,
    normalization_sensitive=True,
)


# ---------------------------------------------------------------------------
# same_dir_normalized
# ---------------------------------------------------------------------------


class TestSameDirNormalized:
    def test_identical_paths(self):
        assert pd.same_dir_normalized(
            Path("/repo/a"),
            Path("/repo/a"),
        )

    def test_different_paths(self):
        assert not pd.same_dir_normalized(
            Path("/repo/a"),
            Path("/repo/b"),
        )

    def test_case_folded_under_insensitive_rules(self):
        assert pd.same_dir_normalized(
            Path("/Repo/a"),
            Path("/repo/a"),
            rules=CASE_INSENSITIVE,
        )

    def test_case_differs_under_sensitive_rules(self):
        assert not pd.same_dir_normalized(
            Path("/Repo/a"),
            Path("/repo/a"),
            rules=CASE_SENSITIVE,
        )


# ---------------------------------------------------------------------------
# is_within_normalized
# ---------------------------------------------------------------------------


class TestIsWithinNormalized:
    def test_target_is_base_itself(self):
        assert pd.is_within_normalized(Path("/repo"), Path("/repo"))

    def test_target_under_base(self):
        assert pd.is_within_normalized(Path("/repo/x/y"), Path("/repo"))

    def test_sibling_is_outside(self):
        assert not pd.is_within_normalized(
            Path("/repo2/x"),
            Path("/repo"),
        )

    def test_parent_is_outside(self):
        assert not pd.is_within_normalized(Path("/repo"), Path("/repo/x"))

    def test_lexical_prefix_is_not_containment(self):
        # /repo_evil is a string prefix of /repo but not a child.
        assert not pd.is_within_normalized(
            Path("/repo_evil/x"),
            Path("/repo"),
        )

    def test_case_folded_containment_under_insensitive_rules(self):
        assert pd.is_within_normalized(
            Path("/Repo/x"),
            Path("/repo"),
            rules=CASE_INSENSITIVE,
        )

    def test_case_folded_rejected_under_sensitive_rules(self):
        assert not pd.is_within_normalized(
            Path("/Repo/x"),
            Path("/repo"),
            rules=CASE_SENSITIVE,
        )


# ---------------------------------------------------------------------------
# coerce_project_dir_entry
# ---------------------------------------------------------------------------


class TestCoerceProjectDirEntry:
    def test_none_returns_none(self):
        assert pd.coerce_project_dir_entry(None) is None

    def test_plain_string(self, tmp_path):
        result = pd.coerce_project_dir_entry(str(tmp_path))
        assert result is not None
        path, label = result
        assert path == tmp_path.resolve()
        assert label is None

    def test_path_object(self, tmp_path):
        result = pd.coerce_project_dir_entry(tmp_path)
        assert result is not None
        assert result[0] == tmp_path.resolve()

    def test_dict_entry_with_label(self, tmp_path):
        result = pd.coerce_project_dir_entry(
            {"path": str(tmp_path), "label": "work"},
        )
        assert result == (tmp_path.resolve(), "work")

    def test_tuple_entry(self, tmp_path):
        result = pd.coerce_project_dir_entry((str(tmp_path), "lbl"))
        assert result == (tmp_path.resolve(), "lbl")

    def test_empty_sequence_returns_none(self):
        assert pd.coerce_project_dir_entry([]) is None

    def test_object_entry_attribute_access(self, tmp_path):
        class Entry:
            path = str(tmp_path)
            label = "obj"

        result = pd.coerce_project_dir_entry(Entry())
        assert result == (tmp_path.resolve(), "obj")

    def test_blank_path_returns_none(self):
        assert (
            pd.coerce_project_dir_entry({"path": "  ", "label": "x"}) is None
        )

    def test_dict_without_label(self, tmp_path):
        result = pd.coerce_project_dir_entry({"path": str(tmp_path)})
        assert result is not None
        assert result[1] is None


# ---------------------------------------------------------------------------
# normalize_dir_entry_list
# ---------------------------------------------------------------------------


class TestNormalizeDirEntryList:
    def test_none_returns_empty(self):
        assert pd.normalize_dir_entry_list(None) == []

    def test_single_non_list_wrapped(self, tmp_path):
        entries = pd.normalize_dir_entry_list(str(tmp_path))
        assert len(entries) == 1
        assert entries[0].path == tmp_path.resolve()

    def test_dedupe_same_directory(self, tmp_path):
        entries = pd.normalize_dir_entry_list(
            [str(tmp_path), {"path": str(tmp_path), "label": "dup"}],
        )
        assert len(entries) == 1
        # First occurrence (and its label) wins.
        assert entries[0].label is None

    def test_missing_entry_flagged(self, tmp_path):
        ghost = tmp_path / "ghost-dir"
        entries = pd.normalize_dir_entry_list(str(ghost))
        assert len(entries) == 1
        assert entries[0].exists is False

    def test_existing_entry_flagged(self, tmp_path):
        entries = pd.normalize_dir_entry_list(str(tmp_path))
        assert entries[0].exists is True

    def test_unusable_entries_dropped(self, tmp_path):
        entries = pd.normalize_dir_entry_list(["   ", str(tmp_path)])
        assert len(entries) == 1
        assert entries[0].path == tmp_path.resolve()

    def test_caps_at_max_project_dirs(self, tmp_path):
        dirs = []
        for i in range(pd.MAX_PROJECT_DIRS + 3):
            d = tmp_path / f"d{i}"
            d.mkdir()
            dirs.append(str(d))
        entries = pd.normalize_dir_entry_list(dirs)
        assert len(entries) == pd.MAX_PROJECT_DIRS
        # First entries kept, tail dropped.
        assert entries[0].path == (tmp_path / "d0").resolve()


# ---------------------------------------------------------------------------
# normalize_project_dir_list
# ---------------------------------------------------------------------------


class TestNormalizeProjectDirList:
    def test_returns_path_label_pairs(self, tmp_path):
        result = pd.normalize_project_dir_list(
            [{"path": str(tmp_path), "label": "main"}],
        )
        assert result == [(tmp_path.resolve(), "main")]


# ---------------------------------------------------------------------------
# nested_root_pairs
# ---------------------------------------------------------------------------


class TestNestedRootPairs:
    def test_child_before_ancestor(self):
        pairs = pd.nested_root_pairs(
            [Path("/repo/sub"), Path("/repo")],
        )
        assert pairs == [(0, 1)]

    def test_ancestor_before_child(self):
        pairs = pd.nested_root_pairs(
            [Path("/repo"), Path("/repo/sub/deep")],
        )
        assert pairs == [(1, 0)]

    def test_no_nesting(self):
        pairs = pd.nested_root_pairs(
            [Path("/a"), Path("/b"), Path("/c")],
        )
        assert pairs == []

    def test_multiple_children_of_one_root(self):
        pairs = pd.nested_root_pairs(
            [Path("/repo/x"), Path("/repo/y"), Path("/repo")],
        )
        assert (0, 2) in pairs
        assert (1, 2) in pairs
        assert len(pairs) == 2

    def test_lexical_prefix_not_nesting(self):
        pairs = pd.nested_root_pairs(
            [Path("/repo"), Path("/repo_evil")],
        )
        assert pairs == []
