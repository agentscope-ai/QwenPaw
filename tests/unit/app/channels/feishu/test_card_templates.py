# -*- coding: utf-8 -*-
"""Unit tests for feishu card_templates.

The module is pure-data card building and parsing with no channel
dependency; every helper is deterministic and directly testable.
"""
# pylint: disable=protected-access
from __future__ import annotations

import json

import pytest

from qwenpaw.app.channels.feishu import card_templates as ct


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_empty_text(self):
        assert ct._truncate("", 10) == ""

    def test_short_text_unchanged(self):
        assert ct._truncate("abc", 10) == "abc"

    def test_exact_limit_unchanged(self):
        assert ct._truncate("abcde", 5) == "abcde"

    def test_long_text_truncated_with_ellipsis(self):
        result = ct._truncate("abcdefgh", 5)
        assert result == "abcd…"
        assert len(result) == 5


# ---------------------------------------------------------------------------
# severity template
# ---------------------------------------------------------------------------


class TestSeverityTemplate:
    @pytest.mark.parametrize(
        ("severity", "template"),
        [
            ("critical", "red"),
            ("high", "red"),
            ("medium", "orange"),
            ("low", "yellow"),
        ],
    )
    def test_known_severities(self, severity, template):
        assert ct._tool_guard_severity_template(severity) == template

    def test_case_insensitive(self):
        assert ct._tool_guard_severity_template("HIGH") == "red"

    def test_unknown_severity_defaults_orange(self):
        assert ct._tool_guard_severity_template("weird") == "orange"
        assert ct._tool_guard_severity_template("") == "orange"
        assert ct._tool_guard_severity_template(None) == "orange"


# ---------------------------------------------------------------------------
# build_tool_guard_approval_card
# ---------------------------------------------------------------------------


class TestBuildApprovalCard:
    def test_card_structure_and_button_values(self):
        raw = ct.build_tool_guard_approval_card(
            request_id="req-1",
            tool_name="shell",
            severity="high",
            body_text="Run rm -rf?",
            session_ctx={"session_id": "s1", "chat_id": "c1"},
        )
        card = json.loads(raw)

        assert card["config"]["wide_screen_mode"] is True
        assert card["header"]["template"] == "red"
        assert card["header"]["title"]["content"] == (
            "🛡️ Tool Approval Required"
        )

        # First element carries the rendered body markdown.
        assert card["elements"][0]["content"] == "Run rm -rf?"

        action_row = card["elements"][-1]
        assert action_row["tag"] == "action"
        approve_btn, deny_btn = action_row["actions"]
        assert approve_btn["type"] == "primary"
        assert deny_btn["type"] == "danger"

        approve_value = approve_btn["value"]
        assert approve_value["type"] == ct.TOOL_GUARD_ACTION_TYPE
        assert approve_value["action"] == "approve"
        assert approve_value["request_id"] == "req-1"
        assert approve_value["tool_name"] == "shell"
        assert approve_value["severity"] == "high"
        assert approve_value["body"] == "Run rm -rf?"
        assert approve_value["session_ctx"] == {
            "session_id": "s1",
            "chat_id": "c1",
        }

        deny_value = deny_btn["value"]
        assert deny_value["action"] == "deny"
        assert deny_value["request_id"] == "req-1"

    def test_defaults_for_missing_optional_fields(self):
        card = json.loads(
            ct.build_tool_guard_approval_card(
                request_id="r",
                tool_name="t",
                severity="",
                body_text="",
            ),
        )
        # Empty severity falls back to the orange template.
        assert card["header"]["template"] == "orange"
        action_row = card["elements"][-1]
        value = action_row["actions"][0]["value"]
        assert value["severity"] == "medium"
        assert value["body"] == ""
        assert value["session_ctx"] == {}

    def test_body_snapshot_truncated_to_limit(self):
        long_body = "x" * 3000
        card = json.loads(
            ct.build_tool_guard_approval_card(
                request_id="r",
                tool_name="t",
                severity="low",
                body_text=long_body,
            ),
        )
        markdown = card["elements"][0]["content"]
        value = card["elements"][-1]["actions"][0]["value"]
        assert len(markdown) == 1800
        assert markdown.endswith("…")
        assert len(value["body"]) == 1500

    def test_round_trip_through_parser(self):
        raw = ct.build_tool_guard_approval_card(
            request_id="req-9",
            tool_name="browser",
            severity="medium",
            body_text="open the page",
            session_ctx={"session_id": "s"},
        )
        approve_value = json.loads(raw)["elements"][-1]["actions"][0]["value"]
        parsed = ct.parse_tool_guard_action_value(approve_value)
        assert parsed is not None
        assert parsed["action"] == "approve"
        assert parsed["request_id"] == "req-9"
        assert parsed["tool_name"] == "browser"
        assert parsed["body"] == "open the page"
        assert parsed["session_ctx"] == {"session_id": "s"}


