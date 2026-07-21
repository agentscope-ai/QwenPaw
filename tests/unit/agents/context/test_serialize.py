# -*- coding: utf-8 -*-
"""Headline extraction and display-cleanup regressions."""

import pytest

from qwenpaw.agents.context.scroll.prompt import build_scroll_system_prompt
from qwenpaw.agents.context.scroll.serialize import (
    extract_headline,
    strip_headline,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("done\n⟦ shipped the fix ⟧", "shipped the fix"),
        (
            "done\n<!-- ⟦ legacy headline ⟧ -->",
            "legacy headline",
        ),
        ("done\n〚 lookalike brackets 〛", "lookalike brackets"),
    ],
)
def test_extract_headline_accepts_plain_and_legacy_fences(
    text: str,
    expected: str,
) -> None:
    assert extract_headline(text) == expected


def test_strip_headline_removes_plain_fence() -> None:
    assert strip_headline("done\n⟦ shipped the fix ⟧") == "done"


def test_structured_task_state_headline_is_extracted_and_hidden() -> None:
    headline = "模型发现修复｜进行中：OpenAI 已完成；" + ("下一步：重写 DashScope normalization")
    text = f"done\n⟦ {headline} ⟧"
    assert extract_headline(text) == headline
    assert strip_headline(text) == "done"


@pytest.mark.parametrize("language", ["en", "zh"])
def test_prompt_uses_only_optional_structured_headline(language: str) -> None:
    prompt = build_scroll_system_prompt(language)
    assert "⟦" in prompt and "⟧" in prompt
    assert "next" in prompt.casefold() or "下一步" in prompt
    assert "optional" in prompt.casefold() or "可选" in prompt
    assert "<context-event>" not in prompt
    assert "<task-state>" not in prompt


@pytest.mark.parametrize(
    ("language", "required_phrases"),
    [
        (
            "en",
            (
                "continuation summary",
                "VERIFIED state",
                "success criterion",
                "failed attempt",
                "2000-character limit",
            ),
        ),
        (
            "zh",
            (
                "continuation summary",
                "成功标准",
                "已经验证",
                "失败尝试",
                "2000 字符",
            ),
        ),
    ],
)
def test_prompt_contains_headline_quality_gate(
    language: str,
    required_phrases: tuple[str, ...],
) -> None:
    prompt = build_scroll_system_prompt(language)
    for phrase in required_phrases:
        assert phrase in prompt


def test_headline_limit_preserves_long_context_up_to_2000_chars() -> None:
    headline = "任务｜进行中：" + "细节" * 700
    assert len(headline) < 2000
    assert extract_headline(f"⟦ {headline} ⟧") == headline


def test_headline_over_2000_chars_is_compatibly_truncated() -> None:
    headline = "x" * 2100
    assert extract_headline(f"⟦ {headline} ⟧") == "x" * 2000


@pytest.mark.parametrize(
    "text",
    [
        "done\n⟦ NEXT_RID is 1003</arg_value></tool_call>",
        "done<!-- ⟦ NEXT_RID is 1003</arg_value></tool_call>",
    ],
)
def test_strip_headline_hides_malformed_trailing_tool_protocol(
    text: str,
) -> None:
    assert extract_headline(text) is None
    assert strip_headline(text) == "done"


def test_strip_headline_preserves_inline_plain_fence() -> None:
    text = "compare ⟦left⟧ and ⟦right⟧"
    assert extract_headline(text) is None
    assert strip_headline(text) == text
