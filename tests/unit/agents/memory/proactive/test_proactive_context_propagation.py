# -*- coding: utf-8 -*-
"""Regression test for the proactive background-task ContextVar propagation
fix (websearch-console-config-plan.md, section 2.7).

``generate_proactive_response`` runs inside an ``asyncio.create_task``
spawned from ``proactive_trigger.py``, bypassing ``ContextVarsSetupHook``
entirely. Both ``current_agent_id`` (used by ``get_search_provider``) and
``current_workspace_dir`` (used by ``_current_agent_anysearch_key``) must
be set explicitly from ``workspace`` at the top of the function, or
downstream tool calls silently fall back to the wrong agent / no
workspace at all.
"""
# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.agents.memory.proactive.proactive_responder import (
    generate_proactive_response,
)
from qwenpaw.app.agent_context import get_current_agent_id
from qwenpaw.config.context import get_current_workspace_dir


def _workspace(agent_id: str, workspace_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(agent_id=agent_id, workspace_dir=workspace_dir)


@pytest.mark.asyncio
async def test_generate_proactive_response_sets_agent_id_and_workspace_dir(
    tmp_path: Path,
) -> None:
    workspace = _workspace("proactive-agent-1", tmp_path)

    observed: dict[str, object] = {}

    async def fake_build_context(*, workspace, agent):  # noqa: ANN001
        del workspace, agent
        # Captured mid-flight: this is where a real tool call (e.g.
        # web_search) would run and need both ContextVars already set.
        observed["agent_id"] = get_current_agent_id()
        observed["workspace_dir"] = get_current_workspace_dir()
        return ""

    with (
        patch(
            "qwenpaw.agents.memory.proactive.proactive_responder"
            "._initialize_single_proactive_agent",
            AsyncMock(return_value=SimpleNamespace()),
        ),
        patch(
            "qwenpaw.agents.memory.proactive.proactive_responder"
            ".build_proactive_memory_context",
            fake_build_context,
        ),
        patch(
            "qwenpaw.agents.memory.proactive.proactive_responder"
            "._was_interrupted",
            AsyncMock(return_value=True),
        ),
    ):
        result = await generate_proactive_response(workspace)

    assert result is None  # short-circuited via _was_interrupted=True
    assert observed["agent_id"] == "proactive-agent-1"
    assert observed["workspace_dir"] == tmp_path
