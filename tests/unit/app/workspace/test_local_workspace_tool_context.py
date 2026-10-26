# -*- coding: utf-8 -*-
"""Workspace tools must share the per-turn request context object.

``AgentBuilder.build`` publishes ``effective_model`` on that dict, and the
guarded tool wrapper reads it back from ``_qp_request_context``.  If the
workspace copied the dict, the model would silently disappear from the
tool-call scope (issue #8378).
"""

# pylint: disable=protected-access

from types import SimpleNamespace

import pytest

from qwenpaw.app.workspace.local_workspace import QwenPawLocalWorkspace


def _echo(x: str) -> str:
    """Return the argument unchanged."""
    return x


@pytest.mark.asyncio
async def test_list_tools_keeps_the_request_context_identity(tmp_path):
    descriptor = SimpleNamespace(func=_echo)
    registry = SimpleNamespace(
        get=lambda _name: None,
        filter=lambda **_kwargs: [descriptor],
    )
    workspace = QwenPawLocalWorkspace(registry, workdir=str(tmp_path))
    request_context = {"effective_model": object()}

    tools = await workspace.list_tools(request_context=request_context)

    assert len(tools) == 1
    assert tools[0]._qp_request_context is request_context
