# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
# pylint: disable=use-implicit-booleaness-not-comparison
# pylint: disable=unused-argument  # _DumpingModel mimics pydantic's
#   model_dump(**kwargs) signature; the keyword args are part of the
#   protocol under test, not something the stub has to consume.
"""Unit tests for ACP permission payload parsing and merging.

``permissions.py`` turns an ACP ``session/request_permission`` update into
the approval card the console shows, and it is the *only* place that
decides whether a tool call is hard-blocked before the user ever sees it.
The existing ``test_acp_permissions_trusted.py`` covers the trusted flag
and the delegation to ``safety_checks``; this file covers the parsing
layer that feeds it:

* module helpers ``_is_blank`` / ``_content_block_text`` / ``_json_object``
  / ``_command_from_args``,
* ``_tool_call_payload`` / ``_option_payload`` pydantic-vs-dict handling,
* ``_merged_payload``: a permission-time delta that only carries
  ``toolCallId`` must be filled in from the accumulated ``ToolCallView``
  (#7732: otherwise the boundary check sees nothing and passes),
* ``_paths`` / ``_target`` / ``_display_path`` path extraction and
  display,
* ``_command_with_prior`` precedence,
* ``build_suspended_permission`` / ``resolve_option_by_id`` /
  ``selected_response``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from qwenpaw.agents.acp.core import SuspendedPermission
from qwenpaw.agents.acp.permissions import (
    _MAX_DISPLAY_PATHS,
    ACPPermissionAdapter,
    _command_from_args,
    _content_block_text,
    _is_blank,
    _json_object,
)


class _DumpingModel:
    """Stand-in for a pydantic ACP schema object."""

    def __init__(self, data: Any):
        self._data = data

    def model_dump(self, *, by_alias: bool = True, exclude_none: bool = True):
        return self._data


def _content_json(text: str) -> dict[str, Any]:
    """Build a ``type == "content"`` block whose text is *text*."""
    return {"type": "content", "content": {"text": text}}


# ---------------------------------------------------------------------
# _is_blank
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, True),
        ("", True),
        ([], True),
        ({}, True),
        ((), True),
        ("x", False),
        ([1], False),
        ({"a": 1}, False),
        # non-container falsy values are *not* blank: dropping them would
        # lose a meaningful ``False``/``0`` argument
        (0, False),
        (False, False),
    ],
)
def test_is_blank(value: Any, expected: bool) -> None:
    assert _is_blank(value) is expected


# ---------------------------------------------------------------------
# _content_block_text
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "content,expected",
    [
        ({"type": "content", "content": {"text": " hi "}}, "hi"),
        # wrong block type
        ({"type": "diff", "content": {"text": "hi"}}, None),
        ({}, None),
        # not a dict at all
        ("plain text", None),
        (None, None),
        # inner payload must be a dict
        ({"type": "content", "content": "hi"}, None),
        ({"type": "content"}, None),
        # text must be a non-empty string
        ({"type": "content", "content": {"text": "   "}}, None),
        ({"type": "content", "content": {"text": 7}}, None),
        ({"type": "content", "content": {"text": None}}, None),
    ],
)
def test_content_block_text(content: Any, expected: str | None) -> None:
    assert _content_block_text(content) == expected


# ---------------------------------------------------------------------
# _json_object
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"path": "a.txt"}', {"path": "a.txt"}),
        ("{}", {}),
        # the leading-{ guard keeps prose out of the parser
        ("shutdown the dev server", None),
        ('please approve {"path": 1}', None),
        # malformed JSON
        ('{"path": ', None),
        # valid JSON but not an object
        ("[1, 2]", None),
        ('"a string"', None),
        ("123", None),
        ("", None),
    ],
)
def test_json_object(text: str, expected: dict[str, Any] | None) -> None:
    assert _json_object(text) == expected


# ---------------------------------------------------------------------
# _command_from_args
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "args,expected",
    [
        ({"command": "  ls -la  "}, "ls -la"),
        # argv/args lists are joined, blanks dropped
        ({"args": ["git", " status ", "  "]}, "git status"),
        ({"argv": ["npm", "run", "dev"]}, "npm run dev"),
        ({"args": []}, None),
        ({"args": ["   ", ""]}, None),
        ({"args": "not-a-list"}, None),
        ({"command": 7}, None),
        ({"command": ""}, None),
        ({}, None),
        # non-string argv items are stringified
        ({"args": ["sleep", 30]}, "sleep 30"),
    ],
)
def test_command_from_args(args: dict[str, Any], expected: str | None) -> None:
    assert _command_from_args(args) == expected


# ---------------------------------------------------------------------
# payload extraction: dict vs pydantic model
# ---------------------------------------------------------------------


def test_tool_call_payload_accepts_dict_and_copies_it(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    source = {"toolCallId": "t1", "title": "Edit"}
    payload = adapter._tool_call_payload(source)

    assert payload == source
    assert payload is not source  # a copy, callers must not be mutated


def test_tool_call_payload_uses_model_dump(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    payload = adapter._tool_call_payload(
        _DumpingModel({"title": "From model"}),
    )

    assert payload == {"title": "From model"}


@pytest.mark.parametrize("tool_call", [None, object(), 7, "str"])
def test_tool_call_payload_unusable_input_is_empty(
    tmp_path: Path,
    tool_call: Any,
) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    assert adapter._tool_call_payload(tool_call) == {}


def test_tool_call_payload_model_dump_returning_non_dict(
    tmp_path: Path,
) -> None:
    """A model whose dump is not a mapping must degrade to empty."""
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    assert adapter._tool_call_payload(_DumpingModel("nope")) == {}


def test_option_payload_variants(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))

    assert adapter._option_payload({"optionId": "allow"}) == {
        "optionId": "allow",
    }
    assert adapter._option_payload(
        _DumpingModel({"optionId": "allow"}),
    ) == {"optionId": "allow"}
    assert adapter._option_payload(_DumpingModel("nope")) is None
    assert adapter._option_payload("not an option") is None
    assert adapter._option_payload(None) is None


# ---------------------------------------------------------------------
# _merged_payload — #7732 regression surface
# ---------------------------------------------------------------------


def test_merged_payload_without_prior_returns_delta(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    delta = {"toolCallId": "t1", "title": ""}

    assert adapter._merged_payload(delta) == delta
    assert adapter._merged_payload(delta, None) == delta


def test_merged_payload_with_unusable_prior_returns_delta(
    tmp_path: Path,
) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    delta = {"toolCallId": "t1", "title": "Edit"}

    assert adapter._merged_payload(delta, object()) == delta


def test_merged_payload_fills_gaps_from_prior(tmp_path: Path) -> None:
    """A delta carrying only ``toolCallId`` must inherit the prior args.

    Without this the boundary check would see no path and no command, so
    an out-of-workspace write would sail through.
    """
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    prior = {"toolCallId": "t1", "rawInput": {"path": "prior.txt"}}
    delta = {"toolCallId": "t1"}

    merged = adapter._merged_payload(delta, prior)

    assert merged["rawInput"] == {"path": "prior.txt"}
    assert adapter._paths(merged) == ["prior.txt"]


def test_merged_payload_delta_wins_over_prior(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    prior = {"rawInput": {"path": "prior.txt"}, "title": "Prior title"}
    delta = {"rawInput": {"path": "delta.txt"}, "title": "Delta title"}

    merged = adapter._merged_payload(delta, prior)

    assert merged["rawInput"] == {"path": "delta.txt"}
    assert merged["title"] == "Delta title"


def test_merged_payload_skips_blank_delta_values(tmp_path: Path) -> None:
    """An empty ``content`` list in the delta must not erase prior args."""
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    prior = {"content": [_content_json('{"path": "prior.txt"}')]}
    delta = {"content": [], "title": "", "rawInput": None}

    merged = adapter._merged_payload(delta, prior)

    assert merged["content"] == prior["content"]
    # blank delta keys are dropped entirely, never written back as None
    assert "title" not in merged
    assert "rawInput" not in merged
    assert adapter._paths(merged) == ["prior.txt"]


def test_merged_payload_concatenates_list_keys_delta_first(
    tmp_path: Path,
) -> None:
    """``content``/``locations`` extend instead of replace, delta first."""
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    prior = {
        "locations": [{"path": "prior_loc.txt"}],
        "content": [_content_json('{"path": "prior.txt"}')],
    }
    delta = {
        "locations": [{"path": "delta_loc.txt"}],
        "content": [_content_json('{"path": "delta.txt"}')],
    }

    merged = adapter._merged_payload(delta, prior)

    assert [loc["path"] for loc in merged["locations"]] == [
        "delta_loc.txt",
        "prior_loc.txt",
    ]
    assert adapter._paths(merged) == [
        "delta_loc.txt",
        "prior_loc.txt",
        "delta.txt",
        "prior.txt",
    ]


def test_merged_payload_list_key_with_scalar_prior_replaces(
    tmp_path: Path,
) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    merged = adapter._merged_payload(
        {"content": [_content_json("{}")]},
        {"content": "scalar"},
    )

    assert isinstance(merged["content"], list)


# ---------------------------------------------------------------------
# _argument_dicts
# ---------------------------------------------------------------------


def test_argument_dicts_extracts_json_from_content_blocks(
    tmp_path: Path,
) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    tool_call = {
        "content": [
            _content_json('{"path": "a.txt"}'),
            # prose must not be parsed as arguments
            _content_json("please approve this edit"),
            # malformed JSON is skipped
            _content_json('{"path": '),
            # non-content blocks are skipped
            {"type": "diff", "path": "d.txt"},
            "a bare string",
            {"type": "content", "content": "not a dict"},
        ],
    }

    assert adapter._argument_dicts(tool_call) == [{"path": "a.txt"}]


def test_argument_dicts_without_content_is_empty(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    assert adapter._argument_dicts({}) == []
    assert adapter._argument_dicts({"content": None}) == []


# ---------------------------------------------------------------------
# _paths
# ---------------------------------------------------------------------


def test_paths_collects_from_every_source_in_order(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    tool_call = {
        "locations": [{"path": "loc.txt"}, "not-a-dict", {}],
        "content": [
            {"type": "diff", "path": "diff.txt"},
            _content_json('{"path": "json.txt", "file_path": ["a.txt"]}'),
        ],
        "rawInput": {"path": "raw.txt", "abs_path": "abs.txt", "other": 1},
    }

    assert adapter._paths(tool_call) == [
        "loc.txt",
        "diff.txt",
        "raw.txt",
        "abs.txt",
        "json.txt",
        "a.txt",
    ]


def test_paths_dedupes_and_ignores_non_strings(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))

    assert adapter._paths(
        {
            "rawInput": {"path": "dup.txt"},
            "locations": [{"path": "dup.txt"}],
        },
    ) == ["dup.txt"]
    assert (
        adapter._paths(
            {"rawInput": {"path": 7}, "locations": [{"path": None}]},
        )
        == []
    )
    assert adapter._paths({}) == []


def test_paths_accepts_snake_case_raw_input(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    assert adapter._paths({"raw_input": {"path": "alias.txt"}}) == [
        "alias.txt",
    ]


def test_paths_is_uncapped_but_display_is(tmp_path: Path) -> None:
    """The boundary check must see *every* path, not just the first few."""
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    many = [f"file_{i}.txt" for i in range(_MAX_DISPLAY_PATHS + 3)]
    paths = adapter._paths({"rawInput": {"path": many}})

    assert len(paths) == len(many)

    suspended = adapter.build_suspended_permission(
        agent="runner",
        tool_call={"rawInput": {"path": many}},
        options=[],
    )
    assert len(suspended.paths) == _MAX_DISPLAY_PATHS
    assert suspended.target == f"{len(many)} files"


# ---------------------------------------------------------------------
# _display_path
# ---------------------------------------------------------------------


def test_display_path_relative_is_unchanged(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    assert adapter._display_path("sub/file.txt") == "sub/file.txt"


def test_display_path_absolute_inside_cwd_is_relative(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    inside = Path(adapter.cwd) / "sub" / "file.txt"

    assert adapter._display_path(str(inside)) == "sub/file.txt"


def test_display_path_absolute_outside_cwd_stays_absolute(
    tmp_path: Path,
) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    assert adapter._display_path("/etc/passwd") == "/etc/passwd"


def test_display_path_tilde_is_expanded(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    shown = adapter._display_path("~/notes.txt")

    assert shown != "~/notes.txt"
    assert shown.endswith("notes.txt")


@pytest.mark.parametrize("bad", ["a\x00b", "/etc/\x00", "~\x00"])
def test_display_path_survives_unusable_value(
    tmp_path: Path,
    bad: str,
) -> None:
    """A NUL byte makes ``Path.expanduser``/``resolve`` raise; the approval
    card must still render instead of blowing up the permission request."""
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    assert adapter._display_path(bad) == bad


# ---------------------------------------------------------------------
# _target
# ---------------------------------------------------------------------


def test_target_variants(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))

    assert adapter._target({"rawInput": {"path": "one.txt"}}) == "one.txt"
    assert (
        adapter._target(
            {"rawInput": {"path": ["one.txt", "two.txt"]}},
        )
        == "2 files"
    )
    assert adapter._target({"rawInput": {"command": "ls -la"}}) == "ls -la"
    assert adapter._target({"title": "Just a title"}) == "Just a title"
    assert adapter._target({}) is None


def test_target_prefers_single_path_over_command(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    tool_call = {
        "title": "Do something",
        "rawInput": {"command": "ls", "path": "a.txt"},
    }

    assert adapter._target(tool_call) == "a.txt"


# ---------------------------------------------------------------------
# command resolution precedence
# ---------------------------------------------------------------------


def test_argument_command_beats_raw_input_and_content(
    tmp_path: Path,
) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))

    assert (
        adapter._argument_command(
            {
                "rawInput": {"command": "from-raw"},
                "content": [_content_json('{"command": "from-content"}')],
            },
        )
        == "from-raw"
    )
    assert (
        adapter._argument_command(
            {"content": [_content_json('{"command": "from-content"}')]},
        )
        == "from-content"
    )
    assert adapter._argument_command({}) is None


def test_title_command_only_for_execute_kind(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))

    assert (
        adapter._title_command(
            {"kind": "execute", "title": "Shutdown the dev server"},
        )
        == "Shutdown the dev server"
    )
    # case/space insensitive on kind
    assert (
        adapter._title_command(
            {"kind": " EXECUTE ", "title": "Run tests"},
        )
        == "Run tests"
    )
    # a non-execute kind must not be mistaken for a command
    assert adapter._title_command({"kind": "edit", "title": "rm -rf /"}) is (
        None
    )
    assert adapter._title_command({"title": "rm -rf /"}) is None
    assert adapter._title_command({"kind": "execute", "title": "  "}) is None
    assert adapter._title_command({}) is None


def test_command_falls_back_to_title(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))

    assert (
        adapter._command(
            {"kind": "execute", "title": "Shutdown the dev server"},
        )
        == "Shutdown the dev server"
    )
    assert (
        adapter._command(
            {
                "kind": "execute",
                "title": "Shutdown",
                "rawInput": {"command": "npm run dev"},
            },
        )
        == "npm run dev"
    )


def test_command_with_prior_precedence(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))

    # delta first
    assert (
        adapter._command_with_prior(
            {"rawInput": {"command": "delta-cmd"}},
            {"rawInput": {"command": "prior-cmd"}},
        )
        == "delta-cmd"
    )
    # then prior arguments
    assert (
        adapter._command_with_prior(
            {},
            {"rawInput": {"command": "prior-cmd"}},
        )
        == "prior-cmd"
    )
    # then the delta title, then the prior title
    assert (
        adapter._command_with_prior(
            {"kind": "execute", "title": "T1"},
            {"kind": "execute", "title": "T2"},
        )
        == "T1"
    )
    assert (
        adapter._command_with_prior(
            {},
            {"kind": "execute", "title": "T2"},
        )
        == "T2"
    )
    assert adapter._command_with_prior({}, {}) is None
    assert adapter._command_with_prior({}) is None


# ---------------------------------------------------------------------
# tool name / kind / action / summary
# ---------------------------------------------------------------------


def test_tool_metadata_defaults(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))

    assert adapter._tool_name({"title": " Edit file "}) == "Edit file"
    assert adapter._tool_name({"title": "   "}) == "external-agent"
    assert adapter._tool_name({"title": 7}) == "external-agent"
    assert adapter._tool_name({}) == "external-agent"

    assert adapter._tool_kind({"kind": " EDIT "}) == "edit"
    assert adapter._tool_kind({"kind": ""}) == "other"
    assert adapter._tool_kind({}) == "other"

    assert adapter._action({"kind": "read"}) == "read"
    assert adapter._action({"kind": ""}) is None
    assert adapter._action({}) is None

    assert adapter._summary({"title": "Do it"}) == "Do it"
    assert adapter._summary({"title": ""}) is None
    assert adapter._summary({}) is None


# ---------------------------------------------------------------------
# resolve_option_by_id / selected_response
# ---------------------------------------------------------------------


def test_resolve_option_by_id(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    options = [
        {"optionId": "allow_once", "name": "Allow once"},
        {"option_id": "reject", "name": "Reject"},
        "not-a-dict",
        {},
    ]

    assert adapter.resolve_option_by_id(options, "allow_once") == options[0]
    assert adapter.resolve_option_by_id(options, " reject ") == options[1]
    assert adapter.resolve_option_by_id(options, "missing") is None
    assert adapter.resolve_option_by_id(options, "") is None
    assert adapter.resolve_option_by_id(options, "   ") is None


def test_selected_response_shapes(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))

    chosen = adapter.selected_response({"optionId": "allow_once"})
    assert chosen.outcome.outcome == "selected"
    assert chosen.outcome.option_id == "allow_once"

    snake = adapter.selected_response({"option_id": "reject"})
    assert snake.outcome.option_id == "reject"

    # an option with no id still has to answer with *something*
    fallback = adapter.selected_response({})
    assert fallback.outcome.option_id == "selected"

    # no matching option -> cancelled, which is a denial
    cancelled = adapter.selected_response(None)
    assert cancelled.outcome.outcome == "cancelled"
    assert adapter.cancelled_response().outcome.outcome == "cancelled"


# ---------------------------------------------------------------------
# build_suspended_permission
# ---------------------------------------------------------------------


def test_build_suspended_permission_from_plain_dicts(
    tmp_path: Path,
) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    inside = str(Path(tmp_path) / "a.txt")

    suspended = adapter.build_suspended_permission(
        agent="kimi-cli",
        tool_call={
            "toolCallId": "t1",
            "title": "Edit file",
            "kind": "edit",
            "rawInput": {"path": inside},
        },
        options=[
            {"optionId": "allow_once", "name": "Allow once"},
            "junk",
        ],
    )

    assert isinstance(suspended, SuspendedPermission)
    assert suspended.agent == "kimi-cli"
    assert suspended.tool_name == "Edit file"
    assert suspended.tool_kind == "edit"
    assert suspended.action == "edit"
    assert suspended.summary == "Edit file"
    assert suspended.paths == [inside]
    assert suspended.target == "a.txt"  # displayed relative to cwd
    assert suspended.command is None
    assert suspended.requires_user_confirmation is True
    assert suspended.options == [
        {"optionId": "allow_once", "name": "Allow once"},
    ]
    assert suspended.payload == {
        "toolCall": {
            "toolCallId": "t1",
            "title": "Edit file",
            "kind": "edit",
            "rawInput": {"path": inside},
        },
        "options": [{"optionId": "allow_once", "name": "Allow once"}],
    }


def test_build_suspended_permission_merges_prior_state(
    tmp_path: Path,
) -> None:
    """#7732: the update carries only an id; the card still needs the args."""
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    prior = {
        "toolCallId": "t1",
        "title": "Run command",
        "kind": "execute",
        "rawInput": {"command": "pytest -q"},
    }

    suspended = adapter.build_suspended_permission(
        agent="runner",
        tool_call={"toolCallId": "t1"},
        options=[],
        prior_state=prior,
    )

    assert suspended.command == "pytest -q"
    assert suspended.tool_name == "Run command"
    # no paths at all -> the command becomes the card's target
    assert suspended.target == "pytest -q"
    assert suspended.paths == []


