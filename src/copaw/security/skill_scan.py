# -*- coding: utf-8 -*-
"""
Security scanning integration for CoPaw skill lifecycle.

Provides a thin API that the skill management layer (``skills_hub``,
``skills_manager``) calls at key lifecycle points:

* **on_skill_install** – after downloading / creating a skill, after
  it has been written to ``customized_skills/``.
* **on_skill_enable** – before a skill is copied to ``active_skills/``.

The scanner itself is lazily instantiated so that import-time is
near-zero.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .skill_scanner import ScanResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment-variable knobs
# ---------------------------------------------------------------------------
#  COPAW_SKILL_SCAN_ENABLED  – "true" (default) / "false"
#  COPAW_SKILL_SCAN_BLOCK    – "true" (default) / "false"
#                               When True, unsafe skills are blocked from
#                               being enabled/installed. When False, only a
#                               warning is logged.

_TRUE_STRINGS = {"true", "1", "yes"}


def _scan_enabled() -> bool:
    return os.environ.get("COPAW_SKILL_SCAN_ENABLED", "true").lower() in _TRUE_STRINGS


def _scan_blocks() -> bool:
    return os.environ.get("COPAW_SKILL_SCAN_BLOCK", "true").lower() in _TRUE_STRINGS


# ---------------------------------------------------------------------------
# Lazy singleton
# ---------------------------------------------------------------------------

_scanner_instance = None


def _get_scanner():
    """Return a lazily-initialised :class:`SkillScanner` singleton."""
    global _scanner_instance
    if _scanner_instance is None:
        from .skill_scanner import SkillScanner

        _scanner_instance = SkillScanner()
    return _scanner_instance


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class SkillScanError(Exception):
    """Raised when a skill fails a security scan and blocking is enabled."""

    def __init__(self, result: "ScanResult") -> None:
        self.result = result
        findings_summary = "; ".join(
            f"[{f.severity.value}] {f.title} ({f.file_path}:{f.line_number})"
            for f in result.findings[:5]
        )
        truncated = f" (and {len(result.findings) - 5} more)" if len(result.findings) > 5 else ""
        super().__init__(
            f"Security scan of skill '{result.skill_name}' found "
            f"{len(result.findings)} issue(s) "
            f"(max severity: {result.max_severity.value}): "
            f"{findings_summary}{truncated}"
        )


def scan_skill_directory(
    skill_dir: str | Path,
    *,
    skill_name: str | None = None,
    block: bool | None = None,
) -> "ScanResult | None":
    """Scan a skill directory and optionally block on unsafe results.

    Parameters
    ----------
    skill_dir:
        Path to the skill directory to scan.
    skill_name:
        Human-readable name (falls back to directory name).
    block:
        Whether to raise :class:`SkillScanError` when the scan finds
        CRITICAL/HIGH issues.  *None* means use the
        ``COPAW_SKILL_SCAN_BLOCK`` env var.

    Returns
    -------
    ScanResult or None
        ``None`` when scanning is disabled.

    Raises
    ------
    SkillScanError
        When blocking is enabled and the skill is deemed unsafe.
    """
    if not _scan_enabled():
        return None

    scanner = _get_scanner()
    result = scanner.scan_skill(skill_dir, skill_name=skill_name)

    if not result.is_safe:
        should_block = block if block is not None else _scan_blocks()
        if should_block:
            raise SkillScanError(result)
        else:
            logger.warning(
                "Skill '%s' has %d security finding(s) (max severity: %s) "
                "but blocking is disabled – proceeding anyway.",
                result.skill_name,
                len(result.findings),
                result.max_severity.value,
            )

    return result
