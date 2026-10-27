# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-order,unreachable,protected-access,redefined-outer-name,too-many-public-methods,unused-argument,unused-variable  # noqa: E501
"""Unit tests for run_tool_batch helpers and control flow.

Covers the pure-logic surface of ``agents/tools/run_tool_batch.py``:
step/vars/args reference resolution, condition and arithmetic
evaluation, batch file loading, response payload normalisation and
the control-flow execution loop (label/goto/set_var) — all exercised
in-process without a running toolkit.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from agentscope.message import DataBlock, TextBlock, ToolResultState, URLSource
from agentscope.tool import ToolChunk

import importlib

rtb = importlib.import_module("qwenpaw.agents.tools.run_tool_batch")


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


def _text_chunk(
    text: str,
    state: ToolResultState = ToolResultState.SUCCESS,
) -> ToolChunk:
    return ToolChunk(
        state=state,
        content=[TextBlock(type="text", text=text)],
    )


class _FakeChunk:
    """Plain chunk stand-in that accepts raw dict blocks.

    ``ToolChunk`` is a pydantic model and rejects untyped dict blocks;
    the code under test defensively handles raw dicts (e.g. blocks
    forwarded from other sources), so these helpers are exercised with
    this stand-in instead.
    """

    def __init__(self, state: ToolResultState, content: list[Any]):
        self.state = state
        self.content = content


def _run(actions: list[dict], stop_on_error: bool = True, maxstep: int = 50):
    """Run _run_steps synchronously with a patched tool caller."""
    return asyncio_run(rtb._run_steps(actions, stop_on_error, maxstep))


def asyncio_run(coro):
    import asyncio

    return (
        asyncio.get_event_loop_policy()
        .new_event_loop()
        .run_until_complete(coro)
    )


@pytest.fixture()
def patch_call_tool():
    """Patch _call_tool to a mock; tests configure return_value/side_effect."""
    mock = AsyncMock()
    with patch.object(rtb, "_call_tool", mock):
        yield mock


# ---------------------------------------------------------------------------
# _extract_text / _is_error_text / _extract_files_info
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_text_block_dict(self):
        chunk = _text_chunk("hello")
        assert rtb._extract_text(chunk) == "hello"

    def test_skips_non_text_blocks(self):
        chunk = _FakeChunk(
            ToolResultState.SUCCESS,
            [
                {"type": "image", "url": "http://x/i.png"},
                TextBlock(type="text", text="real text"),
            ],
        )
        assert rtb._extract_text(chunk) == "real text"

    def test_empty_content_returns_empty(self):
        chunk = ToolChunk(state=ToolResultState.SUCCESS, content=[])
        assert rtb._extract_text(chunk) == ""


class TestIsErrorText:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Error: something failed", True),
            ("ERROR: uppercase", True),
            ("Command failed with exit code 1", True),
            ("all good", False),
            ("", False),
        ],
    )
    def test_detection(self, text, expected):
        assert rtb._is_error_text(text) == expected


class TestExtractFilesInfo:
    def test_data_block_with_source_dict(self):
        blocks = [
            {
                "type": "data",
                "source": {"url": "http://x/f.pdf"},
                "name": "f.pdf",
            },
        ]
        info = rtb._extract_files_info(blocks)
        assert info == [{"url": "http://x/f.pdf", "name": "f.pdf"}]

    def test_data_block_with_source_object(self):
        class _Source:
            url = "http://x/obj.pdf"

        class _Block:
            type = "data"
            source = _Source()
            name = "obj.pdf"

        info = rtb._extract_files_info([_Block()])
        assert info == [{"url": "http://x/obj.pdf", "name": "obj.pdf"}]

    def test_skips_non_data_and_no_source(self):
        blocks = [
            {"type": "text", "text": "x"},
            {"type": "data"},  # no source
        ]
        assert rtb._extract_files_info(blocks) == []

    def test_skips_empty_url(self):
        blocks = [{"type": "data", "source": {"url": ""}, "name": ""}]
        assert rtb._extract_files_info(blocks) == []


# ---------------------------------------------------------------------------
# _response_payload
# ---------------------------------------------------------------------------


class TestResponsePayload:
    def test_json_payload_without_ok_adds_ok_true(self):
        chunk = _text_chunk(json.dumps({"value": 42}))
        payload = rtb._response_payload(chunk)
        assert payload["ok"] is True
        assert payload["value"] == 42

    def test_json_payload_with_error_key_marks_not_ok(self):
        chunk = _text_chunk(json.dumps({"error": "boom"}))
        payload = rtb._response_payload(chunk)
        assert payload["ok"] is False

    def test_json_payload_explicit_ok_overridden_by_error_state(self):
        chunk = _text_chunk(
            json.dumps({"ok": True}),
            state=ToolResultState.ERROR,
        )
        payload = rtb._response_payload(chunk)
        assert payload["ok"] is False

    def test_json_non_dict_payload(self):
        chunk = _text_chunk(json.dumps([1, 2, 3]))
        payload = rtb._response_payload(chunk)
        assert payload["ok"] is True
        assert payload["value"] == [1, 2, 3]

    def test_plain_text_ok(self):
        chunk = _text_chunk("done")
        payload = rtb._response_payload(chunk)
        assert payload["ok"] is True
        assert payload["text"] == "done"

    def test_plain_text_error_prefix(self):
        chunk = _text_chunk("Error: bad path")
        payload = rtb._response_payload(chunk)
        assert payload["ok"] is False
        assert payload["error"] == "Error: bad path"

    def test_error_state_plain_text(self):
        chunk = _text_chunk("some text", state=ToolResultState.ERROR)
        payload = rtb._response_payload(chunk)
        assert payload["ok"] is False

    def test_denied_state(self):
        chunk = _text_chunk("denied", state=ToolResultState.DENIED)
        payload = rtb._response_payload(chunk)
        assert payload["ok"] is False

    def test_raw_blocks_preserved(self):
        chunk = _text_chunk("hi")
        payload = rtb._response_payload(chunk)
        assert "_raw_blocks" in payload


# ---------------------------------------------------------------------------
# resolve_step_refs / _lookup_step_ref / _lookup_var
# ---------------------------------------------------------------------------


RESULTS: list[dict[str, Any]] = [
    {
        "step": 0,
        "tool_name": "t",
        "ok": True,
        "text": "line1\nline2",
        "value": 2,
    },
    {
        "step": 1,
        "tool_name": "t",
        "ok": True,
        "text": "abc",
        "items": ["a", "b"],
    },
]


class TestResolveStepRefs:
    def test_exact_ref_returns_raw_dict(self):
        out = rtb.resolve_step_refs("${steps.0}", RESULTS)
        assert out == RESULTS[0]

    def test_exact_ref_path(self):
        assert rtb.resolve_step_refs("${steps.0.value}", RESULTS) == 2

    def test_inline_ref_substitution(self):
        out = rtb.resolve_step_refs("x=${steps.1.text};", RESULTS)
        assert out == "x=abc;"

    def test_list_index_path(self):
        assert rtb.resolve_step_refs("${steps.1.items.1}", RESULTS) == "b"

    def test_dict_and_list_recursive(self):
        value = {"a": "${steps.0.value}", "b": ["${steps.1.text}"]}
        out = rtb.resolve_step_refs(value, RESULTS)
        assert out == {"a": 2, "b": ["abc"]}

    def test_non_string_passthrough(self):
        assert rtb.resolve_step_refs(123, RESULTS) == 123
        assert rtb.resolve_step_refs(None, RESULTS) is None

    def test_missing_step_raises(self):
        with pytest.raises(ValueError, match="no result"):
            rtb.resolve_step_refs("${steps.9}", RESULTS)

    def test_missing_key_raises(self):
        with pytest.raises(ValueError, match="Missing key"):
            rtb.resolve_step_refs("${steps.0.nonexistent}", RESULTS)

    def test_bad_list_index_raises(self):
        with pytest.raises(ValueError, match="Invalid list index"):
            rtb.resolve_step_refs("${steps.1.items.x}", RESULTS)

    def test_list_index_out_of_range(self):
        with pytest.raises(ValueError, match="out of range"):
            rtb.resolve_step_refs("${steps.1.items.9}", RESULTS)

    def test_path_on_scalar_raises(self):
        with pytest.raises(ValueError, match="Cannot resolve"):
            rtb.resolve_step_refs("${steps.0.text.more}", RESULTS)

    def test_latest_result_wins_for_repeated_step(self):
        results = RESULTS + [
            {"step": 0, "tool_name": "t", "ok": True, "text": "second-run"},
        ]
        assert (
            rtb.resolve_step_refs("${steps.0.text}", results) == "second-run"
        )

    def test_vars_exact(self):
        out = rtb.resolve_step_refs("${vars.i}", [], {"i": 7})
        assert out == 7

    def test_vars_inline(self):
        out = rtb.resolve_step_refs("i=${vars.i}!", [], {"i": 3})
        assert out == "i=3!"

    def test_vars_nested_path(self):
        out = rtb.resolve_step_refs(
            "${vars.cfg.name}",
            [],
            {"cfg": {"name": "x"}},
        )
        assert out == "x"

    def test_vars_missing_raises(self):
        with pytest.raises(ValueError, match="Missing var"):
            rtb.resolve_step_refs("${vars.nope}", [], {})


class TestStringifyResolvedValue:
    def test_string_passthrough(self):
        assert rtb._stringify_resolved_value("abc") == "abc"

    def test_non_string_json_encoded(self):
        assert rtb._stringify_resolved_value({"k": 1}) == '{"k": 1}'


# ---------------------------------------------------------------------------
# _build_label_map
# ---------------------------------------------------------------------------


class TestBuildLabelMap:
    def test_collects_labels(self):
        actions = [
            {"tool_name": "label", "arguments": {"name": "start"}},
            {"tool_name": "goto", "arguments": {"label": "start"}},
            {"tool_name": "label", "arguments": {"name": "end"}},
        ]
        assert rtb._build_label_map(actions) == {"start": 0, "end": 2}

    def test_skips_non_dict_steps(self):
        actions = [
            "not-a-dict",
            {"tool_name": "label", "arguments": {"name": "a"}},
        ]
        assert rtb._build_label_map(actions) == {"a": 1}

    def test_duplicate_label_raises(self):
        actions = [
            {"tool_name": "label", "arguments": {"name": "x"}},
            {"tool_name": "label", "arguments": {"name": "x"}},
        ]
        with pytest.raises(ValueError, match="Duplicate label"):
            rtb._build_label_map(actions)

    def test_label_without_name_raises(self):
        actions = [{"tool_name": "label", "arguments": {}}]
        with pytest.raises(ValueError, match="requires arguments.name"):
            rtb._build_label_map(actions)

    def test_label_non_dict_arguments_raises(self):
        actions = [{"tool_name": "label", "arguments": "bad"}]
        with pytest.raises(ValueError, match="arguments must be an object"):
            rtb._build_label_map(actions)

    def test_tool_alias_field(self):
        actions = [{"tool": "label", "arguments": {"name": "aliased"}}]
        assert rtb._build_label_map(actions) == {"aliased": 0}


# ---------------------------------------------------------------------------
# _parse_scalar / _resolve_token / _coerce_bool
# ---------------------------------------------------------------------------


class TestParseScalar:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("true", True),
            ("TRUE", True),
            ("false", False),
            ("False", False),
            ("42", 42),
            ("-7", -7),
            ("3.14", "3.14"),  # not int-parsed
            ("hello", "hello"),
            (99, 99),  # non-string passthrough
        ],
    )
    def test_parse(self, raw, expected):
        assert rtb._parse_scalar(raw) == expected


class TestResolveToken:
    def test_variable_lookup(self):
        assert rtb._resolve_token("i", [], {"i": 5}) == 5

    def test_scalar_literal(self):
        assert rtb._resolve_token("10", [], {}) == 10
        assert rtb._resolve_token("true", [], {}) is True

    def test_undefined_variable_raises(self):
        with pytest.raises(ValueError, match="Undefined variable"):
            rtb._resolve_token("undefined_var", [], {})

    def test_empty_token_raises(self):
        with pytest.raises(ValueError, match="invalid"):
            rtb._resolve_token("  ", [], {})

    def test_step_ref_token(self):
        out = rtb._resolve_token("${steps.0.value}", RESULTS, {})
        assert out == 2


class TestCoerceBool:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (True, True),
            ("false", False),
            (0, False),
            (1, True),
        ],
    )
    def test_ok(self, value, expected):
        assert rtb._coerce_bool(value, "x") == expected

    def test_unsupported_raises(self):
        with pytest.raises(ValueError, match="Unsupported condition"):
            rtb._coerce_bool("notabool", "notabool")


# ---------------------------------------------------------------------------
# _evaluate_condition / arithmetic / set_var
# ---------------------------------------------------------------------------


class TestEvaluateCondition:
    @pytest.mark.parametrize(
        "cond,vars_,expected",
        [
            ("true", {}, True),
            ("false", {}, False),
            ("1>2", {}, False),
            ("2>=2", {}, True),
            ("i<5", {"i": 3}, True),
            ("i<5", {"i": 7}, False),
            ("i==3", {"i": 3}, True),
            ("i!=3", {"i": 3}, False),
        ],
    )
    def test_comparison(self, cond, vars_, expected):
        assert rtb._evaluate_condition(cond, [], vars_) == expected

    def test_bare_variable_truthy(self):
        assert rtb._evaluate_condition("flag", [], {"flag": True}) is True

    def test_type_mismatch_raises(self):
        with pytest.raises(ValueError, match="Unsupported condition"):
            rtb._evaluate_condition("a>b", [], {"a": "x", "b": 1})


class TestEvaluateArithmeticExpr:
    @pytest.mark.parametrize(
        "expr,vars_,expected",
        [
            ("1+2", {}, 3),
            ("i+1", {"i": 4}, 5),
            ("(i+1)*2", {"i": 4}, 10),
            ("-x", {"x": 3}, -3),
            ("+x", {"x": 3}, 3),
            ("7%3", {}, 1),
            ("10/4", {}, 2.5),
        ],
    )
    def test_eval(self, expr, vars_, expected):
        assert rtb._evaluate_arithmetic_expr(expr, vars_) == expected

    def test_division_by_zero(self):
        with pytest.raises(ValueError, match="division by zero"):
            rtb._evaluate_arithmetic_expr("1/0", {})

    def test_unknown_variable(self):
        with pytest.raises(ValueError, match="numeric expression"):
            rtb._evaluate_arithmetic_expr("nope+1", {})

    def test_boolean_literal_rejected(self):
        with pytest.raises(ValueError, match="numeric expression"):
            rtb._evaluate_arithmetic_expr("True+1", {})

    def test_boolean_variable_rejected(self):
        with pytest.raises(ValueError, match="numeric expression"):
            rtb._evaluate_arithmetic_expr("b+1", {"b": True})

    def test_string_literal_rejected(self):
        with pytest.raises(ValueError, match="numeric expression"):
            rtb._evaluate_arithmetic_expr("'a'+1", {})

    def test_unsupported_operator(self):
        with pytest.raises(ValueError, match="numeric expression"):
            rtb._evaluate_arithmetic_expr("2**3", {})

    def test_syntax_error(self):
        with pytest.raises(ValueError, match="numeric expression"):
            rtb._evaluate_arithmetic_expr("1+", {})


class TestEvaluateSetVarExpr:
    def test_simple_literal(self):
        assert rtb._evaluate_set_var_expr("i=0", [], {}) == ("i", 0)

    def test_bool_literal(self):
        assert rtb._evaluate_set_var_expr("flag=true", [], {}) == (
            "flag",
            True,
        )

    def test_string_value_via_step_ref(self):
        # A step ref that resolves to a string returns the string value.
        name, value = rtb._evaluate_set_var_expr(
            "line=${steps.0.text}",
            RESULTS,
            {},
        )
        assert name == "line"
        assert value == RESULTS[0]["text"]

    def test_plain_identifier_rhs_raises_undefined(self):
        # A bare identifier that is not a defined variable is rejected.
        with pytest.raises(ValueError, match="Undefined variable"):
            rtb._evaluate_set_var_expr("name=hello", [], {})

    def test_arithmetic_rhs(self):
        assert rtb._evaluate_set_var_expr("i=i+1", [], {"i": 4}) == ("i", 5)

    def test_step_ref_rhs(self):
        name, value = rtb._evaluate_set_var_expr(
            "total=${steps.0.value}",
            RESULTS,
            {},
        )
        assert (name, value) == ("total", 2)

    def test_var_ref_rhs(self):
        name, value = rtb._evaluate_set_var_expr("j=${vars.i}", [], {"i": 9})
        assert (name, value) == ("j", 9)

    def test_complex_arithmetic(self):
        name, value = rtb._evaluate_set_var_expr(
            "i=(${vars.i}+1)*2",
            [],
            {"i": 3},
        )
        assert (name, value) == ("i", 8)

    def test_undefined_var_in_rhs_raises(self):
        with pytest.raises(ValueError):
            rtb._evaluate_set_var_expr("i=undefined_xyz", [], {})

    def test_invalid_expr_raises(self):
        with pytest.raises(ValueError, match="simple assignment"):
            rtb._evaluate_set_var_expr("not an assignment", [], {})

    def test_empty_expr_raises(self):
        with pytest.raises(ValueError, match="simple assignment"):
            rtb._evaluate_set_var_expr("", [], {})


# ---------------------------------------------------------------------------
# _load_batch_file / _resolve_args / _lookup_arg
# ---------------------------------------------------------------------------


class TestLoadBatchFile:
    def test_actions_object(self, tmp_path):
        f = tmp_path / "batch.json"
        f.write_text(
            json.dumps(
                {
                    "actions": [
                        {"tool_name": "label", "arguments": {"name": "a"}},
                    ],
                },
            ),
        )
        out = rtb._load_batch_file(str(f))
        assert out == [{"tool_name": "label", "arguments": {"name": "a"}}]

    def test_plain_array(self, tmp_path):
        f = tmp_path / "arr.json"
        f.write_text(json.dumps([{"tool_name": "x"}]))
        assert rtb._load_batch_file(str(f)) == [{"tool_name": "x"}]

    def test_empty_path_raises(self):
        with pytest.raises(ValueError, match="file_path is required"):
            rtb._load_batch_file("")

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ValueError, match="not found"):
            rtb._load_batch_file(str(tmp_path / "nope.json"))

    def test_non_json_suffix_raises(self, tmp_path):
        f = tmp_path / "batch.yaml"
        f.write_text("a: 1")
        with pytest.raises(ValueError, match=r"\.json"):
            rtb._load_batch_file(str(f))

    def test_invalid_json_raises(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{not json")
        with pytest.raises(ValueError, match="Invalid JSON"):
            rtb._load_batch_file(str(f))

    def test_wrong_shape_raises(self, tmp_path):
        f = tmp_path / "shape.json"
        f.write_text(json.dumps({"actions": "notalist"}))
        with pytest.raises(ValueError, match="array of actions"):
            rtb._load_batch_file(str(f))


class TestResolveArgs:
    def test_exact_preserves_type(self):
        assert rtb._resolve_args("${args.count}", {"count": 5}) == 5

    def test_inline_substitution(self):
        out = rtb._resolve_args("run ${args.name} now", {"name": "job"})
        assert out == "run job now"

    def test_inline_non_string_json_encoded(self):
        out = rtb._resolve_args("v=${args.obj}", {"obj": {"a": 1}})
        assert out == 'v={"a": 1}'

    def test_recursive_dict_list(self):
        value = {"cmd": "${args.x}", "items": ["${args.y}"]}
        out = rtb._resolve_args(value, {"x": 1, "y": "z"})
        assert out == {"cmd": 1, "items": ["z"]}

    def test_non_string_passthrough(self):
        assert rtb._resolve_args(3.14, {}) == 3.14

    def test_missing_arg_raises(self):
        with pytest.raises(ValueError, match="Missing arg"):
            rtb._resolve_args("${args.nope}", {})

    def test_nested_arg_path(self):
        assert rtb._resolve_args("${args.a.b}", {"a": {"b": "deep"}}) == "deep"


class TestLookupArg:
    def test_missing_intermediate_raises(self):
        with pytest.raises(ValueError, match="Missing arg"):
            rtb._lookup_arg("a.b", {"a": {}})


# ---------------------------------------------------------------------------
# _step_error / _wait_after_step
# ---------------------------------------------------------------------------


class TestStepError:
    def test_full(self):
        err = rtb._step_error(3, "boom", "shell")
        assert err == {
            "ok": False,
            "error": "boom",
            "step": 3,
            "tool_name": "shell",
        }

    def test_no_step(self):
        err = rtb._step_error(None, "boom")
        assert err == {"ok": False, "error": "boom"}


class TestWaitAfterStep:
    def test_no_wait(self):
        import asyncio

        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            rtb._wait_after_step({}),
        )

    def test_zero_wait(self):
        import asyncio

        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            rtb._wait_after_step({"wait": 0}),
        )


# ---------------------------------------------------------------------------
# _run_steps — control flow (label / goto / set_var) with mocked tools
# ---------------------------------------------------------------------------


class TestRunStepsControlFlow:
    def test_set_var_and_label_and_goto_loop(self, patch_call_tool):
        patch_call_tool.return_value = _text_chunk("line")
        actions = [
            {"tool_name": "set_var", "arguments": {"expr": "i=0"}},
            {"tool_name": "label", "arguments": {"name": "loop"}},
            {"tool_name": "echo_tool", "arguments": {"x": "${vars.i}"}},
            {"tool_name": "set_var", "arguments": {"expr": "i=${vars.i}+1"}},
            {
                "tool_name": "goto",
                "arguments": {"label": "loop", "condition": "${vars.i}<3"},
            },
        ]
        results, blocks, last_text = _run(actions)
        # 3 tool invocations (i=0,1,2), then condition false -> exits
        assert patch_call_tool.call_count == 3
        assert all(r["ok"] for r in results)

    def test_maxstep_guard(self, patch_call_tool):
        patch_call_tool.return_value = _text_chunk("x")
        actions = [
            {"tool_name": "label", "arguments": {"name": "top"}},
            {"tool_name": "echo_tool", "arguments": {}},
            {"tool_name": "goto", "arguments": {"label": "top"}},
        ]
        results, _, _ = _run(actions, maxstep=5)
        last = results[-1]
        assert last["ok"] is False
        assert "Exceeded maximum execution steps" in last["error"]

    def test_recursive_run_tool_batch_rejected(self, patch_call_tool):
        actions = [{"tool_name": "run_tool_batch", "arguments": {}}]
        results, _, _ = _run(actions)
        assert results[0]["ok"] is False
        assert "Recursive" in results[0]["error"]

    def test_step_without_tool_name(self, patch_call_tool):
        results, _, _ = _run([{"arguments": {}}])
        assert results[0]["ok"] is False
        assert "tool_name" in results[0]["error"]

    def test_non_dict_step(self, patch_call_tool):
        results, _, _ = _run(["bad"])
        assert results[0]["ok"] is False
        assert "must be an object" in results[0]["error"]

    def test_non_dict_arguments(self, patch_call_tool):
        results, _, _ = _run([{"tool_name": "t", "arguments": "bad"}])
        assert results[0]["ok"] is False
        assert "arguments must be an object" in results[0]["error"]

    def test_unknown_label(self, patch_call_tool):
        actions = [{"tool_name": "goto", "arguments": {"label": "nowhere"}}]
        results, _, _ = _run(actions)
        assert results[0]["ok"] is False
        assert "Unknown label" in results[0]["error"]

    def test_goto_without_label(self, patch_call_tool):
        results, _, _ = _run([{"tool_name": "goto", "arguments": {}}])
        assert results[0]["ok"] is False
        assert "requires arguments.label" in results[0]["error"]

    def test_label_without_name_at_runtime(self, patch_call_tool):
        # label without name slips past _build_label_map only if name empty
        # after resolution — use a valid label map but empty name here.
        results, _, _ = _run([{"tool_name": "label", "arguments": {}}])
        assert results[0]["ok"] is False
        assert "requires arguments.name" in results[0]["error"]

    def test_goto_condition_false_no_jump(self, patch_call_tool):
        patch_call_tool.return_value = _text_chunk("ok")
        actions = [
            {"tool_name": "label", "arguments": {"name": "top"}},
            {"tool_name": "echo_tool", "arguments": {}},
            {
                "tool_name": "goto",
                "arguments": {"label": "top", "condition": "false"},
            },
        ]
        results, _, _ = _run(actions)
        # label + tool + goto (no jump) = 3 results, loop ends
        assert len(results) == 3
        assert patch_call_tool.call_count == 1

    def test_goto_condition_error_stop_on_error(self, patch_call_tool):
        actions = [
            {"tool_name": "label", "arguments": {"name": "l"}},
            {
                "tool_name": "goto",
                "arguments": {"label": "l", "condition": "a>b"},
                "stop_on_error": True,
            },
        ]
        results, _, _ = _run(actions)
        failed = [r for r in results if not r["ok"]]
        assert len(failed) == 1
        assert "Undefined variable: a" in failed[0]["error"]

    def test_goto_condition_error_continue_when_no_stop(self, patch_call_tool):
        patch_call_tool.return_value = _text_chunk("done")
        actions = [
            {
                "tool_name": "goto",
                "arguments": {"label": "missing", "condition": "a>b"},
                "stop_on_error": False,
            },
        ]
        # unknown label hits before condition; use a valid label instead
        actions = [
            {"tool_name": "label", "arguments": {"name": "l"}},
            {
                "tool_name": "goto",
                "arguments": {"label": "l", "condition": "a>b"},
                "stop_on_error": False,
            },
            {"tool_name": "echo_tool", "arguments": {}},
        ]
        results, _, _ = _run(actions, stop_on_error=False)
        # continues past the failed goto and runs echo_tool
        assert patch_call_tool.call_count == 1

    def test_set_var_error_stop(self, patch_call_tool):
        actions = [
            {"tool_name": "set_var", "arguments": {"expr": "i=undefined_var"}},
        ]
        results, _, _ = _run(actions)
        assert results[0]["ok"] is False

    def test_set_var_error_continue(self, patch_call_tool):
        patch_call_tool.return_value = _text_chunk("ok")
        actions = [
            {
                "tool_name": "set_var",
                "arguments": {"expr": "i=undefined_var"},
                "stop_on_error": False,
            },
            {"tool_name": "echo_tool", "arguments": {}},
        ]
        results, _, _ = _run(actions, stop_on_error=False)
        assert patch_call_tool.call_count == 1

    def test_set_var_missing_expr(self, patch_call_tool):
        results, _, _ = _run([{"tool_name": "set_var", "arguments": {}}])
        assert results[0]["ok"] is False
        assert "requires arguments.expr" in results[0]["error"]

    def test_step_ref_resolution_error_stop(self, patch_call_tool):
        actions = [
            {"tool_name": "echo_tool", "arguments": {"x": "${steps.9.text}"}},
        ]
        results, _, _ = _run(actions)
        assert results[0]["ok"] is False
        assert "no result" in results[0]["error"]

    def test_step_ref_resolution_error_continue(self, patch_call_tool):
        patch_call_tool.return_value = _text_chunk("ok")
        actions = [
            {
                "tool_name": "echo_tool",
                "arguments": {"x": "${steps.9.text}"},
                "stop_on_error": False,
            },
            {"tool_name": "echo_tool", "arguments": {"x": "fine"}},
        ]
        results, _, _ = _run(actions, stop_on_error=False)
        assert patch_call_tool.call_count == 1
        assert results[-1]["ok"] is True

    def test_tool_error_state_stops(self, patch_call_tool):
        patch_call_tool.side_effect = [
            _text_chunk("Error: first failed", ToolResultState.ERROR),
            _text_chunk("never"),
        ]
        actions = [
            {"tool_name": "t1", "arguments": {}},
            {"tool_name": "t2", "arguments": {}},
        ]
        results, _, _ = _run(actions)
        assert len(results) == 1
        assert results[0]["ok"] is False

    def test_tool_error_continues_when_no_stop(self, patch_call_tool):
        patch_call_tool.side_effect = [
            _text_chunk("Error: first failed", ToolResultState.ERROR),
            _text_chunk("second ok"),
        ]
        actions = [
            {"tool_name": "t1", "arguments": {}},
            {"tool_name": "t2", "arguments": {}},
        ]
        results, _, _ = _run(actions, stop_on_error=False)
        assert len(results) == 2

    def test_non_text_blocks_collected_and_files_info(self, patch_call_tool):
        data_block = DataBlock(
            type="data",
            source=URLSource(
                type="url",
                url="http://x/a.png",
                media_type="image/png",
            ),
            name="a.png",
        )
        patch_call_tool.return_value = ToolChunk(
            state=ToolResultState.SUCCESS,
            content=[TextBlock(type="text", text="ok"), data_block],
        )
        actions = [{"tool_name": "t", "arguments": {}}]
        results, blocks, last_text = _run(actions)
        assert len(blocks) == 1  # data block collected
        assert results[0]["files"] == [
            {"url": "http://x/a.png", "name": "a.png"},
        ]

    def test_interrupted_state_breaks(self, patch_call_tool):
        patch_call_tool.return_value = ToolChunk(
            state=ToolResultState.INTERRUPTED,
            content=[],
        )
        actions = [
            {"tool_name": "t1", "arguments": {}},
            {"tool_name": "t2", "arguments": {}},
        ]
        results, _, _ = _run(actions)
        # interrupted -> break before recording result
        assert len(results) == 0
        assert patch_call_tool.call_count == 1

    def test_label_map_error_returns_error_result(self, patch_call_tool):
        actions = [
            {"tool_name": "label", "arguments": {"name": "dup"}},
            {"tool_name": "label", "arguments": {"name": "dup"}},
        ]
        results, blocks, last = _run(actions)
        assert results[0]["ok"] is False
        assert "Duplicate label" in results[0]["error"]


# ---------------------------------------------------------------------------
# _call_tool error paths (no toolkit / no agent state / exception)
# ---------------------------------------------------------------------------


class TestCallTool:
    def test_no_toolkit(self):
        import asyncio

        async def _go():
            with patch.object(rtb, "get_current_toolkit", return_value=None):
                return await rtb._call_tool("anything", {})

        chunk = (
            asyncio.get_event_loop_policy()
            .new_event_loop()
            .run_until_complete(_go())
        )
        payload = rtb._response_payload(chunk)
        assert payload["ok"] is False
        assert "No toolkit" in payload["error"]

    def test_no_agent_state(self):
        import asyncio

        async def _go():
            with patch.object(
                rtb,
                "get_current_toolkit",
                return_value=object(),
            ):
                with patch.object(
                    rtb,
                    "get_current_agent_state",
                    return_value=None,
                ):
                    return await rtb._call_tool("anything", {})

        chunk = (
            asyncio.get_event_loop_policy()
            .new_event_loop()
            .run_until_complete(_go())
        )
        payload = rtb._response_payload(chunk)
        assert payload["ok"] is False
        assert "No agent state" in payload["error"]

    def test_tool_exception_caught(self):
        import asyncio

        class _Toolkit:
            async def call_tool(self, tool_call, agent_state):
                raise RuntimeError("kaboom")
                yield  # pragma: no cover — marks as async generator

        async def _go():
            with patch.object(
                rtb,
                "get_current_toolkit",
                return_value=_Toolkit(),
            ):
                with patch.object(
                    rtb,
                    "get_current_agent_state",
                    return_value=object(),
                ):
                    return await rtb._call_tool("anything", {})

        chunk = (
            asyncio.get_event_loop_policy()
            .new_event_loop()
            .run_until_complete(_go())
        )
        payload = rtb._response_payload(chunk)
        assert payload["ok"] is False
        assert "kaboom" in payload["error"]

    def test_empty_stream_returns_no_response_error(self):
        import asyncio

        class _Toolkit:
            async def call_tool(self, tool_call, agent_state):
                return
                yield  # pragma: no cover

        async def _go():
            with patch.object(
                rtb,
                "get_current_toolkit",
                return_value=_Toolkit(),
            ):
                with patch.object(
                    rtb,
                    "get_current_agent_state",
                    return_value=object(),
                ):
                    return await rtb._call_tool("anything", {})

        chunk = (
            asyncio.get_event_loop_policy()
            .new_event_loop()
            .run_until_complete(_go())
        )
        payload = rtb._response_payload(chunk)
        assert payload["ok"] is False
        assert "no response" in payload["error"]

    def test_interrupted_chunk_stops_stream(self):
        import asyncio

        class _Toolkit:
            async def call_tool(self, tool_call, agent_state):
                yield ToolChunk(state=ToolResultState.INTERRUPTED, content=[])
                yield ToolChunk(state=ToolResultState.SUCCESS, content=[])

        async def _go():
            with patch.object(
                rtb,
                "get_current_toolkit",
                return_value=_Toolkit(),
            ):
                with patch.object(
                    rtb,
                    "get_current_agent_state",
                    return_value=object(),
                ):
                    return await rtb._call_tool("anything", {})

        chunk = (
            asyncio.get_event_loop_policy()
            .new_event_loop()
            .run_until_complete(_go())
        )
        assert chunk.state == ToolResultState.INTERRUPTED


# ---------------------------------------------------------------------------
# _build_batch_response / last_only shaping
# ---------------------------------------------------------------------------


def _summary_payload(chunk: ToolChunk) -> dict:
    """Parse the JSON summary from a batch response's first block."""
    first = chunk.content[0]
    text = first.get("text") if isinstance(first, dict) else first.text
    return json.loads(text)


