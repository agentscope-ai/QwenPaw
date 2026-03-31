# -*- coding: utf-8 -*-
"""Tests for PlanConfig validation and backward compatibility."""
from __future__ import annotations

import json

from copaw.config.config import AgentProfileConfig, PlanConfig


class TestPlanConfigDefaults:
    """PlanConfig should have sensible defaults."""

    def test_default_disabled(self):
        cfg = PlanConfig()
        assert cfg.enabled is False

    def test_default_storage_memory(self):
        cfg = PlanConfig()
        assert cfg.storage_type == "memory"
        assert cfg.storage_path is None

    def test_default_agent_managed(self):
        cfg = PlanConfig()
        assert cfg.agent_managed is True

    def test_default_max_subtasks_none(self):
        cfg = PlanConfig()
        assert cfg.max_subtasks is None


class TestPlanConfigValidation:
    """PlanConfig validation rules."""

    def test_explicit_values(self):
        cfg = PlanConfig(
            enabled=True,
            max_subtasks=5,
            storage_type="file",
            storage_path="/tmp/plans",
            agent_managed=False,
        )
        assert cfg.enabled is True
        assert cfg.max_subtasks == 5
        assert cfg.storage_type == "file"
        assert cfg.storage_path == "/tmp/plans"
        assert cfg.agent_managed is False

    def test_extra_fields_ignored(self):
        cfg = PlanConfig.model_validate(
            {"enabled": True, "unknown_field": 42},
        )
        assert cfg.enabled is True


class TestAgentProfileConfigBackwardCompat:
    """Existing config without 'plan' key should load with defaults."""

    def test_missing_plan_key_defaults(self):
        data = {
            "id": "test-agent",
            "name": "Test",
        }
        config = AgentProfileConfig.model_validate(data)
        assert config.plan.enabled is False
        assert config.plan.storage_type == "memory"

    def test_plan_key_present(self):
        data = {
            "id": "test-agent",
            "name": "Test",
            "plan": {"enabled": True, "max_subtasks": 3},
        }
        config = AgentProfileConfig.model_validate(data)
        assert config.plan.enabled is True
        assert config.plan.max_subtasks == 3

    def test_roundtrip_json(self):
        data = {
            "id": "test-agent",
            "name": "Test",
            "plan": {
                "enabled": True,
                "storage_type": "file",
                "storage_path": "/data/plans",
            },
        }
        config = AgentProfileConfig.model_validate(data)
        dumped = json.loads(config.model_dump_json())
        assert dumped["plan"]["enabled"] is True
        assert dumped["plan"]["storage_type"] == "file"


class TestCreatePlanNotebookFactory:
    """Test the create_plan_notebook factory."""

    def test_returns_none_when_disabled(self, tmp_path):
        from copaw.plan.factory import create_plan_notebook

        cfg = PlanConfig(enabled=False)
        result = create_plan_notebook(cfg, "agent-1", tmp_path)
        assert result is None

    def test_returns_notebook_when_enabled(self, tmp_path):
        from copaw.plan.factory import create_plan_notebook

        cfg = PlanConfig(enabled=True)
        result = create_plan_notebook(cfg, "agent-1", tmp_path)
        assert result is not None

    def test_file_storage_creates_dir(self, tmp_path):
        from copaw.plan.factory import create_plan_notebook

        cfg = PlanConfig(
            enabled=True,
            storage_type="file",
        )
        result = create_plan_notebook(cfg, "agent-1", tmp_path)
        assert result is not None
        plan_dir = tmp_path / "plans" / "agent-1"
        assert plan_dir.exists()
