# -*- coding: utf-8 -*-
"""Skills management: sync skills from code to working_dir."""

import filecmp
import logging
import shutil
from collections.abc import Iterable
from itertools import zip_longest
from pathlib import Path
from typing import Any
from pydantic import BaseModel
import frontmatter

from ..constant import ACTIVE_SKILLS_DIR, CUSTOMIZED_SKILLS_DIR

logger = logging.getLogger(__name__)


IGNORED_RUNTIME_ARTIFACT_NAMES = {
    "__pycache__",
    ".DS_Store",
    "Thumbs.db",
    ".pytest_cache",
}
IGNORED_RUNTIME_ARTIFACT_SUFFIXES = {
    ".pyc",
    ".pyo",
}


def _should_ignore_runtime_artifact(path: Path) -> bool:
    """Return True for generated runtime files that should not sync."""
    if path.name in IGNORED_RUNTIME_ARTIFACT_NAMES:
        return True
    if path.is_file() and path.suffix in IGNORED_RUNTIME_ARTIFACT_SUFFIXES:
        return True
    return False


def _iter_relevant_directory_entries(
    directory: Path,
) -> Iterable[tuple[Path, Path]]:
    """Yield relative paths for non-generated files and directories."""
    if not directory.exists():
        return

    yield from _iter_relevant_directory_entries_from(
        root_dir=directory,
        current_dir=directory,
    )


def _iter_relevant_directory_entries_from(
    root_dir: Path,
    current_dir: Path,
) -> Iterable[tuple[Path, Path]]:
    """Yield sorted non-generated directory entries without buffering."""
    for item in sorted(current_dir.iterdir(), key=lambda path: path.name):
        if _should_ignore_runtime_artifact(item):
            continue

        yield item.relative_to(root_dir), item

        if item.is_dir():
            yield from _iter_relevant_directory_entries_from(
                root_dir=root_dir,
                current_dir=item,
            )


def _directories_match_ignoring_runtime_artifacts(
    dir1: Path,
    dir2: Path,
) -> bool:
    """Compare two directories while ignoring generated runtime artifacts."""
    if not dir1.exists() or not dir2.exists():
        return False

    for entry1, entry2 in zip_longest(
        _iter_relevant_directory_entries(dir1),
        _iter_relevant_directory_entries(dir2),
    ):
        if entry1 is None or entry2 is None:
            return False

        relative_path1, left = entry1
        relative_path2, right = entry2
        if relative_path1 != relative_path2:
            return False
        if left.is_dir() != right.is_dir():
            return False
        if left.is_file() and not filecmp.cmp(left, right, shallow=False):
            return False

    return True


def _dedupe_skills_by_name(skills: list["SkillInfo"]) -> list["SkillInfo"]:
    """Return one skill per name, preferring customized over builtin."""
    merged: dict[str, SkillInfo] = {}
    for skill in skills:
        merged[skill.name] = skill
    return list(merged.values())


class SkillInfo(BaseModel):
    """Skill information structure.

    The references and scripts fields represent directory trees
    as nested dicts.

    When reading existing skills:
    - Files are represented as {filename: None}
    - Directories are represented as {dirname: {nested_structure}}

    When creating new skills via SkillService.create_skill:
    - Files are represented as {filename: "content"}
    - Directories are represented as {dirname: {nested_structure}}

    Example (reading):
        {
            "file.txt": None,
            "subdir": {
                "nested.py": None,
                "deeper": {
                    "file.sh": None
                }
            }
        }
    """

    name: str
    description: str = ""
    content: str
    source: str  # "builtin", "customized", or "active"
    path: str
    references: dict[str, Any] = {}
    scripts: dict[str, Any] = {}


def get_builtin_skills_dir() -> Path:
    """Get the path to built-in skills directory in the code."""
    return Path(__file__).parent / "skills"


def get_customized_skills_dir() -> Path:
    """Get the path to customized skills directory in working_dir."""
    return CUSTOMIZED_SKILLS_DIR


def get_active_skills_dir() -> Path:
    """Get the path to active skills directory in working_dir."""
    return ACTIVE_SKILLS_DIR


