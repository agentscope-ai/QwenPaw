# -*- coding: utf-8 -*-
"""Setup and initialization utilities for agent configuration.

This module handles copying markdown configuration files to
the working directory.
"""
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def copy_md_files(
    language: str,
    skip_existing: bool = False,
    workspace_dir: Path | None = None,
) -> list[str]:
    """Copy md files from agents/md_files to working directory.

    Args:
        language: Language code (e.g. 'en', 'zh')
        skip_existing: If True, skip files that already exist in working dir.
        workspace_dir: Target workspace directory. If None, uses WORKING_DIR.

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
