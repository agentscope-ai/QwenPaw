# -*- coding: utf-8 -*-
"""Pure Feishu approval card builders retained on the actual artifact.

Host dispatch/operator/ACL integration is exercised in Feishu worker tests.
"""
# pylint: disable=protected-access
import json
import pytest
from tests.fixtures.channel_plugins.c6_artifacts import artifact_module

tg = artifact_module("feishu", "card_templates")


def _card(raw: str) -> dict:
    return json.loads(raw)


def _markdown_blocks(card: dict) -> list[str]:
    return [
        element["content"]
        for element in card["elements"]
        if element.get("tag") == "markdown"
    ]


def _action_buttons(card: dict) -> list[dict]:
    for element in card["elements"]:
        if element.get("tag") == "action":
            return element["actions"]
    raise AssertionError("no action element in card")


class TestTruncate:
    @pytest.mark.parametrize("text", ["", None])
    def test_empty(self, text):
        assert tg._truncate(text, 10) == ""

    def test_short_text_untouched(self):
        assert tg._truncate("abc", 10) == "abc"

    def test_exact_limit_untouched(self):
        assert tg._truncate("abcdef", 6) == "abcdef"

    def test_long_text_is_cut_with_ellipsis(self):
        assert tg._truncate("abcdefghij", 6) == "abcde…"
        assert len(tg._truncate("abcdefghij", 6)) == 6

    def test_unicode_preserved(self):
        assert tg._truncate("泰哥你好世界", 4) == "泰哥你…"


class TestSeverityTemplate:
    @pytest.mark.parametrize(
        ("severity", "expected"),
        [
            ("critical", "red"),
            ("high", "red"),
            ("medium", "orange"),
            ("low", "yellow"),
            ("HIGH", "red"),
            (" Low ", "orange"),  # not stripped -> unknown -> default
            ("weird", "orange"),
            ("", "orange"),
            (None, "orange"),
        ],
    )
    def test_mapping(self, severity, expected):
        assert tg._tool_guard_severity_template(severity) == expected


class TestBuildApprovalCard:
    def test_returns_json_with_header_template(self):
        card = _card(
            tg.build_tool_guard_approval_card(
                request_id="r1",
                tool_name="shell",
                severity="high",
                body_text="danger",
            ),
        )

        assert card["header"]["template"] == "red"
        assert card["header"]["title"]["content"] == (
            "🛡️ Tool Approval Required"
        )
        assert card["config"] == {"wide_screen_mode": True}

    def test_body_is_rendered_as_first_markdown_block(self):
        card = _card(
            tg.build_tool_guard_approval_card(
                request_id="r1",
                tool_name="shell",
                severity="low",
                body_text="the request body",
            ),
        )

        assert _markdown_blocks(card)[0] == "the request body"

    def test_help_hint_links_to_callback_docs(self):
        card = _card(
            tg.build_tool_guard_approval_card(
                request_id="r1",
                tool_name="shell",
                severity="low",
                body_text="x",
            ),
        )

        hint = _markdown_blocks(card)[1]
        assert "Buttons not working?" in hint
        assert tg._FEISHU_CALLBACK_CONFIG_DOC_URL in hint

    def test_two_buttons_carry_round_trip_values(self):
        card = _card(
            tg.build_tool_guard_approval_card(
                request_id="req-42",
                tool_name="shell",
                severity="medium",
                body_text="payload body",
                session_ctx={"session_id": "s1"},
            ),
        )

        approve, deny = _action_buttons(card)
        assert approve["text"]["content"] == "✅ Approve"
        assert approve["type"] == "primary"
        assert deny["text"]["content"] == "❌ Deny"
        assert deny["type"] == "danger"

        for button, action in ((approve, "approve"), (deny, "deny")):
            assert button["value"] == {
                "type": "tool_guard_approval",
                "action": action,
                "request_id": "req-42",
                "tool_name": "shell",
                "severity": "medium",
                "body": "payload body",
                "session_ctx": {"session_id": "s1"},
            }

    def test_body_snapshot_is_truncated_separately_from_markdown(self):
        long_body = "x" * 2000
        card = _card(
            tg.build_tool_guard_approval_card(
                request_id="r1",
                tool_name="shell",
                severity="low",
                body_text=long_body,
            ),
        )

        # The visible markdown keeps 1800 chars; the button value 1500.
        assert len(_markdown_blocks(card)[0]) == 1800
        assert len(_action_buttons(card)[0]["value"]["body"]) == 1500

    def test_missing_severity_defaults_to_medium_in_value(self):
        card = _card(
            tg.build_tool_guard_approval_card(
                request_id="r1",
                tool_name="shell",
                severity="",
                body_text="x",
            ),
        )

        assert _action_buttons(card)[0]["value"]["severity"] == "medium"
        # The header still falls back to the default template.
        assert card["header"]["template"] == "orange"

    def test_none_session_ctx_becomes_empty_dict(self):
        card = _card(
            tg.build_tool_guard_approval_card(
                request_id="r1",
                tool_name="shell",
                severity="low",
                body_text="x",
                session_ctx=None,
            ),
        )

        assert _action_buttons(card)[0]["value"]["session_ctx"] == {}

    def test_session_ctx_is_copied_not_aliased(self):
        original = {"session_id": "s1"}
        tg.build_tool_guard_approval_card(
            request_id="r1",
            tool_name="shell",
            severity="low",
            body_text="x",
            session_ctx=original,
        )

        original["session_id"] = "mutated"

        assert original == {"session_id": "mutated"}

    def test_empty_body_text(self):
        card = _card(
            tg.build_tool_guard_approval_card(
                request_id="r1",
                tool_name="shell",
                severity="low",
                body_text="",
            ),
        )

        assert _markdown_blocks(card)[0] == ""

    def test_unicode_is_not_escaped(self):
        raw = tg.build_tool_guard_approval_card(
            request_id="r1",
            tool_name="shell",
            severity="low",
            body_text="泰哥批准",
        )

        assert "泰哥批准" in raw


