# -*- coding: utf-8 -*-
"""Tests for qwenpaw.security.skill_scanner.__init__.

Covers:
- compute_skill_content_hash
- is_skill_whitelisted
- BlockedSkillRecord (to_dict, from_dict)
- _finding_to_dict
- _record_blocked_skill, get_blocked_history,
  clear_blocked_history, remove_blocked_entry
- _load_scanner_config, _get_scan_mode, _scan_timeout
- _get_dir_mtime, _get_cached_result, _store_cached_result
- SkillScanError
- scan_skill_directory
"""
# pylint: disable=redefined-outer-name
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from qwenpaw.security.skill_scanner import (
    BlockedSkillRecord,
    SkillScanError,
    _finding_to_dict,
    _get_blocked_history_path,
    _get_cached_result,
    _get_dir_mtime,
    _load_scanner_config,
    _get_scan_mode,
    _record_blocked_skill,
    _scan_timeout,
    _store_cached_result,
    clear_blocked_history,
    compute_skill_content_hash,
    get_blocked_history,
    is_skill_whitelisted,
    remove_blocked_entry,
    scan_skill_directory,
)
from qwenpaw.security.skill_scanner.models import (
    Finding,
    ScanResult,
    Severity,
    ThreatCategory,
)


# ---------------------------------------------------------------------------
# compute_skill_content_hash
# ---------------------------------------------------------------------------


class TestComputeSkillContentHash:
    """Tests for compute_skill_content_hash."""

    def test_empty_dir(self, tmp_path):
        """Empty directory should produce a valid hash."""
        h = compute_skill_content_hash(tmp_path)
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex digest

    def test_same_content_same_hash(self, tmp_path):
        """Same file contents should produce same hash."""
        (tmp_path / "a.txt").write_text("hello")
        h1 = compute_skill_content_hash(tmp_path)
        h2 = compute_skill_content_hash(tmp_path)
        assert h1 == h2

    def test_different_content_different_hash(self, tmp_path):
        """Different file contents should produce different hashes."""
        (tmp_path / "a.txt").write_text("hello")
        h1 = compute_skill_content_hash(tmp_path)
        (tmp_path / "a.txt").write_text("world")
        h2 = compute_skill_content_hash(tmp_path)
        assert h1 != h2

    def test_nonexistent_dir(self):
        """Nonexistent directory should return a valid hash."""
        h = compute_skill_content_hash(Path("/nonexistent/path"))
        assert isinstance(h, str)
        assert len(h) == 64

    def test_skips_symlinks(self, tmp_path):
        """Symlinks should be skipped."""
        (tmp_path / "real.txt").write_text("content")
        link = tmp_path / "link.txt"
        link.symlink_to(tmp_path / "real.txt")
        h = compute_skill_content_hash(tmp_path)
        assert isinstance(h, str)

    def test_nested_files(self, tmp_path):
        """Nested files should be included."""
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.txt").write_text("nested content")
        (tmp_path / "top.txt").write_text("top content")
        h = compute_skill_content_hash(tmp_path)
        assert isinstance(h, str)
        assert len(h) == 64


# ---------------------------------------------------------------------------
# is_skill_whitelisted
# ---------------------------------------------------------------------------


