# -*- coding: utf-8 -*-
"""Setup and initialization utilities for agent configuration.

This module handles copying markdown configuration files to
the working directory.
"""
import logging
import shutil
from pathlib import Path

from ...constant import SUPPORTED_AGENT_LANGUAGES

logger = logging.getLogger(__name__)

_TEMPLATE_OVERRIDE_FILENAMES = {
    "AGENTS.md",
    "BOOTSTRAP.md",
    "PROFILE.md",
    "SOUL.md",
}


def normalize_agent_language(language: str) -> str:
    """Map *language* to a supported agent language"""
    if language in SUPPORTED_AGENT_LANGUAGES:
        return language
    return "en"


def copy_md_files(
    language: str,
    skip_existing: bool = False,
    workspace_dir: Path | None = None,
    exclude_filenames: set[str] | None = None,
) -> list[str]:
    """Copy md files from agents/md_files to working directory.

    Args:
        language: Language code (e.g. 'en', 'zh')
        skip_existing: If True, skip files that already exist in working dir.
        workspace_dir: Target workspace directory. If None, uses WORKING_DIR.
        exclude_filenames: File names to skip while copying.

    Returns:
        List of copied file names.
    """
    from ...constant import WORKING_DIR

    # Use provided workspace_dir or default to WORKING_DIR
    target_dir = workspace_dir if workspace_dir is not None else WORKING_DIR

    # Get md_files directory path with language subdirectory
    md_files_dir = Path(__file__).parent.parent / "md_files" / language

    if not md_files_dir.exists():
        logger.warning(
            "MD files directory not found: %s, falling back to 'en'",
            md_files_dir,
        )
        # Fallback to English if specified language not found
        md_files_dir = Path(__file__).parent.parent / "md_files" / "en"
        if not md_files_dir.exists():
            logger.error("Default 'en' md files not found either")
            return []

    # Ensure target directory exists
    target_dir.mkdir(parents=True, exist_ok=True)

    # Copy all .md files to target directory
    copied_files: list[str] = []
    for md_file in md_files_dir.glob("*.md"):
        if exclude_filenames and md_file.name in exclude_filenames:
            continue
        target_file = target_dir / md_file.name
        if skip_existing and target_file.exists():
            logger.debug("Skipped existing md file: %s", md_file.name)
            continue
        try:
            shutil.copy2(md_file, target_file)
            logger.debug("Copied md file: %s", md_file.name)
            copied_files.append(md_file.name)
        except Exception as e:
            logger.error(
                "Failed to copy md file '%s': %s",
                md_file.name,
                e,
            )

    if copied_files:
        logger.debug(
            "Copied %d md file(s) [%s] to %s",
            len(copied_files),
            language,
            target_dir,
        )

    return copied_files


def _resolve_md_lang_dir(agents_root: Path, language: str) -> Path:
    """Return ``md_files/<language>``, falling back to ``en`` if missing."""
    md_lang_dir = agents_root / "md_files" / language
    if not md_lang_dir.exists():
        logger.warning(
            "MD lang dir not found: %s, falling back to 'en'",
            md_lang_dir,
        )
        md_lang_dir = agents_root / "md_files" / "en"
    return md_lang_dir


def _template_fallback_language_order(language: str) -> list[str]:
    ordered: list[str] = []
    for lang_opt in (language, "en", "zh", "ru"):
        if lang_opt not in ordered:
            ordered.append(lang_opt)
    return ordered


