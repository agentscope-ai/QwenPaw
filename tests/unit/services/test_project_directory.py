# -*- coding: utf-8 -*-
"""Tests for mode-independent project directory resolution.

Covers the single-value legacy resolver and the multi-root
(session-level) resolution model: an ordered list where index 0 is the
PRIMARY directory (relative paths / shell cwd resolve there) and the
rest are extra directories granted by governance — fully readable and
writable, but never a resolution base.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.config.config import migrate_project_directory_config
from qwenpaw.services.project_directory import (
    MAX_PROJECT_DIRS,
    PathEscapeError,
    SOURCE_AGENT,
    SOURCE_FORK,
    SOURCE_MODE,
    SOURCE_REQUEST,
    SOURCE_SESSION,
    SOURCE_WORKSPACE_FALLBACK,
    default_project_name,
    describe_for_audit,
    detect_nested_roots,
    is_within,
    is_within_roots,
    normalize_project_dir,
    normalize_project_dir_list,
    normalize_project_name,
    resolve_effective_project_dir,
    resolve_effective_project_dirs,
    resolve_project_name,
    resolve_under_roots,
    same_dir,
    session_project_dir,
    session_project_dirs_from_meta,
    session_project_name_from_meta,
)


def test_resolver_priority(tmp_path: Path) -> None:
    """Fork, request, Session, Agent, then workspace define precedence."""
    values = {
        "workspace_dir": tmp_path / "workspace",
        "agent_project_dir": str(tmp_path / "agent"),
        "session_override": str(tmp_path / "session"),
        "trusted_override": str(tmp_path / "request"),
        "active_mode_override": str(tmp_path / "mode"),
        "fork_project_dir": str(tmp_path / "fork"),
    }

    assert resolve_effective_project_dir(**values) == (
        (tmp_path / "fork").resolve(),
        "fork",
    )
    values["fork_project_dir"] = None
    assert resolve_effective_project_dir(**values)[1] == "active_mode"
    values["active_mode_override"] = None
    assert resolve_effective_project_dir(**values)[1] == "request"
    values["trusted_override"] = None
    assert resolve_effective_project_dir(**values)[1] == "session"
    values["session_override"] = None
    assert resolve_effective_project_dir(**values)[1] == "agent"
    values["agent_project_dir"] = None
    assert resolve_effective_project_dir(**values)[1] == "workspace_fallback"


def test_session_project_dir_uses_controlled_namespace() -> None:
    """Unrelated Chat metadata cannot become a directory override."""
    assert session_project_dir({"project_dir": "/wrong"}) is None
    assert (
        session_project_dir(
            {"runtime_context": {"project_dir": "/project"}},
        )
        == "/project"
    )


@pytest.mark.parametrize(
    ("top_level", "legacy", "expected"),
    [
        (None, "/legacy", "/legacy"),
        ("/top", "/legacy", "/top"),
        (None, None, None),
        (None, r"C:\Users\Alice\Project", r"C:\Users\Alice\Project"),
        (None, r"\\server\share\Project", r"\\server\share\Project"),
        (None, "~/Project", "~/Project"),
    ],
)
def test_legacy_project_directory_migration(
    top_level: str | None,
    legacy: str | None,
    expected: str | None,
) -> None:
    """Migration preserves a top-level value and removes the old field."""
    data = {
        "coding_mode": {
            "enabled": False,
            "project_dir": legacy,
        },
    }
    if top_level is not None:
        data["project_dir"] = top_level

    assert migrate_project_directory_config(data) is True
    assert data["project_dir"] == expected
    assert "project_dir" not in data["coding_mode"]
    assert migrate_project_directory_config(data) is False


# ---------------------------------------------------------------------------
# Multi-root resolution
# ---------------------------------------------------------------------------

_WS = str(Path("/tmp/qwenpaw-test-ws").resolve())


def _paths(resolved) -> list[str]:
    return [str(entry.path) for entry in resolved.dirs]


def _p(value: str) -> str:
    """Expected-path helper applying the same normalization as the code."""
    return str(Path(value).resolve())


class TestResolverPrecedence:
    """fork > mode > request > session > agent > workspace_fallback."""

    def test_nothing_configured_falls_back_to_workspace(self):
        resolved = resolve_effective_project_dirs(workspace_dir=_WS)
        assert resolved.source == SOURCE_WORKSPACE_FALLBACK
        assert resolved.is_workspace_fallback is True
        assert resolved.dirs == ()
        # The primary is the workspace, but it is NOT listed as a
        # project dir — tools fall back, the UI shows the empty state.
        assert str(resolved.primary_path) == _WS

    def test_agent_default_beats_fallback(self):
        resolved = resolve_effective_project_dirs(
            workspace_dir=_WS,
            agent_project_dir="/tmp/agent-proj",
        )
        assert resolved.source == SOURCE_AGENT
        assert _paths(resolved) == [_p("/tmp/agent-proj")]

    def test_session_beats_agent_wholesale(self):
        """Session override replaces the whole list — no merging."""
        resolved = resolve_effective_project_dirs(
            workspace_dir=_WS,
            agent_project_dir="/tmp/agent-a",
            session_project_dirs=[{"path": "/tmp/session-proj"}],
        )
        assert resolved.source == SOURCE_SESSION
        assert _paths(resolved) == [_p("/tmp/session-proj")]

    def test_empty_session_list_is_defensive_fallback(self):
        """[] cannot be produced via the API (min_length=1); the resolver
        still degrades to the workspace instead of crashing."""
        resolved = resolve_effective_project_dirs(
            workspace_dir=_WS,
            agent_project_dir="/tmp/agent-proj",
            session_project_dirs=[],
        )
        assert resolved.source == SOURCE_SESSION
        assert resolved.dirs == ()
        assert str(resolved.primary_path) == _WS

    def test_request_becomes_primary_and_keeps_rest(self):
        resolved = resolve_effective_project_dirs(
            workspace_dir=_WS,
            agent_project_dir="/tmp/agent-proj",
            session_project_dirs=[{"path": "/tmp/session-proj"}],
            request_override="/tmp/acp-proj",
        )
        assert resolved.source == SOURCE_REQUEST
        assert _paths(resolved) == [
            _p("/tmp/acp-proj"),
            _p("/tmp/session-proj"),
        ]

    def test_mode_pin_replaces_the_whole_list(self):
        resolved = resolve_effective_project_dirs(
            workspace_dir=_WS,
            agent_project_dir="/tmp/agent-proj",
            session_project_dirs=[{"path": "/tmp/session-proj"}],
            request_override="/tmp/acp-proj",
            mode_override=[{"path": "/tmp/mission-proj"}],
        )
        assert resolved.source == SOURCE_MODE
        assert _paths(resolved) == [_p("/tmp/mission-proj")]

    def test_fork_replaces_primary_but_keeps_rest(self):
        """The fork worktree must win the primary slot; the remaining
        entries are user-configured trusted paths and stay accessible."""
        resolved = resolve_effective_project_dirs(
            workspace_dir=_WS,
            agent_project_dir="/tmp/agent-proj",
            session_project_dirs=[{"path": "/tmp/session-proj"}],
            request_override="/tmp/acp-proj",
            mode_override=[{"path": "/tmp/mission-proj"}],
            fork_project_dir="/tmp/worktree",
        )
        assert resolved.source == SOURCE_FORK
        assert _paths(resolved) == [
            _p("/tmp/worktree"),
            _p("/tmp/mission-proj"),
        ]

    def test_fork_dedupes_itself_out_of_the_rest(self):
        resolved = resolve_effective_project_dirs(
            workspace_dir=_WS,
            agent_project_dir="/tmp/proj",
            fork_project_dir="/tmp/proj",
        )
        assert _paths(resolved) == [_p("/tmp/proj")]

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_blank_values_are_skipped_not_used_as_paths(self, blank):
        resolved = resolve_effective_project_dirs(
            workspace_dir=_WS,
            agent_project_dir=blank,
            session_project_dirs=None,
        )
        assert resolved.source == SOURCE_WORKSPACE_FALLBACK

    def test_missing_workspace_raises(self):
        """Without a fallback we must fail loudly.

        Silently using the process cwd would let agent state escape into
        whatever directory the server happened to start in.
        """
        with pytest.raises(ValueError, match="workspace_dir"):
            resolve_effective_project_dirs(workspace_dir="")

    def test_missing_dir_is_reported_not_swallowed(self):
        resolved = resolve_effective_project_dirs(
            workspace_dir=_WS,
            session_project_dirs=[
                {"path": "/tmp/definitely-not-here-12345"},
            ],
        )
        assert resolved.source == SOURCE_SESSION
        assert resolved.dirs[0].exists is False
        assert len(resolved.dirs) == 1

    def test_existing_dir_reports_exists(self, tmp_path):
        resolved = resolve_effective_project_dirs(
            workspace_dir=_WS,
            session_project_dirs=[{"path": str(tmp_path)}],
        )
        assert resolved.dirs[0].exists is True

    def test_labels_survive_resolution(self):
        resolved = resolve_effective_project_dirs(
            workspace_dir=_WS,
            session_project_dirs=[
                {"path": "/tmp/a", "label": "backend"},
                {"path": "/tmp/b"},
            ],
        )
        assert resolved.dirs[0].label == "backend"
        assert resolved.dirs[1].label is None

    def test_primary_property_matches_first_entry(self):
        resolved = resolve_effective_project_dirs(
            workspace_dir=_WS,
            session_project_dirs=[
                {"path": "/tmp/first"},
                {"path": "/tmp/second"},
            ],
        )
        assert resolved.primary.path == resolved.dirs[0].path
        assert str(resolved.primary_path) == _p("/tmp/first")


class TestNormalizeList:
    def test_order_is_preserved_index_zero_is_primary(self):
        entries = normalize_project_dir_list(
            ["/tmp/one", "/tmp/two", "/tmp/three"],
        )
        assert [str(p) for p, _ in entries] == [
            _p("/tmp/one"),
            _p("/tmp/two"),
            _p("/tmp/three"),
        ]

    def test_duplicates_are_dropped_case_insensitively(self):
        entries = normalize_project_dir_list(
            [
                {"path": "/Repo/Main", "label": "first"},
                {"path": "/repo/main", "label": "dup"},
                {"path": "/tmp/other"},
            ],
        )
        assert len(entries) == 2
        # The first occurrence keeps its label.
        assert entries[0][1] == "first"

    def test_accepts_strings_dicts_tuples_and_objects(self):
        class Entry:
            path = "/tmp/obj"
            label = "from-object"

        entries = normalize_project_dir_list(
            [
                "/tmp/str",
                {"path": "/tmp/dict", "label": "d"},
                ("/tmp/tuple", "t"),
                Entry(),
            ],
        )
        assert [str(p) for p, _ in entries] == [
            _p("/tmp/str"),
            _p("/tmp/dict"),
            _p("/tmp/tuple"),
            _p("/tmp/obj"),
        ]
        assert entries[1][1] == "d"
        assert entries[3][1] == "from-object"

    def test_blank_entries_are_dropped(self):
        entries = normalize_project_dir_list(["", "  ", None, "/tmp/ok"])
        assert len(entries) == 1

    def test_cap_enforced(self):
        raw = [f"/tmp/proj-{i}" for i in range(MAX_PROJECT_DIRS + 5)]
        entries = normalize_project_dir_list(raw)
        assert len(entries) == MAX_PROJECT_DIRS

    def test_labels_are_trimmed_and_capped(self):
        entries = normalize_project_dir_list(
            [{"path": "/tmp/x", "label": "  "}],
        )
        assert entries[0][1] is None
        entries = normalize_project_dir_list(
            [{"path": "/tmp/x", "label": "y" * 80}],
        )
        assert len(entries[0][1]) == 50

    def test_none_is_empty_list(self):
        assert normalize_project_dir_list(None) == []


class TestNormalize:
    def test_tilde_is_expanded(self):
        result = normalize_project_dir("~/some-project")
        assert "~" not in str(result)
        assert result.is_absolute()

    def test_relative_becomes_absolute(self):
        result = normalize_project_dir("some/relative/path")
        assert result.is_absolute()

    def test_dotdot_is_collapsed(self):
        assert str(normalize_project_dir("/a/b/../c")) == str(
            Path("/a/b/../c").resolve(),
        )

    def test_missing_path_still_normalizes(self):
        """A configured-but-missing dir must survive round-trips.

        Raising or dropping here would silently reset the user's config
        instead of letting the UI flag the path as unavailable.
        """
        assert normalize_project_dir("/no/such/dir/anywhere").is_absolute()

    def test_accepts_path_objects(self, tmp_path):
        assert normalize_project_dir(tmp_path) == tmp_path.resolve()


class TestSameDir:
    def test_identical_paths_match(self):
        assert same_dir("/repo", "/repo") is True

    def test_normalizes_before_comparing(self):
        assert same_dir("/repo/", "/repo/../repo") is True

    def test_different_paths_do_not_match(self):
        assert same_dir("/repo", "/other") is False

    def test_case_variants_match(self):
        """macOS/Windows filesystems are case-insensitive; dedupe must
        not keep /Repo and /repo as two entries."""
        assert same_dir("/Repo/Project", "/repo/project") is True


class TestIsWithin:
    def test_child_is_within_parent(self):
        assert is_within("/repo/src/main.py", "/repo") is True

    def test_same_dir_counts_as_within(self):
        assert is_within("/repo", "/repo") is True

    def test_sibling_prefix_is_not_within(self):
        """String ``startswith`` would wrongly say yes here."""
        assert is_within("/repo-backup", "/repo") is False
        assert is_within("/repo-backup/file.txt", "/repo") is False

    def test_parent_is_not_within_child(self):
        assert is_within("/repo", "/repo/src") is False

    def test_none_is_never_within(self):
        assert is_within(None, "/repo") is False
        assert is_within("/repo", None) is False


class TestDetectNestedRoots:
    def test_nested_child_is_reported(self):
        pairs = detect_nested_roots(["/project", "/project/src"])
        assert pairs == [(1, 0)]

    def test_nesting_is_physical_not_positional(self):
        """Order and primary choice do not change the relationship."""
        pairs = detect_nested_roots(["/project/src", "/project"])
        assert pairs == [(0, 1)]

    def test_multiple_levels_report_every_ancestor(self):
        pairs = detect_nested_roots(["/a", "/a/b", "/a/b/c"])
        assert (1, 0) in pairs  # /a/b under /a
        assert (2, 0) in pairs  # /a/b/c under /a
        assert (2, 1) in pairs  # /a/b/c under /a/b

    def test_no_nesting_returns_empty(self):
        assert detect_nested_roots(["/one", "/two"]) == []

    def test_duplicates_are_not_nesting(self):
        """Dupes collapse before the check, so equal dirs never pair."""
        assert detect_nested_roots(["/same", "/same"]) == []


class TestSessionProjectDirsFromMeta:
    def test_reads_controlled_namespace(self):
        meta = {
            "runtime_context": {
                "project_dirs": [{"path": "/s1", "label": "x"}],
            },
        }
        assert session_project_dirs_from_meta(meta) == [
            {"path": _p("/s1"), "label": "x"},
        ]

    def test_legacy_single_value_is_wrapped_into_a_list(self):
        meta = {"runtime_context": {"project_dir": "/legacy"}}
        assert session_project_dirs_from_meta(meta) == [
            {"path": _p("/legacy"), "label": None},
        ]

    def test_list_wins_over_legacy_key(self):
        meta = {
            "runtime_context": {
                "project_dirs": ["/new"],
                "project_dir": "/old",
            },
        }
        result = session_project_dirs_from_meta(meta)
        assert result == [{"path": _p("/new"), "label": None}]

    def test_empty_list_round_trips(self):
        """[] was stored as "explicitly no dirs" and must round-trip."""
        meta = {"runtime_context": {"project_dirs": []}}
        assert session_project_dirs_from_meta(meta) == []

    def test_top_level_meta_key_is_ignored(self):
        """Only the controlled namespace counts.

        A generic meta patch from a client must not be able to set the
        project dirs as a side effect.
        """
        assert session_project_dirs_from_meta({"project_dirs": ["/x"]}) is None

    @pytest.mark.parametrize(
        "meta",
        [
            None,
            {},
            "not-a-dict",
            {"runtime_context": None},
            {"runtime_context": "not-a-dict"},
            {"runtime_context": {}},
            {"runtime_context": {"project_dir": ""}},
        ],
    )
    def test_malformed_meta_returns_none(self, meta):
        assert session_project_dirs_from_meta(meta) is None


class TestPathPolicy:
    """is_within_roots / resolve_under_roots — the security core."""

    @pytest.fixture()
    def roots(self, tmp_path):
        primary = tmp_path / "main"
        extra = tmp_path / "docs"
        primary.mkdir()
        extra.mkdir()
        return primary.resolve(), extra.resolve()

    def test_absolute_inside_any_root_passes(self, roots):
        primary, extra = roots
        assert is_within_roots(primary / "a.txt", [primary, extra])
        assert is_within_roots(extra / "b.txt", [primary, extra])

    def test_sibling_directory_is_not_within(self, roots):
        primary, _ = roots
        evil = primary.parent / (primary.name + "_evil") / "x"
        assert not is_within_roots(evil, list(roots))

    def test_outside_all_roots_is_not_within(self, roots):
        assert not is_within_roots("/totally/elsewhere", list(roots))

    def test_empty_roots_never_contain(self, roots):
        assert not is_within_roots(roots[0] / "a", [])

    def test_relative_resolves_from_primary(self, roots):
        primary, _ = roots
        resolved = resolve_under_roots(
            "README.md",
            roots=list(roots),
            primary=primary,
        )
        assert resolved == (primary / "README.md").resolve()

    def test_relative_never_resolves_from_extra_root(self, roots):
        """Extra roots are not a resolution base: a bare relative path
        lands in the primary even when a same-named file exists in an
        extra root."""
        primary, extra = roots
        (extra / "README.md").write_text("extra")
        resolved = resolve_under_roots(
            "README.md",
            roots=list(roots),
            primary=primary,
        )
        assert resolved == (primary / "README.md").resolve()

    def test_dotdot_landing_in_extra_root_is_legitimate(self, roots):
        """``../docs/x`` from the primary may reach an extra root — the
        target is inside a granted root, so it passes."""
        primary, extra = roots
        resolved = resolve_under_roots(
            f"../{extra.name}/guide.md",
            roots=list(roots),
            primary=primary,
        )
        assert resolved == (extra / "guide.md").resolve()

    def test_escape_via_dotdot_is_rejected(self, roots):
        primary, _ = roots
        with pytest.raises(PathEscapeError):
            resolve_under_roots(
                "../../outside.txt",
                roots=list(roots),
                primary=primary,
            )

    def test_absolute_outside_roots_is_rejected(self, roots):
        with pytest.raises(PathEscapeError):
            resolve_under_roots(
                "/totally/elsewhere/file.txt",
                roots=list(roots),
                primary=roots[0],
            )

    def test_blank_path_is_rejected(self, roots):
        with pytest.raises(ValueError):
            resolve_under_roots("", roots=list(roots), primary=roots[0])


class TestDescribeForAudit:
    def test_records_dirs_and_provenance(self, tmp_path):
        resolved = resolve_effective_project_dirs(
            workspace_dir=str(tmp_path),
            session_project_dirs=[
                {"path": str(tmp_path)},
                {"path": "/tmp/other"},
            ],
        )
        record = describe_for_audit(resolved, str(tmp_path))
        assert record["workspace_dir"] == str(tmp_path.resolve())
        assert record["project_dir"] == str(tmp_path.resolve())
        assert record["project_dir_source"] == SOURCE_SESSION
        assert record["project_dir_exists"] is True
        assert record["project_dirs"] == [
            str(tmp_path.resolve()),
            _p("/tmp/other"),
        ]


class TestProjectName:
    """The project's display name: descriptive only, never a path."""

    def test_derived_from_the_primary_label_then_basename(self):
        assert (
            default_project_name([{"path": "/repos/app", "label": "My App"}])
            == "My App"
        )
        assert (
            default_project_name([{"path": "/repos/app", "label": None}])
            == "app"
        )

    def test_derived_name_ignores_non_primary_entries(self):
        entries = [
            {"path": "/repos/main", "label": None},
            {"path": "/repos/other", "label": "Other"},
        ]
        assert default_project_name(entries) == "main"

    def test_no_directories_means_no_name(self):
        assert default_project_name([]) is None

    def test_session_name_wins_then_derived(self):
        entries = [{"path": "/repos/app", "label": None}]
        assert (
            resolve_project_name(entries=entries, session_name="Session")
            == "Session"
        )
        assert resolve_project_name(entries=entries) == "app"

    def test_blank_override_falls_through_rather_than_blanking(self):
        # Otherwise clearing the field would leave the UI with no name.
        entries = [{"path": "/repos/app", "label": None}]
        assert (
            resolve_project_name(entries=entries, session_name="   ")
            == "app"
        )

    def test_normalize_trims_and_caps_length(self):
        assert normalize_project_name("  spaced  ") == "spaced"
        assert normalize_project_name("") is None
        assert normalize_project_name(None) is None
        assert normalize_project_name(123) is None
        assert len(normalize_project_name("x" * 500)) == 60

    def test_read_from_chat_meta(self):
        assert (
            session_project_name_from_meta(
                {"runtime_context": {"project_name": "From Chat"}},
            )
            == "From Chat"
        )
        assert session_project_name_from_meta({}) is None
        assert session_project_name_from_meta(None) is None