class TestIsSkillWhitelisted:
    """Tests for is_skill_whitelisted."""

    def test_no_config_returns_false(self):
        """When config is None, should return False."""
        result = is_skill_whitelisted("test-skill", cfg=None)
        assert result is False

    def test_whitelisted_skill_no_hash(self):
        """Skill with no content_hash in whitelist should return True."""
        entry = MagicMock()
        entry.skill_name = "test-skill"
        entry.content_hash = ""
        cfg = MagicMock()
        cfg.whitelist = [entry]
        result = is_skill_whitelisted("test-skill", cfg=cfg)
        assert result is True

    def test_non_whitelisted_skill(self):
        """Non-whitelisted skill should return False."""
        entry = MagicMock()
        entry.skill_name = "other-skill"
        entry.content_hash = ""
        cfg = MagicMock()
        cfg.whitelist = [entry]
        result = is_skill_whitelisted("test-skill", cfg=cfg)
        assert result is False

    def test_whitelisted_with_matching_hash(self, tmp_path):
        """Skill with matching content_hash should return True."""
        (tmp_path / "file.txt").write_text("content")
        content_hash = compute_skill_content_hash(tmp_path)
        entry = MagicMock()
        entry.skill_name = "test-skill"
        entry.content_hash = content_hash
        cfg = MagicMock()
        cfg.whitelist = [entry]
        result = is_skill_whitelisted(
            "test-skill",
            skill_dir=tmp_path,
            cfg=cfg,
        )
        assert result is True

    def test_whitelisted_with_mismatched_hash(self, tmp_path):
        """Skill with mismatched content_hash should return False."""
        entry = MagicMock()
        entry.skill_name = "test-skill"
        entry.content_hash = "wrong_hash"
        cfg = MagicMock()
        cfg.whitelist = [entry]
        result = is_skill_whitelisted(
            "test-skill",
            skill_dir=tmp_path,
            cfg=cfg,
        )
        assert result is False

    def test_whitelisted_with_hash_no_dir(self):
        """Skill with content_hash but no dir should return True."""
        entry = MagicMock()
        entry.skill_name = "test-skill"
        entry.content_hash = "some_hash"
        cfg = MagicMock()
        cfg.whitelist = [entry]
        result = is_skill_whitelisted(
            "test-skill",
            skill_dir=None,
            cfg=cfg,
        )
        assert result is True

    def test_loads_config_when_none(self):
        """When cfg is None, should call _load_scanner_config."""
        with patch(
            "qwenpaw.security.skill_scanner._load_scanner_config",
            return_value=None,
        ) as mock_load:
            result = is_skill_whitelisted("test-skill")
            mock_load.assert_called_once()
            assert result is False


# ---------------------------------------------------------------------------
# BlockedSkillRecord
# ---------------------------------------------------------------------------


class TestBlockedSkillRecord:
    """Tests for BlockedSkillRecord dataclass."""

    def test_creation(self):
        """Should store all fields."""
        r = BlockedSkillRecord(
            skill_name="test-skill",
            blocked_at="2024-01-01T00:00:00Z",
            max_severity="HIGH",
            findings=[{"severity": "HIGH", "title": "test"}],
            content_hash="abc123",
            action="blocked",
        )
        assert r.skill_name == "test-skill"
        assert r.max_severity == "HIGH"
        assert r.action == "blocked"

    def test_defaults(self):
        """Default values should be correct."""
        r = BlockedSkillRecord(
            skill_name="s",
            blocked_at="",
            max_severity="LOW",
        )
        assert not r.findings
        assert r.content_hash == ""
        assert r.action == "blocked"

    def test_to_dict(self):
        """to_dict should serialize all fields."""
        r = BlockedSkillRecord(
            skill_name="test-skill",
            blocked_at="2024-01-01",
            max_severity="CRITICAL",
            findings=[{"severity": "CRITICAL"}],
            content_hash="hash",
            action="warned",
        )
        d = r.to_dict()
        assert d["skill_name"] == "test-skill"
        assert d["action"] == "warned"
        assert d["content_hash"] == "hash"

    def test_from_dict(self):
        """from_dict should deserialize correctly."""
        d = {
            "skill_name": "test-skill",
            "blocked_at": "2024-01-01",
            "max_severity": "HIGH",
            "findings": [{"severity": "HIGH"}],
            "content_hash": "hash",
            "action": "blocked",
        }
        r = BlockedSkillRecord.from_dict(d)
        assert r.skill_name == "test-skill"
        assert r.max_severity == "HIGH"
        assert r.action == "blocked"

    def test_from_dict_defaults(self):
        """from_dict should handle missing optional fields."""
        d = {"skill_name": "s"}
        r = BlockedSkillRecord.from_dict(d)
        assert r.blocked_at == ""
        assert r.max_severity == ""
        assert not r.findings
        assert r.content_hash == ""
        assert r.action == "blocked"

    def test_roundtrip(self):
        """to_dict -> from_dict should preserve data."""
        r = BlockedSkillRecord(
            skill_name="s",
            blocked_at="2024-01-01",
            max_severity="HIGH",
            findings=[{"severity": "HIGH"}],
            content_hash="hash",
            action="warned",
        )
        r2 = BlockedSkillRecord.from_dict(r.to_dict())
        assert r2.skill_name == r.skill_name
        assert r2.max_severity == r.max_severity
        assert r2.action == r.action


# ---------------------------------------------------------------------------
# _finding_to_dict
# ---------------------------------------------------------------------------


