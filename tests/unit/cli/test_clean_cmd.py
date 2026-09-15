# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Unit tests for the `clean` CLI command."""

import pytest
from click.testing import CliRunner

from qwenpaw.cli import clean_cmd as clean_mod
from qwenpaw.utils.telemetry import TELEMETRY_MARKER_FILE


@pytest.fixture()
def working_dir(monkeypatch, tmp_path):
    """Redirect WORKING_DIR (value-bound at import) to a temp dir."""
    wd = tmp_path / "qwenpaw-home"
    wd.mkdir()
    monkeypatch.setattr(clean_mod, "WORKING_DIR", wd)
    return wd


class TestIterChildren:
    def test_returns_sorted_names(self, tmp_path):
        for name in ("zebra", "alpha", "middle"):
            (tmp_path / name).write_text("x", encoding="utf-8")

        names = [p.name for p in clean_mod._iter_children(tmp_path)]

        assert names == ["alpha", "middle", "zebra"]

    def test_missing_directory_yields_empty_list(self, tmp_path):
        assert clean_mod._iter_children(tmp_path / "nope") == []

    def test_includes_directories_and_files(self, tmp_path):
        (tmp_path / "adir").mkdir()
        (tmp_path / "afile").write_text("x", encoding="utf-8")

        names = [p.name for p in clean_mod._iter_children(tmp_path)]

        assert names == ["adir", "afile"]


class TestMissingWorkingDir:
    def test_reports_and_exits_zero(self, monkeypatch, tmp_path):
        monkeypatch.setattr(clean_mod, "WORKING_DIR", tmp_path / "absent")

        result = CliRunner().invoke(clean_mod.clean_cmd, ["--yes"])

        assert result.exit_code == 0
        assert "WORKING_DIR does not exist" in result.output


class TestEmptyWorkingDir:
    def test_already_empty_message(self, working_dir):
        result = CliRunner().invoke(clean_mod.clean_cmd, ["--yes"])

        assert result.exit_code == 0
        assert "already empty" in result.output

    def test_only_telemetry_marker_reports_no_removable_files(
        self, working_dir
    ):
        (working_dir / TELEMETRY_MARKER_FILE).write_text("1", encoding="utf-8")

        result = CliRunner().invoke(clean_mod.clean_cmd, ["--yes"])

        assert result.exit_code == 0
        assert "no removable files" in result.output
        # The marker must survive: it records that telemetry was already sent.
        assert (working_dir / TELEMETRY_MARKER_FILE).is_file()


class TestDryRun:
    def test_lists_targets_without_deleting(self, working_dir):
        (working_dir / "keepme.txt").write_text("data", encoding="utf-8")
        (working_dir / "adir").mkdir()

        result = CliRunner().invoke(clean_mod.clean_cmd, ["--dry-run"])

        assert result.exit_code == 0
        assert "Will remove:" in result.output
        assert "keepme.txt" in result.output
        assert "adir" in result.output
        assert "dry-run: nothing deleted." in result.output
        assert (working_dir / "keepme.txt").is_file()
        assert (working_dir / "adir").is_dir()

    def test_dry_run_does_not_prompt_for_confirmation(self, working_dir):
        (working_dir / "f.txt").write_text("d", encoding="utf-8")

        # No --yes and no stdin: a prompt would abort, dry-run must not reach it.
        result = CliRunner().invoke(
            clean_mod.clean_cmd,
            ["--dry-run"],
            input="",
        )

        assert result.exit_code == 0
        assert "Cancelled." not in result.output


class TestTelemetryMarkerPreserved:
    def test_marker_announced_and_kept_while_others_removed(self, working_dir):
        (working_dir / TELEMETRY_MARKER_FILE).write_text("1", encoding="utf-8")
        (working_dir / "chats").mkdir()
        (working_dir / "config.json").write_text("{}", encoding="utf-8")

        result = CliRunner().invoke(clean_mod.clean_cmd, ["--yes"])

        assert result.exit_code == 0
        assert f"Will keep: {TELEMETRY_MARKER_FILE}" in result.output
        assert "Done." in result.output
        assert (working_dir / TELEMETRY_MARKER_FILE).is_file()
        assert not (working_dir / "chats").exists()
        assert not (working_dir / "config.json").exists()