class TestBuildBatchResponse:
    def test_all_ok_response(self):
        results = [{"step": 0, "ok": True, "text": "a"}]
        chunk = rtb._build_batch_response([{}], results, [])
        payload = _summary_payload(chunk)
        assert payload["ok"] is True
        assert payload["total"] == 1
        assert payload["completed"] == 1
        assert chunk.state == ToolResultState.SUCCESS

    def test_failed_response_includes_error(self):
        results = [{"step": 0, "ok": False, "error": "boom"}]
        chunk = rtb._build_batch_response([{}], results, [])
        payload = _summary_payload(chunk)
        assert payload["ok"] is False
        assert payload["error"] == "boom"
        assert chunk.state == ToolResultState.ERROR

    def test_last_only_shape(self):
        results = [
            {"step": 0, "ok": True, "text": "a"},
            {"step": 1, "ok": True, "text": "b"},
        ]
        chunk = rtb._build_batch_response(
            [{}, {}],
            results,
            [],
            last_only=True,
        )
        payload = _summary_payload(chunk)
        assert "results" not in payload
        assert payload["last_step_result"] == results[-1]

    def test_content_blocks_appended(self):
        block = DataBlock(
            type="data",
            source=URLSource(
                type="url",
                url="http://x/u.png",
                media_type="image/png",
            ),
            name="n",
        )
        chunk = rtb._build_batch_response(
            [{}],
            [{"step": 0, "ok": True}],
            [block],
        )
        assert block in chunk.content


