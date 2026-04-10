# -*- coding: utf-8 -*-
"""Tests for learning-related config classes."""
from copaw.config.config import (
    AgentsDefaultsConfig,
    SignalWeightsConfig,
    SkillLearningConfig,
    TaskDispatcherConfig,
)


class TestSignalWeightsConfig:
    def test_defaults(self):
        w = SignalWeightsConfig()
        assert w.tool_call == 1
        assert w.error_recovery == 3
        assert w.user_correction == 5

    def test_alias_parsing(self):
        w = SignalWeightsConfig.model_validate(
            {
                "toolCall": 2,
                "errorRecovery": 4,
                "userCorrection": 6,
            },
        )
        assert w.tool_call == 2
        assert w.error_recovery == 4
        assert w.user_correction == 6


class TestSkillLearningConfig:
    def test_defaults(self):
        cfg = SkillLearningConfig()
        assert cfg.enabled is False
        assert cfg.threshold == 10
        assert cfg.target == "workspace"
        assert cfg.notify == "last"
        assert cfg.track_usage is True

    def test_from_json(self):
        cfg = SkillLearningConfig.model_validate(
            {
                "enabled": True,
                "threshold": 15,
                "signalWeights": {
                    "toolCall": 2,
                    "errorRecovery": 5,
                    "userCorrection": 10,
                },
                "maxIterations": 12,
                "timeoutSeconds": 300,
                "notify": "last",
            },
        )
        assert cfg.enabled is True
        assert cfg.threshold == 15
        assert cfg.signal_weights.tool_call == 2
        assert cfg.max_iterations == 12


class TestTaskDispatcherConfig:
    def test_defaults(self):
        cfg = TaskDispatcherConfig()
        assert cfg.enabled is False
        assert cfg.check_interval == "5m"
        assert cfg.task_board == "markdown"
        assert cfg.max_concurrent_dispatches == 3

    def test_from_json(self):
        cfg = TaskDispatcherConfig.model_validate(
            {
                "enabled": True,
                "checkInterval": "10m",
                "taskBoard": "json",
                "maxConcurrentDispatches": 5,
                "taskTimeoutMinutes": 60,
            },
        )
        assert cfg.enabled is True
        assert cfg.check_interval == "10m"
        assert cfg.max_concurrent_dispatches == 5


class TestAgentsDefaultsConfig:
    def test_with_learning(self):
        cfg = AgentsDefaultsConfig.model_validate(
            {
                "skillLearning": {"enabled": True, "threshold": 20},
                "taskDispatcher": {"enabled": True},
            },
        )
        assert cfg.skill_learning is not None
        assert cfg.skill_learning.enabled is True
        assert cfg.skill_learning.threshold == 20
        assert cfg.task_dispatcher is not None
        assert cfg.task_dispatcher.enabled is True

    def test_backward_compat(self):
        """Old config without new fields still works."""
        cfg = AgentsDefaultsConfig.model_validate(
            {"heartbeat": {"enabled": False}},
        )
        assert cfg.heartbeat is not None
        assert cfg.skill_learning is None
        assert cfg.task_dispatcher is None
