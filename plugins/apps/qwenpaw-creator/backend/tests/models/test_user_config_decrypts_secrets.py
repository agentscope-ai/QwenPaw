# -*- coding: utf-8 -*-
"""Test _get_user_config() decrypts encrypted secret fields."""
# pylint: disable=protected-access
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from models import config


def test_get_user_config_decrypts_encrypted_secrets(tmp_path: Path) -> None:
    """_get_user_config() should decrypt ENC:... values to plaintext."""
    config_file = tmp_path / "model_config.json"
    config_file.write_text(
        json.dumps(
            {
                "llm": {
                    "api_key": "ENC:encrypted_llm_key",
                    "base_url": "https://example.com/v1",
                },
                "oss": {
                    "access_key_secret": "ENC:encrypted_oss_secret",
                    "policy_api_key": "ENC:encrypted_policy_key",
                },
            },
        ),
        encoding="utf-8",
    )

    def mock_decrypt(value: str) -> str:
        if value.startswith("ENC:"):
            return value[4:].replace("encrypted_", "decrypted_")
        return value

    def mock_is_encrypted(value: str) -> bool:
        return value.startswith("ENC:")

    config._clear_user_config_cache()

    with (
        patch.object(config, "_SECRET_STORE_AVAILABLE", True),
        patch.object(config, "_secret_decrypt", mock_decrypt),
        patch.object(
            config,
            "_secret_is_encrypted",
            mock_is_encrypted,
        ),
        patch.object(
            config,
            "_get_model_config_path",
            return_value=config_file,
        ),
    ):
        result = config._get_user_config()

    assert result["llm"]["api_key"] == "decrypted_llm_key"
    assert result["oss"]["access_key_secret"] == "decrypted_oss_secret"
    assert result["oss"]["policy_api_key"] == "decrypted_policy_key"
    assert result["llm"]["base_url"] == "https://example.com/v1"


def test_get_user_config_handles_mixed_encrypted_and_plaintext(
    tmp_path: Path,
) -> None:
    """Handle a mix of encrypted and plaintext values."""
    config_file = tmp_path / "model_config.json"
    config_file.write_text(
        json.dumps(
            {
                "llm": {
                    "api_key": "ENC:encrypted_key",
                },
                "image": {
                    "api_key": "sk-plaintext-image-key",
                },
                "oss": {
                    "access_key_secret": "",
                    "policy_api_key": None,
                },
            },
        ),
        encoding="utf-8",
    )

    def mock_decrypt(value: str) -> str:
        return value[4:] if value.startswith("ENC:") else value

    def mock_is_encrypted(value: str) -> bool:
        return value.startswith("ENC:")

    config._clear_user_config_cache()

    with (
        patch.object(config, "_SECRET_STORE_AVAILABLE", True),
        patch.object(config, "_secret_decrypt", mock_decrypt),
        patch.object(
            config,
            "_secret_is_encrypted",
            mock_is_encrypted,
        ),
        patch.object(
            config,
            "_get_model_config_path",
            return_value=config_file,
        ),
    ):
        result = config._get_user_config()

    assert result["llm"]["api_key"] == "encrypted_key"
    assert result["image"]["api_key"] == "sk-plaintext-image-key"
    assert result["oss"]["access_key_secret"] == ""
    assert result["oss"]["policy_api_key"] is None


def test_get_user_config_graceful_when_secret_store_unavailable(
    tmp_path: Path,
) -> None:
    """Return raw values when secret store is unavailable."""
    config_file = tmp_path / "model_config.json"
    config_file.write_text(
        json.dumps(
            {
                "llm": {
                    "api_key": "ENC:encrypted_key",
                },
            },
        ),
        encoding="utf-8",
    )

    config._clear_user_config_cache()

    with (
        patch.object(config, "_SECRET_STORE_AVAILABLE", False),
        patch.object(
            config,
            "_get_model_config_path",
            return_value=config_file,
        ),
    ):
        result = config._get_user_config()

    assert result["llm"]["api_key"] == "ENC:encrypted_key"
