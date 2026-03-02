# -*- coding: utf-8 -*-
import pytest

from copaw.agents.react_agent import normalize_reasoning_tool_choice


@pytest.mark.parametrize(
    ("tool_choice_in", "has_tools", "expected"),
    [
        (None, True, "auto"),
        (None, False, None),
        ("required", True, "required"),
        ("none", True, "none"),
    ],
)
def test_normalize_reasoning_tool_choice(
    tool_choice_in: str | None,
    has_tools: bool,
    expected: str | None,
) -> None:
    assert (
        normalize_reasoning_tool_choice(
            tool_choice=tool_choice_in,
            has_tools=has_tools,
        )
        == expected
    )
