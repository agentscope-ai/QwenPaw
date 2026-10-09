# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Regression tests for MissionGate PRD validation."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from qwenpaw.loop.gates.base import StopAction
from qwenpaw.modes.mission.gates import MissionGate


@pytest.mark.parametrize(
    "stories",
    [
        pytest.param("invalid", id="scalar"),
        pytest.param([None], id="non-object"),
    ],
)
def test_malformed_user_stories_terminate_mission(tmp_path, stories):
    """Malformed story data stops a mission without a continuation."""
    gate = MissionGate()

    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="mission-session",
    ):
        gate.activate_for_mission(tmp_path)

        result = gate._eval_prd({"userStories": stories}, {})

        assert result.action == StopAction.TERMINATE
        assert result.reason == "Invalid user stories in prd.json"
        assert gate._state() is None
