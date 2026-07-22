# -*- coding: utf-8 -*-
"""Tests for memory guidance prompts."""

import pytest

from qwenpaw.agents.memory.prompts import build_memory_guidance_prompt


@pytest.mark.parametrize(
    ("language", "expected_instructions"),
    [
        (
            "zh",
            (
                "`edit_file` 只在已知精确原文时使用",
                "不要对同一个 replacement 重试",
                "重新 `read_file`，再用合并后的完整内容调用 `write_file`",
            ),
        ),
        (
            "en",
            (
                "Use `edit_file` only when you know the exact existing text.",
                "do not retry the same replacement.",
                (
                    "read the file again and use `write_file` with the "
                    "merged full content."
                ),
            ),
        ),
    ],
)
def test_memory_guidance_recovers_from_failed_edit(
    language,
    expected_instructions,
):
    """A failed replacement must direct the agent to a safe fallback."""
    prompt = build_memory_guidance_prompt(
        language,
        daily_dir="memory/daily",
    )

    for instruction in expected_instructions:
        assert instruction in prompt