def get_working_skills_dir() -> Path:
    """
    Get the path to skills directory in working_dir.

    Deprecated: Use get_active_skills_dir() instead.
    """
    return get_active_skills_dir()


def _build_directory_tree(directory: Path) -> dict[str, Any]:
    """
    Recursively build a directory tree structure.

    Args:
        directory: Directory to scan.

    Returns:
        Dictionary representing the tree structure where:
        - Files are represented as {filename: None}
        - Directories are represented as {dirname: {nested_structure}}

    Example:
        {
            "file1.txt": None,
            "subdir": {
                "file2.py": None,
                "nested": {
                    "file3.sh": None
                }
            }
        }
    """
    tree: dict[str, Any] = {}

    if not directory.exists() or not directory.is_dir():
        return tree

    for item in sorted(directory.iterdir()):
        if item.is_file():
            tree[item.name] = None
        elif item.is_dir():
            tree[item.name] = _build_directory_tree(item)

    return tree


def _collect_skills_from_dir(directory: Path) -> dict[str, Path]:
    """
    Collect skills from a directory.

    Args:
        directory: Directory to scan for skills.

    Returns:
        Dictionary mapping skill names to their paths.
    """
    skills: dict[str, Path] = {}
    if directory.exists():
        for skill_dir in directory.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                skills[skill_dir.name] = skill_dir
    return skills


def sync_skills_to_working_dir(
    skill_names: list[str] | None = None,
    force: bool = False,
) -> tuple[int, int]:
    """
    Sync skills from builtin and customized to active_skills directory.

    Args:
        skill_names: List of skill names to sync. If None, sync all skills.
        force: If True, overwrite existing skills in active_skills.

    Returns:
        Tuple of (synced_count, skipped_count).
    """
    builtin_skills = get_builtin_skills_dir()
    customized_skills = get_customized_skills_dir()
    active_skills = get_active_skills_dir()

    # Ensure active skills directory exists
    active_skills.mkdir(parents=True, exist_ok=True)

    # Collect skills from both sources (customized overwrites builtin)
    skills_to_sync = _collect_skills_from_dir(builtin_skills)
    if not skills_to_sync and not builtin_skills.exists():
        logger.warning(
            "Built-in skills directory not found: %s",
            builtin_skills,
        )

    # Customized skills override builtin with same name
    skills_to_sync.update(_collect_skills_from_dir(customized_skills))

    # Filter by skill_names if specified
    if skill_names is not None:
        filtered_skills: dict[str, Path] = {}
        for name, path in skills_to_sync.items():
            if name in skill_names:
                filtered_skills[name] = path
        skills_to_sync = filtered_skills

    if not skills_to_sync:
        logger.debug("No skills to sync.")
        return 0, 0

    synced_count = 0
    skipped_count = 0

    # Sync each skill
    for skill_name, skill_dir in skills_to_sync.items():
        target_dir = active_skills / skill_name

        # Check if skill already exists
        if target_dir.exists() and not force:
            logger.debug(
                "Skill '%s' already exists in active_skills, skipping. "
                "Use force=True to overwrite.",
                skill_name,
            )
            skipped_count += 1
            continue

        # Copy skill directory
        try:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(skill_dir, target_dir)
            logger.debug("Synced skill '%s' to active_skills.", skill_name)
            synced_count += 1
        except Exception as e:
            logger.error(
                "Failed to sync skill '%s': %s",
                skill_name,
                e,
            )

    return synced_count, skipped_count


