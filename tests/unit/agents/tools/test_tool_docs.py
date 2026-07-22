# -*- coding: utf-8 -*-
"""Unit tests for built-in tool docs and schema helpers."""

from __future__ import annotations

from qwenpaw.agents.tools.tool_docs import (
    get_tool_input_schema,
    load_tool_doc,
    normalize_tool_doc_lang,
    resolve_tool_presentation,
)


def test_normalize_tool_doc_lang() -> None:
    assert normalize_tool_doc_lang("zh-CN") == "zh"
    assert normalize_tool_doc_lang("en-US") == "en"
    assert normalize_tool_doc_lang("ja") == "ja"
    assert normalize_tool_doc_lang("pt-BR") == "pt-BR"
    assert normalize_tool_doc_lang("") == "en"
    assert normalize_tool_doc_lang(None) == "en"


def test_load_tool_doc_zh_and_en() -> None:
    zh = load_tool_doc("read_file", "zh")
    en = load_tool_doc("read_file", "en")
    assert zh is not None
    assert en is not None
    assert "读取文件" in zh["summary"]
    assert "Read file" in en["summary"]
    assert "start_line" in zh["body"]
    assert "start_line" in en["body"]


def test_load_tool_doc_ja_falls_back_to_en() -> None:
    ja = load_tool_doc("grep_search", "ja")
    en = load_tool_doc("grep_search", "en")
    assert ja is not None
    assert en is not None
    assert ja["summary"] == en["summary"]
    assert "pattern" in ja["body"]


def test_get_tool_input_schema_read_file() -> None:
    schema = get_tool_input_schema("read_file")
    props = schema.get("properties") or {}
    assert "file_path" in props
    assert "file_path" in (schema.get("required") or [])


def test_resolve_tool_presentation_prefers_curated() -> None:
    zh = resolve_tool_presentation(
        "read_file",
        lang="zh",
        fallback_description="fallback",
    )
    assert "读取文件" in zh["summary"]
    assert zh["detail"]
    assert "file_path" in (zh["input_schema"].get("properties") or {})
