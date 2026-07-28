# -*- coding: utf-8 -*-
"""Tool registry annotation materialisation.

Tool modules use ``from __future__ import annotations`` (this very module
does), which turns annotations into strings. The downstream JSON-schema
builder rebuilds a model directly from the raw annotations in a namespace
that lacks typing names like ``Optional``/``List``; stringized annotations
therefore fail to resolve and abort the whole toolkit build. The
``@tool_descriptor`` decorator must hand back concrete type objects so schema
generation succeeds.
"""

# The probe functions exist for their annotations alone, so their parameters
# are never read.
# pylint: disable=unused-argument

from __future__ import annotations

from typing import Dict, List, Optional

from qwenpaw.runtime.tool_registry import (
    _materialize_annotations,
    tool_descriptor,
)


def _plain(
    region: Optional[List[int]] = None,
    name: str = "a",
) -> Dict[str, int]:
    return {}


def test_materialize_resolves_stringized_typing_annotations() -> None:
    # Under `from __future__ import annotations` the raw annotation is a
    # string.
    assert _plain.__annotations__["region"] == "Optional[List[int]]"

    _materialize_annotations(_plain)

    region = _plain.__annotations__["region"]
    assert not isinstance(region, str)
    assert region == Optional[List[int]]
    assert _plain.__annotations__["return"] == Dict[str, int]


def test_tool_descriptor_materializes_annotations() -> None:
    @tool_descriptor(name="annotated_probe", enabled_by_default=False)
    def probe(region: Optional[List[int]] = None, name: str = "a") -> str:
        """Probe.

        Args:
            region: a region
            name: a name
        """
        return name

    region = probe.__annotations__["region"]
    assert not isinstance(region, str)
    assert region == Optional[List[int]]


def test_materialize_is_best_effort_on_unresolvable_hint() -> None:
    # The hint is deliberately unresolvable, so both linters are told to
    # leave it alone: that is exactly the case under test.
    def broken(
        value: "DefinitelyNotARealType",  # type: ignore[name-defined] # noqa: F821,E501
    ) -> None:
        return None

    original = dict(broken.__annotations__)

    # Must not raise even though the hint cannot be resolved.
    _materialize_annotations(broken)

    # Annotations are left untouched so a previously-working tool never
    # regresses.
    assert broken.__annotations__ == original
