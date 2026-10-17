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
    strip_injected_context,
    strip_model_scaffolding,
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


def test_strip_injected_context_drops_leading_blocks() -> None:
    text = (
        "<system-info>\n[context compressed] …\n</system-info>\n"
        "<system-notification>\nBackground tool call …\n"
        "</system-notification>\n"
        "主人，好了。"
    )
    assert strip_injected_context(text) == "主人，好了。"


def test_strip_injected_context_strips_repeated_blocks() -> None:
    text = (
        "<system-info>\na\n</system-info>"
        + "<system-info>\nb\n</system-info>ok"
    )
    assert strip_injected_context(text) == "ok"


def test_strip_injected_context_keeps_quoted_mention() -> None:
    text = "`<system-info>` 是框架注入的块。"
    assert strip_injected_context(text) == text


def test_strip_injected_context_keeps_mid_text_mention() -> None:
    text = "正文里出现了 <system-info> 标记。"
    assert strip_injected_context(text) == text


def test_strip_injected_context_keeps_unbalanced_block() -> None:
    text = "<system-info>\n没闭合的注入块"
    assert strip_injected_context(text) == text


def test_strip_injected_context_drops_pure_injected_text() -> None:
    """A message that is nothing but an injected block has nothing to show."""
    text = "<system-info>\nonly\n</system-info>"
    assert strip_injected_context(text) == ""


@pytest.mark.parametrize(
    "tag",
    ["system-warning", "system-reminder", "system-error"],
)
def test_strip_injected_context_drops_every_system_notice(tag: str) -> None:
    text = f"<{tag}>\n注意\n</{tag}>\n主人，好了。"
    assert strip_injected_context(text) == "主人，好了。"


def test_strip_injected_context_drops_short_close_form() -> None:
    """The framework closes <system-notification> with </notification>."""
    text = (
        "<system-notification>\nBackground tool call finished.\n"
        "</notification>\n主人，好了。"
    )
    assert strip_injected_context(text) == "主人，好了。"


def test_strip_model_scaffolding_drops_paired_block() -> None:
    text = "<thinking>IncompleteRead(226257 bytes read)</thinking>读取被截断了"
    assert strip_model_scaffolding(text) == "读取被截断了"


def test_strip_model_scaffolding_drops_block_between_prose() -> None:
    text = "开头一段正文。<thinking>中间推理</thinking>后面还有正文"
    assert strip_model_scaffolding(text) == "开头一段正文。后面还有正文"


def test_strip_model_scaffolding_drops_truncated_tail() -> None:
    """A bare close tag means the reasoning head was cut off upstream."""
    text = "推理半句，我应该先查库里的。</think>主人，我查到了"
    assert strip_model_scaffolding(text) == "主人，我查到了"


def test_strip_model_scaffolding_drops_leading_bare_close() -> None:
    text = "</thinking>\n正文开始"
    assert strip_model_scaffolding(text) == "正文开始"


def test_strip_model_scaffolding_keeps_reply_before_trailing_close() -> None:
    """A trailing bare close ends a reasoning paragraph, not the reply."""
    text = "主人，已经改好了。\n\nneed to look at the log first.</think>"
    assert strip_model_scaffolding(text) == "主人，已经改好了。"


def test_strip_model_scaffolding_keeps_backticked_mention() -> None:
    text = "主人问：`<thinking>` 这个标签是什么意思？"
    assert strip_model_scaffolding(text) == text


def test_strip_model_scaffolding_keeps_fenced_example() -> None:
    text = "示例：\n```\n<thinking>x</thinking>\n```\n就是这种"
    assert strip_model_scaffolding(text) == text


def test_strip_model_scaffolding_keeps_plain_prose() -> None:
    text = "我先看看这个函数是怎么写的，然后再决定要不要改"
    assert strip_model_scaffolding(text) == text


def test_strip_model_scaffolding_keeps_bare_word() -> None:
    text = "thinking 是一个英文单词，thinking hard 也行"
    assert strip_model_scaffolding(text) == text


def test_strip_model_scaffolding_drops_truncated_tool_shell() -> None:
    text = '<parameter name="content">截断的工具调用'
    assert strip_model_scaffolding(text) == ""


def test_strip_model_scaffolding_empties_pure_reasoning() -> None:
    """Nothing but reasoning: the block must not become an empty bubble."""
    assert strip_model_scaffolding("先查库。</think>") == ""


def test_strip_model_scaffolding_drops_shell_opening_a_paragraph() -> None:
    """Narration before a truncated tool call leaves the shell mid-message."""
    text = '主人，我先查。\n\n<parameter name="content">截断的工具调用'
    assert strip_model_scaffolding(text) == "主人，我先查。"


def test_strip_model_scaffolding_keeps_shell_mid_sentence() -> None:
    text = '正文里提到 <parameter name="content"> 这种壳。'
    assert strip_model_scaffolding(text) == text


def test_strip_model_scaffolding_keeps_unclosed_open_tag() -> None:
    """An unclosed tag is prose about tags, not leaked reasoning."""
    text = "我还是先去确认 <thinking> 这个标签有没有闭合"
    assert strip_model_scaffolding(text) == text


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
