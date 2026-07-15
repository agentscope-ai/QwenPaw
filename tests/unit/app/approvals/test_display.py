# -*- coding: utf-8 -*-
"""Unit tests for :mod:`qwenpaw.app.approvals.display`.

The scope-gating fields (``exact_target`` / ``similar_target`` /
``is_generalized``) are already pinned in
``tests/unit/app/test_approval_scope.py``.  This file covers the
remaining branches of ``approval_display_fields``: non-dict ``display``
payloads, partial overrides and the ``tool_name`` / ``tool_source``
fallbacks.
"""

from __future__ import annotations

# pylint: disable=use-implicit-booleaness-not-comparison,unused-argument

from qwenpaw.app.approvals.display import approval_display_fields


class _FakePending:
    """Minimal stand-in exposing ``extra`` + ``tool_name`` for display."""

    def __init__(self, extra: dict, tool_name: str = "Bash") -> None:
        self.extra = extra
        self.tool_name = tool_name


# ---------------------------------------------------------------------------
# Non-dict ``display`` payload falls back to safe defaults
# ---------------------------------------------------------------------------


def test_display_non_dict_string_falls_back_safely():
    """If a legacy caller stored a string under ``display`` the helper must
    not crash — it should discard the value and yield the empty defaults."""
    pending = _FakePending({"display": "not-a-dict"})
    fields = approval_display_fields(pending)
    assert fields["tool_display_name"] == "Bash"
    assert fields["tool_source"] == "No rule hit"
    assert fields["exact_target"] == ""
    assert fields["similar_target"] == ""
    assert fields["is_generalized"] is False


def test_display_none_falls_back_safely():
    """``display`` key present but None → same safe defaults."""
    pending = _FakePending({"display": None})
    fields = approval_display_fields(pending)
    assert fields["is_generalized"] is False
    assert fields["tool_display_name"] == "Bash"


def test_display_missing_key_entirely():
    """No ``display`` key in ``extra`` at all → safe defaults."""
    pending = _FakePending({})
    fields = approval_display_fields(pending)
    assert fields["tool_display_name"] == "Bash"
    assert fields["tool_source"] == "No rule hit"
    assert fields["is_generalized"] is False


# ---------------------------------------------------------------------------
# Partial overrides
# ---------------------------------------------------------------------------


def test_tool_source_honored_when_present():
    pending = _FakePending(
        {"display": {"tool_source": "builtin_rules"}},
    )
    fields = approval_display_fields(pending)
    assert fields["tool_source"] == "builtin_rules"
    # tool_name missing in display → falls back to pending.tool_name.
    assert fields["tool_display_name"] == "Bash"


def test_tool_display_name_overrides_pending_tool_name():
    pending = _FakePending(
        {"display": {"tool_name": "run_shell"}},
        tool_name="Bash",
    )
    fields = approval_display_fields(pending)
    assert fields["tool_display_name"] == "run_shell"


def test_empty_string_in_display_falls_back_to_pending_value():
    """An empty ``tool_name`` string in display must fall through to
    ``pending.tool_name`` (truthy coalescing)."""
    pending = _FakePending(
        {"display": {"tool_name": ""}},
        tool_name="Bash",
    )
    fields = approval_display_fields(pending)
    assert fields["tool_display_name"] == "Bash"


def test_is_generalized_truthy_values():
    pending = _FakePending(
        {"display": {"is_generalized": True}},
    )
    assert approval_display_fields(pending)["is_generalized"] is True


def test_is_generalized_falsy_values():
    pending = _FakePending(
        {"display": {"is_generalized": 0}},
    )
    assert approval_display_fields(pending)["is_generalized"] is False
