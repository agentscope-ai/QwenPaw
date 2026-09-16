# -*- coding: utf-8 -*-
"""循环配置文件保存与重载保真测试。"""

import json
from threading import RLock

import pytest
from pydantic import ValidationError

from qwenpaw.config import config as config_module
from qwenpaw.config import utils as config_utils
from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    AgentsConfig,
    Config,
    load_agent_config,
    save_agent_config,
)


def test_loop_config_roundtrip_preserves_builtin_and_custom_pipeline(
    tmp_path,
    monkeypatch,
):
    workspace_dir = tmp_path / "workspaces" / "agent"
    workspace_dir.mkdir(parents=True)
    root_config = Config(
        agents=AgentsConfig(
            active_agent="agent",
            profiles={
                "agent": AgentProfileRef(
                    id="agent",
                    workspace_dir=str(workspace_dir),
                ),
            },
        ),
    )
    monkeypatch.setattr(config_utils, "load_config", lambda: root_config)
    monkeypatch.setattr(config_utils, "_agent_config_cache", {})
    monkeypatch.setattr(config_utils, "_agent_config_lock", RLock())

    raw_loop = {
        "iteration": {"enabled": True, "max_iterations": 77},
        "doom_loop": {
            "enabled": True,
            "window_size": 5,
            "similarity_threshold": 0.8,
            "stages": [
                {"after": 2, "action": "modify_prompt", "prompt": "change"},
                {"after": 4, "action": "stop", "prompt": "stop"},
            ],
            "in_loop_modes": True,
        },
        "rubric": {
            "enabled": True,
            "prompt": "Continue when incomplete",
            "max_interventions": 3,
            "in_loop_modes": True,
        },
        "goal": {"max_iterations": 12, "max_tokens": 34567},
        "mission": {
            "max_iterations": 8,
            "max_retries_per_story": 2,
            "default_verification_instructions": "Inspect the rendered UI",
            "default_verify_command": "pytest -q",
        },
        "custom_modes": [
            {
                "id": "quality-mode",
                "name": "Quality mode",
                "description": "Two ordered gates",
                "slash_command": "quality-mode",
                "enabled": True,
                "gates": [
                    {
                        "id": "iteration-first",
                        "type": "iteration",
                        "enabled": True,
                        "params": {"max_iterations": 19},
                    },
                    {
                        "id": "rubric-second",
                        "type": "completion_rubric",
                        "enabled": True,
                        "params": {
                            "prompt": "Verify every requirement",
                            "completion_signal": "DONE",
                            "max_evaluations": 4,
                        },
                    },
                ],
            },
        ],
    }
    profile = AgentProfileConfig(id="agent", name="Agent")
    profile.running.loop = config_module.LoopConfig.model_validate(raw_loop)

    save_agent_config("agent", profile)
    loaded = load_agent_config("agent")
    persisted = json.loads(
        (workspace_dir / "agent.json").read_text(encoding="utf-8"),
    )

    assert loaded.running.loop.model_dump(exclude_none=True) == raw_loop
    assert persisted["running"]["loop"] == raw_loop


@pytest.mark.parametrize(
    "custom_modes",
    [
        [
            {
                "id": "duplicate-gates",
                "name": "Duplicate gates",
                "slash_command": "duplicate-gates",
                "enabled": True,
                "gates": [
                    {
                        "id": "same-id",
                        "type": "iteration",
                        "enabled": True,
                        "params": {"max_iterations": 5},
                    },
                    {
                        "id": "same-id",
                        "type": "timeout",
                        "enabled": True,
                        "params": {"max_seconds": 30},
                    },
                ],
            },
        ],
        [
            {
                "id": "unknown-type",
                "name": "Unknown type",
                "slash_command": "unknown-type",
                "enabled": True,
                "gates": [
                    {
                        "id": "unknown-gate",
                        "type": "external_gate",
                        "enabled": True,
                        "params": {},
                    },
                ],
            },
        ],
        [
            {
                "id": "invalid-range",
                "name": "Invalid range",
                "slash_command": "invalid-range",
                "enabled": True,
                "gates": [
                    {
                        "id": "bad-timeout",
                        "type": "timeout",
                        "enabled": True,
                        "params": {"max_seconds": 86401},
                    },
                ],
            },
        ],
    ],
)
def test_loop_config_rejects_invalid_pipeline_before_save(custom_modes):
    with pytest.raises(ValidationError):
        config_module.LoopConfig(custom_modes=custom_modes)
