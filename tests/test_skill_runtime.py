# -*- coding: utf-8 -*-
import os

import pytest
from fastapi import HTTPException

from copaw.agents.skill_metadata import parse_skill_metadata_from_content
from copaw.agents.skill_runtime import (
    apply_skill_env_overrides,
    compute_skill_eligibility,
    has_skill_env_overrides,
)
from copaw.agents.skills_manager import SkillInfo
from copaw.app.routers.skills import _validate_skill_env_payload
from copaw.config.config import Config, SkillEntryConfig, SkillsConfig


class DummySkill:
    def __init__(self, name, metadata):
        self.name = name
        self.metadata = metadata


def test_skill_metadata_enables_api_key_backed_eligibility(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DEMO_API_KEY", raising=False)

    content = """---
name: demo_skill
description: demo
metadata:
  {
    "copaw":
      {
        "skillKey": "demo_alias",
        "primaryEnv": "DEMO_API_KEY",
        "requires": { "env": ["DEMO_API_KEY"] }
      }
  }
---
demo
"""

    metadata = parse_skill_metadata_from_content(content)
    assert metadata is not None
    assert metadata.primary_env == "DEMO_API_KEY"

    empty_config = Config()
    missing = compute_skill_eligibility(
        config=empty_config,
        skill_name="demo_skill",
        metadata=metadata,
    )
    assert missing.eligible is False
    assert missing.missing_env == ["DEMO_API_KEY"]

    configured = Config(
        skills=SkillsConfig(
            entries={
                "demo_alias": SkillEntryConfig(apiKey="secret-token"),
            },
        ),
    )
    eligible = compute_skill_eligibility(
        config=configured,
        skill_name="demo_skill",
        metadata=metadata,
    )
    assert eligible.eligible is True
    assert eligible.missing_env == []


def test_apply_skill_env_overrides_injects_and_restores(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_API_KEY", "existing-token")
    monkeypatch.setenv("DEMO_REGION", "us")

    metadata = parse_skill_metadata_from_content(
        """---
name: demo_skill
description: demo
metadata:
  {
    "copaw":
      {
        "skillKey": "demo_alias",
        "primaryEnv": "DEMO_API_KEY",
        "requires": { "env": ["DEMO_API_KEY"] }
      }
  }
---
demo
""",
    )
    assert metadata is not None

    config = Config(
        skills=SkillsConfig(
            entries={
                "demo_alias": SkillEntryConfig(
                    apiKey="secret-token",
                    env={"DEMO_REGION": "cn"},
                ),
            },
        ),
    )

    skill = DummySkill(name="demo_skill", metadata=metadata)
    assert has_skill_env_overrides([skill], config) is True

    with apply_skill_env_overrides([skill], config):
        assert os.environ["DEMO_API_KEY"] == "secret-token"
        assert os.environ["DEMO_REGION"] == "cn"

    assert os.environ["DEMO_API_KEY"] == "existing-token"
    assert os.environ["DEMO_REGION"] == "us"


def test_validate_skill_env_payload_rejects_undeclared_keys() -> None:
    metadata = parse_skill_metadata_from_content(
        """---
name: demo_skill
description: demo
metadata:
  {
    "copaw":
      {
        "skillKey": "demo_alias",
        "primaryEnv": "DEMO_API_KEY",
        "requires": { "env": ["DEMO_API_KEY", "DEMO_REGION"] }
      }
  }
---
demo
""",
    )
    assert metadata is not None

    skill = SkillInfo(
        name="demo_skill",
        content="demo",
        source="builtin",
        path="/tmp/demo_skill",
        metadata=metadata,
        resolved_skill_key="demo_alias",
    )

    _validate_skill_env_payload(
        skill,
        {"DEMO_REGION": "cn", "DEMO_API_KEY": "secret-token"},
    )

    with pytest.raises(HTTPException) as exc:
        _validate_skill_env_payload(
            skill,
            {"OPENAI_API_KEY": "should-not-be-allowed"},
        )

    assert exc.value.status_code == 400
    assert "OPENAI_API_KEY" in str(exc.value.detail)
