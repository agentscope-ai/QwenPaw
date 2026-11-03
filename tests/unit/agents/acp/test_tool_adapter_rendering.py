# -*- coding: utf-8 -*-
"""Unit tests for :mod:`qwenpaw.agents.acp.tool_adapter`.

Every helper is a pure renderer: event dicts and suspended-permission
objects go in, ``ToolChunk`` text goes out.  The tests pin the exact
rendered wording because downstream agents match on those markers
(``[assistant]``, ``[tool_call]``, ``[permission_request]``, ``[error]``).
"""
# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from agentscope.message import ToolResultState

from qwenpaw.agents.acp import tool_adapter as ta


def _text(chunk) -> str:
    """Join every text block of a chunk into one string."""
    return "\n".join(block.text for block in chunk.content)


def _blocks_text(chunk) -> list[str]:
    return [block.text for block in chunk.content]


def _block_types(chunk) -> list[str]:
    return [block.type for block in chunk.content]


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


class TestResponseBuilders:
    def test_text_block_shape(self):
        block = ta._text_block("hi")

        assert block.type == "text"
        assert block.text == "hi"

    def test_response_blocks_defaults_to_last(self):
        chunk = ta.response_blocks([ta._text_block("a")])

        assert chunk.state == ToolResultState.SUCCESS
        assert chunk.is_last is True
        assert _blocks_text(chunk) == ["a"]
        assert _block_types(chunk) == ["text"]

    def test_response_blocks_honours_is_last(self):
        chunk = ta.response_blocks([ta._text_block("a")], is_last=False)

        assert chunk.is_last is False

    def test_response_text_wraps_single_block(self):
        chunk = ta.response_text("payload")

        assert _blocks_text(chunk) == ["payload"]
        assert chunk.state == ToolResultState.SUCCESS

    def test_response_text_streaming_flag(self):
        assert ta.response_text("x", is_last=False).is_last is False

    def test_header_text_layout(self):
        cwd = Path("/tmp/work")
        header = ta._header_text(
            runner_name="codex",
            execution_cwd=cwd,
        )

        # Build the expectation from the same Path so the separator
        # follows the platform (Windows renders "\tmp\work").
        assert header == f"runner: codex working directory: {cwd}"


class TestStringHelper:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("  padded  ", "padded"),
            ("", ""),
            (None, ""),
            (0, ""),
            (False, ""),
            (123, "123"),
            ("multi\nline", "multi\nline"),
        ],
    )
    def test_coercion_and_strip(self, value, expected):
        assert ta._string(value) == expected


# ---------------------------------------------------------------------------
# _option_parts
# ---------------------------------------------------------------------------


class TestOptionParts:
    @pytest.mark.parametrize(
        ("option", "expected"),
        [
            ({"optionId": "yes", "title": "Allow"}, ("Allow", "yes")),
            ({"option_id": "no", "title": "Deny"}, ("Deny", "no")),
            ({"id": "maybe", "name": "Ask"}, ("Ask", "maybe")),
            # optionId wins over option_id wins over id; a missing title
            # falls back to the resolved id.
            (
                {"optionId": "a", "option_id": "b", "id": "c"},
                ("a", "a"),
            ),
            # title wins over name.
            ({"optionId": "a", "title": "T", "name": "N"}, ("T", "a")),
        ],
    )
    def test_dict_options(self, option, expected):
        assert ta._option_parts(option) == expected

    def test_dict_option_without_id_falls_back_to_title(self):
        assert ta._option_parts({"title": "Only title"}) == (
            "Only title",
            "",
        )

    def test_dict_option_without_title_falls_back_to_id(self):
        assert ta._option_parts({"optionId": "only-id"}) == (
            "only-id",
            "only-id",
        )

    def test_dict_option_with_neither_yields_placeholder(self):
        assert ta._option_parts({}) == ("option", "")

    def test_object_options(self):
        option = SimpleNamespace(option_id="ok", title="Allow once")

        assert ta._option_parts(option) == ("Allow once", "ok")

    def test_object_option_id_aliases(self):
        assert ta._option_parts(
            SimpleNamespace(optionId="x", title="T"),
        ) == ("T", "x")
        assert ta._option_parts(SimpleNamespace(id="y", name="N")) == (
            "N",
            "y",
        )

    def test_object_option_without_anything(self):
        assert ta._option_parts(object()) == ("option", "")

    def test_blank_values_are_treated_as_missing(self):
        assert ta._option_parts({"optionId": "  ", "title": " "}) == (
            "option",
            "",
        )