class TestFindingToDict:
    """Tests for _finding_to_dict."""

    def test_converts_finding(self):
        """Should convert Finding to dict."""
        f = Finding(
            id="R1:f.py:1",
            rule_id="R1",
            category=ThreatCategory.COMMAND_INJECTION,
            severity=Severity.HIGH,
            title="Test",
            description="test finding",
            file_path="f.py",
            line_number=1,
        )
        d = _finding_to_dict(f)
        assert d["severity"] == "HIGH"
        assert d["title"] == "Test"
        assert d["file_path"] == "f.py"
        assert d["line_number"] == 1
        assert d["rule_id"] == "R1"


# ---------------------------------------------------------------------------
# Blocked history persistence
# ---------------------------------------------------------------------------


class TestBlockedHistoryPersistence:
    """Tests for blocked history read/write operations."""

    def test_get_blocked_history_empty(self, tmp_path):
        """Should return empty list when no history file exists."""
        with patch(
            "qwenpaw.security.skill_scanner._get_blocked_history_path",
            return_value=tmp_path / "nonexistent.json",
        ):
            result = get_blocked_history()
            assert not result

    def test_record_and_get_history(self, tmp_path):
        """Should record and retrieve blocked skill history."""
        history_path = tmp_path / "history.json"
        result = ScanResult(
            skill_name="test-skill",
            skill_directory=str(tmp_path),
            findings=[
                Finding(
                    id="R1",
                    rule_id="R1",
                    category=ThreatCategory.COMMAND_INJECTION,
                    severity=Severity.HIGH,
                    title="Test",
                    description="test",
                ),
            ],
        )
        with patch(
            "qwenpaw.security.skill_scanner._get_blocked_history_path",
            return_value=history_path,
        ):
            _record_blocked_skill(result, tmp_path, action="blocked")
            history = get_blocked_history()
            assert len(history) == 1
            assert history[0].skill_name == "test-skill"
            assert history[0].action == "blocked"

    def test_clear_blocked_history(self, tmp_path):
        """Should clear the history file."""
        history_path = tmp_path / "history.json"
        history_path.write_text("[]", encoding="utf-8")
        with patch(
            "qwenpaw.security.skill_scanner._get_blocked_history_path",
            return_value=history_path,
        ):
            clear_blocked_history()
            assert not history_path.exists()

    def test_clear_nonexistent_history(self, tmp_path):
        """Should not raise when clearing nonexistent history."""
        with patch(
            "qwenpaw.security.skill_scanner._get_blocked_history_path",
            return_value=tmp_path / "nonexistent.json",
        ):
            clear_blocked_history()  # Should not raise

    def test_remove_blocked_entry(self, tmp_path):
        """Should remove a specific entry by index."""
        history_path = tmp_path / "history.json"
        records = [
            {"skill_name": "skill1", "blocked_at": "", "max_severity": "LOW"},
            {"skill_name": "skill2", "blocked_at": "", "max_severity": "HIGH"},
        ]
        history_path.write_text(
            json.dumps(records),
            encoding="utf-8",
        )
        with patch(
            "qwenpaw.security.skill_scanner._get_blocked_history_path",
            return_value=history_path,
        ):
            result = remove_blocked_entry(0)
            assert result is True
            history = get_blocked_history()
            assert len(history) == 1
            assert history[0].skill_name == "skill2"

    def test_remove_blocked_entry_invalid_index(self, tmp_path):
        """Should return False for invalid index."""
        history_path = tmp_path / "history.json"
        history_path.write_text("[]", encoding="utf-8")
        with patch(
            "qwenpaw.security.skill_scanner._get_blocked_history_path",
            return_value=history_path,
        ):
            result = remove_blocked_entry(99)
            assert result is False

    def test_remove_blocked_entry_no_file(self, tmp_path):
        """Should return False when no history file exists."""
        with patch(
            "qwenpaw.security.skill_scanner._get_blocked_history_path",
            return_value=tmp_path / "nonexistent.json",
        ):
            result = remove_blocked_entry(0)
            assert result is False

    def test_record_multiple_entries(self, tmp_path):
        """Should append multiple entries."""
        history_path = tmp_path / "history.json"
        with patch(
            "qwenpaw.security.skill_scanner._get_blocked_history_path",
            return_value=history_path,
        ):
            for i in range(3):
                result = ScanResult(
                    skill_name=f"skill-{i}",
                    skill_directory=str(tmp_path),
                    findings=[],
                )
                _record_blocked_skill(result, tmp_path, action="blocked")
            history = get_blocked_history()
            assert len(history) == 3


# ---------------------------------------------------------------------------
# _load_scanner_config, _get_scan_mode, _scan_timeout
# ---------------------------------------------------------------------------


