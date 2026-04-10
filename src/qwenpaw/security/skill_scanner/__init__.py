# -*- coding: utf-8 -*-
"""
Skill security scanner for CoPaw.

Scans skills for security threats before they are activated or installed.

Architecture
~~~~~~~~~~~~

The scanner follows a lightweight, extensible design:

* **BaseAnalyzer** - abstract interface every analyzer must implement.
* **PatternAnalyzer** - YAML regex-signature matching (fast, line-based).
* **SkillScanner** - orchestrator that runs registered analyzers and
  aggregates findings into a :class:`ScanResult`.

This branch intentionally ships the baseline pattern analyzer only.
Additional analyzers can be plugged in later without changing the
orchestrator.

Quick start::

    from qwenpaw.security.skill_scanner import SkillScanner

    scanner = SkillScanner()
    result = scanner.scan_skill("/path/to/skill_directory")
    if not result.is_safe:
        print(f"Blocked: {result.max_severity.value} findings detected")
"""
from __future__ import annotations

from concurrent import futures
import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import (
    Finding,
    ScanResult,
    Severity,
    SkillFile,
    ThreatCategory,
)
from .scan_policy import ScanPolicy
from ...constant import EnvVarLoader
from .analyzers import BaseAnalyzer
from .analyzers.pattern_analyzer import PatternAnalyzer
from .scanner import SkillScanner

logger = logging.getLogger(__name__)

__all__ = [
    "BaseAnalyzer",
    "BlockedSkillRecord",
    "Finding",
    "PatternAnalyzer",
    "ScanPolicy",
    "ScanResult",
    "Severity",
    "SkillFile",
    "SkillScanner",
    "SkillScanError",
    "ThreatCategory",
    "compute_skill_content_hash",
    "get_blocked_history",
    "clear_blocked_history",
    "remove_blocked_entry",
    "is_skill_whitelisted",
    "scan_skill_directory",
]

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


_VALID_MODES = {"block", "warn", "off"}


def _load_scanner_config() -> Any:
    """Load SkillScannerConfig from the app config (lazy import)."""
    try:
        from ...config import load_config

        return load_config().security.skill_scanner
    except Exception:
        return None


def _get_scan_mode(cfg: Any = None) -> str:
    """Return the effective scan mode: ``block``, ``warn``, or ``off``.

    Priority: env ``QWENPAW_SKILL_SCAN_MODE`` > config > default ``warn``.
    """
    env = EnvVarLoader.get_str("QWENPAW_SKILL_SCAN_MODE") or None
    if env is not None:
        val = env.lower().strip()
        if val in _VALID_MODES:
            return val
    if cfg is None:
        cfg = _load_scanner_config()
    return cfg.mode if cfg is not None else "block"


def _scan_timeout(cfg: Any = None) -> float:
    if cfg is None:
        cfg = _load_scanner_config()
    return float(cfg.timeout) if cfg is not None else 30.0


# ---------------------------------------------------------------------------
# Content hash
# ---------------------------------------------------------------------------


def compute_skill_content_hash(skill_dir: Path) -> str:
    """SHA-256 hash of all regular file contents in *skill_dir* (sorted)."""
    h = hashlib.sha256()
    try:
        for p in sorted(skill_dir.rglob("*")):
            if p.is_file() and not p.is_symlink():
                try:
                    h.update(p.read_bytes())
                except OSError:
                    pass
    except OSError:
        pass
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Whitelist helpers
# ---------------------------------------------------------------------------


def is_skill_whitelisted(
    skill_name: str,
    skill_dir: Path | None = None,
    *,
    cfg: Any = None,
) -> bool:
    """Return True if *skill_name* is on the whitelist.

    When a whitelist entry has a non-empty ``content_hash``, the hash must
    match the current directory contents for the entry to apply.
    """
    if cfg is None:
        cfg = _load_scanner_config()
    if cfg is None:
        return False
    for entry in cfg.whitelist:
        if entry.skill_name != skill_name:
            continue
        if not entry.content_hash:
            return True
        if skill_dir is not None:
            current_hash = compute_skill_content_hash(skill_dir)
            if current_hash == entry.content_hash:
                return True
        else:
            return True
    return False


# ---------------------------------------------------------------------------
# Blocked history persistence
# ---------------------------------------------------------------------------

