# -*- coding: utf-8 -*-
from __future__ import annotations

from copaw.acp.config import ACPConfig


def test_default_harnesses_include_qwen() -> None:
    config = ACPConfig()

    assert "qwen" in config.harnesses
    assert config.require_approval is True
    assert config.show_tool_calls is True

    qwen = config.harnesses["qwen"]
    assert qwen.enabled is True
    assert qwen.command == "npx"
    assert qwen.args == ["-y", "@qwen-code/qwen-code@latest", "--acp"]
    assert qwen.keep_session_default is False
    assert qwen.permission_broker_verified is False


def test_user_harness_overrides_preserve_new_defaults() -> None:
    config = ACPConfig.model_validate(
        {
            "enabled": True,
            "harnesses": {
                "opencode": {"enabled": False},
                "gemini": {"enabled": True},
            },
        },
    )

    assert list(config.harnesses.keys()) == ["opencode", "qwen", "gemini"]
    assert config.harnesses["opencode"].enabled is False
    assert config.harnesses["opencode"].command == "npx"
    assert config.harnesses["opencode"].args == [
        "-y",
        "opencode-ai@latest",
        "acp",
    ]
    assert config.harnesses["qwen"].enabled is True
    assert config.harnesses["qwen"].args == [
        "-y",
        "@qwen-code/qwen-code@latest",
        "--acp",
    ]
    assert config.harnesses["gemini"].enabled is True


def test_show_tool_calls_can_be_overridden() -> None:
    config = ACPConfig.model_validate(
        {
            "enabled": True,
            "show_tool_calls": False,
            "harnesses": {
                "opencode": {"enabled": True},
            },
        },
    )

    assert config.show_tool_calls is False


def test_keep_session_default_can_be_overridden_per_harness() -> None:
    config = ACPConfig.model_validate(
        {
            "enabled": True,
            "harnesses": {
                "opencode": {
                    "enabled": True,
                    "keep_session_default": True,
                },
            },
        },
    )

    assert config.harnesses["opencode"].keep_session_default is True
    assert config.harnesses["qwen"].keep_session_default is False


def test_user_harness_overrides_preserve_keep_session_default() -> None:
    config = ACPConfig.model_validate(
        {
            "enabled": True,
            "harnesses": {
                "opencode": {"enabled": False},
            },
        },
    )

    assert config.harnesses["opencode"].keep_session_default is False
    assert config.harnesses["qwen"].keep_session_default is False


def test_permission_broker_verified_defaults_to_false_for_legacy_config() -> (
    None
):
    config = ACPConfig.model_validate(
        {
            "enabled": True,
            "harnesses": {
                "opencode": {"enabled": True},
            },
        },
    )

    assert config.harnesses["opencode"].permission_broker_verified is False
