# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""ACP tool-call argument parsing, driven by the kimi-cli runner (#7727).

Every payload below was produced by executing kimi-cli **v1.50.0**'s own
conversion functions -- ``kimi_cli.utils.diff.build_diff_blocks``,
``kimi_cli.acp.convert.display_block_to_acp_content``,
``kimi_cli.tools.extract_key_argument`` -- and by reading the source that
assembles each message, then transcribing the result as a literal so this
suite does not need kimi-cli installed.  Provenance is cited per fixture.

The wire facts that shape the implementation:

* kimi-cli sends **only** ``toolCallId`` / ``title`` / ``content``.  It never
  populates ``kind``, ``locations`` or ``rawInput``
  (``kimi_cli/acp/session.py:387-398`` for ``ToolCallStart``,
  ``:526-531`` for the ``request_permission`` ``ToolCallUpdate``).
* The tool **arguments** are serialised as a JSON string inside a
  ``type == "content"`` text block on the ``ToolCallStart``
  (``session.py:390-397``), and are *not* repeated at permission time.
* At permission time the path survives only when the write produced a diff
  block (``convert.py:53-64``).  ``build_diff_blocks`` returns ``[]`` when
  ``old_text == new_text`` (``utils/diff.py:130-135``), and kimi's
  ``ShellDisplayBlock`` is never converted at all -- it is not referenced
  anywhere in ``kimi_cli/acp/`` -- so a Shell approval carries only the prose
  fallback built at ``session.py:496-505``.

Because ACP's ``session/request_permission`` delivers a ``ToolCallUpdate``
whose only required field is ``toolCallId``, recovering the arguments
requires both halves of this change: parsing arguments out of content text
blocks, and consulting the accumulated ``ToolCallStart`` state for the same
id before deciding.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from acp.schema import ToolCallStart, ToolCallUpdate

from qwenpaw.agents.acp.client import ACPHostedClient
from qwenpaw.agents.acp.permissions import ACPPermissionAdapter
from qwenpaw.config.config import ACPAgentConfig

WORKSPACE = "/tmp/kimi_oob_ws_XvWO"
OOB_TARGET = "/tmp/kimi_oob_probe_7727.txt"
WRITE_CALL_ID = "turn1/tc_write"
SHELL_CALL_ID = "turn1/tc_shell"


def _text_content(text: str) -> dict[str, Any]:
    """A ``type == "content"`` block wrapping a text block (kimi's shape)."""
    return {"type": "content", "content": {"type": "text", "text": text}}


def _diff_content(path: str, old: str, new: str) -> dict[str, Any]:
    return {"type": "diff", "path": path, "oldText": old, "newText": new}


# --- kimi-cli WriteFile -----------------------------------------------------
# `session.py:387-398`: title from `extract_key_argument`, args JSON as text.
KIMI_WRITE_START = {
    "sessionUpdate": "tool_call",
    "toolCallId": WRITE_CALL_ID,
    "title": f"WriteFile: {OOB_TARGET}",
    "status": "in_progress",
    "content": [
        _text_content(
            '{"path": "%s", "content": "probe", "mode": "overwrite"}'
            % OOB_TARGET,
        ),
    ],
}

# `session.py:526-531` + `convert.py:53-64`, write whose content differs from
# what is on disk, so build_diff_blocks produced one DiffDisplayBlock.
KIMI_WRITE_PERM = {
    "toolCallId": WRITE_CALL_ID,
    "title": f"WriteFile: {OOB_TARGET}",
    "content": [_diff_content(OOB_TARGET, "", "probe")],
}

# Same, but `utils/diff.py:130-135` returned [] (old_text == new_text, e.g.
# writing an empty file), so `session.py:496-505` emitted the prose fallback
# with the description from `tools/file/write.py:148`.
KIMI_WRITE_PERM_NO_DIFF = {
    "toolCallId": WRITE_CALL_ID,
    "title": f"WriteFile: {OOB_TARGET}",
    "content": [
        _text_content(
            "Requesting approval to perform: " f"Write file `{OOB_TARGET}`",
        ),
    ],
}

