# -*- coding: utf-8 -*-
"""Tests for runtime exception mapping in query handler."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Type

_MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "copaw"
    / "app"
    / "runner"
    / "error_mapping.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "copaw_runner_error_mapping",
    _MODULE_PATH,
)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Failed to load module spec from {_MODULE_PATH}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

AgentModelTimeoutError = _MODULE.AgentModelTimeoutError
is_model_timeout_error = _MODULE.is_model_timeout_error
map_query_exception = _MODULE.map_query_exception


OpenAITimeoutError: Type[Exception] = type(
    "APITimeoutError",
    (Exception,),
    {"__module__": "openai"},
)
HttpxReadTimeout: Type[Exception] = type(
    "ReadTimeout",
    (Exception,),
    {"__module__": "httpx"},
)


def test_map_query_exception_returns_timeout_error() -> None:
    exc = OpenAITimeoutError("Request timed out.")

    mapped = map_query_exception(exc)

    assert isinstance(mapped, AgentModelTimeoutError)
    assert "Model provider request timed out." in str(mapped)
    assert "APITimeoutError: Request timed out." in str(mapped)


def test_map_query_exception_timeout_via_cause_chain() -> None:
    try:
        try:
            raise HttpxReadTimeout("Read timed out")
        except HttpxReadTimeout as inner:
            raise RuntimeError("Model call failed") from inner
    except RuntimeError as outer:
        mapped = map_query_exception(outer)

    assert isinstance(mapped, AgentModelTimeoutError)
    assert "ReadTimeout: Read timed out" in str(mapped)


def test_map_query_exception_passes_non_timeout_error() -> None:
    exc = ValueError("Invalid model name")
    mapped = map_query_exception(exc)
    assert mapped is exc


def test_plain_timeout_without_network_module_is_not_model_timeout() -> None:
    exc = TimeoutError("Tool execution timed out")
    assert not is_model_timeout_error(exc)
