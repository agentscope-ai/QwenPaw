# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""System prompt building utilities.

This module provides utilities for building system prompts from
markdown configuration files in the working directory.
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Default fallback prompt
DEFAULT_SYS_PROMPT = """
You are a helpful assistant.
"""

# Backward compatibility alias
SYS_PROMPT = DEFAULT_SYS_PROMPT


class PromptConfig:
    """Configuration for system prompt building."""

    # Default files to load when no config is provided
    # All files are optional - if they don't exist, they'll be skipped
    DEFAULT_FILES = [
        "AGENTS.md",
        "SOUL.md",
        "PROFILE.md",
    ]


class PromptBuilder:
    """Builder for constructing system prompts from markdown files."""

    def __init__(
        self,
        working_dir: Path,
        enabled_files: list[str] | None = None,
    ):
        """Initialize prompt builder.

        Args:
            working_dir: Directory containing markdown configuration files
            enabled_files: List of filenames to load (if None, uses default order)
        """
        self.working_dir = working_dir
        self.enabled_files = enabled_files
        self.prompt_parts = []
        self.loaded_count = 0

    def _load_file(self, filename: str) -> None:
        """Load a single markdown file.

        All files are optional - if they don't exist or can't be read,
        they will be silently skipped.

        Args:
            filename: Name of the file to load
        """
        file_path = self.working_dir / filename

        if not file_path.exists():
            logger.debug("File %s not found, skipping", filename)
            return

        try:
            content = file_path.read_text(encoding="utf-8").strip()

            # Remove YAML frontmatter if present
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    content = parts[2].strip()

            if content:
                if self.prompt_parts:  # Add separator if not first section
                    self.prompt_parts.append("")
                # Add section header with filename
                self.prompt_parts.append(f"# {filename}")
                self.prompt_parts.append("")
                self.prompt_parts.append(content)
                self.loaded_count += 1
                logger.debug("Loaded %s", filename)
            else:
                logger.debug("Skipped empty file: %s", filename)

        except Exception as e:
            logger.warning(
                "Failed to read file %s: %s, skipping",
                filename,
                e,
            )

    def build(self) -> str:
        """Build the system prompt from markdown files.

        All files are optional. If no files can be loaded, returns the default prompt.

        Returns:
            Constructed system prompt string
        """
        # Determine which files to load
        files_to_load = (
            PromptConfig.DEFAULT_FILES
            if self.enabled_files is None
            else self.enabled_files
        )

        # Load all files (all are optional)
        for filename in files_to_load:
            self._load_file(filename)

        if not self.prompt_parts:
            logger.warning("No content loaded from working directory")
            return DEFAULT_SYS_PROMPT

        # Join all parts with double newlines
        final_prompt = "\n\n".join(self.prompt_parts)

        logger.debug(
            "System prompt built from %d file(s), total length: %d chars",
            self.loaded_count,
            len(final_prompt),
        )

        return final_prompt


def build_system_prompt_from_working_dir() -> str:
    """
    Build system prompt by reading markdown files from working directory.

    This function constructs the system prompt by loading markdown files from
    WORKING_DIR (~/.copaw by default). These files define the agent's behavior,
    personality, and operational guidelines.

    The files to load are determined by the agents.system_prompt_files configuration.
    If not configured, falls back to default files:
    - AGENTS.md - Detailed workflows, rules, and guidelines
    - SOUL.md - Core identity and behavioral principles
    - PROFILE.md - Agent identity and user profile

    All files are optional. If a file doesn't exist or can't be read, it will be
    skipped. If no files can be loaded, returns the default prompt.

    Returns:
        str: Constructed system prompt from markdown files.
             If no files exist, returns the default prompt.

    Example:
        If working_dir contains AGENTS.md, SOUL.md and PROFILE.md, they will be combined:
        "# AGENTS.md\\n\\n...\\n\\n# SOUL.md\\n\\n...\\n\\n# PROFILE.md\\n\\n..."
    """
    from ..constant import WORKING_DIR
    from ..config import load_config

    # Load enabled files from config
    config = load_config()
    enabled_files = (
        config.agents.system_prompt_files
        if config.agents.system_prompt_files is not None
        else None
    )

    builder = PromptBuilder(
        working_dir=Path(WORKING_DIR),
        enabled_files=enabled_files,
    )
    return builder.build()


def build_bootstrap_guidance(
    language: str = "zh",
) -> str:
    """Build bootstrap guidance message for first-time setup.

    Args:
        language: Language code (en/zh)

    Returns:
        Formatted bootstrap guidance message
    """
    if language == "en":
        return """# 🌟 BOOTSTRAP MODE ACTIVATED

**IMPORTANT: You are in first-time setup mode.**

A `BOOTSTRAP.md` file exists in your working directory. This means you should guide the user through the bootstrap process to establish your identity and preferences.

**Your task:**
1. Read the BOOTSTRAP.md file, greet the user warmly as a first meeting, and guide them through the bootstrap process.
2. Follow the instructions in BOOTSTRAP.md. For example, help the user define your identity, their preferences, and establish the working relationship.
3. Create and update the necessary files (PROFILE.md, MEMORY.md, etc.) as described in the guide.
4. After completing the bootstrap process, delete BOOTSTRAP.md as instructed.

**If the user wants to skip:**
If the user explicitly says they want to skip the bootstrap or just want their question answered directly, then proceed to answer their original question below. You can always help them bootstrap later.

**Original user message:**
"""
    else:  # zh
        return """# 🌟 引导模式已激活

**重要：你正处于首次设置模式。**

你的工作目录中存在 `BOOTSTRAP.md` 文件。这意味着你应该引导用户完成引导流程，以建立你的身份和偏好。

**你的任务：**
1. 阅读 BOOTSTRAP.md 文件，友好地表示初次见面，引导用户完成引导流程。
2. 按照BOOTSTRAP.md 里面的指示执行。例如，帮助用户定义你的身份、他们的偏好，并建立工作关系
3. 按照指南中的描述创建和更新必要的文件（PROFILE.md、MEMORY.md 等）
4. 完成引导流程后，按照指示删除 BOOTSTRAP.md

**如果用户希望跳过：**
如果用户明确表示想跳过引导，那就继续回答下面的原始问题。你随时可以帮助他们完成引导。

**用户的原始消息：**
"""


__all__ = [
    "build_system_prompt_from_working_dir",
    "build_bootstrap_guidance",
    "PromptBuilder",
    "PromptConfig",
    "DEFAULT_SYS_PROMPT",
    "SYS_PROMPT",  # Backward compatibility
]
