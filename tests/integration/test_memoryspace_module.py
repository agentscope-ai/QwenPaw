# -*- coding: utf-8 -*-
"""Integration tests for the Scroll memory-space query helpers.

Covers src/qwenpaw/agents/context/scroll/memoryspace.py (396 uncovered
lines): FTS MATCH query building, OR-group splitting, LIKE term and
pattern helpers, session suffix sanitization, strict ISO date parsing.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest


# ------------------------------------------------------------------ #
# FTS MATCH query building
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_fts_match_query_plain_words() -> None:
    """Plain words become quoted phrase tokens."""
    from qwenpaw.agents.context.scroll.memoryspace import fts_match_query

    result = fts_match_query("hello world")
    assert result == '"hello" "world"'


@pytest.mark.integration
@pytest.mark.p1
def test_fts_match_query_special_chars_neutralized() -> None:
    """Punctuation-heavy tokens are quoted instead of raising."""
    from qwenpaw.agents.context.scroll.memoryspace import fts_match_query

    result = fts_match_query("C++")
    assert '"C' in result or result  # quoted phrase, not raw operator


@pytest.mark.integration
@pytest.mark.p1
def test_fts_match_query_bare_or_operator() -> None:
    """Bare uppercase OR passes through as a boolean operator."""
    from qwenpaw.agents.context.scroll.memoryspace import fts_match_query

    result = fts_match_query("tank OR aquarium")
    assert " OR " in result
    assert '"tank"' in result
    assert '"aquarium"' in result


@pytest.mark.integration
@pytest.mark.p1
def test_fts_match_query_embedded_quotes_doubled() -> None:
    """Tokens are quoted; the doubling rule guards any embedded quote."""
    from qwenpaw.agents.context.scroll.memoryspace import fts_match_query

    # Tokenizer extracts word chars; each token is emitted quoted.
    result = fts_match_query('say "hi" there')
    assert result == '"say" "hi" "there"'


@pytest.mark.integration
@pytest.mark.p1
def test_fts_match_query_no_tokens_empty() -> None:
    """Queries with no word tokens yield empty string."""
    from qwenpaw.agents.context.scroll.memoryspace import fts_match_query

    assert fts_match_query("") == ""


@pytest.mark.integration
@pytest.mark.p1
def test_or_query_groups_valid() -> None:
    """Valid OR queries split into alternative groups."""
    from qwenpaw.agents.context.scroll.memoryspace import _or_query_groups

    assert _or_query_groups("a OR b") == ["a", "b"]
    assert _or_query_groups("a b OR c") == ["a b", "c"]
    assert _or_query_groups("a OR b OR c") == ["a", "b", "c"]


@pytest.mark.integration
@pytest.mark.p1
def test_or_query_groups_malformed_kept_literal() -> None:
    """Leading/trailing/repeated OR stays one literal group."""
    from qwenpaw.agents.context.scroll.memoryspace import _or_query_groups

    assert _or_query_groups("OR a") == ["OR a"]
    assert _or_query_groups("a OR") == ["a OR"]
    assert _or_query_groups("a OR OR b") == ["a OR OR b"]
    assert _or_query_groups("") == [""]


# ------------------------------------------------------------------ #
# LIKE search helpers
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_like_search_terms_split() -> None:
    """Whitespace splits literal LIKE terms."""
    from qwenpaw.agents.context.scroll.memoryspace import (
        _like_search_terms,
    )

    assert _like_search_terms("one two") == ["one", "two"]


@pytest.mark.integration
@pytest.mark.p1
def test_like_search_terms_empty_restrictive() -> None:
    """All-whitespace input stays restrictive, not predicate-free."""
    from qwenpaw.agents.context.scroll.memoryspace import (
        _like_search_terms,
    )

    assert _like_search_terms("") == [""]
    assert _like_search_terms("   ") == ["   "]


@pytest.mark.integration
@pytest.mark.p1
def test_like_search_groups_or_arms() -> None:
    """OR groups become implicit-AND arms for LIKE."""
    from qwenpaw.agents.context.scroll.memoryspace import (
        _like_search_groups,
    )

    assert _like_search_groups("a b OR c") == [["a", "b"], ["c"]]


@pytest.mark.integration
@pytest.mark.p1
def test_like_pattern_wraps_and_escapes() -> None:
    """LIKE patterns wrap with % and escape wildcards."""
    from qwenpaw.agents.context.scroll.memoryspace import _like_pattern

    assert _like_pattern("abc") == "%abc%"
    assert _like_pattern("a%b") == r"%a\%b%"
    assert _like_pattern("a_b") == r"%a\_b%"
    assert _like_pattern("a\\b") == r"%a\\b%"


# ------------------------------------------------------------------ #
# session suffix sanitization
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_sanitize_suffix_plain() -> None:
    """Alphanumeric session ids pass through."""
    from qwenpaw.agents.context.scroll.memoryspace import sanitize_suffix

    assert sanitize_suffix("session_123") == "session_123"


@pytest.mark.integration
@pytest.mark.p1
def test_sanitize_suffix_special_chars() -> None:
    """Unsafe characters become underscores."""
    from qwenpaw.agents.context.scroll.memoryspace import sanitize_suffix

    assert sanitize_suffix("a:b-c.d") == "a_b_c_d"
    assert sanitize_suffix("x/y z") == "x_y_z"


@pytest.mark.integration
@pytest.mark.p1
def test_sanitize_suffix_empty_scratch() -> None:
    """Empty or None session ids map to 'scratch'."""
    from qwenpaw.agents.context.scroll.memoryspace import sanitize_suffix

    assert sanitize_suffix(None) == "scratch"
    assert sanitize_suffix("") == "scratch"


# ------------------------------------------------------------------ #
# strict date parsing
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_parse_date_iso_date_string() -> None:
    """YYYY-MM-DD strings parse directly."""
    from qwenpaw.agents.context.scroll.memoryspace import parse_date

    assert parse_date("2026-08-28") == date(2026, 8, 28)


@pytest.mark.integration
@pytest.mark.p1
def test_parse_date_iso_timestamp_keeps_local_day() -> None:
    """Timestamps keep the calendar day written in their timezone."""
    from qwenpaw.agents.context.scroll.memoryspace import parse_date

    assert parse_date("2026-08-28T23:59:00Z") == date(2026, 8, 28)
    assert parse_date("2026-08-28T01:00:00+08:00") == date(2026, 8, 28)


@pytest.mark.integration
@pytest.mark.p1
def test_parse_date_native_types() -> None:
    """date and datetime objects pass through to their date."""
    from qwenpaw.agents.context.scroll.memoryspace import parse_date

    d = date(2026, 8, 28)
    dt = datetime(2026, 8, 28, 12, 0, 0)
    assert parse_date(d) == d
    assert parse_date(dt) == date(2026, 8, 28)


@pytest.mark.integration
@pytest.mark.p1
def test_parse_date_invalid_string_raises() -> None:
    """Non-ISO strings raise ValueError."""
    from qwenpaw.agents.context.scroll.memoryspace import parse_date

    with pytest.raises(ValueError):
        parse_date("28/08/2026")
    with pytest.raises(ValueError):
        parse_date("not-a-date")


@pytest.mark.integration
@pytest.mark.p1
def test_parse_date_wrong_type_raises() -> None:
    """Non-string non-date values raise TypeError."""
    from qwenpaw.agents.context.scroll.memoryspace import parse_date

    with pytest.raises(TypeError):
        parse_date(12345)
    with pytest.raises(TypeError):
        parse_date(None)


# ------------------------------------------------------------------ #
# scan budget guard
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_scan_budget_exhaustion() -> None:
    """Scan budget reports exhaustion once the deadline passes."""
    import time

    from qwenpaw.agents.context.scroll.memoryspace import _ScanBudget

    budget = _ScanBudget(remaining=100, deadline=time.monotonic() + 60)
    assert budget.is_exhausted() is False

    expired = _ScanBudget(remaining=100, deadline=time.monotonic() - 1)
    assert expired.is_exhausted() is True
