# -*- coding: utf-8 -*-
# pylint: disable=unreachable,protected-access,too-many-public-methods,unnecessary-lambda,unused-argument,unused-import  # noqa: E501
"""Unit tests for the run_tool_batch engine.

Coverage-driven backfill (batch 2, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: the reference-resolution,
condition/arithmetic evaluation, batch-file loading, control-flow loop,
and tool-call plumbing in ``run_tool_batch``, which previously sat at
~13% coverage.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from agentscope.message import DataBlock, TextBlock, ToolResultState, URLSource
from agentscope.tool import ToolChunk

# Note: ``qwenpaw.agents.tools.run_tool_batch`` (the module) is shadowed by
# the same-named function exported from ``qwenpaw.agents.tools``, so the
# module must be imported via importlib to reach the internals.
rtb = importlib.import_module("qwenpaw.agents.tools.run_tool_batch")


def _ok_chunk(
    payload: dict | None = None,
    text: str | None = None,
) -> ToolChunk:
    if text is not None:
        return ToolChunk(
            state=ToolResultState.SUCCESS,
            content=[TextBlock(type="text", text=text)],
        )
    return rtb._json_tool_response({"ok": True, **(payload or {})})


def _make_mock_call_tool(monkeypatch, handler):
    """Patch the module-level ``_call_tool`` used by ``_run_steps``."""
    calls: list[tuple[str, dict]] = []

    async def fake(tool_name: str, arguments: dict) -> ToolChunk:
        calls.append((tool_name, arguments))
        return await handler(tool_name, arguments)

    monkeypatch.setattr(rtb, "_call_tool", fake)
    return calls


# ---------------------------------------------------------------------------
# Step / var reference resolution
# ---------------------------------------------------------------------------


class TestResolveStepRefs:
    RESULTS = [
        {"step": 0, "tool_name": "a", "ok": True, "text": "first", "n": 7},
        {
            "step": 1,
            "tool_name": "b",
            "ok": True,
            "value": {"items": [10, 20]},
        },
    ]

    def test_exact_step_ref_preserves_type(self):
        got = rtb.resolve_step_refs("${steps.0.n}", self.RESULTS)
        assert got == 7
        assert isinstance(got, int)

    def test_exact_step_ref_whole_result(self):
        got = rtb.resolve_step_refs("${steps.0}", self.RESULTS)
        assert got["text"] == "first"

    def test_nested_dict_path(self):
        got = rtb.resolve_step_refs("${steps.1.value.items}", self.RESULTS)
        assert got == [10, 20]

    def test_list_index_path(self):
        got = rtb.resolve_step_refs("${steps.1.value.items.1}", self.RESULTS)
        assert got == 20

    def test_missing_step_raises(self):
        with pytest.raises(ValueError, match="no result"):
            rtb.resolve_step_refs("${steps.9.n}", self.RESULTS)

    def test_missing_key_raises(self):
        with pytest.raises(ValueError, match="Missing key"):
            rtb.resolve_step_refs("${steps.0.nope}", self.RESULTS)

    def test_list_index_out_of_range_raises(self):
        with pytest.raises(ValueError, match="out of range"):
            rtb.resolve_step_refs("${steps.1.value.items.9}", self.RESULTS)

    def test_non_digit_list_index_raises(self):
        with pytest.raises(ValueError, match="Invalid list index"):
            rtb.resolve_step_refs("${steps.1.value.items.x}", self.RESULTS)

    def test_scalar_traversal_raises(self):
        with pytest.raises(ValueError, match="Cannot resolve"):
            rtb.resolve_step_refs("${steps.0.text.deeper}", self.RESULTS)

    def test_inline_ref_stringified(self):
        got = rtb.resolve_step_refs("n=${steps.1.value}", self.RESULTS)
        assert got == 'n={"items": [10, 20]}'

    def test_var_ref_exact(self):
        got = rtb.resolve_step_refs("${vars.i}", [], {"i": 3})
        assert got == 3

    def test_var_ref_inline(self):
        got = rtb.resolve_step_refs("i is ${vars.i} now", [], {"i": 3})
        assert got == "i is 3 now"

    def test_missing_var_raises(self):
        with pytest.raises(ValueError, match="Missing var"):
            rtb.resolve_step_refs("${vars.nope}", [], {})

    def test_recursive_structures(self):
        got = rtb.resolve_step_refs(
            {"a": ["${steps.0.n}", {"b": "${vars.i}"}], "c": 5},
            self.RESULTS,
            {"i": "x"},
        )
        assert got == {"a": [7, {"b": "x"}], "c": 5}

    def test_non_string_passthrough(self):
        assert rtb.resolve_step_refs(42, self.RESULTS) == 42
        assert rtb.resolve_step_refs(None, self.RESULTS) is None

    def test_latest_execution_wins_for_repeated_step(self):
        results = [
            {"step": 0, "value": "old"},
            {"step": 1, "value": "x"},
            {"step": 0, "value": "new"},
        ]
        assert rtb.resolve_step_refs("${steps.0.value}", results) == "new"


class TestBuildLabelMap:
    def test_collects_labels(self):
        actions = [
            {"tool_name": "label", "arguments": {"name": "top"}},
            {"tool_name": "echo"},
            {"tool": "label", "arguments": {"name": "end"}},
        ]
        assert rtb._build_label_map(actions) == {"top": 0, "end": 2}

    def test_duplicate_label_raises(self):
        actions = [
            {"tool_name": "label", "arguments": {"name": "x"}},
            {"tool_name": "label", "arguments": {"name": "x"}},
        ]
        with pytest.raises(ValueError, match="Duplicate label"):
            rtb._build_label_map(actions)

    def test_missing_name_raises(self):
        with pytest.raises(ValueError, match="requires arguments.name"):
            rtb._build_label_map(
                [{"tool_name": "label", "arguments": {}}],
            )

    def test_non_dict_arguments_raises(self):
        with pytest.raises(ValueError, match="must be an object"):
            rtb._build_label_map(
                [{"tool_name": "label", "arguments": "x"}],
            )

    def test_non_dict_steps_are_ignored(self):
        assert rtb._build_label_map(["junk", 5]) == {}


# ---------------------------------------------------------------------------
# Scalar parsing, tokens, conditions, arithmetic
# ---------------------------------------------------------------------------


class TestParseScalar:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("true", True),
            ("False", False),
            ("7", 7),
            ("-3", -3),
            ("1.5", "1.5"),
            ("x", "x"),
        ],
    )
    def test_scalars(self, raw, expected):
        assert rtb._parse_scalar(raw) == expected

    def test_non_string_passthrough(self):
        assert rtb._parse_scalar(9) == 9


class TestEvaluateCondition:
    @pytest.mark.parametrize(
        ("expr", "expected"),
        [
            ("1>2", False),
            ("3>2", True),
            ("2<5", True),
            ("2<=2", True),
            ("3>=4", False),
            ("a==a", True),
            ("a!=b", True),
        ],
    )
    def test_comparisons(self, expr, expected):
        # Bare identifiers resolve as variables, so seed them explicitly.
        variables = {"a": "a", "b": "b"}
        assert rtb._evaluate_condition(expr, [], variables) is expected

    def test_plain_true(self):
        assert rtb._evaluate_condition("true", [], {}) is True

    def test_plain_false(self):
        assert rtb._evaluate_condition("false", [], {}) is False

    def test_int_truthiness(self):
        assert rtb._evaluate_condition("1", [], {}) is True
        assert rtb._evaluate_condition("0", [], {}) is False

    def test_var_refs_in_condition(self):
        assert rtb._evaluate_condition(
            "${vars.i}<=${vars.total}",
            [],
            {"i": 2, "total": 3},
        )
        assert not rtb._evaluate_condition(
            "${vars.i}<=${vars.total}",
            [],
            {"i": 4, "total": 3},
        )

    def test_steps_refs_in_condition(self):
        results = [{"step": 0, "value": 5}]
        assert rtb._evaluate_condition("${steps.0.value}>3", results, {})

    def test_undefined_variable_raises(self):
        with pytest.raises(ValueError, match="Undefined variable"):
            rtb._evaluate_condition("nope", [], {})

    def test_unsupported_condition_raises(self):
        with pytest.raises(ValueError, match="Unsupported condition"):
            rtb._evaluate_condition("a>1", [], {"a": {}})

    def test_empty_token_raises(self):
        with pytest.raises(ValueError, match="invalid"):
            rtb._evaluate_condition("   ", [], {})


class TestEvaluateArithmetic:
    @pytest.mark.parametrize(
        ("expr", "expected"),
        [
            ("1+2", 3),
            ("10-4", 6),
            ("3*4", 12),
            ("7/2", 3.5),
            ("7%3", 1),
            ("-5", -5),
            ("+5", 5),
            ("(1+2)*3", 9),
            ("2+3*4", 14),
        ],
    )
    def test_numeric_expressions(self, expr, expected):
        assert rtb._evaluate_arithmetic_expr(expr, {}) == expected

    def test_variable_lookup(self):
        assert rtb._evaluate_arithmetic_expr("i+1", {"i": 4}) == 5

    def test_division_by_zero_raises(self):
        with pytest.raises(ValueError, match="division by zero"):
            rtb._evaluate_arithmetic_expr("1/0", {})

    def test_unknown_variable_raises(self):
        # Internal errors are wrapped in the generic assignment message.
        with pytest.raises(ValueError, match="numeric expression"):
            rtb._evaluate_arithmetic_expr("j+1", {})

    def test_boolean_rejected(self):
        with pytest.raises(ValueError):
            rtb._evaluate_arithmetic_expr("True", {})

    def test_boolean_variable_rejected(self):
        with pytest.raises(ValueError, match="numeric"):
            rtb._evaluate_arithmetic_expr("b+1", {"b": True})

    def test_string_literal_rejected(self):
        with pytest.raises(ValueError, match="numeric expression"):
            rtb._evaluate_arithmetic_expr("'x'", {})

    def test_call_rejected(self):
        with pytest.raises(ValueError, match="numeric expression"):
            rtb._evaluate_arithmetic_expr("abs(1)", {})

    def test_attribute_rejected(self):
        with pytest.raises(ValueError, match="numeric expression"):
            rtb._evaluate_arithmetic_expr("a.b", {"a": SimpleNamespace(b=1)})

    def test_power_operator_rejected(self):
        with pytest.raises(ValueError, match="numeric expression"):
            rtb._evaluate_arithmetic_expr("2**3", {})

    def test_syntax_error_raises(self):
        with pytest.raises(ValueError, match="numeric expression"):
            rtb._evaluate_arithmetic_expr("1+", {})


class TestEvaluateSetVarExpr:
    def test_simple_int(self):
        assert rtb._evaluate_set_var_expr("i=0", [], {}) == ("i", 0)

    def test_arithmetic_with_var(self):
        assert rtb._evaluate_set_var_expr("i=${vars.i}+1", [], {"i": 2}) == (
            "i",
            3,
        )

    def test_arithmetic_with_parens(self):
        assert rtb._evaluate_set_var_expr(
            "i=(${vars.i}+1)*2",
            [],
            {"i": 2},
        ) == ("i", 6)

    def test_from_step_ref(self):
        results = [{"step": 1, "value": 5}]
        assert rtb._evaluate_set_var_expr(
            "total=${steps.1.value}",
            results,
            {},
        ) == ("total", 5)

    def test_string_literal(self):
        # Bare identifiers look like variables; use a non-identifier literal.
        assert rtb._evaluate_set_var_expr("name=hello world", [], {}) == (
            "name",
            "hello world",
        )

    def test_bare_identifier_rhs_is_undefined_variable(self):
        with pytest.raises(ValueError, match="Undefined variable"):
            rtb._evaluate_set_var_expr("name=hello", [], {})

    def test_bool_string(self):
        assert rtb._evaluate_set_var_expr("flag=true", [], {}) == (
            "flag",
            True,
        )

    def test_non_string_rhs_passthrough(self):
        results = [{"step": 0, "value": {"k": 1}}]
        assert rtb._evaluate_set_var_expr(
            "d=${steps.0.value}",
            results,
            {},
        ) == ("d", {"k": 1})

    def test_invalid_assignment_raises(self):
        with pytest.raises(ValueError, match="simple assignment"):
            rtb._evaluate_set_var_expr("no equals sign", [], {})

    def test_arithmetic_looking_rhs_with_unknown_var_raises(self):
        with pytest.raises(ValueError):
            rtb._evaluate_set_var_expr("x=undefined_var+1", [], {})


# ---------------------------------------------------------------------------
# Batch file loading and args substitution
# ---------------------------------------------------------------------------


class TestLoadBatchFile:
    def test_plain_array(self, tmp_path):
        path = tmp_path / "batch.json"
        path.write_text(json.dumps([{"tool_name": "x"}]), encoding="utf-8")
        assert rtb._load_batch_file(str(path)) == [{"tool_name": "x"}]

    def test_actions_object(self, tmp_path):
        path = tmp_path / "batch.json"
        path.write_text(
            json.dumps({"actions": [{"tool_name": "x"}]}),
            encoding="utf-8",
        )
        assert rtb._load_batch_file(str(path)) == [{"tool_name": "x"}]

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ValueError, match="not found"):
            rtb._load_batch_file(str(tmp_path / "nope.json"))

    def test_wrong_extension_raises(self, tmp_path):
        path = tmp_path / "batch.txt"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError, match=r"\.json"):
            rtb._load_batch_file(str(path))

    def test_invalid_json_raises(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            rtb._load_batch_file(str(path))

    def test_bad_shape_raises(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"nope": 1}), encoding="utf-8")
        with pytest.raises(ValueError, match="actions"):
            rtb._load_batch_file(str(path))

    def test_empty_path_raises(self):
        with pytest.raises(ValueError, match="required"):
            rtb._load_batch_file("   ")


class TestResolveArgs:
    def test_exact_ref_preserves_type(self):
        assert rtb._resolve_args("${args.n}", {"n": 5}) == 5

    def test_inline_ref(self):
        assert (
            rtb._resolve_args("dir=${args.folder}", {"folder": "/d"})
            == "dir=/d"
        )

    def test_inline_non_string_jsonified(self):
        assert rtb._resolve_args("x=${args.n}", {"n": 5}) == "x=5"

    def test_dotted_path(self):
        assert rtb._resolve_args("${args.a.b}", {"a": {"b": "deep"}}) == "deep"

    def test_missing_arg_raises(self):
        with pytest.raises(ValueError, match="Missing arg"):
            rtb._resolve_args("${args.nope}", {})

    def test_missing_nested_arg_raises(self):
        with pytest.raises(ValueError, match="Missing arg"):
            rtb._resolve_args("${args.a.b}", {"a": 5})

    def test_nested_structures(self):
        got = rtb._resolve_args(
            {"cmd": ["${args.x}", {"y": "${args.y}"}]},
            {"x": 1, "y": "z"},
        )
        assert got == {"cmd": [1, {"y": "z"}]}

    def test_non_string_passthrough(self):
        assert rtb._resolve_args(7, {}) == 7


# ---------------------------------------------------------------------------
# _call_tool plumbing (contextvars + toolkit mocking)
# ---------------------------------------------------------------------------


class TestCallTool:
    async def test_no_toolkit_returns_error(self, monkeypatch):
        monkeypatch.setattr(rtb, "get_current_toolkit", lambda: None)
        response = await rtb._call_tool("any", {})
        payload = json.loads(rtb._extract_text(response))
        assert payload == {
            "ok": False,
            "error": "No toolkit available in current context",
        }
        assert response.state == ToolResultState.ERROR

    async def test_no_agent_state_returns_error(self, monkeypatch):
        monkeypatch.setattr(rtb, "get_current_toolkit", lambda: object())
        monkeypatch.setattr(rtb, "get_current_agent_state", lambda: None)
        response = await rtb._call_tool("any", {})
        payload = json.loads(rtb._extract_text(response))
        assert (
            payload["error"] == "No agent state available in current context"
        )

    async def test_successful_call_returns_last_chunk(self, monkeypatch):
        async def stream(tool_call, agent_state):
            yield _ok_chunk(text="partial")
            yield _ok_chunk(text="final")

        toolkit = SimpleNamespace(call_tool=lambda tc, st: stream(tc, st))
        monkeypatch.setattr(rtb, "get_current_toolkit", lambda: toolkit)
        monkeypatch.setattr(rtb, "get_current_agent_state", lambda: object())

        response = await rtb._call_tool("demo", {"a": 1})
        assert rtb._extract_text(response) == "final"

    async def test_interrupted_chunk_is_terminal(self, monkeypatch):
        async def stream(tool_call, agent_state):
            yield ToolChunk(state=ToolResultState.INTERRUPTED, content=[])
            yield _ok_chunk(text="should never appear")

        toolkit = SimpleNamespace(call_tool=lambda tc, st: stream(tc, st))
        monkeypatch.setattr(rtb, "get_current_toolkit", lambda: toolkit)
        monkeypatch.setattr(rtb, "get_current_agent_state", lambda: object())

        response = await rtb._call_tool("demo", {})
        assert response.state == ToolResultState.INTERRUPTED

    async def test_empty_stream_returns_error(self, monkeypatch):
        async def stream(tool_call, agent_state):
            return
            yield  # pragma: no cover

        toolkit = SimpleNamespace(call_tool=lambda tc, st: stream(tc, st))
        monkeypatch.setattr(rtb, "get_current_toolkit", lambda: toolkit)
        monkeypatch.setattr(rtb, "get_current_agent_state", lambda: object())

        response = await rtb._call_tool("demo", {})
        payload = json.loads(rtb._extract_text(response))
        assert payload["ok"] is False
        assert "returned no response" in payload["error"]

    async def test_tool_exception_wrapped(self, monkeypatch):
        async def stream(tool_call, agent_state):
            raise RuntimeError("boom")
            yield  # pragma: no cover

        toolkit = SimpleNamespace(call_tool=lambda tc, st: stream(tc, st))
        monkeypatch.setattr(rtb, "get_current_toolkit", lambda: toolkit)
        monkeypatch.setattr(rtb, "get_current_agent_state", lambda: object())

        response = await rtb._call_tool("demo", {})
        payload = json.loads(rtb._extract_text(response))
        assert payload == {"ok": False, "error": "RuntimeError: boom"}


# ---------------------------------------------------------------------------
# Response payload normalisation
# ---------------------------------------------------------------------------


class TestResponsePayload:
    def test_json_dict_with_explicit_ok(self):
        payload = rtb._response_payload(_ok_chunk({"value": 1}))
        assert payload["ok"] is True
        assert payload["value"] == 1

    def test_json_dict_without_ok_success(self):
        chunk = ToolChunk(
            state=ToolResultState.SUCCESS,
            content=[TextBlock(type="text", text='{"value": 2}')],
        )
        payload = rtb._response_payload(chunk)
        assert payload["ok"] is True

    def test_error_state_forces_ok_false(self):
        chunk = ToolChunk(
            state=ToolResultState.ERROR,
            content=[TextBlock(type="text", text='{"ok": true}')],
        )
        payload = rtb._response_payload(chunk)
        assert payload["ok"] is False

    def test_json_non_dict_wrapped_as_value(self):
        chunk = ToolChunk(
            state=ToolResultState.SUCCESS,
            content=[TextBlock(type="text", text="[1, 2]")],
        )
        payload = rtb._response_payload(chunk)
        assert payload == {
            "ok": True,
            "value": [1, 2],
            "_raw_blocks": list(chunk.content),
        }

    def test_plain_text_ok(self):
        chunk = _ok_chunk(text="hello")
        payload = rtb._response_payload(chunk)
        assert payload["ok"] is True
        assert payload["text"] == "hello"
        assert payload["_raw_blocks"] == list(chunk.content)

    def test_plain_text_error_prefix(self):
        payload = rtb._response_payload(_ok_chunk(text="Error: bad"))
        assert payload["ok"] is False

    def test_denied_state_is_error(self):
        chunk = ToolChunk(
            state=ToolResultState.DENIED,
            content=[TextBlock(type="text", text="nope")],
        )
        assert rtb._response_payload(chunk)["ok"] is False


class TestExtractHelpers:
    def test_extract_text_skips_non_text_blocks(self):
        chunk = ToolChunk(
            state=ToolResultState.SUCCESS,
            content=[
                DataBlock(
                    type="data",
                    source=URLSource(
                        url="file:///x",
                        media_type="text/plain",
                    ),
                ),
                TextBlock(type="text", text="obj"),
            ],
        )
        assert rtb._extract_text(chunk) == "obj"

    def test_extract_text_empty_when_missing(self):
        chunk = ToolChunk(state=ToolResultState.SUCCESS, content=[])
        assert rtb._extract_text(chunk) == ""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Error: x", True),
            ("ERROR: x", True),
            ("Command failed with exit code 1", True),
            ("all good", False),
            ("the Error is inside", False),
        ],
    )
    def test_is_error_text(self, text, expected):
        assert rtb._is_error_text(text) is expected

    def test_extract_files_info(self):
        blocks = [
            {
                "type": "data",
                "source": {"url": "file:///a.txt"},
                "name": "a.txt",
            },
            SimpleNamespace(
                type="data",
                source=SimpleNamespace(url="file:///b"),
                name="",
            ),
            {"type": "text", "text": "x"},
            {"type": "data", "source": None},
        ]
        assert rtb._extract_files_info(blocks) == [
            {"url": "file:///a.txt", "name": "a.txt"},
            {"url": "file:///b", "name": ""},
        ]


# ---------------------------------------------------------------------------
# End-to-end batch execution (control flow via mocked _call_tool)
# ---------------------------------------------------------------------------


class TestRunStepsControlFlow:
    async def test_sequential_steps_and_summary(self, monkeypatch):
        async def handler(name, arguments):
            return _ok_chunk({"echo": arguments.get("x")})

        _make_mock_call_tool(monkeypatch, handler)
        response = await rtb.run_tool_batch(
            actions=[
                {"tool_name": "t1", "arguments": {"x": 1}},
                {"tool_name": "t2", "arguments": {"x": "${steps.0.echo}"}},
            ],
        )
        summary = json.loads(rtb._extract_text(response))
        assert summary["ok"] is True
        assert summary["total"] == 2
        assert summary["completed"] == 2
        assert summary["results"][1]["echo"] == 1

    async def test_loop_with_goto_and_condition(self, monkeypatch):
        calls = _make_mock_call_tool(
            monkeypatch,
            lambda name, arguments: _async_ok({"n": arguments.get("i")}),
        )
        actions = [
            {"tool_name": "set_var", "arguments": {"expr": "i=0"}},
            {"tool_name": "label", "arguments": {"name": "loop"}},
            {"tool_name": "counter", "arguments": {"i": "${vars.i}"}},
            {"tool_name": "set_var", "arguments": {"expr": "i=${vars.i}+1"}},
            {
                "tool_name": "goto",
                "arguments": {"label": "loop", "condition": "${vars.i}<3"},
            },
        ]
        response = await rtb.run_tool_batch(actions=actions)
        summary = json.loads(rtb._extract_text(response))
        assert summary["ok"] is True
        assert len(calls) == 3
        assert [c[1]["i"] for c in calls] == [0, 1, 2]

    async def test_steps_ref_resolves_latest_in_loop(self, monkeypatch):
        _make_mock_call_tool(
            monkeypatch,
            lambda name, arguments: _async_ok({"got": dict(arguments)}),
        )
        actions = [
            {"tool_name": "set_var", "arguments": {"expr": "i=0"}},
            {"tool_name": "label", "arguments": {"name": "loop"}},
            {"tool_name": "counter", "arguments": {"i": "${vars.i}"}},
            {"tool_name": "set_var", "arguments": {"expr": "i=${vars.i}+1"}},
            {
                "tool_name": "goto",
                "arguments": {"label": "loop", "condition": "${vars.i}<2"},
            },
            {"tool_name": "reader", "arguments": {"v": "${steps.2.got.i}"}},
        ]
        response = await rtb.run_tool_batch(actions=actions)
        summary = json.loads(rtb._extract_text(response))
        assert summary["ok"] is True
        # ${steps.2.got.i} must resolve to the LATEST counter execution (i=1).
        assert summary["results"][-1]["got"]["v"] == 1

    async def test_stop_on_error_halts(self, monkeypatch):
        async def handler(name, arguments):
            if name == "bad":
                return ToolChunk(
                    state=ToolResultState.ERROR,
                    content=[TextBlock(type="text", text="Error: kaput")],
                )
            return _ok_chunk()

        calls = _make_mock_call_tool(monkeypatch, handler)
        response = await rtb.run_tool_batch(
            actions=[
                {"tool_name": "ok1"},
                {"tool_name": "bad"},
                {"tool_name": "ok2"},
            ],
        )
        summary = json.loads(rtb._extract_text(response))
        assert summary["ok"] is False
        assert summary["completed"] == 1
        assert summary["error"].startswith("Error: kaput")
        assert [c[0] for c in calls] == ["ok1", "bad"]

    async def test_per_step_continue_on_error(self, monkeypatch):
        async def handler(name, arguments):
            if name == "bad":
                return ToolChunk(
                    state=ToolResultState.ERROR,
                    content=[TextBlock(type="text", text="Error: kaput")],
                )
            return _ok_chunk()

        calls = _make_mock_call_tool(monkeypatch, handler)
        response = await rtb.run_tool_batch(
            actions=[
                {"tool_name": "bad", "stop_on_error": False},
                {"tool_name": "after"},
            ],
        )
        summary = json.loads(rtb._extract_text(response))
        assert summary["ok"] is False
        assert summary["completed"] == 1
        assert [c[0] for c in calls] == ["bad", "after"]

    async def test_maxstep_exceeded(self, monkeypatch):
        _make_mock_call_tool(monkeypatch, lambda n, a: _async_ok())
        actions = [
            {"tool_name": "label", "arguments": {"name": "spin"}},
            {"tool_name": "goto", "arguments": {"label": "spin"}},
        ]
        response = await rtb.run_tool_batch(actions=actions, maxstep=5)
        summary = json.loads(rtb._extract_text(response))
        assert summary["ok"] is False
        assert "maximum execution steps" in summary["error"].lower()

    async def test_recursive_batch_rejected(self, monkeypatch):
        _make_mock_call_tool(monkeypatch, lambda n, a: _async_ok())
        response = await rtb.run_tool_batch(
            actions=[{"tool_name": "run_tool_batch", "arguments": {}}],
        )
        summary = json.loads(rtb._extract_text(response))
        assert summary["ok"] is False
        assert "Recursive" in summary["error"]

    async def test_unknown_label_error(self, monkeypatch):
        _make_mock_call_tool(monkeypatch, lambda n, a: _async_ok())
        response = await rtb.run_tool_batch(
            actions=[{"tool_name": "goto", "arguments": {"label": "ghost"}}],
        )
        summary = json.loads(rtb._extract_text(response))
        assert summary["ok"] is False
        assert "Unknown label" in summary["error"]

    async def test_goto_missing_label_error(self, monkeypatch):
        _make_mock_call_tool(monkeypatch, lambda n, a: _async_ok())
        response = await rtb.run_tool_batch(
            actions=[{"tool_name": "goto", "arguments": {}}],
        )
        summary = json.loads(rtb._extract_text(response))
        assert "requires arguments.label" in summary["error"]

    async def test_duplicate_label_top_level_error(self, monkeypatch):
        response = await rtb.run_tool_batch(
            actions=[
                {"tool_name": "label", "arguments": {"name": "a"}},
                {"tool_name": "label", "arguments": {"name": "a"}},
            ],
        )
        summary = json.loads(rtb._extract_text(response))
        assert summary["ok"] is False
        assert "Duplicate label" in summary["error"]

    async def test_goto_bad_condition_stops_by_default(self, monkeypatch):
        _make_mock_call_tool(monkeypatch, lambda n, a: _async_ok())
        response = await rtb.run_tool_batch(
            actions=[
                {"tool_name": "label", "arguments": {"name": "a"}},
                {
                    "tool_name": "goto",
                    "arguments": {"label": "a", "condition": "nope"},
                },
            ],
        )
        summary = json.loads(rtb._extract_text(response))
        assert summary["ok"] is False
        assert "Undefined variable" in summary["error"]

    async def test_goto_bad_condition_continues_when_not_stopping(
        self,
        monkeypatch,
    ):
        _make_mock_call_tool(monkeypatch, lambda n, a: _async_ok())
        response = await rtb.run_tool_batch(
            actions=[
                {"tool_name": "label", "arguments": {"name": "a"}},
                {
                    "tool_name": "goto",
                    "arguments": {"label": "a", "condition": "nope"},
                    "stop_on_error": False,
                },
                {"tool_name": "tail"},
            ],
            stop_on_error=False,
        )
        summary = json.loads(rtb._extract_text(response))
        assert summary["completed"] == 2
        assert summary["results"][1]["ok"] is False
        assert summary["results"][2]["tool_name"] == "tail"

    async def test_set_var_missing_expr_error(self, monkeypatch):
        response = await rtb.run_tool_batch(
            actions=[{"tool_name": "set_var", "arguments": {}}],
        )
        summary = json.loads(rtb._extract_text(response))
        assert "requires arguments.expr" in summary["error"]

    async def test_set_var_bad_expr_stops(self, monkeypatch):
        response = await rtb.run_tool_batch(
            actions=[
                {"tool_name": "set_var", "arguments": {"expr": "no equals"}},
            ],
        )
        summary = json.loads(rtb._extract_text(response))
        assert summary["ok"] is False

    async def test_label_missing_name_error(self, monkeypatch):
        response = await rtb.run_tool_batch(
            actions=[{"tool_name": "label", "arguments": {}}],
        )
        summary = json.loads(rtb._extract_text(response))
        assert "requires arguments.name" in summary["error"]

    async def test_non_dict_step_error(self, monkeypatch):
        response = await rtb.run_tool_batch(actions=["junk"])
        summary = json.loads(rtb._extract_text(response))
        assert summary["ok"] is False
        assert "must be an object" in summary["error"]

    async def test_missing_tool_name_error(self, monkeypatch):
        response = await rtb.run_tool_batch(actions=[{"arguments": {}}])
        summary = json.loads(rtb._extract_text(response))
        assert "must include tool_name" in summary["error"]

    async def test_non_dict_arguments_error(self, monkeypatch):
        response = await rtb.run_tool_batch(
            actions=[{"tool_name": "x", "arguments": "bad"}],
        )
        summary = json.loads(rtb._extract_text(response))
        assert "must be an object" in summary["error"]

    async def test_bad_step_ref_continues_when_not_stopping(self, monkeypatch):
        calls = _make_mock_call_tool(monkeypatch, lambda n, a: _async_ok())
        response = await rtb.run_tool_batch(
            actions=[
                {"tool_name": "x", "arguments": {"v": "${steps.9.z}"}},
                {"tool_name": "y"},
            ],
            stop_on_error=False,
        )
        summary = json.loads(rtb._extract_text(response))
        assert summary["results"][0]["ok"] is False
        assert summary["results"][1]["ok"] is True
        assert [c[0] for c in calls] == ["y"]

    async def test_interrupted_tool_breaks_batch(self, monkeypatch):
        async def handler(name, arguments):
            if name == "halt":
                return ToolChunk(
                    state=ToolResultState.INTERRUPTED,
                    content=[],
                )
            return _ok_chunk()

        calls = _make_mock_call_tool(monkeypatch, handler)
        response = await rtb.run_tool_batch(
            actions=[
                {"tool_name": "halt"},
                {"tool_name": "never"},
            ],
        )
        assert [c[0] for c in calls] == ["halt"]
        summary = json.loads(rtb._extract_text(response))
        assert summary["completed"] == 0

    async def test_files_info_surfaced_in_result(self, monkeypatch):
        chunk = ToolChunk(
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(type="text", text="sent"),
                DataBlock(
                    type="data",
                    source=URLSource(
                        url="file:///f.txt",
                        media_type="text/plain",
                    ),
                    name="f.txt",
                ),
            ],
        )

        async def handler(name, arguments):
            return chunk

        _make_mock_call_tool(monkeypatch, handler)
        response = await rtb.run_tool_batch(actions=[{"tool_name": "send"}])
        summary = json.loads(rtb._extract_text(response))
        assert summary["results"][0]["files"] == [
            {"url": "file:///f.txt", "name": "f.txt"},
        ]

    async def test_last_only_payload_shape(self, monkeypatch):
        _make_mock_call_tool(
            monkeypatch,
            lambda n, a: _async_ok(text="final answer"),
        )
        response = await rtb.run_tool_batch(
            actions=[
                {"tool_name": "one"},
                {"tool_name": "two"},
            ],
            last_only=True,
        )
        summary = json.loads(rtb._extract_text(response))
        assert summary["ok"] is True
        assert summary["completed"] == 2
        assert "results" not in summary
        assert summary["last_step_result"]["step"] == 1
        # The last text lives inside last_step_result, so last_only must not
        # duplicate it as an extra content block.
        assert summary["last_step_result"]["text"] == "final answer"
        assert len(response.content) == 1


async def _async_ok(payload: dict | None = None, text: str | None = None):
    return _ok_chunk(payload, text)


# ---------------------------------------------------------------------------
# Input preparation (entry-point validation)
# ---------------------------------------------------------------------------


class TestPrepareBatchInputs:
    def test_actions_and_file_path_conflict(self):
        with pytest.raises(ValueError, match="not both"):
            rtb._prepare_batch_inputs(
                [{"tool_name": "x"}],
                "/a.json",
                None,
                10,
            )

    def test_actions_json_string(self):
        actions, maxstep = rtb._prepare_batch_inputs(
            '[{"tool_name": "x"}]',
            "",
            None,
            10,
        )
        assert actions == [{"tool_name": "x"}]
        assert maxstep == 10

    def test_actions_invalid_json_string(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            rtb._prepare_batch_inputs("{bad", "", None, 10)

    def test_args_json_string(self):
        # args substitution only applies to batches loaded from file_path;
        # inline actions pass through with args merely coerced.
        actions, _ = rtb._prepare_batch_inputs(
            [{"tool_name": "x"}],
            "",
            '{"k": "yes"}',
            10,
        )
        assert actions == [{"tool_name": "x"}]

    def test_args_invalid_json_string(self):
        with pytest.raises(ValueError, match="must be an object"):
            rtb._prepare_batch_inputs([{"tool_name": "x"}], "", "{bad", 10)

    def test_args_non_dict(self):
        with pytest.raises(ValueError, match="must be an object"):
            rtb._prepare_batch_inputs([{"tool_name": "x"}], "", [1], 10)

    def test_empty_actions_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            rtb._prepare_batch_inputs([], "", None, 10)

    def test_none_actions_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            rtb._prepare_batch_inputs(None, "", None, 10)

    def test_too_many_steps_rejected(self):
        actions = [{"tool_name": "x"} for _ in range(rtb.MAX_BATCH_STEPS + 1)]
        with pytest.raises(ValueError, match="Too many steps"):
            rtb._prepare_batch_inputs(actions, "", None, 10)

    def test_maxstep_string_coerced(self):
        _, maxstep = rtb._prepare_batch_inputs(
            [{"tool_name": "x"}],
            "",
            None,
            "25",
        )
        assert maxstep == 25

    def test_maxstep_invalid(self):
        with pytest.raises(ValueError, match="positive integer"):
            rtb._prepare_batch_inputs([{"tool_name": "x"}], "", None, "abc")

    def test_maxstep_non_positive(self):
        with pytest.raises(ValueError, match="positive integer"):
            rtb._prepare_batch_inputs([{"tool_name": "x"}], "", None, 0)

    def test_file_path_loaded_with_args(self, tmp_path):
        path = tmp_path / "batch.json"
        path.write_text(
            json.dumps([{"tool_name": "x", "arguments": {"v": "${args.k}"}}]),
            encoding="utf-8",
        )
        actions, _ = rtb._prepare_batch_inputs(
            None,
            str(path),
            {"k": "done"},
            10,
        )
        assert actions == [{"tool_name": "x", "arguments": {"v": "done"}}]


class TestEntryPointErrors:
    async def test_bad_inputs_return_error_chunk(self):
        response = await rtb.run_tool_batch(actions=None, file_path="")
        summary = json.loads(rtb._extract_text(response))
        assert summary["ok"] is False
        assert response.state == ToolResultState.ERROR

    async def test_file_path_end_to_end(self, tmp_path, monkeypatch):
        _make_mock_call_tool(monkeypatch, lambda n, a: _async_ok())
        path = tmp_path / "batch.json"
        path.write_text(
            json.dumps([{"tool_name": "x"}]),
            encoding="utf-8",
        )
        response = await rtb.run_tool_batch(file_path=str(path))
        summary = json.loads(rtb._extract_text(response))
        assert summary["ok"] is True
        assert summary["completed"] == 1