_BLOCKED_HISTORY_FILE = "skill_scanner_blocked.json"
_history_lock = threading.Lock()


def _get_blocked_history_path() -> Path:
    try:
        from ...constant import WORKING_DIR

        return WORKING_DIR / _BLOCKED_HISTORY_FILE
    except Exception:
        return Path.home() / ".copaw" / _BLOCKED_HISTORY_FILE


@dataclass
class BlockedSkillRecord:
    """A record of a scan alert (blocked or warned)."""

    skill_name: str
    blocked_at: str
    max_severity: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    content_hash: str = ""
    action: str = "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "blocked_at": self.blocked_at,
            "max_severity": self.max_severity,
            "findings": self.findings,
            "content_hash": self.content_hash,
            "action": self.action,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BlockedSkillRecord:
        return cls(
            skill_name=data.get("skill_name", ""),
            blocked_at=data.get("blocked_at", ""),
            max_severity=data.get("max_severity", ""),
            findings=data.get("findings", []),
            content_hash=data.get("content_hash", ""),
            action=data.get("action", "blocked"),
        )


def _finding_to_dict(f: Finding) -> dict[str, Any]:
    return {
        "severity": f.severity.value,
        "title": f.title,
        "description": f.description,
        "file_path": f.file_path,
        "line_number": f.line_number,
        "rule_id": f.rule_id,
    }


def _record_blocked_skill(
    result: ScanResult,
    skill_dir: Path,
    *,
    action: str = "blocked",
) -> None:
    """Append a scan alert to the history file."""
    record = BlockedSkillRecord(
        skill_name=result.skill_name,
        blocked_at=datetime.now(timezone.utc).isoformat(),
        max_severity=result.max_severity.value,
        findings=[_finding_to_dict(f) for f in result.findings],
        content_hash=compute_skill_content_hash(skill_dir),
        action=action,
    )
    path = _get_blocked_history_path()
    with _history_lock:
        try:
            existing: list[dict[str, Any]] = []
            if path.is_file():
                existing = json.loads(path.read_text(encoding="utf-8"))
            existing.append(record.to_dict())
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to record blocked skill: %s", exc)


def get_blocked_history() -> list[BlockedSkillRecord]:
    """Load all blocked skill records from disk."""
    path = _get_blocked_history_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [BlockedSkillRecord.from_dict(d) for d in data]
    except Exception as exc:
        logger.warning("Failed to load blocked history: %s", exc)
        return []


def clear_blocked_history() -> None:
    """Delete all blocked skill records."""
    path = _get_blocked_history_path()
    try:
        if path.is_file():
            path.unlink()
    except OSError as exc:
        logger.warning("Failed to clear blocked history: %s", exc)


