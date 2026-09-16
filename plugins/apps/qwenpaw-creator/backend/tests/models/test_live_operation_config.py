# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
"""Live operation default and the disable paths users actually have."""

from models import config


def test_live_operation_defaults_on_and_persisted_disable_wins(
    tmp_path,
    monkeypatch,
):
    """Enabled by default (no settings UI exists yet to turn it on), while
    persisted config remains the authoritative off-switch over environment."""
    config_path = tmp_path / "model_config.json"
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("CREATOR_LIVE_OPERATION_ENABLED", raising=False)
    monkeypatch.delenv("CREATOR_COMPUTER_USE_ENABLED", raising=False)
    config._clear_user_config_cache()
    try:
        assert config.get_live_operation_enabled() is True
        assert config.get_computer_use_enabled() is False

        monkeypatch.setenv("CREATOR_LIVE_OPERATION_ENABLED", "0")
        assert config.get_live_operation_enabled() is False

        config_path.write_text(
            '{"live_operation":{"enabled":"false"}}',
            encoding="utf-8",
        )
        monkeypatch.setenv("CREATOR_LIVE_OPERATION_ENABLED", "1")
        config._clear_user_config_cache()
        assert config.get_live_operation_enabled() is False
    finally:
        config._clear_user_config_cache()