# ---------------------------------------------------------------------------
# Event renderers
# ---------------------------------------------------------------------------


class TestRenderTextEvent:
    def test_plain_text(self):
        assert ta._render_text_event({"text": "hello"}) == (
            "[assistant]\nhello"
        )

    def test_text_is_stripped(self):
        assert ta._render_text_event({"text": "  hi  "}) == "[assistant]\nhi"

    @pytest.mark.parametrize("event", [{}, {"text": ""}, {"text": None}])
    def test_empty_text_renders_nothing(self, event):
        assert ta._render_text_event(event) is None


class TestRenderToolEvent:
    def test_kind_and_detail(self):
        assert (
            ta._render_tool_event(
                {"kind": "execute", "detail": "ls -la"},
            )
            == "[tool_call] execute (ls -la)"
        )

    def test_title_is_used_when_detail_missing(self):
        assert (
            ta._render_tool_event(
                {"kind": "read", "title": "file.txt"},
            )
            == "[tool_call] read (file.txt)"
        )

    def test_detail_wins_over_title(self):
        assert (
            ta._render_tool_event(
                {"kind": "read", "detail": "d", "title": "t"},
            )
            == "[tool_call] read (d)"
        )

    @pytest.mark.parametrize(
        "event",
        [
            {"detail": "only detail"},
            {"kind": "only kind"},
            {},
            {"kind": "", "detail": ""},
        ],
    )
    def test_requires_both_kind_and_detail(self, event):
        assert ta._render_tool_event(event) is None


class TestRenderStatusEvent:
    def test_run_finished_is_suppressed(self):
        assert ta._render_status_event({"status": "run_finished"}) is None

    def test_run_finished_suppressed_even_with_summary(self):
        assert (
            ta._render_status_event(
                {"status": "run_finished", "summary": "done"},
            )
            is None
        )

    def test_missing_status_becomes_unknown(self):
        assert ta._render_status_event({}) == "[status] unknown"

    def test_agent_thinking_uses_summary(self):
        assert (
            ta._render_status_event(
                {"status": "agent_thinking", "summary": "planning"},
            )
            == "planning"
        )

    def test_agent_thinking_fallback_without_summary(self):
        assert ta._render_status_event({"status": "agent_thinking"}) == (
            "agent thinking..."
        )

    def test_other_status_with_summary_is_two_lines(self):
        assert (
            ta._render_status_event(
                {"status": "queued", "summary": "waiting"},
            )
            == "[status] queued\nwaiting"
        )

    def test_other_status_without_summary(self):
        assert ta._render_status_event({"status": "queued"}) == (
            "[status] queued"
        )


class TestRenderPermissionEvent:
    def test_title_from_event(self):
        assert (
            ta._render_permission_event(
                {"title": "Allow shell?"},
            )
            == "[permission_request] Allow shell?"
        )

    def test_reason_is_used_when_title_missing(self):
        assert (
            ta._render_permission_event(
                {"reason": "needs access"},
            )
            == "[permission_request] needs access"
        )

    def test_default_title(self):
        assert ta._render_permission_event({}) == (
            "[permission_request] permission request"
        )

    def test_title_wins_over_reason(self):
        assert (
            ta._render_permission_event(
                {"title": "T", "reason": "R"},
            )
            == "[permission_request] T"
        )

    def test_options_are_rendered_with_ids(self):
        text = ta._render_permission_event(
            {
                "title": "Confirm",
                "options": [
                    {"optionId": "allow", "title": "Allow"},
                    {"optionId": "deny", "title": "Deny"},
                ],
            },
        )

        assert text == (
            "[permission_request] Confirm\n"
            "options: Allow (allow), Deny (deny)"
        )

    def test_option_without_id_renders_name_only(self):
        text = ta._render_permission_event(
            {"title": "Confirm", "options": [{"title": "Allow"}]},
        )

        assert text == "[permission_request] Confirm\noptions: Allow"

    def test_empty_option_list_omits_options_line(self):
        text = ta._render_permission_event({"title": "Confirm", "options": []})

        assert "options:" not in text

    def test_unusable_options_are_dropped(self):
        text = ta._render_permission_event(
            {"title": "Confirm", "options": [{"title": "Keep"}]},
        )

        assert text.endswith("options: Keep")


