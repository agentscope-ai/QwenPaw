# -*- coding: utf-8 -*-

from pathlib import Path

from ..agents.skills_manager import SkillService, sync_skill_dir_to_active


KNOWLEDGE_MODULE_SKILLS_DIR = Path(__file__).parent / "skills"
KNOWLEDGE_MODULE_SKILL_NAMES = ("knowledge_search_assistant",)


def sync_knowledge_module_skills(enabled: bool) -> None:
    """Keep knowledge module skills aligned with the runtime enabled state."""
    for skill_name in KNOWLEDGE_MODULE_SKILL_NAMES:
        if enabled:
            skill_dir = KNOWLEDGE_MODULE_SKILLS_DIR / skill_name
            if not sync_skill_dir_to_active(skill_dir, force=True):
                raise RuntimeError(
                    f"Failed to enable knowledge module skill: {skill_name}"
                )
            continue

        SkillService.disable_skill(skill_name)