class TestConfirmation:
    def test_declining_cancels_and_keeps_files(self, working_dir):
        (working_dir / "important.txt").write_text("d", encoding="utf-8")

        result = CliRunner().invoke(clean_mod.clean_cmd, [], input="n\n")

        assert result.exit_code == 0
        assert "Cancelled." in result.output
        assert (working_dir / "important.txt").is_file()

    def test_accepting_deletes_contents_but_keeps_dir(self, working_dir):
        (working_dir / "a.txt").write_text("d", encoding="utf-8")

        result = CliRunner().invoke(clean_mod.clean_cmd, [], input="y\n")

        assert result.exit_code == 0
        assert "Done." in result.output
        assert not (working_dir / "a.txt").exists()
        assert working_dir.is_dir()

    def test_yes_flag_skips_prompt(self, working_dir):
        (working_dir / "a.txt").write_text("d", encoding="utf-8")

        result = CliRunner().invoke(clean_mod.clean_cmd, ["--yes"])

        assert result.exit_code == 0
        assert not (working_dir / "a.txt").exists()


class TestDeletionMechanics:
    def test_removes_nested_directories_recursively(self, working_dir):
        nested = working_dir / "workspaces" / "default" / "memory"
        nested.mkdir(parents=True)
        (nested / "MEMORY.md").write_text("x", encoding="utf-8")

        result = CliRunner().invoke(clean_mod.clean_cmd, ["--yes"])

        assert result.exit_code == 0
        assert not (working_dir / "workspaces").exists()

    def test_removes_symlink_without_following_target(
        self, working_dir, tmp_path
    ):
        """A symlinked dir must be unlinked, not rmtree'd into the target."""
        outside = tmp_path / "outside-data"
        outside.mkdir()
        (outside / "precious.txt").write_text("keep", encoding="utf-8")
        (working_dir / "link").symlink_to(outside, target_is_directory=True)

        result = CliRunner().invoke(clean_mod.clean_cmd, ["--yes"])

        assert result.exit_code == 0
        assert not (working_dir / "link").exists()
        # The symlink target must be untouched.
        assert (outside / "precious.txt").read_text(encoding="utf-8") == "keep"

    def test_vanished_child_does_not_abort_the_run(
        self,
        working_dir,
        monkeypatch,
    ):
        """A child removed concurrently must not surface as an error.

        The listing is taken before deletion, so a race is possible; the loop
        swallows FileNotFoundError. Drive it by listing a path that is already
        gone instead of patching pathlib globally.
        """
        survivor = working_dir / "survivor.txt"
        survivor.write_text("x", encoding="utf-8")
        vanished = working_dir / "vanished.txt"

        real_iter = clean_mod._iter_children

        def listing_with_ghost(path):
            return real_iter(path) + [vanished]

        monkeypatch.setattr(clean_mod, "_iter_children", listing_with_ghost)

        result = CliRunner().invoke(clean_mod.clean_cmd, ["--yes"])

        assert result.exit_code == 0
        assert "Done." in result.output
        assert not survivor.exists()

    def test_vanished_directory_child_does_not_abort(
        self, working_dir, monkeypatch
    ):
        """Same race on the rmtree branch (a directory that vanished)."""
        ghost_dir = working_dir / "ghost-dir"
        real_iter = clean_mod._iter_children

        monkeypatch.setattr(
            clean_mod,
            "_iter_children",
            lambda path: real_iter(path) + [ghost_dir],
        )

        result = CliRunner().invoke(clean_mod.clean_cmd, ["--yes"])

        # A missing directory is neither is_dir() nor a symlink, so it takes
        # the unlink branch and FileNotFoundError is swallowed.
        assert result.exit_code == 0
        assert "Done." in result.output