def sync_skills_from_active_to_customized(
    skill_names: list[str] | None = None,
) -> tuple[int, int]:
    """
    Sync skills from active_skills to customized_skills directory.

    Args:
        skill_names: List of skill names to sync. If None, sync all skills.

    Returns:
        Tuple of (synced_count, skipped_count).
    """
    active_skills = get_active_skills_dir()
    customized_skills = get_customized_skills_dir()
    builtin_skills = get_builtin_skills_dir()

    customized_skills.mkdir(parents=True, exist_ok=True)

    active_skills_dict = _collect_skills_from_dir(active_skills)
    if not active_skills_dict:
        logger.debug("No skills found in active_skills.")
        return 0, 0

    builtin_skills_dict = _collect_skills_from_dir(builtin_skills)

    synced_count = 0
    skipped_count = 0

    for skill_name, skill_dir in active_skills_dict.items():
        if skill_names is not None and skill_name not in skill_names:
            continue

        if skill_name in builtin_skills_dict:
            builtin_skill_dir = builtin_skills_dict[skill_name]
            if _directories_match_ignoring_runtime_artifacts(
                skill_dir,
                builtin_skill_dir,
            ):
                skipped_count += 1
                continue

        target_dir = customized_skills / skill_name

        try:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(skill_dir, target_dir)
            logger.debug(
                "Synced skill '%s' from active_skills to customized_skills.",
                skill_name,
            )
            synced_count += 1
        except Exception as e:
            logger.debug(
                "Failed to sync skill '%s' to customized_skills: %s",
                skill_name,
                e,
            )

    return synced_count, skipped_count


def list_available_skills() -> list[str]:
    """
    List all available skills in active_skills directory.

    Returns:
        List of skill names.
    """
    active_skills = get_active_skills_dir()

    if not active_skills.exists():
        return []

    return [
        d.name
        for d in active_skills.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    ]


def ensure_skills_initialized() -> None:
    """
    Check if skills are initialized in active_skills directory.

    Logs a warning if no skills are found, or info about loaded skills.
    Skills should be configured via `copaw init` or
    `copaw skills config`.
    """
    active_skills = get_active_skills_dir()
    available = list_available_skills()

    if not active_skills.exists() or not available:
        logger.warning(
            "No skills found in active_skills directory. "
            "Run 'copaw init' or 'copaw skills config' "
            "to configure skills.",
        )
    else:
        logger.debug(
            "Loaded %d skill(s) from active_skills: %s",
            len(available),
            ", ".join(available),
        )


def _read_skills_from_dir(
    directory: Path,
    source: str,
) -> list[SkillInfo]:
    """
    Read skills from a directory and return SkillInfo list.

    Args:
        directory: Directory to read skills from.
        source: Source label for the skills.

    Returns:
        List of SkillInfo objects.
    """
    skills: list[SkillInfo] = []

    if not directory.exists():
        return skills

    for skill_dir in directory.iterdir():
        if not skill_dir.is_dir():
            continue

        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue

        try:
            content = skill_md.read_text(encoding="utf-8")
            description = ""
            try:
                post = frontmatter.loads(content)
                description = str(post.get("description", "") or "")
            except Exception as e:
                logger.warning(
                    "Failed to parse SKILL.md frontmatter for skill '%s': %s",
                    skill_dir.name,
                    e,
                )
                logger.debug(
                    "Invalid SKILL.md frontmatter/content in '%s': %r",
                    skill_md,
                    e,
                )
                description = ""

            # Build references directory tree
            references = {}
            references_dir = skill_dir / "references"
            if references_dir.exists() and references_dir.is_dir():
                references = _build_directory_tree(references_dir)

            # Build scripts directory tree
            scripts = {}
            scripts_dir = skill_dir / "scripts"
            if scripts_dir.exists() and scripts_dir.is_dir():
                scripts = _build_directory_tree(scripts_dir)

            skills.append(
                SkillInfo(
                    name=skill_dir.name,
                    description=description,
                    content=content,
                    source=source,
                    path=str(skill_dir),
                    references=references,
                    scripts=scripts,
                ),
            )
        except Exception as e:
            logger.error(
                "Failed to read skill '%s': %s",
                skill_dir.name,
                e,
            )

    return skills


def _create_files_from_tree(
    base_dir: Path,
    tree: dict[str, Any],
) -> None:
    """
    Create files and directories from a tree structure.

    Args:
        base_dir: Base directory to create files in.
        tree: Tree structure where:
            - {filename: str_content} creates a file with content
            - {dirname: {nested_tree}} creates a directory recursively

    Raises:
        ValueError: If tree contains invalid value types.

    Example:
        tree = {
            "file.txt": "content",
            "subdir": {
                "nested.py": "print('hello')",
                "deeper": {
                    "file.sh": "#!/bin/bash"
                }
            }
        }
    """
    if not tree:
        return

    for name, value in tree.items():
        item_path = base_dir / name

        if value is None or isinstance(value, str):
            # It's a file
            content = value if isinstance(value, str) else ""
            item_path.write_text(content, encoding="utf-8")
        elif isinstance(value, dict):
            # It's a directory
            item_path.mkdir(parents=True, exist_ok=True)
            _create_files_from_tree(item_path, value)
        else:
            raise ValueError(
                f"Invalid tree value for '{name}': {type(value)}. "
                "Expected None, str, or dict.",
            )


