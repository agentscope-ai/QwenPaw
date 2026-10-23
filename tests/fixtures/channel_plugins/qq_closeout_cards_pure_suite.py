"""Original QQ pure card builder/parser inputs on actual private helpers."""

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/channel/qq"))
from qwenpaw_channel_qq.cards import tool_guard as tg  # noqa: E402


def _button_data(action="approve", request_id="rid-12345678", **extra):
    payload = {
        "p": tg.ACTION_DATA_PREFIX,
        "a": action,
        "rid": request_id,
        "tool": "shell",
        "sev": "medium",
    }
    payload.update(extra)
    return json.dumps(payload, separators=(",", ":"))


def _click_event(action="approve", ctx=None, **overrides):
    """Build an ``INTERACTION_CREATE`` event.

    ``ctx`` is merged into the button payload: in production the routing
    keys are encoded when the card is rendered, so a click carries them
    back.
    """
    event = {
        "id": "interaction-1",
        "group_member_openid": "openid-abcdef",
        "data": {
            "resolved": {
                "button_data": _button_data(action, **(ctx or {})),
            },
        },
    }
    event.update(overrides)
    return event


class TestBuildActionData:
    def test_payload_is_compact_and_keyed(self):
        raw = tg._build_action_data(
            "approve",
            "rid-1",
            "shell",
            "high",
            {"sid": "s1"},
        )

        assert json.loads(raw) == {
            "p": "tg_",
            "a": "approve",
            "rid": "rid-1",
            "tool": "shell",
            "sev": "high",
            "sid": "s1",
        }
        # Compact separators keep the payload inside QQ's size budget.
        assert ", " not in raw and '": "' not in raw

    def test_non_ascii_context_is_preserved(self):
        raw = tg._build_action_data("deny", "rid", "tool", "low", {"n": "泰哥"})

        assert "泰哥" in raw


class TestBuildApprovalKeyboard:
    def test_button_actions_carry_callback_data(self):
        keyboard = tg.build_approval_keyboard(
            request_id="rid-1",
            tool_name="shell",
            severity="medium",
            session_ctx={"sid": "s1"},
        )

        buttons = keyboard["content"]["rows"][0]["buttons"]
        for button, expected_action in zip(buttons, ("approve", "deny")):
            action = button["action"]
            assert action["type"] == 1
            assert action["permission"] == {"type": 2}
            payload = json.loads(action["data"])
            assert payload["a"] == expected_action
            assert payload["sid"] == "s1"

    def test_unsupported_client_tips_are_action_specific(self):
        buttons = tg.build_approval_keyboard(
            request_id="rid-1",
            tool_name="shell",
            severity="medium",
        )["content"]["rows"][0]["buttons"]

        assert buttons[0]["action"]["unsupport_tips"].endswith("approve")
        assert buttons[1]["action"]["unsupport_tips"].endswith("deny")

    @pytest.mark.parametrize("severity", ["", None])
    def test_blank_severity_falls_back_to_medium(self, severity):
        keyboard = tg.build_approval_keyboard(
            request_id="rid-1",
            tool_name="shell",
            severity=severity,
        )

        data = json.loads(
            keyboard["content"]["rows"][0]["buttons"][0]["action"]["data"],
        )
        assert data["sev"] == "medium"

    def test_whitespace_severity_is_only_lowered(self):
        """``severity or "medium"`` keeps whitespace: it is truthy."""
        keyboard = tg.build_approval_keyboard(
            request_id="rid-1",
            tool_name="shell",
            severity="  ",
        )

        data = json.loads(
            keyboard["content"]["rows"][0]["buttons"][0]["action"]["data"],
        )
        assert data["sev"] == "  "

    def test_missing_session_ctx_yields_no_extra_keys(self):
        keyboard = tg.build_approval_keyboard(
            request_id="rid-1",
            tool_name="shell",
            severity="medium",
        )

        data = json.loads(
            keyboard["content"]["rows"][0]["buttons"][0]["action"]["data"],
        )
        assert set(data) == {"p", "a", "rid", "tool", "sev"}