# --- kimi-cli Shell ---------------------------------------------------------
# `tools/shell/__init__.py:92-99` passes a ShellDisplayBlock, which
# `convert.py:53-64` does not handle, so the approval content is the prose
# fallback with the description "Run command `<command>`".
KIMI_SHELL_RM_START = {
    "sessionUpdate": "tool_call",
    "toolCallId": SHELL_CALL_ID,
    "title": "Shell: rm -rf / --no-preserve-root",
    "status": "in_progress",
    "content": [
        _text_content(
            '{"command": "rm -rf / --no-preserve-root", '
            '"run_in_background": false}',
        ),
    ],
}

KIMI_SHELL_RM_PERM: dict[str, Any] = {
    "toolCallId": SHELL_CALL_ID,
    "title": "Shell: rm -rf / --no-preserve-root",
    "content": [
        _text_content(
            "Requesting approval to perform: "
            "Run command `rm -rf / --no-preserve-root`",
        ),
    ],
}

KIMI_SHELL_REDIRECT_START = {
    "sessionUpdate": "tool_call",
    "toolCallId": SHELL_CALL_ID,
    "title": f"Shell: echo probe > {OOB_TARGET}",
    "status": "in_progress",
    "content": [
        _text_content(
            '{"command": "echo probe > %s", "run_in_background": false}'
            % OOB_TARGET,
        ),
    ],
}

KIMI_SHELL_REDIRECT_PERM = {
    "toolCallId": SHELL_CALL_ID,
    "title": f"Shell: echo probe > {OOB_TARGET}",
    "content": [
        _text_content(
            "Requesting approval to perform: "
            f"Run command `echo probe > {OOB_TARGET}`",
        ),
    ],
}

_ALLOW_OPTIONS = [
    {"optionId": "approve", "name": "Approve once", "kind": "allow_once"},
    {"optionId": "reject", "name": "Reject", "kind": "reject_once"},
]


def _adapter(trusted: bool = True) -> ACPPermissionAdapter:
    return ACPPermissionAdapter(cwd=WORKSPACE, trusted=trusted)


def _client(trusted: bool = True) -> ACPHostedClient:
    return ACPHostedClient(
        agent_name="kimi-cli",
        agent_config=ACPAgentConfig(
            enabled=True,
            command="kimi-cli",
            args=["acp"],
            trusted=trusted,
        ),
        cwd=WORKSPACE,
    )


async def _noop_message_handler(_payload: dict, _is_last: bool) -> None:
    return None


async def _decide(
    trusted: bool,
    start: dict[str, Any] | None,
    permission: dict[str, Any],
) -> str:
    """Run one delegated turn and return the permission outcome.

    ``start`` is fed through ``session_update`` first, exactly as a real
    runner would send it, so the accumulator holds the arguments by the time
    the permission request arrives.
    """
    client = _client(trusted=trusted)
    client.start_prompt(_noop_message_handler)
    if start is not None:
        await client.session_update("s1", ToolCallStart.model_validate(start))
    response = await asyncio.wait_for(
        client.request_permission(
            options=list(_ALLOW_OPTIONS),
            session_id="s1",
            tool_call=ToolCallUpdate.model_validate(permission),
        ),
        timeout=3.0,
    )
    return str(response.outcome)


class TestKimiWireFormatAssumptions:
    """Pin the kimi-cli payload shape the parsing is built on.

    If a future kimi-cli starts populating kind/locations/rawInput these
    assertions break loudly, which is the signal to re-derive the fixtures
    rather than keep trusting them.
    """

    @pytest.mark.parametrize(
        "payload",
        [
            KIMI_WRITE_PERM,
            KIMI_WRITE_PERM_NO_DIFF,
            KIMI_SHELL_RM_PERM,
            KIMI_SHELL_REDIRECT_PERM,
        ],
    )
    def test_permission_payload_has_no_structured_fields(
        self,
        payload: dict[str, Any],
    ) -> None:
        assert sorted(payload) == ["content", "title", "toolCallId"]

    def test_start_payload_has_no_kind_locations_or_raw_input(self) -> None:
        for start in (KIMI_WRITE_START, KIMI_SHELL_RM_START):
            assert "kind" not in start
            assert "locations" not in start
            assert "rawInput" not in start

    def test_shell_approval_carries_prose_not_arguments(self) -> None:
        """ShellDisplayBlock is never converted, so only prose arrives."""
        text = KIMI_SHELL_RM_PERM["content"][0]["content"]["text"]
        assert text.startswith("Requesting approval to perform:")
        assert not text.startswith("{")