class TestShouldIncludeLastTextBlock:
    def test_none_block(self):
        assert (
            rtb._should_include_last_text_block(None, [{"ok": True}]) is False
        )

    def test_empty_results(self):
        assert rtb._should_include_last_text_block({"text": "x"}, []) is False

    def test_text_already_in_result(self):
        block = {"type": "text", "text": "same"}
        results = [{"step": 0, "ok": True, "text": "same"}]
        assert rtb._should_include_last_text_block(block, results) is False

    def test_json_value_matches_result(self):
        # Parsed JSON equals the result's ``value`` field -> duplicated.
        block = {"type": "text", "text": json.dumps([1, 2])}
        results = [{"step": 0, "tool_name": "t", "ok": True, "value": [1, 2]}]
        assert rtb._should_include_last_text_block(block, results) is False

    def test_json_matches_full_result_minus_meta(self):
        body = {"ok": True, "text": "x"}
        block = {"type": "text", "text": json.dumps(body)}
        results = [{"step": 0, "tool_name": "t", "ok": True, "text": "x"}]
        assert rtb._should_include_last_text_block(block, results) is False

    def test_different_text_included(self):
        block = {"type": "text", "text": "unique"}
        results = [{"step": 0, "ok": True, "text": "other"}]
        assert rtb._should_include_last_text_block(block, results) is True

    def test_non_string_text_field(self):
        block = {"type": "text"}  # no text key -> None
        results = [{"step": 0, "ok": True}]
        assert rtb._should_include_last_text_block(block, results) is False


