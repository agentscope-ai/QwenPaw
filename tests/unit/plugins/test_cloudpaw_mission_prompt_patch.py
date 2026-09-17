# -*- coding: utf-8 -*-
"""Tests for the CloudPaw mission prompt patch."""

import importlib.util
import sys
import types
from pathlib import Path


def _load_mission_prompts(monkeypatch):
    """Load mission prompts without importing the full qwenpaw package."""
    for package_name in (
        "qwenpaw",
        "qwenpaw.modes",
        "qwenpaw.modes.mission",
    ):
        package = types.ModuleType(package_name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, package_name, package)

    prompts_path = (
        Path(__file__).parents[3]
        / "src"
        / "qwenpaw"
        / "modes"
        / "mission"
        / "prompts.py"
    )
    spec = importlib.util.spec_from_file_location(
        "qwenpaw.modes.mission.prompts",
        prompts_path,
    )
    assert spec is not None
    assert spec.loader is not None
    mission_prompts = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(
        sys.modules,
        "qwenpaw.modes.mission.prompts",
        mission_prompts,
    )
    spec.loader.exec_module(mission_prompts)

    mission_handler = types.ModuleType("qwenpaw.modes.mission.handler")
    mission_handler.build_master_prompt = mission_prompts.build_master_prompt
    monkeypatch.setitem(
        sys.modules,
        "qwenpaw.modes.mission.handler",
        mission_handler,
    )
    return mission_prompts, mission_handler


def test_mission_patch_accepts_upstream_prompt_kwargs(monkeypatch):
    """Both patched prompt paths accept the upstream mission kwargs."""
    mission_prompts, mission_handler = _load_mission_prompts(monkeypatch)

    from plugins.bundle.cloudpaw.hooks import _patch_mission_master_prompt

    _patch_mission_master_prompt()

    prompt_kwargs = {
        "loop_dir": "/tmp/mission-loop",
        "verification_instructions": "Check the regression scenario.",
        "max_retries_per_story": 7,
    }
    default_prompt = mission_prompts.build_master_prompt(
        agent_id="default",
        **prompt_kwargs,
    )
    cloudpaw_prompt = mission_handler.build_master_prompt(
        agent_id="cloud-orchestrator",
        **prompt_kwargs,
    )

    assert "Check the regression scenario." in default_prompt
    assert "Max 7 retries per story" in default_prompt
    assert "Check the regression scenario." in cloudpaw_prompt
    assert cloudpaw_prompt