# ---------------------------------------------------------------------------
# build_tool_guard_resolved_card
# ---------------------------------------------------------------------------


class TestBuildResolvedCard:
    def test_approve_card(self):
        card = json.loads(
            ct.build_tool_guard_resolved_card(
                tool_name="shell",
                action="approve",
                operator_display="泰哥",
                body_text="original body",
            ),
        )
        assert card["header"]["template"] == "green"
        assert card["header"]["title"]["content"] == "✅ Approved"
        contents = [e.get("content") for e in card["elements"]]
        assert "original body" in contents
        status_line = contents[-1]
        assert "approved" in status_line
        assert "泰哥" in status_line

    def test_deny_card_without_operator(self):
        card = json.loads(
            ct.build_tool_guard_resolved_card(
                tool_name="shell",
                action="deny",
            ),
        )
        assert card["header"]["template"] == "red"
        status = card["elements"][-1]["content"]
        assert "denied" in status
        assert "by" not in status

    def test_unknown_action_shows_expired(self):
        card = json.loads(
            ct.build_tool_guard_resolved_card(
                tool_name="shell",
                action="garbage",
            ),
        )
        assert card["header"]["template"] == "grey"
        assert card["header"]["title"]["content"] == "⌛ Expired"
        assert "expired" in card["elements"][-1]["content"]

    def test_empty_body_skips_body_elements(self):
        card = json.loads(
            ct.build_tool_guard_resolved_card(
                tool_name="shell",
                action="approve",
                body_text="",
            ),
        )
        # Only the status line remains without a body/hr pair.
        assert len(card["elements"]) == 1


# ---------------------------------------------------------------------------
# parse_tool_guard_action_value
# ---------------------------------------------------------------------------


class TestParseActionValue:
    def _valid_value(self, **overrides):
        value = {
            "type": ct.TOOL_GUARD_ACTION_TYPE,
            "action": "approve",
            "request_id": "req-1",
            "tool_name": "shell",
            "severity": "high",
            "body": "body",
            "session_ctx": {"session_id": "s"},
        }
        value.update(overrides)
        return value

    def test_non_dict_returns_none(self):
        assert ct.parse_tool_guard_action_value("nope") is None
        assert ct.parse_tool_guard_action_value(None) is None

    def test_wrong_type_returns_none(self):
        assert ct.parse_tool_guard_action_value({"type": "other_card"}) is None

    def test_missing_request_id_returns_none(self):
        assert (
            ct.parse_tool_guard_action_value(
                self._valid_value(request_id=""),
            )
            is None
        )

    def test_invalid_action_returns_none(self):
        assert (
            ct.parse_tool_guard_action_value(self._valid_value(action="x"))
            is None
        )

    def test_action_normalized_to_lowercase(self):
        parsed = ct.parse_tool_guard_action_value(
            self._valid_value(action=" DENY "),
        )
        assert parsed is not None
        assert parsed["action"] == "deny"

    def test_non_dict_session_ctx_defaults_empty(self):
        parsed = ct.parse_tool_guard_action_value(
            self._valid_value(session_ctx="junk"),
        )
        assert parsed is not None
        assert parsed["session_ctx"] == {}

    def test_missing_optional_fields_default(self):
        parsed = ct.parse_tool_guard_action_value(
            {
                "type": ct.TOOL_GUARD_ACTION_TYPE,
                "action": "approve",
                "request_id": "r",
            },
        )
        assert parsed is not None
        assert parsed["tool_name"] == ""
        assert parsed["severity"] == "medium"
        assert parsed["body"] == ""


# ---------------------------------------------------------------------------
# build_tool_guard_toast
# ---------------------------------------------------------------------------


class TestBuildToast:
    def test_approve_toast(self):
        toast = ct.build_tool_guard_toast("approve", "shell")
        assert toast == {
            "type": "success",
            "content": "Approved tool shell",
        }

    def test_deny_toast(self):
        toast = ct.build_tool_guard_toast("deny", "shell")
        assert toast["type"] == "info"
        assert "Denied tool shell" in toast["content"]

    def test_unknown_action_toast(self):
        toast = ct.build_tool_guard_toast("mystery", "shell")
        assert toast["type"] == "warning"
        assert "expired" in toast["content"]
