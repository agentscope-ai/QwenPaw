# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from copaw.acp.types import parse_external_agent_config


def test_parse_external_agent_config_from_top_level_extra() -> None:
    request = SimpleNamespace(
        external_agent={
            "enabled": True,
            "harness": "qwen-code",
            "keep_session": True,
        },
    )

    config = parse_external_agent_config(request)

    assert config is not None
    assert config.enabled is True
    assert config.harness == "qwen"
    assert config.keep_session is True


def test_parse_external_agent_config_from_model_extra() -> None:
    request = SimpleNamespace(
        model_extra={
            "biz_params": {
                "external_agent": {
                    "enabled": True,
                    "harness": "opencode",
                    "keep_session": False,
                }
            }
        },
    )

    config = parse_external_agent_config(request)

    assert config is not None
    assert config.harness == "opencode"
    assert config.keep_session is False


def test_parse_external_agent_config_from_biz_params() -> None:
    request = SimpleNamespace(
        biz_params={
            "external_agent": {
                "enabled": True,
                "harness": "open-code",
                "keep_session": True,
            }
        },
    )

    config = parse_external_agent_config(request)

    assert config is not None
    assert config.harness == "opencode"
    assert config.keep_session is True


def test_parse_external_agent_config_returns_none_for_disabled_payload() -> None:
    request = SimpleNamespace(
        external_agent={"enabled": False, "harness": "opencode"},
    )

    assert parse_external_agent_config(request) is None
