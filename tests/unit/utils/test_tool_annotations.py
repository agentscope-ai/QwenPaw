# -*- coding: utf-8 -*-
"""Tests for qwenpaw.utils.tool_annotations (QwenPaw #7082).

Under ``from __future__ import annotations`` (PEP 563) a tool function's
annotations are plain strings. agentscope's ``FunctionTool`` feeds those
strings into ``pydantic.create_model(...).model_json_schema()`` and — because
agentscope's own ``tool/_utils.py`` only imports ``Any``/``Dict``/``Callable``
— fails to resolve names such as ``Optional`` with::

    PydanticUserError: `_StructuredOutputDynamicClass` is not fully defined;
    you should define `Optional`, ...

which aborts tool registration at startup. ``resolve_tool_annotations``
rewrites the annotations to real objects (resolved in the function's own
module namespace) before agentscope introspects the function.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pytest

from qwenpaw.utils.tool_annotations import resolve_tool_annotations


def test_resolves_pep563_optional_annotations() -> None:
    async def tool(
        operation: str,
        file_path: Optional[Path] = None,
        count: Optional[int] = None,
    ) -> Any:
        return operation

    # PEP 563: annotations start life as strings.
    assert isinstance(tool.__annotations__["file_path"], str)

    result = resolve_tool_annotations(tool)

    assert result is tool
    assert tool.__annotations__["operation"] is str
    assert tool.__annotations__["file_path"] == Optional[Path]
    assert tool.__annotations__["count"] == Optional[int]


def test_noop_when_function_has_no_annotations() -> None:
    def tool():  # noqa: ANN202
        return None

    tool.__annotations__ = {}
    assert resolve_tool_annotations(tool) is tool
    assert tool.__annotations__ == {}


def test_noop_when_annotations_already_concrete() -> None:
    def tool(x, y):  # noqa: ANN001,ANN202
        return None

    # Real objects, not strings — nothing to resolve.
    tool.__annotations__ = {"x": int, "y": str}
    resolve_tool_annotations(tool)
    assert tool.__annotations__ == {"x": int, "y": str}


def test_unresolvable_string_annotation_is_left_untouched() -> None:
    def tool(x):  # noqa: ANN001,ANN202
        return None

    tool.__annotations__ = {"x": "DefinitelyNotADefinedName"}
    resolve_tool_annotations(tool)
    assert tool.__annotations__ == {"x": "DefinitelyNotADefinedName"}


def test_agentscope_functiontool_builds_after_resolve() -> None:
    """End-to-end: agentscope schema extraction fails before, works after."""
    pytest.importorskip("agentscope")
    from agentscope.tool import FunctionTool
    from pydantic.errors import PydanticUserError

    async def tool(
        operation: str,
        file_path: Optional[Path] = None,
    ) -> Any:
        """A demo tool.

        Args:
            operation (str): the operation.
            file_path (Optional[Path]): optional path.
        """
        return operation

    # Reproduces #7082: unresolved PEP 563 string annotations.
    with pytest.raises(PydanticUserError, match="not fully defined"):
        FunctionTool(tool)

    resolve_tool_annotations(tool)

    built = FunctionTool(tool)
    assert getattr(built, "input_schema", None) is not None