class TestBuildResolvedCard:
    @pytest.mark.parametrize(
        ("action", "title", "template", "verb"),
        [
            ("approve", "✅ Approved", "green", "approved"),
            ("deny", "🚫 Denied", "red", "denied"),
            ("anything", "⌛ Expired", "grey", "expired"),
            ("", "⌛ Expired", "grey", "expired"),
        ],
    )
    def test_status_variants(self, action, title, template, verb):
        card = _card(
            tg.build_tool_guard_resolved_card(
                tool_name="shell",
                action=action,
            ),
        )

        assert card["header"]["title"]["content"] == title
        assert card["header"]["template"] == template
        blocks = _markdown_blocks(card)
        assert len(blocks) == 1  # no body -> status line only
        assert "shell" in blocks[0]
        assert verb in blocks[0]

    def test_expired_ignores_operator(self):
        card = _card(
            tg.build_tool_guard_resolved_card(
                tool_name="shell",
                action="expired",
                operator_display="alice",
            ),
        )

        assert "alice" not in _markdown_blocks(card)[0]

    def test_operator_is_appended_for_approve(self):
        card = _card(
            tg.build_tool_guard_resolved_card(
                tool_name="shell",
                action="approve",
                operator_display="alice",
            ),
        )

        assert "Tool `shell` approved by `alice`." in _markdown_blocks(card)[0]

    def test_operator_is_appended_for_deny(self):
        card = _card(
            tg.build_tool_guard_resolved_card(
                tool_name="shell",
                action="deny",
                operator_display="bob",
            ),
        )

        assert "denied by `bob`" in _markdown_blocks(card)[0]

    def test_body_text_prepends_a_markdown_block_and_rule(self):
        card = _card(
            tg.build_tool_guard_resolved_card(
                tool_name="shell",
                action="approve",
                body_text="original body",
            ),
        )

        tags = [element["tag"] for element in card["elements"]]
        assert tags == ["markdown", "hr", "markdown"]
        assert _markdown_blocks(card)[0] == "original body"

    def test_body_text_is_truncated(self):
        card = _card(
            tg.build_tool_guard_resolved_card(
                tool_name="shell",
                action="approve",
                body_text="y" * 2500,
            ),
        )

        assert len(_markdown_blocks(card)[0]) == 1800