class TestArgumentsParsedFromContentTextBlocks:
    """The parsing itself: arguments embedded as JSON in a text block."""

    def test_write_arguments_yield_the_path(self) -> None:
        adapter = _adapter()
        assert adapter._paths(KIMI_WRITE_START) == [OOB_TARGET]

    def test_shell_arguments_yield_the_command(self) -> None:
        adapter = _adapter()
        assert adapter._command(KIMI_SHELL_RM_START) == (
            "rm -rf / --no-preserve-root"
        )

    def test_prose_content_is_not_parsed_as_arguments(self) -> None:
        adapter = _adapter()
        assert not adapter._paths(KIMI_SHELL_RM_PERM)
        assert adapter._command(KIMI_SHELL_RM_PERM) is None

    def test_malformed_json_content_is_ignored(self) -> None:
        adapter = _adapter()
        broken = {
            "toolCallId": "turn1/tc_broken",
            "title": "WriteFile: /tmp/x",
            "content": [_text_content('{"path": "/tmp/x", ')],
        }
        assert not adapter._paths(broken)
        assert adapter.is_hard_blocked(broken) is False

    def test_json_array_content_is_ignored(self) -> None:
        adapter = _adapter()
        array = {
            "toolCallId": "turn1/tc_array",
            "title": "WriteFile",
            "content": [_text_content('["/etc/passwd"]')],
        }
        assert not adapter._paths(array)

    @pytest.mark.parametrize(
        "key",
        ["path", "file_path", "filePath", "abs_path", "notebook_path"],
    )
    def test_path_argument_key_variants_in_raw_input(self, key: str) -> None:
        """claude-agent-acp sends `file_path`; other runners vary."""
        adapter = _adapter()
        call = {
            "toolCallId": "turn1/tc_key",
            "title": "Write",
            "kind": "edit",
            "rawInput": {key: OOB_TARGET},
        }
        assert adapter._paths(call) == [OOB_TARGET]
        assert adapter.is_hard_blocked(call) is True

    def test_list_valued_path_argument(self) -> None:
        adapter = _adapter()
        call = {
            "toolCallId": "turn1/tc_list",
            "title": "Write",
            "rawInput": {"path": [f"{WORKSPACE}/a.txt", OOB_TARGET]},
        }
        assert adapter._paths(call) == [f"{WORKSPACE}/a.txt", OOB_TARGET]
        assert adapter.is_hard_blocked(call) is True

    def test_argv_argument_joined_into_command(self) -> None:
        adapter = _adapter()
        call = {
            "toolCallId": "turn1/tc_argv",
            "title": "Execute",
            "content": [_text_content('{"argv": ["rm", "-rf", "/"]}')],
        }
        assert adapter._command(call) == "rm -rf /"
        assert adapter.is_hard_blocked(call) is True


class TestKimiOutOfWorkspaceWriteIsBlocked:
    """End to end, through the real client and both trust settings."""

    async def test_write_with_diff_block_is_blocked(self) -> None:
        outcome = await _decide(True, KIMI_WRITE_START, KIMI_WRITE_PERM)
        assert "cancelled" in outcome

    async def test_write_with_diff_block_is_blocked_untrusted(self) -> None:
        outcome = await _decide(False, KIMI_WRITE_START, KIMI_WRITE_PERM)
        assert "cancelled" in outcome

    async def test_write_without_diff_block_is_blocked(self) -> None:
        """The arguments come from the accumulated ToolCallStart."""
        outcome = await _decide(
            True,
            KIMI_WRITE_START,
            KIMI_WRITE_PERM_NO_DIFF,
        )
        assert "cancelled" in outcome

    async def test_write_without_diff_block_is_blocked_untrusted(self) -> None:
        outcome = await _decide(
            False,
            KIMI_WRITE_START,
            KIMI_WRITE_PERM_NO_DIFF,
        )
        assert "cancelled" in outcome

    async def test_in_workspace_write_is_still_allowed(self) -> None:
        inside = f"{WORKSPACE}/notes.md"
        start = {
            "sessionUpdate": "tool_call",
            "toolCallId": WRITE_CALL_ID,
            "title": f"WriteFile: {inside}",
            "status": "in_progress",
            "content": [
                _text_content(
                    '{"path": "%s", "content": "hi", "mode": "overwrite"}'
                    % inside,
                ),
            ],
        }
        permission = {
            "toolCallId": WRITE_CALL_ID,
            "title": f"WriteFile: {inside}",
            "content": [_diff_content(inside, "", "hi")],
        }
        outcome = await _decide(True, start, permission)
        assert "selected" in outcome


