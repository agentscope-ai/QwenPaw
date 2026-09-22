# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Unit tests for the `uninstall` CLI command.

The command rewrites shell profiles discovered at import time from
``Path.home()``, so every test redirects ``_SHELL_PROFILES`` to temp paths.
"""

import pytest
from click.testing import CliRunner

from qwenpaw.cli import uninstall_cmd as un_mod

# The exact block the installer appends to shell profiles.
_PATH_BLOCK = '# QwenPaw\nexport PATH="$HOME/.qwenpaw/bin:$PATH"\n'


@pytest.fixture()
def env(monkeypatch, tmp_path):
    """Isolate WORKING_DIR and the shell profiles from the real machine."""
    wd = tmp_path / "qwenpaw-home"
    wd.mkdir()
    monkeypatch.setattr(un_mod, "WORKING_DIR", wd)

    profiles = tuple(
        tmp_path / name for name in ("zshrc", "bashrc", "profile")
    )
    monkeypatch.setattr(un_mod, "_SHELL_PROFILES", profiles)
    return {"wd": wd, "profiles": profiles, "tmp": tmp_path}


class TestRemovePathEntry:
    def test_missing_profile_returns_false(self, tmp_path):
        assert un_mod._remove_path_entry(tmp_path / "absent") is False

    def test_profile_without_block_is_untouched(self, tmp_path):
        profile = tmp_path / "bashrc"
        original = "export EDITOR=vim\nalias ll='ls -la'\n"
        profile.write_text(original, encoding="utf-8")

        changed = un_mod._remove_path_entry(profile)

        assert changed is False
        assert profile.read_text(encoding="utf-8") == original

    def test_removes_the_qwenpaw_block(self, tmp_path):
        profile = tmp_path / "bashrc"
        profile.write_text(
            "export EDITOR=vim\n" + _PATH_BLOCK + "alias ll='ls -la'\n",
            encoding="utf-8",
        )

        changed = un_mod._remove_path_entry(profile)

        assert changed is True
        result = profile.read_text(encoding="utf-8")
        assert "# QwenPaw" not in result
        assert ".qwenpaw/bin" not in result

    def test_preserves_unrelated_lines(self, tmp_path):
        profile = tmp_path / "bashrc"
        profile.write_text(
            "export EDITOR=vim\n" + _PATH_BLOCK + "alias ll='ls -la'\n",
            encoding="utf-8",
        )

        un_mod._remove_path_entry(profile)

        result = profile.read_text(encoding="utf-8")
        assert "export EDITOR=vim" in result
        assert "alias ll='ls -la'" in result

    def test_only_matches_the_exact_export_line(self, tmp_path):
        """A different QwenPaw comment must not be stripped."""
        profile = tmp_path / "bashrc"
        profile.write_text(
            "# QwenPaw notes\nexport PATH=/usr/bin:$PATH\n",
            encoding="utf-8",
        )

        assert un_mod._remove_path_entry(profile) is False


class TestConfirmation:
    def test_declining_cancels_and_keeps_everything(self, env):
        (env["wd"] / "venv").mkdir()
        (env["wd"] / "config.json").write_text("{}", encoding="utf-8")

        result = CliRunner().invoke(un_mod.uninstall_cmd, [], input="n\n")

        assert result.exit_code == 0
        assert "Cancelled." in result.output
        assert (env["wd"] / "venv").is_dir()
        assert (env["wd"] / "config.json").is_file()

    def test_accepting_proceeds(self, env):
        result = CliRunner().invoke(un_mod.uninstall_cmd, [], input="y\n")

        assert result.exit_code == 0
        assert "Cancelled." not in result.output
        assert "QwenPaw uninstalled." in result.output


class TestWithoutPurge:
    def test_announces_that_data_is_preserved(self, env):
        result = CliRunner().invoke(un_mod.uninstall_cmd, ["--yes"])

        assert result.exit_code == 0
        assert "will be preserved" in result.output
        assert "This will remove ALL QwenPaw data" not in result.output

    def test_removes_installer_dirs_only(self, env):
        (env["wd"] / "venv").mkdir()
        (env["wd"] / "bin").mkdir()
        (env["wd"] / "config.json").write_text("{}", encoding="utf-8")
        (env["wd"] / "chats").mkdir()

        result = CliRunner().invoke(un_mod.uninstall_cmd, ["--yes"])

        assert result.exit_code == 0
        assert not (env["wd"] / "venv").exists()
        assert not (env["wd"] / "bin").exists()
        # User data survives without --purge.
        assert (env["wd"] / "config.json").is_file()
        assert (env["wd"] / "chats").is_dir()

    def test_reports_each_removed_dir(self, env):
        (env["wd"] / "venv").mkdir()
        (env["wd"] / "bin").mkdir()

        result = CliRunner().invoke(un_mod.uninstall_cmd, ["--yes"])

        assert result.output.count("Removed") == 2

    def test_missing_installer_dirs_are_skipped(self, env):
        result = CliRunner().invoke(un_mod.uninstall_cmd, ["--yes"])

        assert result.exit_code == 0
        assert "Removed" not in result.output
        assert env["wd"].is_dir()


class TestWithPurge:
    def test_announces_total_removal(self, env):
        result = CliRunner().invoke(un_mod.uninstall_cmd, ["--purge", "--yes"])

        assert result.exit_code == 0
        assert "This will remove ALL QwenPaw data" in result.output

    def test_removes_working_dir_entirely(self, env):
        (env["wd"] / "config.json").write_text("{}", encoding="utf-8")
        (env["wd"] / "chats").mkdir()

        result = CliRunner().invoke(un_mod.uninstall_cmd, ["--purge", "--yes"])

        assert result.exit_code == 0
        assert not env["wd"].exists()

    def test_purge_still_requires_confirmation(self, env):
        (env["wd"] / "config.json").write_text("{}", encoding="utf-8")

        result = CliRunner().invoke(
            un_mod.uninstall_cmd,
            ["--purge"],
            input="n\n",
        )

        assert result.exit_code == 0
        assert "Cancelled." in result.output
        assert (env["wd"] / "config.json").is_file()

    def test_purge_on_absent_working_dir_does_not_raise(
        self,
        monkeypatch,
        tmp_path,
    ):
        monkeypatch.setattr(un_mod, "WORKING_DIR", tmp_path / "absent")
        monkeypatch.setattr(un_mod, "_SHELL_PROFILES", ())

        result = CliRunner().invoke(un_mod.uninstall_cmd, ["--purge", "--yes"])

        assert result.exit_code == 0
        assert "QwenPaw uninstalled." in result.output


class TestShellProfileCleanup:
    def test_reports_cleaned_profiles(self, env):
        profile = env["profiles"][1]
        profile.write_text("keep\n" + _PATH_BLOCK, encoding="utf-8")

        result = CliRunner().invoke(un_mod.uninstall_cmd, ["--yes"])

        assert result.exit_code == 0
        assert "Cleaned" in result.output
        assert str(profile) in result.output
        assert "# QwenPaw" not in profile.read_text(encoding="utf-8")

    def test_no_cleaned_line_when_nothing_to_strip(self, env):
        for profile in env["profiles"]:
            profile.write_text("export EDITOR=vim\n", encoding="utf-8")

        result = CliRunner().invoke(un_mod.uninstall_cmd, ["--yes"])

        assert result.exit_code == 0
        assert "Cleaned" not in result.output

    def test_absent_profiles_are_skipped_silently(self, env):
        result = CliRunner().invoke(un_mod.uninstall_cmd, ["--yes"])

        assert result.exit_code == 0
        assert "Cleaned" not in result.output
        for profile in env["profiles"]:
            assert not profile.exists()

    def test_cleanup_runs_even_when_no_installer_dirs(self, env):
        profile = env["profiles"][0]
        profile.write_text(_PATH_BLOCK, encoding="utf-8")

        result = CliRunner().invoke(un_mod.uninstall_cmd, ["--yes"])

        assert result.exit_code == 0
        assert "Cleaned" in result.output


class TestFinalMessage:
    def test_asks_to_restart_terminal(self, env):
        result = CliRunner().invoke(un_mod.uninstall_cmd, ["--yes"])

        assert result.exit_code == 0
        assert "Please restart your terminal." in result.output
