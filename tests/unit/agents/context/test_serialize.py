# -*- coding: utf-8 -*-
"""Headline extraction and display-cleanup regressions."""

import pytest

from qwenpaw.agents.context.scroll.prompt import build_scroll_system_prompt
from qwenpaw.agents.context.scroll.serialize import (
    HeadlineDeltaState,
    extract_headline,
    flush_headline_delta,
    strip_headline,
    strip_headline_delta,
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
def test_prompt_uses_high_coverage_retrieval_headline(language: str) -> None:
    prompt = build_scroll_system_prompt(language)
    assert "⟦" in prompt and "⟧" in prompt
    assert "next" in prompt.casefold() or "下一步" in prompt
    assert "anchors" in prompt.casefold() or "锚点" in prompt
    assert "every substantive" in prompt or "每个有实质信息" in prompt
    assert "rather than omitting" in prompt or "而不是省略" in prompt
    assert "<context-event>" not in prompt
    assert "<task-state>" not in prompt


@pytest.mark.parametrize(
    ("language", "required_phrases"),
    [
        (
            "en",
            (
                "retrieval label",
                "VERIFIED state",
                "success criterion",
                "failed attempt",
                "two to four",
                "five high-value",
                "2000-character limit",
            ),
        ),
        (
            "zh",
            (
                "检索标签",
                "成功标准",
                "已经验证",
                "失败尝试",
                "2～4 个短分句",
                "5 个高价值",
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


def test_strip_headline_delta_suppresses_split_protocol_line() -> None:
    state = HeadlineDeltaState()
    visible, state = strip_headline_delta(
        "done\n⟦ model discovery |",
        state=state,
    )
    assert visible == "done"
    assert state.suppressing is True

    visible, state = strip_headline_delta(
        " status: fixed; next: test",
        state=state,
    )
    assert visible == ""
    assert state.suppressing is True

    visible, state = strip_headline_delta(
        " | anchors: TC-1 ⟧",
        state=state,
    )
    assert visible == ""
    assert state.suppressing is False


@pytest.mark.parametrize(
    "split_at",
    range(1, len("<!-- ⟦ hidden headline ⟧ -->")),
)
def test_strip_headline_delta_buffers_every_legacy_marker_split(
    split_at: int,
) -> None:
    marker = "<!-- ⟦ hidden headline ⟧ -->"
    state = HeadlineDeltaState()
    first, state = strip_headline_delta(
        "answer\n" + marker[:split_at],
        state=state,
    )
    second, state = strip_headline_delta(
        marker[split_at:],
        state=state,
    )

    assert first + second == "answer\n"
    assert state == HeadlineDeltaState()


def test_strip_headline_delta_releases_non_protocol_prefix() -> None:
    state = HeadlineDeltaState()
    first, state = strip_headline_delta("answer\n<!", state=state)
    second, state = strip_headline_delta("important", state=state)

    assert first + second == "answer\n<!important"
    assert state == HeadlineDeltaState()


@pytest.mark.parametrize("suffix", ("<", "<!", "<!--"))
def test_flush_headline_delta_releases_unconfirmed_prefix(
    suffix: str,
) -> None:
    state = HeadlineDeltaState()
    visible, state = strip_headline_delta(
        "ordinary comparison ends in " + suffix,
        state=state,
    )

    assert visible == "ordinary comparison ends in "
    assert flush_headline_delta(state) == suffix
    assert state == HeadlineDeltaState()


def test_flush_headline_delta_discards_confirmed_headline() -> None:
    state = HeadlineDeltaState()
    visible, state = strip_headline_delta(
        "answer\n<!-- ⟦ unfinished headline",
        state=state,
    )

    assert visible == "answer\n"
    assert state.suppressing is True
    assert flush_headline_delta(state) == ""
    assert state == HeadlineDeltaState()
