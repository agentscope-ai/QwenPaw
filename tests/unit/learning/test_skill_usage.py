# -*- coding: utf-8 -*-
"""Tests for SkillUsageTracker."""
import tempfile
from pathlib import Path

from copaw.app.learning.skill_usage import SkillUsageTracker


class TestSkillUsageTracker:
    def _make_tracker(self, tmp_path: Path) -> SkillUsageTracker:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        return SkillUsageTracker(skills_dir)

    def test_init_and_get_stats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = self._make_tracker(Path(tmpdir))
            tracker.init_meta("test-skill")
            stats = tracker.get_stats("test-skill")
            assert stats is not None
            assert stats.use_count == 0
            assert stats.origin == "auto"
            assert stats.success_rate == 1.0

    def test_record_usage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = self._make_tracker(Path(tmpdir))
            tracker.init_meta("my-skill")
            tracker.record_usage("my-skill", outcome="success")
            tracker.record_usage("my-skill", outcome="success")
            tracker.record_usage("my-skill", outcome="failure")
            stats = tracker.get_stats("my-skill")
            assert stats.use_count == 3
            assert stats.success_count == 2
            assert stats.failure_count == 1
            assert abs(stats.success_rate - 2 / 3) < 0.01

    def test_record_revision(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = self._make_tracker(Path(tmpdir))
            tracker.init_meta("my-skill")
            tracker.record_revision(
                "my-skill",
                reason="added error handling",
            )
            stats = tracker.get_stats("my-skill")
            assert len(stats.revision_history) == 1
            assert (
                stats.revision_history[0]["reason"]
                == "added error handling"
            )

    def test_list_underperforming(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = self._make_tracker(Path(tmpdir))
            # Good skill
            tracker.init_meta("good-skill")
            for _ in range(5):
                tracker.record_usage(
                    "good-skill",
                    outcome="success",
                )
            # Bad skill
            tracker.init_meta("bad-skill")
            for _ in range(3):
                tracker.record_usage(
                    "bad-skill",
                    outcome="failure",
                )
            result = tracker.list_underperforming(
                min_uses=3,
                max_success_rate=0.5,
            )
            assert "bad-skill" in result
            assert "good-skill" not in result

    def test_no_meta_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = self._make_tracker(Path(tmpdir))
            assert tracker.get_stats("nonexistent") is None

    def test_record_on_missing_meta_is_noop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = self._make_tracker(Path(tmpdir))
            # Should not raise
            tracker.record_usage("nope", outcome="success")
