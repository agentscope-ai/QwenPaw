# -*- coding: utf-8 -*-

import shutil
from pathlib import Path

from ..agents import skills_manager


KNOWLEDGE_MODULE_SKILLS_DIR = Path(__file__).parent / "skills"
KNOWLEDGE_MODULE_SKILL_NAMES = ("knowledge_search_assistant",)


def sync_knowledge_module_skills(enabled: bool) -> None:
    """Keep knowledge module skills aligned with the runtime enabled state."""
    for skill_name in KNOWLEDGE_MODULE_SKILL_NAMES:
        if enabled:
            skill_dir = KNOWLEDGE_MODULE_SKILLS_DIR / skill_name
            if not skills_manager.sync_skill_dir_to_active(skill_dir, force=True):
                raise RuntimeError(
                    f"Failed to enable knowledge module skill: {skill_name}"
                )
            continue

        target_dir = skills_manager.ACTIVE_SKILLS_DIR / skill_name
        if target_dir.exists():
            shutil.rmtree(target_dir)