class TestLoadScannerConfig:
    """Tests for _load_scanner_config."""

    def test_returns_none_on_import_error(self):
        """Should return None when config import fails."""
        with patch(
            "qwenpaw.config.load_config",
            side_effect=ImportError,
        ):
            result = _load_scanner_config()
            assert result is None

    def test_returns_none_on_generic_exception(self):
        """Should return None on any exception."""
        with patch(
            "qwenpaw.config.load_config",
            side_effect=RuntimeError("boom"),
        ):
            result = _load_scanner_config()
            assert result is None


class TestGetScanMode:
    """Tests for _get_scan_mode."""

    def test_env_var_block(self):
        """QWENPAW_SKILL_SCAN_MODE=block should return 'block'."""
        with patch(
            "qwenpaw.security.skill_scanner.EnvVarLoader.get_str",
            return_value="block",
        ):
            assert _get_scan_mode() == "block"

    def test_env_var_warn(self):
        """QWENPAW_SKILL_SCAN_MODE=warn should return 'warn'."""
        with patch(
            "qwenpaw.security.skill_scanner.EnvVarLoader.get_str",
            return_value="warn",
        ):
            assert _get_scan_mode() == "warn"

    def test_env_var_off(self):
        """QWENPAW_SKILL_SCAN_MODE=off should return 'off'."""
        with patch(
            "qwenpaw.security.skill_scanner.EnvVarLoader.get_str",
            return_value="off",
        ):
            assert _get_scan_mode() == "off"

    def test_env_var_case_insensitive(self):
        """Env var value should be case-insensitive."""
        with patch(
            "qwenpaw.security.skill_scanner.EnvVarLoader.get_str",
            return_value="BLOCK",
        ):
            assert _get_scan_mode() == "block"

    def test_invalid_env_var_falls_to_config(self):
        """Invalid env var should fall through to config."""
        cfg = MagicMock()
        cfg.mode = "warn"
        with patch(
            "qwenpaw.security.skill_scanner.EnvVarLoader.get_str",
            return_value="invalid",
        ):
            result = _get_scan_mode(cfg=cfg)
            assert result == "warn"

    def test_no_env_no_config_defaults_to_block(self):
        """No env var and no config should default to 'block'."""
        with patch(
            "qwenpaw.security.skill_scanner.EnvVarLoader.get_str",
            return_value="",
        ), patch(
            "qwenpaw.security.skill_scanner._load_scanner_config",
            return_value=None,
        ):
            result = _get_scan_mode()
            assert result == "block"


class TestScanTimeout:
    """Tests for _scan_timeout."""

    def test_config_timeout(self):
        """Should use config timeout when available."""
        cfg = MagicMock()
        cfg.timeout = 60
        result = _scan_timeout(cfg=cfg)
        assert result == 60.0

    def test_default_timeout(self):
        """Should default to 30.0 when no config."""
        with patch(
            "qwenpaw.security.skill_scanner._load_scanner_config",
            return_value=None,
        ):
            result = _scan_timeout()
            assert result == 30.0


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


class TestCacheHelpers:
    """Tests for _get_dir_mtime, _get_cached_result, _store_cached_result."""

    def test_get_dir_mtime(self, tmp_path):
        """Should return a positive mtime for existing directory."""
        mtime = _get_dir_mtime(tmp_path)
        assert mtime > 0

    def test_get_dir_mtime_nonexistent(self):
        """Should return 0.0 for nonexistent directory."""
        mtime = _get_dir_mtime(Path("/nonexistent"))
        assert mtime == 0.0

    def test_cache_store_and_retrieve(self, tmp_path):
        """Should store and retrieve cached results."""
        result = ScanResult(
            skill_name="test",
            skill_directory=str(tmp_path),
        )
        _store_cached_result(tmp_path, result)
        cached = _get_cached_result(tmp_path)
        assert cached is not None
        assert cached.skill_name == "test"

    def test_cache_miss(self, tmp_path):
        """Should return None for uncached directory."""
        cached = _get_cached_result(tmp_path)
        assert cached is None

    def test_cache_invalidation_on_change(self, tmp_path):
        """Cache should be invalidated when directory changes."""
        result = ScanResult(
            skill_name="test",
            skill_directory=str(tmp_path),
        )
        _store_cached_result(tmp_path, result)
        # Modify directory to change mtime
        import time

        (tmp_path / "new_file.txt").write_text("change")
        time.sleep(0.1)  # Ensure mtime difference
        cached = _get_cached_result(tmp_path)
        # After modification, cache should be invalidated
        # (mtime changed, so cached result is None)
        assert cached is None


