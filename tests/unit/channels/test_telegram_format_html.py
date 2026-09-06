# -*- coding: utf-8 -*-
"""Focused unit tests for Markdown table handling in Telegram HTML output.

Covers Issue #7585: Markdown tables must not be echoed back with raw
``|`` / ``---`` syntax. They are rendered as a ``<pre>`` monospace block.

Run:
    pytest tests/unit/channels/test_telegram_format_html.py -q
"""
from __future__ import annotations

from qwenpaw.app.channels.telegram.format_html import markdown_to_telegram_html


class TestTelegramMarkdownTable:
    def test_basic_table_becomes_pre(self):
        out = markdown_to_telegram_html("| A | B |\n|---|---|\n| 1 | 2 |")
        assert "<pre>" in out
        assert "|---|---|" not in out
        assert "A" in out and "1" in out

    def test_issue_example_table(self):
        md = "| 期限 | 总利息 |\n|------|--------|\n| 30 年 | 91 万 |"
        out = markdown_to_telegram_html(md)
        assert "<pre>" in out
        assert "|------|--------|" not in out
        assert "91 万" in out

    def test_alignment_markers_accepted(self):
        md = "| L | C | R |\n|:---|:---:|---:|\n| a | b | c |"
        out = markdown_to_telegram_html(md)
        assert "<pre>" in out
        assert "|:---|:---:|---:|" not in out
        assert "a" in out and "b" in out and "c" in out

    def test_surrounding_prose_preserved(self):
        md = "before\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nafter"
        out = markdown_to_telegram_html(md)
        assert "before" in out
        assert "after" in out
        assert "<pre>" in out

    def test_table_cells_are_html_escaped(self):
        md = "| A | B |\n|---|---|\n| <script> | A & B |"
        out = markdown_to_telegram_html(md)
        assert "<pre>" in out
        assert "&lt;script&gt;" in out
        assert "A &amp; B" in out
        assert "<script>" not in out

    def test_fenced_code_with_pipes_not_converted_to_table(self):
        md = "```\na | b\n--|--\n```"
        out = markdown_to_telegram_html(md)
        assert "--|--" in out  # raw code content preserved
        assert "-+-" not in out  # no table separator injected

    def test_spoiler_still_works(self):
        out = markdown_to_telegram_html("||secret||")
        assert out == "<tg-spoiler>secret</tg-spoiler>"
        assert "<pre>" not in out

    def test_plain_pipe_text_not_converted(self):
        out = markdown_to_telegram_html("foo | bar")
        assert out == "foo | bar"
        assert "<pre>" not in out

    def test_malformed_table_not_converted(self):
        md = "| A | B |\n| xx | yy |\n| 1 | 2 |"
        out = markdown_to_telegram_html(md)
        assert "<pre>" not in out
        assert "| xx | yy |" in out

    def test_table_with_inline_code_cell_stays_plain_text(self):
        md = "| Name | Value |\n| --- | --- |\n| x | `a|b` |"
        out = markdown_to_telegram_html(md)
        assert "<pre>" in out
        assert "a|b" in out
        assert "<code>" not in out
        assert "\x00" not in out

    def test_table_with_link_cell_stays_plain_text(self):
        md = (
            "| Name | URL |\n| --- | --- |\n"
            "| QwenPaw | [site](https://example.com) |"
        )
        out = markdown_to_telegram_html(md)
        assert "<pre>" in out
        assert "site" in out
        assert "<a " not in out
        assert "\x00" not in out
