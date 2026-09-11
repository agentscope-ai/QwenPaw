# -*- coding: utf-8 -*-
"""Integration tests for run_tool_batch internals.

Covers src/qwenpaw/agents/tools/run_tool_batch.py (466 uncovered
lines): step/var reference resolution, scalar parsing, condition and
arithmetic evaluation, batch file loading.
"""

from __future__ import annotations

import json

import pytest


# ------------------------------------------------------------------ #
# reference resolution
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_step_refs_plain_value() -> None:
    """resolve_step_refs passes through non-string values."""
    from qwenpaw.agents.tools.run_tool_batch import resolve_step_refs

    assert resolve_step_refs(42, []) == 42
    assert resolve_step_refs(None, []) is None


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_step_refs_step_ref() -> None:
    """resolve_step_refs resolves ${steps.N.value}."""
    from qwenpaw.agents.tools.run_tool_batch import resolve_step_refs

    results = [{"step": 0, "value": "hello"}]
    resolved = resolve_step_refs("${steps.0.value}", results)
    assert resolved == "hello"


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_step_refs_var_ref() -> None:
    """resolve_step_refs resolves ${vars.name}."""
    from qwenpaw.agents.tools.run_tool_batch import resolve_step_refs

    resolved = resolve_step_refs("${vars.count}", [], {"count": 3})
    assert resolved == 3


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_step_refs_nested() -> None:
    """resolve_step_refs walks dicts and lists recursively."""
    from qwenpaw.agents.tools.run_tool_batch import resolve_step_refs

    results = [{"step": 0, "value": "x"}]
    resolved = resolve_step_refs(
        {"a": ["${steps.0.value}", 1]},
        results,
    )
    assert resolved == {"a": ["x", 1]}


# ------------------------------------------------------------------ #
# scalar parsing
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_parse_scalar_bool() -> None:
    """_parse_scalar converts true/false strings."""
    from qwenpaw.agents.tools.run_tool_batch import _parse_scalar

    assert _parse_scalar("true") is True
    assert _parse_scalar("False") is False
    assert _parse_scalar("other") == "other"


@pytest.mark.integration
@pytest.mark.p1
def test_parse_scalar_int() -> None:
    """_parse_scalar converts integer strings."""
    from qwenpaw.agents.tools.run_tool_batch import _parse_scalar

    assert _parse_scalar("42") == 42
    assert _parse_scalar("-7") == -7
    assert _parse_scalar("3.5") == "3.5"


# ------------------------------------------------------------------ #
# condition evaluation
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_evaluate_condition_comparison() -> None:
    """_evaluate_condition handles simple comparisons."""
    from qwenpaw.agents.tools.run_tool_batch import _evaluate_condition

    assert _evaluate_condition("1<2", [], {}) is True
    assert _evaluate_condition("2<=1", [], {}) is False
    assert _evaluate_condition("${vars.i}==5", [], {"i": 5}) is True


@pytest.mark.integration
@pytest.mark.p1
def test_evaluate_condition_bool_token() -> None:
    """_evaluate_condition coerces bare boolean tokens."""
    from qwenpaw.agents.tools.run_tool_batch import _evaluate_condition

    assert _evaluate_condition("true", [], {}) is True
    assert _evaluate_condition("false", [], {}) is False


# ------------------------------------------------------------------ #
# arithmetic evaluation
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_evaluate_arithmetic_expr() -> None:
    """_evaluate_arithmetic_expr computes simple expressions."""
    from qwenpaw.agents.tools.run_tool_batch import (
        _evaluate_arithmetic_expr,
    )

    assert _evaluate_arithmetic_expr("1+2", {}) == 3
    assert _evaluate_arithmetic_expr("(1+2)*2", {}) == 6


@pytest.mark.integration
@pytest.mark.p1
def test_evaluate_set_var_expr() -> None:
    """_evaluate_set_var_expr assigns arithmetic results."""
    from qwenpaw.agents.tools.run_tool_batch import (
        _evaluate_set_var_expr,
    )

    result = _evaluate_set_var_expr("i=(${vars.i}+1)", [], {"i": 1})
    name, value = result if isinstance(result, tuple) else (None, result)
    assert name == "i"
    assert value == 2


# ------------------------------------------------------------------ #
# batch file loading
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_load_batch_file(tmp_path) -> None:
    """_load_batch_file reads an actions list from JSON."""
    from qwenpaw.agents.tools.run_tool_batch import _load_batch_file

    batch = tmp_path / "batch.json"
    batch.write_text(
        json.dumps({"actions": [{"tool_name": "x", "arguments": {}}]}),
    )
    actions = _load_batch_file(str(batch))
    assert isinstance(actions, list)
    assert len(actions) == 1
    assert actions[0]["tool_name"] == "x"


@pytest.mark.integration
@pytest.mark.p1
def test_load_batch_file_plain_list(tmp_path) -> None:
    """_load_batch_file accepts a bare JSON array."""
    from qwenpaw.agents.tools.run_tool_batch import _load_batch_file

    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps([{"tool_name": "y"}]))
    actions = _load_batch_file(str(batch))
    assert actions[0]["tool_name"] == "y"


# ------------------------------------------------------------------ #
# args resolution
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_args_placeholder() -> None:
    """_resolve_args substitutes ${args.name} placeholders."""
    from qwenpaw.agents.tools.run_tool_batch import _resolve_args

    resolved = _resolve_args(
        "run ${args.folder}",
        {"folder": "/data"},
    )
    assert resolved == "run /data"