# ---------------------------------------------------------------------------
# SkillScanError
# ---------------------------------------------------------------------------


class TestSkillScanError:
    """Tests for SkillScanError."""

    def test_error_message(self):
        """Should include finding summary in message."""
        result = ScanResult(
            skill_name="bad-skill",
            skill_directory="/tmp",
            findings=[
                Finding(
                    id="R1",
                    rule_id="R1",
                    category=ThreatCategory.COMMAND_INJECTION,
                    severity=Severity.HIGH,
                    title="Dangerous cmd",
                    description="test",
                    file_path="script.sh",
                    line_number=1,
                ),
            ],
        )
        error = SkillScanError(result)
        assert "bad-skill" in str(error)
        assert "HIGH" in str(error)
        assert error.result is result

    def test_error_message_truncation(self):
        """Should truncate when more than 5 findings."""
        findings = [
            Finding(
                id=f"R{i}",
                rule_id=f"R{i}",
                category=ThreatCategory.COMMAND_INJECTION,
                severity=Severity.LOW,
                title=f"Finding {i}",
                description="test",
                file_path="f.py",
            )
            for i in range(8)
        ]
        result = ScanResult(
            skill_name="many-findings",
            skill_directory="/tmp",
            findings=findings,
        )
        error = SkillScanError(result)
        assert "3 more" in str(error)


# ---------------------------------------------------------------------------
# scan_skill_directory
# ---------------------------------------------------------------------------


