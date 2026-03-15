# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from copaw.acp.config import ACPConfig


def test_default_harnesses_include_qwen() -> None:
    config = ACPConfig()

    assert "qwen" in config.harnesses

    qwen = config.harnesses["qwen"]
    assert qwen.enabled is True
    assert qwen.command == "npx"
    assert qwen.args == ["-y", "@qwen-code/qwen-code@latest", "--acp"]


def test_user_harness_overrides_preserve_new_defaults() -> None:
    config = ACPConfig.model_validate(
        {
            "enabled": True,
            "harnesses": {
                "opencode": {"enabled": False},
                "gemini": {"enabled": True},
            },
        }
    )

    assert list(config.harnesses.keys()) == ["opencode", "qwen", "gemini"]
    assert config.harnesses["opencode"].enabled is False
    assert config.harnesses["opencode"].command == "npx"
    assert config.harnesses["opencode"].args == ["-y", "opencode-ai@latest", "acp"]
    assert config.harnesses["qwen"].enabled is True
    assert config.harnesses["qwen"].args == ["-y", "@qwen-code/qwen-code@latest", "--acp"]
    assert config.harnesses["gemini"].enabled is True