def remove_blocked_entry(index: int) -> bool:
    """Remove a single blocked record by index. Returns True on success."""
    path = _get_blocked_history_path()
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if 0 <= index < len(data):
            data.pop(index)
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return True
        return False
    except Exception as exc:
        logger.warning("Failed to remove blocked entry: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Lazy singleton (thread-safe)
# ---------------------------------------------------------------------------

_scanner_instance: SkillScanner | None = None
_scanner_lock = threading.Lock()


def _get_scanner() -> SkillScanner:
    """Return a lazily-initialised :class:`SkillScanner` singleton."""
    global _scanner_instance
    if _scanner_instance is None:
        with _scanner_lock:
            if _scanner_instance is None:
                _scanner_instance = SkillScanner()
    return _scanner_instance


# ---------------------------------------------------------------------------
# Scan result cache (mtime-based)
# ---------------------------------------------------------------------------

_MAX_CACHE_ENTRIES = 64
_scan_cache: dict[str, tuple[float, ScanResult]] = {}
_cache_lock = threading.Lock()


def _get_dir_mtime(skill_dir: Path) -> float:
    """Return the latest mtime among the directory and its immediate files."""
    try:
        latest = skill_dir.stat().st_mtime
    except OSError:
        return 0.0
    try:
        for p in skill_dir.iterdir():
            if p.is_file() and not p.is_symlink():
                latest = max(latest, p.stat().st_mtime)
    except OSError:
        pass
    return latest


def _get_cached_result(
    skill_dir: Path,
) -> ScanResult | None:
    """Return a cached ScanResult if the directory hasn't changed."""
    key = str(skill_dir)
    with _cache_lock:
        entry = _scan_cache.get(key)
    if entry is None:
        return None
    cached_mtime, cached_result = entry
    current_mtime = _get_dir_mtime(skill_dir)
    if current_mtime == cached_mtime:
        logger.debug(
            "Returning cached scan result for '%s'",
            cached_result.skill_name,
        )
        return cached_result
    return None


def _store_cached_result(
    skill_dir: Path,
    result: ScanResult,
) -> None:
    """Store a scan result in the cache (LRU eviction)."""
    key = str(skill_dir)
    mtime = _get_dir_mtime(skill_dir)
    with _cache_lock:
        _scan_cache.pop(key, None)
        _scan_cache[key] = (mtime, result)
        while len(_scan_cache) > _MAX_CACHE_ENTRIES:
            oldest = next(iter(_scan_cache))
            del _scan_cache[oldest]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _format_finding_location(f: Finding) -> str:
    if f.line_number is not None:
        return f"({f.file_path}:{f.line_number})"
    return f"({f.file_path})"


class SkillScanError(Exception):
    """Raised when a skill fails a security scan and blocking is enabled."""

    def __init__(self, result: ScanResult) -> None:
        self.result = result
        findings_summary = "; ".join(
            f"[{f.severity.value}] {f.title} " f"{_format_finding_location(f)}"
            for f in result.findings[:5]
        )
        truncated = (
            f" (and {len(result.findings) - 5} more)"
            if len(result.findings) > 5
            else ""
        )
        super().__init__(
            f"Security scan of skill '{result.skill_name}' found "
            f"{len(result.findings)} issue(s) "
            f"(max severity: {result.max_severity.value}): "
            f"{findings_summary}{truncated}",
        )


def scan_skill_directory(
    skill_dir: str | Path,
    *,
    skill_name: str | None = None,
    block: bool | None = None,
    timeout: float | None = None,
) -> ScanResult | None:
    """Scan a skill directory and optionally block on unsafe results.

    Parameters
    ----------
    skill_dir:
        Path to the skill directory to scan.
    skill_name:
        Human-readable name (falls back to directory name).
    block:
        Whether to raise :class:`SkillScanError` when the scan finds
        CRITICAL/HIGH issues.  *None* means use the configured mode
        (``block`` mode → True, ``warn`` mode → False).
    timeout:
        Maximum seconds to wait for the scan to complete before
        giving up and returning ``None``.  *None* reads from config.

    Returns
    -------
    ScanResult or None
        ``None`` when scanning is disabled, whitelisted, or timed out.

    Raises
    ------
    SkillScanError
        When blocking is enabled and the skill is deemed unsafe.
    """
    cfg = _load_scanner_config()
    mode = _get_scan_mode(cfg)
    if mode == "off":
        return None

    resolved = Path(skill_dir).resolve()
    effective_name = skill_name or resolved.name

    if is_skill_whitelisted(effective_name, resolved, cfg=cfg):
        logger.debug(
            "Skill '%s' is whitelisted, skipping scan",
            effective_name,
        )
        return None

    effective_timeout = timeout if timeout is not None else _scan_timeout(cfg)

    cached = _get_cached_result(resolved)
    if cached is not None:
        result = cached
    else:
        scanner = _get_scanner()

        with futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                scanner.scan_skill,
                resolved,
                skill_name=skill_name,
            )
            try:
                result = future.result(timeout=effective_timeout)
            except futures.TimeoutError:
                logger.warning(
                    "Security scan of skill '%s' timed out after %.0fs",
                    effective_name,
                    effective_timeout,
                )
                future.cancel()
                return None

        _store_cached_result(resolved, result)

    if not result.is_safe:
        should_block = block if block is not None else (mode == "block")
        if should_block:
            _record_blocked_skill(result, resolved, action="blocked")
            raise SkillScanError(result)
        _record_blocked_skill(result, resolved, action="warned")
        logger.warning(
            "Skill '%s' has %d security finding(s) (max severity: %s) "
            "but blocking is disabled – proceeding anyway.",
            result.skill_name,
            len(result.findings),
            result.max_severity.value,
        )

    return result