class TestKimiShellIsBlocked:
    """Destructive shell commands reach the guard once arguments are parsed."""

    def test_permission_delta_alone_carries_no_command(self) -> None:
        """Why the accumulated state is needed, not just the parsing."""
        assert _adapter()._command(KIMI_SHELL_RM_PERM) is None

    def test_merged_state_recovers_the_command(self) -> None:
        adapter = _adapter()
        merged = adapter._merged_payload(
            KIMI_SHELL_RM_PERM,
            KIMI_SHELL_RM_START,
        )
        assert adapter._command(merged) == "rm -rf / --no-preserve-root"

    async def test_destructive_shell_is_blocked(self) -> None:
        outcome = await _decide(True, KIMI_SHELL_RM_START, KIMI_SHELL_RM_PERM)
        assert "cancelled" in outcome

    async def test_destructive_shell_is_blocked_untrusted(self) -> None:
        outcome = await _decide(
            False,
            KIMI_SHELL_RM_START,
            KIMI_SHELL_RM_PERM,
        )
        assert "cancelled" in outcome

    async def test_benign_shell_is_still_allowed(self) -> None:
        start = {
            "sessionUpdate": "tool_call",
            "toolCallId": SHELL_CALL_ID,
            "title": "Shell: ls -la",
            "status": "in_progress",
            "content": [_text_content('{"command": "ls -la"}')],
        }
        permission = {
            "toolCallId": SHELL_CALL_ID,
            "title": "Shell: ls -la",
            "content": [
                _text_content(
                    "Requesting approval to perform: Run command `ls -la`",
                ),
            ],
        }
        outcome = await _decide(True, start, permission)
        assert "selected" in outcome

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Product gap, out of scope for argument parsing: an "
            "out-of-workspace write performed via shell redirection "
            "(`echo probe > /tmp/...`) is still allowed. The command string "
            "is now parsed and reaches `is_command_destructive`, but that "
            "only classifies wipe/mkfs/dd/fork-bomb/power-command patterns; "
            "redirection targets are not boundary-checked, and the "
            "arguments carry no path key. Remove the marker once "
            "redirection targets (or absolute paths in a command) are run "
            "through `is_path_outside_boundary`."
        ),
    )
    async def test_shell_redirect_out_of_workspace_is_blocked(self) -> None:
        outcome = await _decide(
            True,
            KIMI_SHELL_REDIRECT_START,
            KIMI_SHELL_REDIRECT_PERM,
        )
        assert "cancelled" in outcome