class SkillService:
    """
    Service for managing skills.

    Manages skills across builtin, customized, and active directories.
    """

    @staticmethod
    def _get_customized_skill_dir(name: str) -> Path | None:
        """Return the Path to a skill inside customized_skills, or None."""
        skill_dir = get_customized_skills_dir() / name
        return skill_dir if skill_dir.exists() else None

    @staticmethod
    def get_customized_skill_dir(name: str) -> Path | None:
        """Public wrapper for accessing a customized skill directory."""
        return SkillService._get_customized_skill_dir(name)

    @staticmethod
    def list_all_skills() -> list[SkillInfo]:
        """
        List all skills from builtin and customized directories.

        Returns:
            List of SkillInfo with name, content, source, and path.
        """
        try:
            synced, _ = sync_skills_from_active_to_customized()
            if synced > 0:
                logger.debug(
                    "Synced %d skill(s) from active_skills",
                    synced,
                )
        except Exception as e:
            logger.debug(
                "Failed to sync skills from active_skills: %s",
                e,
            )

        skills: list[SkillInfo] = []

        # Collect from builtin and customized skills. Customized skills
        # override built-in skills with the same name in the UI/API listing.
        skills.extend(
            _read_skills_from_dir(get_builtin_skills_dir(), "builtin"),
        )
        skills.extend(
            _read_skills_from_dir(get_customized_skills_dir(), "customized"),
        )

        return _dedupe_skills_by_name(skills)

    @staticmethod
    def list_available_skills() -> list[SkillInfo]:
        """
        List all available (active) skills in active_skills directory.

        Returns:
            List of SkillInfo with name, content, source, and path.
        """
        return _read_skills_from_dir(get_active_skills_dir(), "active")

    @staticmethod
    def create_skill(
        name: str,
        content: str,
        overwrite: bool = False,
        references: dict[str, Any] | None = None,
        scripts: dict[str, Any] | None = None,
        extra_files: dict[str, Any] | None = None,
    ) -> bool:
        """
        Create a new skill in customized_skills directory.

        Args:
            name: Skill name (will be the directory name).
            content: Content of SKILL.md file.
            overwrite: If True, overwrite existing skill.
            references: Optional tree structure for references/ subdirectory.
                Can be flat {filename: content} or nested
                {dirname: {filename: content}}.
            scripts: Optional tree structure for scripts/ subdirectory.
                Can be flat {filename: content} or nested
                {dirname: {filename: content}}.
            extra_files: Optional tree structure for additional files
                written to skill root (excluding SKILL.md), usually used
                by imported hub skills that contain runtime assets.

        Returns:
            True if skill was created successfully, False otherwise.

        Examples:
            # Simple flat structure
            create_skill(
                name="my_skill",
                content="# My Skill\\n...",
                references={"doc1.md": "content1"},
                scripts={"script1.py": "print('hello')"}
            )

            # Nested structure
            create_skill(
                name="my_skill",
                content="# My Skill\\n...",
                references={
                    "readme.md": "# Documentation",
                    "examples": {
                        "example1.py": "print('example')",
                        "data": {
                            "sample.json": '{"key": "value"}'
                        }
                    }
                }
            )
        """
        # Validate SKILL.md content has required YAML Front Matter
        try:
            post = frontmatter.loads(content)
            skill_name = post.get("name", None)
            skill_description = post.get("description", None)

            if not skill_name or not skill_description:
                logger.error(
                    "SKILL.md content must have YAML Front Matter "
                    "with 'name' and 'description' fields.",
                )
                return False

            logger.debug(
                "Validated SKILL.md: name='%s', description='%s'",
                skill_name,
                skill_description,
            )
        except Exception as e:
            logger.error(
                "Failed to parse SKILL.md YAML Front Matter: %s",
                e,
            )
            return False

        customized_dir = get_customized_skills_dir()
        customized_dir.mkdir(parents=True, exist_ok=True)

        skill_dir = customized_dir / name
        skill_md = skill_dir / "SKILL.md"

        # Check if skill already exists
        if skill_dir.exists() and not overwrite:
            logger.debug(
                "Skill '%s' already exists in customized_skills. "
                "Use overwrite=True to replace.",
                name,
            )
            return False

        # Create skill directory and SKILL.md
        try:
            # Clean up existing directory if overwriting
            if skill_dir.exists() and overwrite:
                shutil.rmtree(skill_dir)

            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_md.write_text(content, encoding="utf-8")

            # Create extra files in skill root
            if extra_files:
                _create_files_from_tree(skill_dir, extra_files)
                logger.debug(
                    "Created extra root files for skill '%s'.",
                    name,
                )

            # Create references subdirectory and files from tree
            if references:
                references_dir = skill_dir / "references"
                references_dir.mkdir(parents=True, exist_ok=True)
                _create_files_from_tree(references_dir, references)
                logger.debug(
                    "Created references structure for skill '%s'.",
                    name,
                )

            # Create scripts subdirectory and files from tree
            if scripts:
                scripts_dir = skill_dir / "scripts"
                scripts_dir.mkdir(parents=True, exist_ok=True)
                _create_files_from_tree(scripts_dir, scripts)
                logger.debug(
                    "Created scripts structure for skill '%s'.",
                    name,
                )

            # --- Security scan (post-write, warning only) -------------------
            try:
                from ..security.skill_scanner import scan_skill_directory

                scan_skill_directory(skill_dir, skill_name=name, block=False)
            except Exception as scan_exc:
                logger.debug(
                    "Security scan error for skill '%s' (non-fatal): %s",
                    name,
                    scan_exc,
                )
            # ---------------------------------------------------------------

            logger.debug("Created skill '%s' in customized_skills.", name)
            return True
        except Exception as e:
            logger.error(
                "Failed to create skill '%s': %s",
                name,
                e,
            )
            return False

    @staticmethod
    def disable_skill(name: str) -> bool:
        """
        Disable a skill by removing it from active_skills directory.

        Args:
            name: Skill name to disable.

        Returns:
            True if skill was disabled successfully, False otherwise.
        """
        active_dir = get_active_skills_dir()
        skill_dir = active_dir / name

        if not skill_dir.exists():
            logger.debug(
                "Skill '%s' not found in active_skills.",
                name,
            )
            return False

        try:
            shutil.rmtree(skill_dir)
            logger.debug("Disabled skill '%s' from active_skills.", name)
            return True
        except Exception as e:
            logger.error(
                "Failed to disable skill '%s': %s",
                name,
                e,
            )
            return False

    @staticmethod
    def enable_skill(name: str, force: bool = False) -> bool:
        """
        Enable a skill by syncing it to active_skills directory.

        Before syncing the skill runs through a security scan.
        If issues are detected a warning is logged; the skill is
        still activated (blocking will be enforced via the frontend
        in a future update).

        Args:
            name: Skill name to enable.
            force: If True, overwrite existing skill in active_skills.

        Returns:
            True if skill was enabled successfully, False otherwise.
        """
        # --- Security scan (pre-activation, warning only) ------------------
        try:
            from ..security.skill_scanner import scan_skill_directory

            # Determine the source directory that will be synced.
            source_dir = None
            customized = get_customized_skills_dir() / name
            builtin = get_builtin_skills_dir() / name
            if customized.is_dir():
                source_dir = customized
            elif builtin.is_dir():
                source_dir = builtin

            if source_dir is not None:
                scan_skill_directory(source_dir, skill_name=name, block=False)
        except Exception as scan_exc:
            logger.debug(
                "Security scan error for skill '%s' (non-fatal): %s",
                name,
                scan_exc,
            )
        # -------------------------------------------------------------------

        sync_skills_to_working_dir(skill_names=[name], force=force)
        # Check if skill was actually synced
        active_dir = get_active_skills_dir()
        return (active_dir / name).exists()

    @staticmethod
    def delete_skill(name: str) -> bool:
        """
        Delete a skill from customized_skills directory permanently.

        This only deletes skills from customized_skills directory.
        Built-in skills cannot be deleted.
        If the skill is currently active, it will remain in active_skills
        until manually disabled.

        Args:
            name: Skill name to delete.

        Returns:
            True if skill was deleted successfully, False otherwise.
        """
        customized_dir = get_customized_skills_dir()
        skill_dir = customized_dir / name

        if not skill_dir.exists():
            logger.debug(
                "Skill '%s' not found in customized_skills.",
                name,
            )
            return False

        try:
            shutil.rmtree(skill_dir)
            logger.debug(
                "Deleted skill '%s' from customized_skills.",
                name,
            )
            return True
        except Exception as e:
            logger.error(
                "Failed to delete skill '%s': %s",
                name,
                e,
            )
            return False

    @staticmethod
    def sync_from_active_to_customized(
        skill_names: list[str] | None = None,
    ) -> tuple[int, int]:
        """
        Sync skills from active_skills to customized_skills directory.

        Args:
            skill_names: List of skill names to sync. If None, sync all skills.

        Returns:
            Tuple of (synced_count, skipped_count).
        """
        return sync_skills_from_active_to_customized(
            skill_names=skill_names,
        )

    @staticmethod
    def load_skill_file(  # pylint: disable=too-many-return-statements
        skill_name: str,
        file_path: str,
        source: str,
    ) -> str | None:
        """
        Load a specific file from a skill's references or scripts directory.

        Args:
            skill_name: Name of the skill.
            file_path: Relative path to the file within the skill directory.
                Must start with "references/" or "scripts/".
                Example: "references/doc.md" or "scripts/utils/helper.py"
            source: Source directory, must be "builtin" or "customized".

        Returns:
            File content as string, or None if failed.

        Examples:
            # Load from customized skills
            content = load_skill_file(
                "my_skill",
                "references/doc.md",
                "customized"
            )

            # Load nested file from builtin
            content = load_skill_file(
                "builtin_skill",
                "scripts/utils/helper.py",
                "builtin"
            )
        """
        # Validate source
        if source not in {"builtin", "customized"}:
            logger.error(
                "Invalid source '%s'. Must be 'builtin' or 'customized'.",
                source,
            )
            return None

        # Normalize separators to forward slash for consistent checking
        normalized = file_path.replace("\\", "/")

        # Validate file_path starts with references/ or scripts/
        is_references = normalized.startswith("references/")
        is_scripts = normalized.startswith("scripts/")
        if not (is_references or is_scripts):
            logger.error(
                "Invalid file_path '%s'. Must start with refs or scripts.",
                file_path,
            )
            return None

        # Prevent path traversal attacks
        if ".." in normalized or normalized.startswith("/"):
            logger.error(
                "Invalid file_path '%s': path traversal not allowed",
                file_path,
            )
            return None

        # Get source directory
        if source == "customized":
            base_dir = get_customized_skills_dir()
        else:  # builtin
            base_dir = get_builtin_skills_dir()

        skill_dir = base_dir / skill_name
        full_path = skill_dir / normalized

        # Check if skill exists
        if not skill_dir.exists():
            logger.debug(
                "Skill '%s' not found in %s",
                skill_name,
                source,
            )
            return None

        # Check if file exists
        if not full_path.exists():
            logger.debug(
                "File '%s' not found in skill '%s' (%s)",
                file_path,
                skill_name,
                source,
            )
            return None

        # Check if it's actually a file (not a directory)
        if not full_path.is_file():
            logger.debug(
                "Path '%s' is not a file in skill '%s' (%s)",
                file_path,
                skill_name,
                source,
            )
            return None

        # Read file content
        try:
            content = full_path.read_text(encoding="utf-8")
            logger.debug(
                "Loaded file '%s' from skill '%s' (%s)",
                file_path,
                skill_name,
                source,
            )
            return content
        except Exception as e:
            logger.error(
                "Failed to read file '%s' from skill '%s': %s",
                file_path,
                skill_name,
                e,
            )
            return None
