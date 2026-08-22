# -*- coding: utf-8 -*-
"""``AdvisorModeConfig`` defaults, persistence and legacy compatibility."""
from __future__ import annotations

import json

from qwenpaw.config.config import AdvisorModeConfig, AgentProfileConfig


def test_defaults_are_off_with_followup_on():
    cfg = AdvisorModeConfig()
    assert cfg.enabled is False
    assert cfg.plan_enabled is True
    assert cfg.followup_enabled is True
    assert cfg.on_demand_enabled is True
    assert cfg.max_consults == 3
    assert AgentProfileConfig(id="a", name="A").advisor_mode == cfg


def test_round_trips_through_json():
    cfg = AgentProfileConfig(id="a", name="A")
    cfg.advisor_mode.enabled = True
    cfg.advisor_mode.followup_enabled = False
    raw = json.loads(cfg.model_dump_json())
    assert raw["advisor_mode"] == {
        "enabled": True,
        "plan_enabled": True,
        "followup_enabled": False,
        "on_demand_enabled": True,
        "max_consults": 3,
    }
    back = AgentProfileConfig.model_validate(raw)
    assert back.advisor_mode.enabled is True
    assert back.advisor_mode.followup_enabled is False


def test_legacy_agent_json_without_the_section_loads_with_defaults():
    """Configs written before Advisor Mode existed must keep loading."""
    legacy = AgentProfileConfig(id="a", name="A").model_dump()
    legacy.pop("advisor_mode")
    cfg = AgentProfileConfig.model_validate(legacy)
    assert cfg.advisor_mode.enabled is False
    assert cfg.advisor_mode.followup_enabled is True


def test_max_consults_cannot_be_negative():
    import pytest

    with pytest.raises(ValueError):
        AdvisorModeConfig(max_consults=-1)