def test_build_suspended_permission_with_pydantic_inputs(
    tmp_path: Path,
) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))

    suspended = adapter.build_suspended_permission(
        agent="runner",
        tool_call=_DumpingModel(
            {"title": "Read file", "kind": "read", "rawInput": {"path": "r"}},
        ),
        options=[_DumpingModel({"optionId": "allow_once"})],
    )

    assert suspended.tool_name == "Read file"
    assert suspended.options == [{"optionId": "allow_once"}]


def test_build_suspended_permission_without_anything(
    tmp_path: Path,
) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))

    suspended = adapter.build_suspended_permission(
        agent="runner",
        tool_call=None,
        options=[],
    )

    assert suspended.tool_name == "external-agent"
    assert suspended.tool_kind == "other"
    assert suspended.target is None
    assert suspended.command is None
    assert suspended.paths == []
    assert suspended.payload["toolCall"] == {}


# ---------------------------------------------------------------------
# is_hard_blocked sees the merged payload
# ---------------------------------------------------------------------


def test_hard_block_uses_command_from_prior_state(tmp_path: Path) -> None:
    """A destructive command that only exists in accumulated state must
    still be blocked."""
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))

    assert (
        adapter.is_hard_blocked(
            {"toolCallId": "t1"},
            prior_state={"rawInput": {"command": "rm -rf /"}},
        )
        is True
    )
    assert (
        adapter.is_hard_blocked(
            {"toolCallId": "t1"},
            prior_state={"rawInput": {"command": "echo hello"}},
        )
        is False
    )


def test_hard_block_uses_path_from_prior_state(tmp_path: Path) -> None:
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))

    assert (
        adapter.is_hard_blocked(
            {"toolCallId": "t1"},
            prior_state={"locations": [{"path": "/etc/passwd"}]},
        )
        is True
    )
    assert (
        adapter.is_hard_blocked(
            {"toolCallId": "t1"},
            prior_state={
                "locations": [{"path": str(Path(adapter.cwd) / "ok.txt")}],
            },
        )
        is False
    )


def test_hard_block_reads_command_from_json_content_block(
    tmp_path: Path,
) -> None:
    """kimi-cli serialises arguments as JSON inside a content text block."""
    adapter = ACPPermissionAdapter(cwd=str(tmp_path))
    tool_call = {
        "content": [_content_json(json.dumps({"command": "rm -rf /"}))],
    }

    assert adapter.is_hard_blocked(tool_call) is True
