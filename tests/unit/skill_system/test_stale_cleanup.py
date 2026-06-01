# -*- coding: utf-8 -*-
"""Unit tests for stale skill directory cleanup (#4839).

Verifies that ~-prefixed directories left by pip upgrades on Windows
are properly handled: deleted if they contain SKILL.md (confirmed stale
skill), or warned about if they don't.
"""

from pathlib import Path
from unittest.mock import patch

from qwenpaw.agents.skill_system.registry import cleanup_stale_skill_dirs


class TestCleanupStaleSkillDirs:
    """Tests for cleanup_stale_skill_dirs()."""

    def test_removes_tilde_dir_with_skill_md(self, tmp_path):
        """~-prefixed dir containing SKILL.md should be deleted."""
        stale = tmp_path / "~ron-en"
        stale.mkdir()
        (stale / "SKILL.md").write_text("# Stale skill")

        cleanup_stale_skill_dirs(tmp_path)

        assert not stale.exists()

    def test_preserves_normal_skill_dirs(self, tmp_path):
        """Normal skill directories should not be touched."""
        normal = tmp_path / "cron-en"
        normal.mkdir()
        (normal / "SKILL.md").write_text("# Real skill")

        cleanup_stale_skill_dirs(tmp_path)

        assert normal.exists()
        assert (normal / "SKILL.md").exists()

    def test_warns_tilde_dir_without_skill_md(self, tmp_path):
        """~-prefixed dir without SKILL.md should only produce a warning."""
        suspicious = tmp_path / "~_pycache__"
        suspicious.mkdir()
        (suspicious / "some_file.py").write_text("# not a skill")

        with patch(
            "qwenpaw.agents.skill_system.registry.logger",
        ) as mock_logger:
            cleanup_stale_skill_dirs(tmp_path)

        assert suspicious.exists()  # Not deleted
        mock_logger.warning.assert_called_once()
        assert (
            "possible stale directory"
            in mock_logger.warning.call_args[0][0].lower()
        )

    def test_handles_permission_error(self, tmp_path):
        """Deletion failure should log warning, not crash."""
        stale = tmp_path / "~hat_with_agent-en"
        stale.mkdir()
        (stale / "SKILL.md").write_text("# Stale")

        with patch(
            "qwenpaw.agents.skill_system.registry.logger",
        ) as mock_logger:
            with patch("shutil.rmtree", side_effect=OSError("Access denied")):
                cleanup_stale_skill_dirs(tmp_path)

        mock_logger.warning.assert_called_once()
        assert (
            "failed to remove" in mock_logger.warning.call_args[0][0].lower()
        )

    def test_nonexistent_directory(self):
        """Should not raise for non-existent target directory."""
        cleanup_stale_skill_dirs(Path("/nonexistent/path/12345"))

    def test_multiple_stale_dirs(self, tmp_path):
        """Multiple stale dirs should all be cleaned."""
        names = ["~ron-en", "~-on-en", "~uidance-zh"]
        for name in names:
            d = tmp_path / name
            d.mkdir()
            (d / "SKILL.md").write_text("# Stale")

        # Also create a normal dir
        normal = tmp_path / "cron-en"
        normal.mkdir()
        (normal / "SKILL.md").write_text("# Real")

        cleanup_stale_skill_dirs(tmp_path)

        for name in names:
            assert not (tmp_path / name).exists()
        assert normal.exists()

    def test_files_starting_with_tilde_ignored(self, tmp_path):
        """Regular files starting with ~ should not be affected."""
        tilde_file = tmp_path / "~tempfile.txt"
        tilde_file.write_text("temp")

        cleanup_stale_skill_dirs(tmp_path)

        assert tilde_file.exists()