def _copy_template_md_files(
    template_root: Path,
    fallback_langs: list[str],
    workspace_dir: Path,
    only_if_missing: bool,
) -> list[str]:
    candidate_names: list[str] = []
    seen_names: set[str] = set()

    for lang_opt in fallback_langs:
        lang_dir = template_root / lang_opt
        if not lang_dir.exists():
            continue
        for template_file in lang_dir.glob("*.md"):
            if template_file.name in seen_names:
                continue
            seen_names.add(template_file.name)
            candidate_names.append(template_file.name)

    copied: list[str] = []
    for filename in candidate_names:
        dst_p = workspace_dir / filename
        if only_if_missing and dst_p.exists():
            continue
        source_p = None
        for lang_opt in fallback_langs:
            cand = template_root / lang_opt / filename
            if cand.exists():
                source_p = cand
                break
        if source_p is None:
            logger.warning(
                "Workspace template missing for %s (langs tried: %s)",
                filename,
                fallback_langs,
            )
            continue
        try:
            shutil.copy2(source_p, dst_p)
            copied.append(filename)
        except OSError as e:
            logger.warning(
                "Failed to copy workspace template file %s: %s",
                filename,
                e,
            )
    return copied


def _remove_bootstrap_from_workspace(workspace_dir: Path) -> None:
    bootstrap = workspace_dir / "BOOTSTRAP.md"
    if not bootstrap.exists():
        return
    try:
        bootstrap.unlink()
        logger.info(
            "Removed BOOTSTRAP.md from builtin QA workspace %s",
            workspace_dir,
        )
    except OSError as e:
        logger.warning("Could not remove BOOTSTRAP.md: %s", e)


def copy_template_md_files(
    template_id: str,
    language: str,
    workspace_dir: Path | str,
    *,
    only_if_missing: bool = True,
) -> list[str]:
    """Copy template-specific markdown files into an agent workspace.

    Files are read from ``md_files/<template_id>/<language>/`` with fallback
    order ``language`` → ``en`` → ``zh`` → ``ru`` on a per-file basis.

    Args:
        template_id: Template directory name under ``agents/md_files``.
        language: Language code (en/zh/ru).
        workspace_dir: Agent workspace root.
        only_if_missing: If True, skip targets that already exist.

    Returns:
        List of copied or overwritten file names.
    """
    workspace_dir = Path(workspace_dir).expanduser()
    workspace_dir.mkdir(parents=True, exist_ok=True)

    agents_root = Path(__file__).resolve().parent.parent
    template_root = agents_root / "md_files" / template_id
    if not template_root.exists():
        logger.warning(
            "Workspace template directory not found: %s",
            template_root,
        )
        return []

    copied_files = _copy_template_md_files(
        template_root,
        _template_fallback_language_order(language),
        workspace_dir,
        only_if_missing,
    )
    _remove_bootstrap_from_workspace(workspace_dir)
    return copied_files


def copy_workspace_md_files(
    language: str,
    workspace_dir: Path | str,
    *,
    md_template_id: str | None = None,
    only_if_missing: bool = True,
) -> list[str]:
    """Copy common workspace md files plus optional template overrides."""
    workspace_dir = Path(workspace_dir).expanduser()

    initialized_markers = (
        workspace_dir / "AGENTS.md",
        workspace_dir / "PROFILE.md",
        workspace_dir / "MEMORY.md",
    )
    workspace_initialized = (
        (workspace_dir / ".bootstrap_completed").exists()
        or all(path.exists() for path in initialized_markers)
    )

    exclude_filenames = (
        set(_TEMPLATE_OVERRIDE_FILENAMES) if md_template_id else set()
    )
    if workspace_initialized:
        exclude_filenames.add("BOOTSTRAP.md")

    copied_files = copy_md_files(
        language,
        skip_existing=only_if_missing,
        workspace_dir=workspace_dir,
        exclude_filenames=exclude_filenames or None,
    )

    if not md_template_id:
        return copied_files

    copied_files.extend(
        copy_template_md_files(
            md_template_id,
            language,
            workspace_dir,
            only_if_missing=only_if_missing,
        ),
    )
    return copied_files


def copy_builtin_qa_md_files(
    language: str,
    workspace_dir: Path | str,
    *,
    only_if_missing: bool = True,
) -> list[str]:
    """Backward-compatible wrapper for builtin QA workspace templates."""
    return copy_workspace_md_files(
        language,
        workspace_dir,
        md_template_id="qa",
        only_if_missing=only_if_missing,
    )