class TestLastStepResultContainsText:
    def test_invalid_json_returns_false(self):
        assert (
            rtb._last_step_result_contains_text({"text": "other"}, "not json")
            is False
        )

    def test_json_none_value(self):
        assert (
            rtb._last_step_result_contains_text({"value": [1]}, "[1]") is True
        )


# ---------------------------------------------------------------------------
# input validation helpers
# ---------------------------------------------------------------------------


class TestPrepareBatchInputs:
    def test_both_actions_and_file_raises(self):
        with pytest.raises(ValueError, match="not both"):
            rtb._prepare_batch_inputs([{}], "/tmp/x.json", None, 10)

    def test_actions_json_string(self):
        actions, maxstep = rtb._prepare_batch_inputs(
            json.dumps([{"tool_name": "label", "arguments": {"name": "a"}}]),
            "",
            None,
            10,
        )
        assert actions[0]["tool_name"] == "label"
        assert maxstep == 10

    def test_invalid_actions_json_string(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            rtb._prepare_batch_inputs("not json", "", None, 10)

    def test_args_json_string(self, tmp_path):
        # ${args.*} substitution applies when loading from a file.
        f = tmp_path / "a.json"
        f.write_text(
            json.dumps(
                {
                    "actions": [
                        {"tool_name": "t", "arguments": {"x": "${args.v}"}},
                    ],
                },
            ),
        )
        actions, _ = rtb._prepare_batch_inputs(
            None,
            str(f),
            json.dumps({"v": "ok"}),
            10,
        )
        assert actions[0]["arguments"]["x"] == "ok"

    def test_invalid_args_json_string(self):
        with pytest.raises(ValueError, match="JSON string"):
            rtb._prepare_batch_inputs([{}], "", "bad json", 10)

    def test_args_non_object(self):
        with pytest.raises(ValueError, match="must be an object"):
            rtb._prepare_batch_inputs([{}], "", 123, 10)

    def test_empty_actions_raises(self):
        with pytest.raises(ValueError, match="non-empty list"):
            rtb._prepare_batch_inputs([], "", None, 10)

    def test_none_actions_no_file_raises(self):
        with pytest.raises(ValueError, match="non-empty list"):
            rtb._prepare_batch_inputs(None, "", None, 10)

    def test_too_many_steps_raises(self):
        actions = [
            {"tool_name": "label", "arguments": {"name": f"l{i}"}}
            for i in range(51)
        ]
        with pytest.raises(ValueError, match="Too many steps"):
            rtb._prepare_batch_inputs(actions, "", None, 10)

    def test_maxstep_zero_raises(self):
        with pytest.raises(ValueError, match="positive integer"):
            rtb._prepare_batch_inputs([{}], "", None, 0)

    def test_maxstep_non_numeric_raises(self):
        with pytest.raises(ValueError, match="positive integer"):
            rtb._prepare_batch_inputs([{}], "", None, "abc")

    def test_file_path_loads_and_resolves_args(self, tmp_path):
        f = tmp_path / "b.json"
        f.write_text(
            json.dumps(
                {
                    "actions": [
                        {"tool_name": "t", "arguments": {"x": "${args.v}"}},
                    ],
                },
            ),
        )
        actions, maxstep = rtb._prepare_batch_inputs(
            None,
            str(f),
            {"v": 42},
            10,
        )
        assert actions[0]["arguments"]["x"] == 42


# ---------------------------------------------------------------------------
# run_tool_batch top-level entry point
# ---------------------------------------------------------------------------


class TestRunToolBatchEntry:
    def test_invalid_input_returns_error_chunk(self):
        import asyncio

        chunk = (
            asyncio.get_event_loop_policy()
            .new_event_loop()
            .run_until_complete(
                rtb.run_tool_batch.__wrapped__(
                    actions=None,
                    file_path="",
                    args=None,
                )
                if hasattr(rtb.run_tool_batch, "__wrapped__")
                else rtb.run_tool_batch(actions=None, file_path="", args=None),
            )
        )
        payload = rtb._response_payload(chunk)
        assert payload["ok"] is False

    def test_full_batch_with_mocked_tools(self, patch_call_tool):
        import asyncio

        patch_call_tool.return_value = _text_chunk("done")
        actions = [
            {"tool_name": "set_var", "arguments": {"expr": "i=1"}},
            {"tool_name": "echo_tool", "arguments": {"x": "${vars.i}"}},
        ]
        chunk = (
            asyncio.get_event_loop_policy()
            .new_event_loop()
            .run_until_complete(
                rtb.run_tool_batch.__wrapped__(
                    actions=actions,
                    file_path="",
                    args=None,
                )
                if hasattr(rtb.run_tool_batch, "__wrapped__")
                else rtb.run_tool_batch(
                    actions=actions,
                    file_path="",
                    args=None,
                ),
            )
        )
        payload = rtb._response_payload(chunk)
        assert payload["ok"] is True
        assert payload["completed"] == 2

    def test_last_only_entry(self, patch_call_tool):
        import asyncio

        patch_call_tool.return_value = _text_chunk("done")
        actions = [{"tool_name": "echo_tool", "arguments": {}}]
        chunk = (
            asyncio.get_event_loop_policy()
            .new_event_loop()
            .run_until_complete(
                rtb.run_tool_batch.__wrapped__(
                    actions=actions,
                    file_path="",
                    args=None,
                    last_only=True,
                )
                if hasattr(rtb.run_tool_batch, "__wrapped__")
                else rtb.run_tool_batch(
                    actions=actions,
                    file_path="",
                    args=None,
                    last_only=True,
                ),
            )
        )
        payload = rtb._response_payload(chunk)
        assert payload["ok"] is True
        assert "last_step_result" in payload
