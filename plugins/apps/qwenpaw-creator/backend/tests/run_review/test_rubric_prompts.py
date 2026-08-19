# -*- coding: utf-8 -*-
"""Rubric prompt generation and taste-principle derivation regression."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.run_review.rubric_prompts import (
    build_appeal_system_prompt,
    build_image_check_system_prompt,
    build_scene_check_system_prompt,
    render_taste_principles,
)
from vendor.media_toolkit.review_rubrics import (
    APPEAL_RUBRIC_ROWS,
    SCENE_REVIEW_CHECKS,
)

pytestmark = pytest.mark.unit

_PROMPTS_DIR = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "file_agent_runtime"
    / "prompts"
)
_TASTE_ROLES = {
    "creator_agent": "creator_agent.system.txt",
    "ai_editing_director": "ai_editing_director.system.txt",
    "r2v_generation_director": "r2v_generation_director.system.txt",
    "visual_development_agent": "visual_development_agent.system.txt",
}


def test_appeal_prompt_embeds_verbatim_rows_without_veto() -> None:
    text_prompt = build_appeal_system_prompt("text")
    for row in APPEAL_RUBRIC_ROWS[:3]:
        assert row.key in text_prompt
        assert row.anchor_questions in text_prompt
    motion_prompt = build_appeal_system_prompt("motion")
    assert APPEAL_RUBRIC_ROWS[3].anchor_questions in motion_prompt
    assert APPEAL_RUBRIC_ROWS[6].anchor_questions in motion_prompt
    # The upstream veto semantics must never reach a prompt: advisory only.
    for prompt in (text_prompt, motion_prompt):
        assert "一票否决" not in prompt
        assert "caps the total verdict" not in prompt
        assert "建议不是门禁" in prompt


def test_scene_prompt_embeds_all_six_checks() -> None:
    prompt = build_scene_check_system_prompt()
    for check in SCENE_REVIEW_CHECKS:
        assert check.key in prompt
        assert check.description in prompt


def test_image_prompt_embeds_relevant_checks() -> None:
    prompt = build_image_check_system_prompt()
    for key in ("devices", "type_fonts", "composition_safety", "craft"):
        assert key in prompt


def test_prompt_files_carry_derived_taste_principles() -> None:
    for role, filename in _TASTE_ROLES.items():
        content = (_PROMPTS_DIR / filename).read_text(encoding="utf-8")
        assert "# 创作品味准则" in content, filename
        rendered = render_taste_principles(role)
        assert (
            rendered in content
        ), f"{filename} taste section drifted from render_taste_principles"