class TestRenderErrorEvent:
    def test_message(self):
        assert ta._render_error_event({"message": "boom"}) == "[error] boom"

    def test_default_message(self):
        assert ta._render_error_event({}) == "[error] Unknown error"

    @pytest.mark.parametrize("message", [None, ""])
    def test_falsy_message_uses_default(self, message):
        assert ta._render_error_event({"message": message}) == (
            "[error] Unknown error"
        )

    def test_whitespace_only_message_renders_nothing(self):
        """A blank-but-truthy message strips to empty and is dropped."""
        assert ta._render_error_event({"message": "   "}) is None


class TestRenderEventText:
    def test_text_event(self):
        assert ta.render_event_text({"type": "text", "text": "hi"}) == (
            "[assistant]\nhi"
        )

    @pytest.mark.parametrize(
        "event_type",
        ["tool_call", "tool_result", "tool_output", "TOOL_CALL"],
    )
    def test_tool_prefixed_events(self, event_type):
        assert (
            ta.render_event_text(
                {"type": event_type, "kind": "execute", "detail": "ls"},
            )
            == "[tool_call] execute (ls)"
        )

    def test_status_event(self):
        assert (
            ta.render_event_text(
                {"type": "status", "status": "queued", "summary": "s"},
            )
            == "[status] queued\ns"
        )

    def test_permission_request_event(self):
        assert (
            ta.render_event_text(
                {"type": "permission_request", "title": "T"},
            )
            == "[permission_request] T"
        )

    def test_error_event(self):
        assert ta.render_event_text({"type": "error", "message": "m"}) == (
            "[error] m"
        )

    def test_type_is_case_insensitive(self):
        assert ta.render_event_text({"type": "TEXT", "text": "hi"}) == (
            "[assistant]\nhi"
        )

    def test_type_is_stripped(self):
        assert ta.render_event_text({"type": "  text ", "text": "hi"}) == (
            "[assistant]\nhi"
        )

    @pytest.mark.parametrize(
        "event_type",
        ["", None, "unknown", "message", "tool", "statusx"],
    )
    def test_unknown_types_render_nothing(self, event_type):
        assert ta.render_event_text({"type": event_type}) is None

    def test_known_type_with_empty_payload_renders_nothing(self):
        assert ta.render_event_text({"type": "text"}) is None


# ---------------------------------------------------------------------------
# format_stream_snapshot_response
# ---------------------------------------------------------------------------


class TestFormatStreamSnapshotResponse:
    def test_items_become_separate_blocks(self):
        chunk = ta.format_stream_snapshot_response(
            ["first", "second"],
            runner_name="codex",
            execution_cwd=Path("/tmp"),
        )

        assert chunk is not None
        assert _blocks_text(chunk) == ["first", "second"]
        # A snapshot is never terminal.
        assert chunk.is_last is False

    def test_blank_items_are_dropped(self):
        chunk = ta.format_stream_snapshot_response(
            ["", "   ", None, "kept"],
            runner_name="codex",
            execution_cwd=Path("/tmp"),
        )

        assert _blocks_text(chunk) == ["kept"]

    def test_items_are_stripped(self):
        chunk = ta.format_stream_snapshot_response(
            ["  padded  "],
            runner_name="codex",
            execution_cwd=Path("/tmp"),
        )

        assert _blocks_text(chunk) == ["padded"]

    def test_empty_snapshot_returns_none(self):
        assert (
            ta.format_stream_snapshot_response(
                [],
                runner_name="codex",
                execution_cwd=Path("/tmp"),
            )
            is None
        )

    def test_all_blank_snapshot_returns_none(self):
        assert (
            ta.format_stream_snapshot_response(
                ["", "  ", None],
                runner_name="codex",
                execution_cwd=Path("/tmp"),
            )
            is None
        )

    def test_arguments_are_ignored(self):
        """Header injection is deliberately disabled for snapshots."""
        with_header = ta.format_stream_snapshot_response(
            ["body"],
            runner_name="codex",
            execution_cwd=Path("/work"),
            include_header=True,
        )
        without_header = ta.format_stream_snapshot_response(
            ["body"],
            runner_name="other",
            execution_cwd=Path("/elsewhere"),
            include_header=False,
        )

        assert (
            _blocks_text(with_header)
            == _blocks_text(without_header)
            == [
                "body",
            ]
        )


