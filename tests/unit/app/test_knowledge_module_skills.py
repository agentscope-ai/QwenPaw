# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
from pathlib import Path


def test_sync_knowledge_module_skills_toggles_active_skill(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = importlib.import_module("copaw.knowledge.module_skills")
    skills_manager = importlib.import_module("copaw.agents.skills_manager")

    module_skills_dir = tmp_path / "module_skills"
    knowledge_skill_dir = module_skills_dir / "knowledge_search_assistant"
    knowledge_skill_dir.mkdir(parents=True)
    (knowledge_skill_dir / "SKILL.md").write_text(
        "---\nname: knowledge_search_assistant\ndescription: test\n---\n",
        encoding="utf-8",
    )

    active_skills_dir = tmp_path / "active_skills"
    monkeypatch.setattr(module, "KNOWLEDGE_MODULE_SKILLS_DIR", module_skills_dir)
    monkeypatch.setattr(skills_manager, "ACTIVE_SKILLS_DIR", active_skills_dir)

    module.sync_knowledge_module_skills(True)
    assert (active_skills_dir / "knowledge_search_assistant" / "SKILL.md").exists()

    module.sync_knowledge_module_skills(False)
    assert not (active_skills_dir / "knowledge_search_assistant").exists()