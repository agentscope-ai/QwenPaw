# -*- coding: utf-8 -*-
"""Regression test for proactive ContextVar propagation.

``deliver_proactive_round`` runs inside an ``asyncio.create_task`` spawned
from ``proactive_trigger.py``, bypassing ``ContextVarsSetupHook`` entirely.
Both ``current_agent_id`` and ``current_workspace_dir`` must be set from
the caller's arguments at the top of the function, or downstream lookups
(the inbox store, the cached agent config) silently fall back to the
default agent and the wrong workspace.
"""
# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from qwenpaw.agents.memory.proactive.proactive_responder import (
    AgendaRound,
    ProactiveSettings,
    deliver_proactive_round,
)
from qwenpaw.app.agent_context import get_current_agent_id
from qwenpaw.config.context import get_current_workspace_dir


@pytest.mark.asyncio
async def test_deliver_proactive_round_sets_agent_id_and_workspace_dir(
    tmp_path: Path,
) -> None:
    observed: dict[str, object] = {}

    async def fake_collect(_memory_manager, **kwargs):  # noqa: ANN001
        del kwargs
        # Captured mid-flight: this is where the inbox append and the
        # delivery ledger resolve the current agent and workspace.
        observed["agent_id"] = get_current_agent_id()
        observed["workspace_dir"] = get_current_workspace_dir()
        return AgendaRound(available=True, skip_reason="empty")

    with patch(
        "qwenpaw.agents.memory.proactive.proactive_responder.collect_agenda",
        fake_collect,
    ):
        outcome = await deliver_proactive_round(
            agent_id="proactive-agent-1",
            workspace_dir=str(tmp_path),
            memory_manager=SimpleNamespace(),
            settings=ProactiveSettings(enabled=True, inbox_enabled=True),
        )

    assert outcome.skip_reason == "empty"
    assert outcome.pushed is False
    assert observed["agent_id"] == "proactive-agent-1"
    assert observed["workspace_dir"] == tmp_path