class TestBuildResolvedText:
    def test_approved_includes_operator_and_tool(self):
        assert tg.build_resolved_text("shell", "approve", "abc123") == (
            "✅ **Approved** by **abc123**\nTool: `shell`"
        )

    def test_denied_includes_operator_and_tool(self):
        assert tg.build_resolved_text("shell", "deny", "abc123") == (
            "🚫 **Denied** by **abc123**\nTool: `shell`"
        )

    def test_missing_operator_omits_the_by_clause(self):
        text = tg.build_resolved_text("shell", "approve")

        assert text == "✅ **Approved**\nTool: `shell`"

    def test_unknown_action_reports_expiry(self):
        assert tg.build_resolved_text("shell", "whatever") == (
            "⌛ **Expired**\nApproval for `shell` has expired."
        )


class TestParseInteractionEvent:
    def test_resolved_button_data_is_parsed(self):
        parsed = tg.parse_interaction_event(_click_event())

        assert parsed == {
            "action": "approve",
            "request_id": "rid-12345678",
            "tool_name": "shell",
            "severity": "medium",
            "session_ctx": {},
        }

    def test_top_level_button_data_is_accepted(self):
        parsed = tg.parse_interaction_event(
            {"button_data": _button_data(action="deny")},
        )

        assert parsed["action"] == "deny"

    def test_session_ctx_drops_guard_keys(self):
        parsed = tg.parse_interaction_event(
            {"button_data": _button_data(sid="s1", mt="group")},
        )

        assert parsed["session_ctx"] == {"sid": "s1", "mt": "group"}

    def test_missing_severity_defaults_to_medium(self):
        payload = json.loads(_button_data())
        del payload["sev"]
        parsed = tg.parse_interaction_event(
            {"button_data": json.dumps(payload)},
        )

        assert parsed["severity"] == "medium"

    @pytest.mark.parametrize(
        "event",
        [
            {},
            {"data": {}},
            {"data": {"resolved": {}}},
            {"data": {"resolved": {"button_data": ""}}, "button_data": ""},
            {"data": {"resolved": {"button_data": None}}},
        ],
    )
    def test_events_without_payload_are_ignored(self, event):
        assert tg.parse_interaction_event(event) is None

    @pytest.mark.parametrize("raw", ["not-json", "[1,2", '{"p":'])
    def test_malformed_payload_is_ignored(self, raw):
        assert tg.parse_interaction_event({"button_data": raw}) is None

    def test_foreign_button_prefix_is_ignored(self):
        foreign = json.dumps({"p": "other_", "a": "approve", "rid": "r"})

        assert tg.parse_interaction_event({"button_data": foreign}) is None

    @pytest.mark.parametrize("action", ["", "retry", "APPROVE"])
    def test_unknown_actions_are_ignored(self, action):
        raw = _button_data(action=action)

        assert tg.parse_interaction_event({"button_data": raw}) is None

    def test_non_string_payload_is_coerced(self):
        payload = json.loads(_button_data())
        payload["rid"] = 4242
        parsed = tg.parse_interaction_event(
            {"button_data": json.dumps(payload)},
        )

        assert parsed["request_id"] == "4242"


def test_card_cache_instance_isolation_and_original_fixed_bound():
    first, second = tg.CardCache(), tg.CardCache()
    assert first._mark_processed("rid-1", "approve") is False
    assert first._mark_processed("rid-1", "approve") is True
    assert first._processed_requests["rid-1"] == "approve"
    assert second._mark_processed("rid-1", "deny") is False
    for index in range(499):
        assert first._mark_processed(f"bounded-{index}", "approve") is False
    assert len(first._processed_requests) == 500
    assert first._mark_processed("overflow", "approve") is False
    assert len(first._processed_requests) == 251
    assert "rid-1" not in first._processed_requests
    assert first._processed_requests["overflow"] == "approve"
    assert second._processed_requests == {"rid-1": "deny"}