# ---------------------------------------------------------------------------
# format_final_assistant_response
# ---------------------------------------------------------------------------


class TestFormatFinalAssistantResponse:
    def test_final_event_text_is_used_as_body(self):
        cwd = Path("/work")
        chunk = ta.format_final_assistant_response(
            runner_name="codex",
            execution_cwd=cwd,
            final_event={"type": "text", "text": "final answer"},
        )

        # The body is the full rendered event text, marker included.
        assert _blocks_text(chunk) == [
            f"runner: codex working directory: {cwd}",
            "[assistant]\nfinal answer",
        ]
        assert chunk.is_last is True
        assert chunk.state == ToolResultState.SUCCESS

    def test_missing_final_event_says_no_text_output(self):
        chunk = ta.format_final_assistant_response(
            runner_name="codex",
            execution_cwd=Path("/work"),
            final_event=None,
        )

        assert _blocks_text(chunk)[1] == "completed without text output"

    def test_unrenderable_final_event_falls_back_to_completed(self):
        chunk = ta.format_final_assistant_response(
            runner_name="codex",
            execution_cwd=Path("/work"),
            final_event={"type": "unknown"},
        )

        assert _blocks_text(chunk)[1] == "completed"

    def test_suppressed_status_event_falls_back_to_completed(self):
        chunk = ta.format_final_assistant_response(
            runner_name="codex",
            execution_cwd=Path("/work"),
            final_event={"type": "status", "status": "run_finished"},
        )

        assert _blocks_text(chunk)[1] == "completed"

    def test_empty_dict_event_falls_back_to_completed(self):
        chunk = ta.format_final_assistant_response(
            runner_name="codex",
            execution_cwd=Path("/work"),
            final_event={},
        )

        assert _blocks_text(chunk)[1] == "completed"

    def test_error_event_body(self):
        chunk = ta.format_final_assistant_response(
            runner_name="codex",
            execution_cwd=Path("/work"),
            final_event={"type": "error", "message": "failed"},
        )

        assert _blocks_text(chunk)[1] == "[error] failed"

    def test_header_reflects_arguments(self):
        cwd = Path("/home/user/project")
        chunk = ta.format_final_assistant_response(
            runner_name="claude-code",
            execution_cwd=cwd,
            final_event=None,
        )

        assert _blocks_text(chunk)[0] == (
            f"runner: claude-code working directory: {cwd}"
        )


# ---------------------------------------------------------------------------
# format_permission_suspended_response
# ---------------------------------------------------------------------------


