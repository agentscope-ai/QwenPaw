# -*- coding: utf-8 -*-
"""Skill security scanner orchestrator.

:class:`SkillScanner` discovers files in a skill directory, runs all
registered :class:`BaseAnalyzer` instances and collects their findings
into a single :class:`ScanResult`.

Usage::

    scanner = SkillScanner()              # default analyzers
    result = scanner.scan_skill("/path/to/skill")
    if not result.is_safe:
        ...

Custom analyzers can be registered at construction time or later via
:meth:`register_analyzer`.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from .analyzers import BaseAnalyzer
from .analyzers.consistency_analyzer import ConsistencyAnalyzer
from .analyzers.pattern_analyzer import PatternAnalyzer
from .analyzers.yara_analyzer import YaraAnalyzer
from .models import Finding, ScanResult, SkillFile
from .scan_policy import ScanPolicy

logger = logging.getLogger(__name__)

# Extensions we skip by default (binaries, images, etc.)
_SKIP_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".woff", ".woff2", ".eot", ".ttf", ".otf",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".o", ".a",
    ".pyc", ".pyo", ".class",
    ".db", ".sqlite", ".sqlite3",
    ".lock",
}

# Maximum number of files to scan per skill (safety valve).
_MAX_FILES = 500

# Maximum single file size to read (10 MB).
_MAX_FILE_SIZE = 10 * 1024 * 1024


class SkillScanner:
    """Orchestrates security scanning of an agent skill package.

    Parameters
    ----------
    analyzers:
        Explicit list of analyzers.  If *None* the default set
        (pattern + yara + consistency) is used.
    policy:
        Scan policy for org-specific rule scoping, severity overrides,
        and allowlists.  When *None*, the built-in default policy is used.
        Pass ``ScanPolicy.from_yaml("my_policy.yaml")`` to customise.
    skip_extensions:
        Extra file extensions to skip (merged with built-in set).
    max_files:
        Safety cap on the number of files to scan per skill.
    max_file_size:
        Maximum individual file size in bytes to load for scanning.
    """

    def __init__(
        self,
        analyzers: list[BaseAnalyzer] | None = None,
        *,
        policy: ScanPolicy | None = None,
        skip_extensions: set[str] | None = None,
        max_files: int = _MAX_FILES,
        max_file_size: int = _MAX_FILE_SIZE,
    ) -> None:
        self._policy = policy or ScanPolicy.default()

        if analyzers is not None:
            self._analyzers = list(analyzers)
        else:
            self._analyzers = self._default_analyzers(self._policy)

        self._skip_ext = _SKIP_EXTENSIONS | (skip_extensions or set())
        self._max_files = max_files
        self._max_file_size = max_file_size

    @property
    def policy(self) -> ScanPolicy:
        """The active scan policy."""
        return self._policy

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_analyzer(self, analyzer: BaseAnalyzer) -> None:
        """Add an analyzer at runtime (e.g. a future LLM analyzer)."""
        self._analyzers.append(analyzer)

    def scan_skill(
        self,
        skill_dir: str | Path,
        *,
        skill_name: str | None = None,
    ) -> ScanResult:
        """Scan a skill directory and return aggregated findings.

        Parameters
        ----------
        skill_dir:
            Root directory of the skill package.
        skill_name:
            Optional human-readable name (extracted from directory
            name when not provided).

        Returns
        -------
        ScanResult
            Result containing all findings and metadata.
        """
        t0 = time.monotonic()
        skill_path = Path(skill_dir).resolve()
        name = skill_name or skill_path.name

        if not skill_path.is_dir():
            logger.warning("Skill directory does not exist: %s", skill_path)
            return ScanResult(
                skill_name=name,
                skill_directory=str(skill_path),
                scan_duration_seconds=time.monotonic() - t0,
            )

        # 1. Discover files ------------------------------------------------
        files = self._discover_files(skill_path)
        logger.debug(
            "Discovered %d scannable files in %s",
            len(files),
            skill_path,
        )

        # 2. Run analyzers --------------------------------------------------
        all_findings: list[Finding] = []
        analyzers_used: list[str] = []
        analyzers_failed: list[dict[str, str]] = []

        for analyzer in self._analyzers:
            try:
                findings = analyzer.analyze(
                    skill_path,
                    files,
                    skill_name=name,
                )
                all_findings.extend(findings)
                analyzers_used.append(analyzer.get_name())
            except Exception as exc:
                logger.error(
                    "Analyzer '%s' failed: %s",
                    analyzer.get_name(),
                    exc,
                    exc_info=True,
                )
                analyzers_failed.append(
                    {"analyzer": analyzer.get_name(), "error": str(exc)}
                )

        # 3. De-duplicate by finding id ------------------------------------
        seen: set[str] = set()
        unique: list[Finding] = []
        for f in all_findings:
            if f.id not in seen:
                seen.add(f.id)
                unique.append(f)

        elapsed = time.monotonic() - t0
        result = ScanResult(
            skill_name=name,
            skill_directory=str(skill_path),
            findings=unique,
            scan_duration_seconds=round(elapsed, 4),
            analyzers_used=analyzers_used,
            analyzers_failed=analyzers_failed,
        )

        logger.info(
            "Scan of '%s' completed in %.2fs – %d finding(s), safe=%s",
            name,
            elapsed,
            len(unique),
            result.is_safe,
        )
        return result

    # ------------------------------------------------------------------
    # File discovery
    # ------------------------------------------------------------------

    def _discover_files(self, skill_dir: Path) -> list[SkillFile]:
        """Walk *skill_dir* and return scannable :class:`SkillFile` objects."""
        result: list[SkillFile] = []
        try:
            candidates = sorted(skill_dir.rglob("*"))
        except OSError as exc:
            logger.warning("Cannot walk %s: %s", skill_dir, exc)
            return result

        for p in candidates:
            # Skip symlinks to prevent path-traversal attacks where a
            # malicious skill symlinks to sensitive files outside the
            # skill directory (e.g. /etc/shadow).
            if p.is_symlink():
                logger.warning("Skipping symlink %s", p)
                continue
            if not p.is_file():
                continue
            # Even for non-symlink entries, resolve and verify the real
            # path stays within the skill directory boundary.
            try:
                real = p.resolve(strict=True)
            except OSError:
                continue
            if not str(real).startswith(str(skill_dir) + "/") and real != skill_dir:
                logger.warning(
                    "Skipping file outside skill directory: %s -> %s",
                    p, real,
                )
                continue
            if p.suffix.lower() in self._skip_ext:
                continue
            try:
                size = real.stat().st_size
            except OSError:
                continue
            if size > self._max_file_size:
                logger.debug("Skipping large file %s (%d bytes)", p, size)
                continue
            if len(result) >= self._max_files:
                logger.warning(
                    "Hit max file cap (%d) for %s",
                    self._max_files,
                    skill_dir,
                )
                break

            sf = SkillFile.from_path(p, skill_dir)
            result.append(sf)

        return result

    # ------------------------------------------------------------------
    # Default analyzer set
    # ------------------------------------------------------------------

    @staticmethod
    def _default_analyzers(policy: ScanPolicy | None = None) -> list[BaseAnalyzer]:
        """Instantiate the default set of analyzers, sharing the active policy."""
        analyzers: list[BaseAnalyzer] = []

        # YAML regex signatures.
        try:
            analyzers.append(PatternAnalyzer(policy=policy))
        except Exception as exc:
            logger.error("Failed to load PatternAnalyzer: %s", exc)

        # YARA rules.
        try:
            analyzers.append(YaraAnalyzer(policy=policy))
        except Exception as exc:
            logger.debug("YaraAnalyzer unavailable: %s", exc)

        # Consistency / behavioral patterns (file I/O, network, loops).
        try:
            analyzers.append(ConsistencyAnalyzer(policy=policy))
        except Exception as exc:
            logger.error("Failed to load ConsistencyAnalyzer: %s", exc)

        return analyzers
