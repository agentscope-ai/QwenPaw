import pytest
from pydantic import ValidationError

from qwenpaw.config.config import AgentsRunningConfig
from qwenpaw.config.config import DoomLoopStageConfig


def test_running_config_accepts_minimum_acquire_timeout_without_cross_field_limit():
    config = AgentsRunningConfig(
        llm_rate_limit_pause=60,
        llm_rate_limit_jitter=10,
        llm_acquire_timeout=10,
    )

    assert config.llm_acquire_timeout == 10


@pytest.mark.parametrize("value", ["invalid", "bypass", "ROOT"])
def test_running_config_rejects_unknown_tool_execution_level(value: str):
    with pytest.raises(ValidationError):
        AgentsRunningConfig(approval_level=value)


@pytest.mark.parametrize("action", ["continue", "retry", "STOP"])
def test_doom_loop_stage_rejects_unknown_action(action: str):
    with pytest.raises(ValidationError):
        DoomLoopStageConfig(after=2, action=action, prompt="invalid")