def _permission(**overrides):
    base = {
        "agent": "codex",
        "tool_name": "shell",
        "tool_kind": "execute",
        "options": [{"optionId": "allow", "title": "Allow"}],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestFormatPermissionSuspendedResponse:
    def test_mandatory_details(self):
        text = _text(
            ta.format_permission_suspended_response(
                suspended_permission=_permission(),
            ),
        )

        assert "- Agent: `codex`" in text
        assert "- Tool: `shell` (kind: `execute`)" in text

    def test_intro_and_reply_hint_are_present(self):
        text = _text(
            ta.format_permission_suspended_response(
                suspended_permission=_permission(),
            ),
        )

        assert "External Agent Permission Request" in text
        assert "Do not make permission decisions" in text
        assert 'delegate_external_agent(action="respond"' in text

    def test_options_section(self):
        text = _text(
            ta.format_permission_suspended_response(
                suspended_permission=_permission(
                    options=[
                        {"optionId": "allow", "title": "Allow"},
                        {"optionId": "deny", "title": "Deny"},
                    ],
                ),
            ),
        )

        assert "Options:" in text
        assert "  - **Allow** (`allow`)" in text
        assert "  - **Deny** (`deny`)" in text

    def test_option_without_id_renders_bold_only(self):
        text = _text(
            ta.format_permission_suspended_response(
                suspended_permission=_permission(
                    options=[{"title": "Allow"}],
                ),
            ),
        )

        assert "  - **Allow**" in text
        assert "(``)" not in text

    def test_no_options_omits_section(self):
        text = _text(
            ta.format_permission_suspended_response(
                suspended_permission=_permission(options=[]),
            ),
        )

        assert "Options:" not in text

    def test_paths_are_listed(self):
        text = _text(
            ta.format_permission_suspended_response(
                suspended_permission=_permission(
                    paths=["/etc/passwd", "/tmp/x"],
                ),
            ),
        )

        assert "- Files:" in text
        assert "  - `/etc/passwd`" in text
        assert "  - `/tmp/x`" in text

    def test_target_used_when_no_paths(self):
        text = _text(
            ta.format_permission_suspended_response(
                suspended_permission=_permission(target="https://x.dev"),
            ),
        )

        assert "- Target: `https://x.dev`" in text
        assert "- Files:" not in text

    def test_paths_win_over_target(self):
        text = _text(
            ta.format_permission_suspended_response(
                suspended_permission=_permission(
                    paths=["/a"],
                    target="https://x.dev",
                ),
            ),
        )

        assert "  - `/a`" in text
        assert "- Target:" not in text

    def test_empty_paths_fall_back_to_target(self):
        text = _text(
            ta.format_permission_suspended_response(
                suspended_permission=_permission(paths=[], target="t1"),
            ),
        )

        assert "- Target: `t1`" in text

    def test_action_command_summary_lines(self):
        text = _text(
            ta.format_permission_suspended_response(
                suspended_permission=_permission(
                    action="write",
                    command="rm -rf /tmp/x",
                    summary="wants to delete",
                ),
            ),
        )

        assert "- Action: `write`" in text
        assert "- Command: `rm -rf /tmp/x`" in text
        assert "- Summary: wants to delete" in text

    def test_optional_fields_absent_are_omitted(self):
        text = _text(
            ta.format_permission_suspended_response(
                suspended_permission=_permission(),
            ),
        )

        assert "- Action:" not in text
        assert "- Command:" not in text
        assert "- Summary:" not in text

    def test_missing_attributes_use_defaults(self):
        text = _text(
            ta.format_permission_suspended_response(
                suspended_permission=object(),
            ),
        )

        assert "- Agent: `unknown`" in text
        assert "- Tool: `external-agent` (kind: `other`)" in text

    def test_none_paths_and_options_are_safe(self):
        text = _text(
            ta.format_permission_suspended_response(
                suspended_permission=_permission(paths=None, options=None),
            ),
        )

        assert "Options:" not in text
        assert "- Agent: `codex`" in text

    def test_result_is_single_final_block(self):
        chunk = ta.format_permission_suspended_response(
            suspended_permission=_permission(),
        )

        assert len(chunk.content) == 1
        assert chunk.is_last is True
        assert chunk.state == ToolResultState.SUCCESS


# ---------------------------------------------------------------------------
# format_close_response
# ---------------------------------------------------------------------------


class TestFormatCloseResponse:
    def test_closed_session(self):
        text = _text(
            ta.format_close_response(runner_name="codex", closed=True),
        )

        assert text == "Closed the bound ACP session for runner 'codex'."

    def test_no_bound_session(self):
        text = _text(
            ta.format_close_response(runner_name="codex", closed=False),
        )

        assert text == (
            "No bound ACP session found for runner 'codex' "
            "in the current chat."
        )

    def test_runner_name_is_interpolated(self):
        text = _text(
            ta.format_close_response(runner_name="claude-code", closed=True),
        )

        assert "'claude-code'" in text
