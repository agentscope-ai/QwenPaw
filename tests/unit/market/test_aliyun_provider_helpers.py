# -*- coding: utf-8 -*-
"""Tests for the Aliyun market provider pure helpers.

Covers _str/_opt_str/_opt_int coercion, _category_label composition,
_to_market_result field mapping (stats population, slug fallback, detail
URL encoding), and _build_runtime timeout handling, which previously had
no coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations


from qwenpaw.market.providers import aliyun as aliyun_mod


# ---------------------------------------------------------------------------
# _str / _opt_str / _opt_int
# ---------------------------------------------------------------------------


class TestCoercion:
    def test_str_strips(self):
        assert aliyun_mod._str("  hello  ") == "hello"

    def test_str_non_string_empty(self):
        assert aliyun_mod._str(123) == ""
        assert aliyun_mod._str(None) == ""

    def test_opt_str_none_for_blank(self):
        assert aliyun_mod._opt_str("   ") is None
        assert aliyun_mod._opt_str("") is None

    def test_opt_str_value(self):
        assert aliyun_mod._opt_str(" x ") == "x"

    def test_opt_int_int(self):
        assert aliyun_mod._opt_int(5) == 5

    def test_opt_int_digit_string(self):
        assert aliyun_mod._opt_int(" 42 ") == 42

    def test_opt_int_bool_rejected(self):
        assert aliyun_mod._opt_int(True) is None
        assert aliyun_mod._opt_int(False) is None

    def test_opt_int_non_digit_string(self):
        assert aliyun_mod._opt_int("abc") is None
        assert aliyun_mod._opt_int("1.5") is None

    def test_opt_int_other_types(self):
        assert aliyun_mod._opt_int(1.5) is None
        assert aliyun_mod._opt_int(None) is None


# ---------------------------------------------------------------------------
# _category_label
# ---------------------------------------------------------------------------


class TestCategoryLabel:
    def test_parent_and_child(self):
        item = {"categoryName": "Tools", "subCategoryName": "Search"}
        assert aliyun_mod._category_label(item) == "Tools / Search"

    def test_parent_only(self):
        assert aliyun_mod._category_label({"categoryName": "Tools"}) == "Tools"

    def test_child_only(self):
        assert (
            aliyun_mod._category_label({"subCategoryName": "Search"})
            == "Search"
        )

    def test_empty(self):
        assert aliyun_mod._category_label({}) == ""


# ---------------------------------------------------------------------------
# _to_market_result
# ---------------------------------------------------------------------------


class TestToMarketResult:
    def test_full_item_mapped(self):
        item = {
            "skillName": "my-skill",
            "displayName": "My Skill",
            "description": "does things",
            "installCount": 100,
            "likeCount": "50",
            "categoryName": "Tools",
            "subCategoryName": "Search",
            "updatedAt": "2026-01-01",
        }
        result = aliyun_mod._to_market_result(item)
        assert result is not None
        assert result.source == "aliyun"
        assert result.slug == "my-skill"
        assert result.name == "My Skill"
        assert result.description == "does things"
        assert result.source_url.endswith("/agentexplorer/skills/my-skill")
        assert result.stats == {
            "installs": 100,
            "likes": 50,
            "category": "Tools / Search",
            "updated_at": "2026-01-01",
        }

    def test_no_name_fields_returns_none(self):
        assert aliyun_mod._to_market_result({}) is None

    def test_slug_falls_back_to_display(self):
        item = {"displayName": "Only Display"}
        result = aliyun_mod._to_market_result(item)
        assert result is not None
        assert result.slug == "Only Display"
        assert result.name == "Only Display"

    def test_slug_url_encodes_spaces(self):
        item = {"displayName": "My Skill"}
        result = aliyun_mod._to_market_result(item)
        assert result.source_url.endswith("My%20Skill")

    def test_empty_stats_becomes_none(self):
        item = {"skillName": "s"}
        result = aliyun_mod._to_market_result(item)
        assert result.stats is None

    def test_invalid_counts_skipped(self):
        item = {"skillName": "s", "installCount": "not-a-number"}
        result = aliyun_mod._to_market_result(item)
        assert result.stats is None


# ---------------------------------------------------------------------------
# _build_runtime
# ---------------------------------------------------------------------------


class TestBuildRuntime:
    def test_none_timeout_defaults(self):
        runtime = aliyun_mod._build_runtime(None)
        assert runtime is not None

    def test_timeout_converted_to_ms(self):
        runtime = aliyun_mod._build_runtime(2.5)
        assert runtime.connect_timeout == 2500
        assert runtime.read_timeout == 2500

    def test_minimum_one_ms(self):
        runtime = aliyun_mod._build_runtime(0.0001)
        assert runtime.connect_timeout == 1
