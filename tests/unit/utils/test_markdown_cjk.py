# -*- coding: utf-8 -*-
"""Tests for :mod:`qwenpaw.utils.markdown_cjk`."""

from qwenpaw.utils.markdown_cjk import normalize_cjk_emphasis


def test_repairs_all_supported_emphasis_delimiters():
    assert normalize_cjk_emphasis("**粗体。**后文") == "**粗体**。后文"
    assert normalize_cjk_emphasis("__粗体！__后文") == "__粗体__！后文"
    assert normalize_cjk_emphasis("*斜体；*後文") == "*斜体*；後文"
    assert normalize_cjk_emphasis("_斜体：_かな") == "_斜体_：かな"


def test_repairs_combined_three_character_delimiters():
    assert normalize_cjk_emphasis("***内容。***后文") == "***内容***。后文"
    assert normalize_cjk_emphasis("___内容。___后文") == "___内容___。后文"


def test_moves_every_approved_punctuation_mark():
    for mark in "。！？；：，、…":
        source = f"**内容{mark}**后"
        assert normalize_cjk_emphasis(source) == f"**内容**{mark}后"


def test_moves_trailing_full_width_closers():
    for closer in "”’」』】》〉）〕］":
        source = f"**内容。{closer}**後"
        assert normalize_cjk_emphasis(source) == f"**内容**。{closer}後"
    assert normalize_cjk_emphasis("**内容！？…”）**后") == "**内容**！？…”）后"


def test_recognizes_cjk_and_supplementary_han_followers():
    for follower in ["后", "あ", "ア", "한", "\U00020000"]:
        source = f"**内容。**{follower}"
        assert normalize_cjk_emphasis(source) == f"**内容**。{follower}"


def test_handles_multiple_adjacent_and_nested_emphasis():
    assert (
        normalize_cjk_emphasis("**甲。**乙 __丙！__丁 *戊？*己")
        == "**甲**。乙 __丙__！丁 *戊*？己"
    )
    assert normalize_cjk_emphasis("**外层 *内层。*后续**") == "**外层 *内层*。后续**"


def test_does_not_widen_punctuation_or_follower_scope():
    unchanged = [
        "**内容.**后",
        "**内容。**latin",
        "**内容。** 后",
        "**内容」**后",
        "plain 中文。**后",
        "**已经规范**。后",
    ]
    for source in unchanged:
        assert normalize_cjk_emphasis(source) == source


def test_preserves_fenced_inline_and_indented_code():
    source = "\n".join(
        [
            "outside **正文。**后",
            "```markdown",
            "**代码。**后",
            "```",
            "~~~",
            "__代码！__後",
            "~~~",
            "inline `**代码。**后` end",
            "    *缩进代码；*後",
            "\t_缩进代码：_かな",
        ],
    )
    expected = source.replace("**正文。**后", "**正文**。后")
    assert normalize_cjk_emphasis(source) == expected


def test_preserves_unclosed_fenced_and_inline_code():
    unclosed_fence = "before\n```md\n**代码。**后\n"
    unclosed_inline = "before `code **示例。**后\nand more __示例！__後"
    assert normalize_cjk_emphasis(unclosed_fence) == unclosed_fence
    assert normalize_cjk_emphasis(unclosed_inline) == unclosed_inline


def test_honors_odd_and_even_backslash_escaping():
    assert normalize_cjk_emphasis("\\**内容。**后") == "\\**内容。**后"
    assert normalize_cjk_emphasis("\\\\**内容。**后") == "\\\\**内容**。后"
    assert normalize_cjk_emphasis("**内容。\\**后") == "**内容。\\**后"
    assert normalize_cjk_emphasis("**内容\\\\。**后") == "**内容\\\\**。后"


def test_preserves_matched_repairs_around_unclosed_delimiters():
    assert normalize_cjk_emphasis("**内容。**后 *未闭合") == "**内容**。后 *未闭合"
    assert normalize_cjk_emphasis("**甲。**乙 **未闭合") == "**甲**。乙 **未闭合"
    assert normalize_cjk_emphasis("*未闭合 **甲。**乙") == "*未闭合 **甲**。乙"


def test_preserves_crossing_invalid_delimiters():
    source = "**外层 *内层。**后续"
    assert normalize_cjk_emphasis(source) == source


def test_preserves_crlf_and_unfinished_emphasis():
    crlf = "**甲。**乙\r\n__丙！__丁\r\n"
    assert normalize_cjk_emphasis(crlf) == "**甲**。乙\r\n__丙__！丁\r\n"
    for source in ["**未闭合。后", "_未闭合！後", "结尾 **"]:
        assert normalize_cjk_emphasis(source) == source


def test_is_deterministic_and_idempotent():
    source = "**甲。**乙 and *丙！*丁"
    once = normalize_cjk_emphasis(source)
    assert normalize_cjk_emphasis(source) == once
    assert normalize_cjk_emphasis(once) == once


def test_empty_and_plain_text_are_unchanged():
    assert normalize_cjk_emphasis("") == ""
    plain = "普通中文，没有任何强调标记。"
    assert normalize_cjk_emphasis(plain) == plain