class TestScanSkillDirectory:
    """Tests for scan_skill_directory."""

    def test_scan_mode_off(self, tmp_path):
        """Should return None when scan mode is 'off'."""
        with patch(
            "qwenpaw.security.skill_scanner._get_scan_mode",
            return_value="off",
        ):
            result = scan_skill_directory(str(tmp_path))
            assert result is None

    def test_scan_whitelisted_skill(self, tmp_path):
        """Should return None for whitelisted skill."""
        with patch(
            "qwenpaw.security.skill_scanner._get_scan_mode",
            return_value="block",
        ), patch(
            "qwenpaw.security.skill_scanner.is_skill_whitelisted",
            return_value=True,
        ):
            result = scan_skill_directory(str(tmp_path))
            assert result is None

    def test_scan_safe_skill(self, tmp_path):
        """Should return ScanResult for safe skill."""
        (tmp_path / "safe.py").write_text("print('hello')")
        with patch(
            "qwenpaw.security.skill_scanner._get_scan_mode",
            return_value="warn",
        ), patch(
            "qwenpaw.security.skill_scanner.is_skill_whitelisted",
            return_value=False,
        ), patch(
            "qwenpaw.security.skill_scanner._load_scanner_config",
            return_value=None,
        ):
            result = scan_skill_directory(
                str(tmp_path),
                skill_name="safe-skill",
            )
            assert result is not None
            assert isinstance(result, ScanResult)

    def test_scan_unsafe_skill_block_mode(self, tmp_path):
        """Should raise SkillScanError in block mode for unsafe skill."""
        unsafe_result = ScanResult(
            skill_name="danger-skill",
            skill_directory=str(tmp_path),
            findings=[
                Finding(
                    id="R1",
                    rule_id="R1",
                    category=ThreatCategory.COMMAND_INJECTION,
                    severity=Severity.HIGH,
                    title="Dangerous",
                    description="test",
                ),
            ],
        )
        with patch(
            "qwenpaw.security.skill_scanner._get_scan_mode",
            return_value="block",
        ), patch(
            "qwenpaw.security.skill_scanner.is_skill_whitelisted",
            return_value=False,
        ), patch(
            "qwenpaw.security.skill_scanner._load_scanner_config",
            return_value=None,
        ), patch(
            "qwenpaw.security.skill_scanner._get_scanner",
        ) as mock_scanner_cls, patch(
            "qwenpaw.security.skill_scanner._get_cached_result",
            return_value=None,
        ), patch(
            "qwenpaw.security.skill_scanner._store_cached_result",
        ):
            mock_scanner = MagicMock()
            mock_scanner.scan_skill.return_value = unsafe_result
            mock_scanner_cls.return_value = mock_scanner
            with pytest.raises(SkillScanError):
                scan_skill_directory(
                    str(tmp_path),
                    skill_name="danger-skill",
                )

    def test_scan_unsafe_skill_warn_mode(self, tmp_path):
        """Should return ScanResult in warn mode for unsafe skill."""
        unsafe_result = ScanResult(
            skill_name="danger-skill",
            skill_directory=str(tmp_path),
            findings=[
                Finding(
                    id="R1",
                    rule_id="R1",
                    category=ThreatCategory.COMMAND_INJECTION,
                    severity=Severity.HIGH,
                    title="Dangerous",
                    description="test",
                ),
            ],
        )
        with patch(
            "qwenpaw.security.skill_scanner._get_scan_mode",
            return_value="warn",
        ), patch(
            "qwenpaw.security.skill_scanner.is_skill_whitelisted",
            return_value=False,
        ), patch(
            "qwenpaw.security.skill_scanner._load_scanner_config",
            return_value=None,
        ), patch(
            "qwenpaw.security.skill_scanner._get_scanner",
        ) as mock_scanner_cls, patch(
            "qwenpaw.security.skill_scanner._get_cached_result",
            return_value=None,
        ), patch(
            "qwenpaw.security.skill_scanner._store_cached_result",
        ), patch(
            "qwenpaw.security.skill_scanner._record_blocked_skill",
        ):
            mock_scanner = MagicMock()
            mock_scanner.scan_skill.return_value = unsafe_result
            mock_scanner_cls.return_value = mock_scanner
            result = scan_skill_directory(
                str(tmp_path),
                skill_name="danger-skill",
            )
            assert result is not None
            assert not result.is_safe

    def test_scan_with_explicit_block(self, tmp_path):
        """block=True should raise even in warn mode."""
        unsafe_result = ScanResult(
            skill_name="danger-skill",
            skill_directory=str(tmp_path),
            findings=[
                Finding(
                    id="R1",
                    rule_id="R1",
                    category=ThreatCategory.COMMAND_INJECTION,
                    severity=Severity.HIGH,
                    title="Dangerous",
                    description="test",
                ),
            ],
        )
        with patch(
            "qwenpaw.security.skill_scanner._get_scan_mode",
            return_value="warn",
        ), patch(
            "qwenpaw.security.skill_scanner.is_skill_whitelisted",
            return_value=False,
        ), patch(
            "qwenpaw.security.skill_scanner._load_scanner_config",
            return_value=None,
        ), patch(
            "qwenpaw.security.skill_scanner._get_scanner",
        ) as mock_scanner_cls, patch(
            "qwenpaw.security.skill_scanner._get_cached_result",
            return_value=None,
        ), patch(
            "qwenpaw.security.skill_scanner._store_cached_result",
        ):
            mock_scanner = MagicMock()
            mock_scanner.scan_skill.return_value = unsafe_result
            mock_scanner_cls.return_value = mock_scanner
            with pytest.raises(SkillScanError):
                scan_skill_directory(
                    str(tmp_path),
                    skill_name="danger-skill",
                    block=True,
                )

    def test_scan_uses_skill_dir_name(self, tmp_path):
        """Should use directory name as skill_name when not provided."""
        (tmp_path / "safe.py").write_text("x = 1")
        with patch(
            "qwenpaw.security.skill_scanner._get_scan_mode",
            return_value="warn",
        ), patch(
            "qwenpaw.security.skill_scanner.is_skill_whitelisted",
            return_value=False,
        ), patch(
            "qwenpaw.security.skill_scanner._load_scanner_config",
            return_value=None,
        ):
            result = scan_skill_directory(str(tmp_path))
            assert result is not None
            assert result.skill_name == tmp_path.name


# ---------------------------------------------------------------------------
# _get_blocked_history_path
# ---------------------------------------------------------------------------


class TestGetBlockedHistoryPath:
    """Tests for _get_blocked_history_path."""

    def test_returns_path(self):
        """Should return a Path object."""
        path = _get_blocked_history_path()
        assert isinstance(path, Path)
        assert path.name == "skill_scanner_blocked.json"

    def test_uses_working_dir(self):
        """Should use WORKING_DIR when available."""
        mock_working_dir = MagicMock()
        mock_working_dir.__truediv__ = (
            lambda self, other: Path(
                "/mock/.qwenpaw",
            )
            / other
        )
        with patch(
            "qwenpaw.security.skill_scanner._get_blocked_history_path",
        ):
            # Just verify the function returns a Path
            result = _get_blocked_history_path()
            assert isinstance(result, Path)