class TestMergeSemantics:
    """The permission delta wins; the accumulated state only fills gaps."""

    def test_delta_overrides_prior_scalar_fields(self) -> None:
        adapter = _adapter()
        merged = adapter._merged_payload(
            {"toolCallId": "t/1", "title": "newer", "kind": "edit"},
            {"toolCallId": "t/1", "title": "older", "kind": "read"},
        )
        assert merged["title"] == "newer"
        assert merged["kind"] == "edit"

    def test_prior_fills_fields_the_delta_omits(self) -> None:
        adapter = _adapter()
        merged = adapter._merged_payload(
            {"toolCallId": "t/1", "title": "newer"},
            {
                "toolCallId": "t/1",
                "title": "older",
                "kind": "edit",
                "locations": [{"path": OOB_TARGET}],
            },
        )
        assert merged["kind"] == "edit"
        assert merged["locations"] == [{"path": OOB_TARGET}]
        assert (
            adapter.is_hard_blocked(
                {"toolCallId": "t/1", "title": "newer"},
                prior_state={
                    "toolCallId": "t/1",
                    "locations": [{"path": OOB_TARGET}],
                },
            )
            is True
        )

    def test_content_is_concatenated_not_replaced(self) -> None:
        """Both the arguments and the approval prose stay inspectable."""
        adapter = _adapter()
        merged = adapter._merged_payload(
            KIMI_WRITE_PERM_NO_DIFF,
            KIMI_WRITE_START,
        )
        assert len(merged["content"]) == 2
        assert adapter._paths(merged) == [OOB_TARGET]

    def test_without_prior_state_behaviour_is_unchanged(self) -> None:
        adapter = _adapter()
        assert adapter._merged_payload(KIMI_WRITE_PERM, None) == (
            adapter._tool_call_payload(KIMI_WRITE_PERM)
        )

    def test_unknown_tool_call_id_has_no_prior_state(self) -> None:
        client = _client()
        assert client._prior_tool_call_state({"toolCallId": "nope"}) is None
        assert client._prior_tool_call_state({"title": "no id"}) is None

    async def test_accumulator_supplies_prior_state(self) -> None:
        client = _client()
        client.start_prompt(_noop_message_handler)
        await client.session_update(
            "s1",
            ToolCallStart.model_validate(KIMI_WRITE_START),
        )
        prior = client._prior_tool_call_state(
            {"toolCallId": WRITE_CALL_ID},
        )
        assert prior is not None
        assert _adapter()._paths(
            _adapter()._merged_payload(
                KIMI_WRITE_PERM_NO_DIFF,
                prior,
            ),
        ) == [OOB_TARGET]


class TestRemainingGaps:
    """Gaps this change deliberately does not close."""

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Product gap: when a call is recognisably a file write but no "
            "path can be determined from any source -- no diff block, no "
            "arguments, no locations -- the trusted auto-approve path in "
            "client.py still returns an allow option silently, with no event "
            "and no log. It should decline to auto-approve and fall through "
            "to the interactive suspend flow, so an unverifiable boundary "
            "becomes an explicit user decision. This is the fail-closed "
            "behaviour issue #7727 asks for; it must demote to a prompt "
            "rather than hard-deny, because runners that never send a path "
            "(Gemini CLI sends `locations: []` with no rawInput) would "
            "otherwise have every legitimate in-workspace write rejected. "
            "Remove the marker once implemented."
        ),
    )
    async def test_undeterminable_write_is_not_auto_approved(self) -> None:
        permission = {
            "toolCallId": "turn1/tc_unknown",
            "title": "WriteFile",
            "content": [
                _text_content("Requesting approval to perform: Write file"),
            ],
        }
        outcome = await _decide(True, None, permission)
        assert "selected" not in outcome

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Product gap: `_paths` returns `paths[:5]` and "
            "`_is_hard_blocked` iterates that same truncated list, so the "
            "sixth and later locations of a multi-file call are never "
            "checked. The cap exists for display (`_target`), not for the "
            "security decision. Remove the marker once the deny loop sees "
            "the full path list and only the display path is truncated."
        ),
    )
    def test_sixth_out_of_workspace_location_is_blocked(self) -> None:
        paths = [f"{WORKSPACE}/f{i}.txt" for i in range(5)]
        paths.append(OOB_TARGET)
        call = {
            "toolCallId": "turn1/tc_multi",
            "title": "WriteFile: batch",
            "kind": "edit",
            "locations": [{"path": p} for p in paths],
        }
        assert _adapter().is_hard_blocked(call) is True

    def test_first_out_of_workspace_location_is_blocked(self) -> None:
        paths = [OOB_TARGET]
        paths.extend(f"{WORKSPACE}/f{i}.txt" for i in range(5))
        call = {
            "toolCallId": "turn1/tc_multi",
            "title": "WriteFile: batch",
            "kind": "edit",
            "locations": [{"path": p} for p in paths],
        }
        assert _adapter().is_hard_blocked(call) is True