class TestBuildToast:
    def test_approve(self):
        assert tg.build_tool_guard_toast("approve", "shell") == {
            "type": "success",
            "content": "Approved tool shell",
        }

    def test_deny(self):
        assert tg.build_tool_guard_toast("deny", "shell") == {
            "type": "info",
            "content": "Denied tool shell",
        }

    @pytest.mark.parametrize("action", ["expired", "", "unknown"])
    def test_other_actions(self, action):
        assert tg.build_tool_guard_toast(action, "shell") == {
            "type": "warning",
            "content": "Approval request has expired",
        }


def _value(**overrides) -> dict:
    data = {
        "type": "tool_guard_approval",
        "action": "approve",
        "request_id": "req-1",
        "tool_name": "shell",
        "severity": "high",
        "body": "b",
        "session_ctx": {"session_id": "s1"},
    }
    data.update(overrides)
    return data


class TestParseActionValue:
    def test_full_payload(self):
        assert tg.parse_tool_guard_action_value(_value()) == {
            "action": "approve",
            "request_id": "req-1",
            "tool_name": "shell",
            "severity": "high",
            "body": "b",
            "session_ctx": {"session_id": "s1"},
        }

    @pytest.mark.parametrize("bad", [None, "string", 42, ["list"]])
    def test_non_dict_is_rejected(self, bad):
        assert tg.parse_tool_guard_action_value(bad) is None

    def test_wrong_action_type_is_rejected(self):
        assert tg.parse_tool_guard_action_value(_value(type="other")) is None

    def test_missing_action_type_is_rejected(self):
        value = _value()
        del value["type"]

        assert tg.parse_tool_guard_action_value(value) is None

    @pytest.mark.parametrize(
        "action",
        ["approve", "deny", " APPROVE ", "Deny"],
    )
    def test_action_is_normalised(self, action):
        assert tg.parse_tool_guard_action_value(_value(action=action))[
            "action"
        ] == (action.strip().lower())

    @pytest.mark.parametrize("action", ["", None, "maybe", "approve_all"])
    def test_unknown_action_is_rejected(self, action):
        assert tg.parse_tool_guard_action_value(_value(action=action)) is None

    @pytest.mark.parametrize("request_id", ["", None, "   "])
    def test_blank_request_id_is_rejected(self, request_id):
        assert (
            tg.parse_tool_guard_action_value(_value(request_id=request_id))
            is None
        )

    def test_request_id_is_stripped(self):
        assert (
            tg.parse_tool_guard_action_value(_value(request_id="  r1 "))[
                "request_id"
            ]
            == "r1"
        )

    def test_optional_fields_default(self):
        parsed = tg.parse_tool_guard_action_value(
            {
                "type": "tool_guard_approval",
                "action": "deny",
                "request_id": "r1",
            },
        )

        assert parsed == {
            "action": "deny",
            "request_id": "r1",
            "tool_name": "",
            "severity": "medium",
            "body": "",
            "session_ctx": {},
        }

    @pytest.mark.parametrize("ctx", [None, "string", 42, ["list"]])
    def test_non_dict_session_ctx_becomes_empty_dict(self, ctx):
        assert (
            tg.parse_tool_guard_action_value(_value(session_ctx=ctx))[
                "session_ctx"
            ]
            == {}
        )

    def test_round_trip_from_built_card(self):
        raw = tg.build_tool_guard_approval_card(
            request_id="rt-1",
            tool_name="python",
            severity="critical",
            body_text="round trip",
            session_ctx={"session_id": "sw-1"},
        )
        approve_value = _action_buttons(_card(raw))[0]["value"]

        assert tg.parse_tool_guard_action_value(approve_value) == {
            "action": "approve",
            "request_id": "rt-1",
            "tool_name": "python",
            "severity": "critical",
            "body": "round trip",
            "session_ctx": {"session_id": "sw-1"},
        }
