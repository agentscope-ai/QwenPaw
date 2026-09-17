# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from models import config


def test_persisted_grounding_disabled_wins_over_enabled_environment(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "model_config.json"
    config_path.write_text(
        '{"grounding":{"enabled":false}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("WEB_GROUNDING_ENABLED", "1")
    config._clear_user_config_cache()

    try:
        assert config.get_web_grounding_enabled() is False
    finally:
        config._clear_user_config_cache()


def test_runtime_reads_decrypt_persisted_search_provider_keys(
    tmp_path,
    monkeypatch,
):
    """Encrypted-at-rest search keys must decrypt on the runtime read path."""
    config_path = tmp_path / "model_config.json"
    config_path.write_text(
        '{"grounding":{'
        '"tavily_api_key":"ENC:tvly",'
        '"serper_api_key":"ENC:serper"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("WEB_GROUNDING_SERPER_API_KEY", raising=False)
    monkeypatch.setattr(config, "_SECRET_STORE_AVAILABLE", True)
    monkeypatch.setattr(
        config,
        "_secret_is_encrypted",
        lambda value: value.startswith("ENC:"),
    )
    monkeypatch.setattr(
        config,
        "_secret_decrypt",
        lambda value: f"decrypted-{value.removeprefix('ENC:')}",
    )
    config._clear_user_config_cache()

    try:
        assert config.get_web_grounding_tavily_api_key() == "decrypted-tvly"
        assert config.get_web_grounding_serper_api_key() == "decrypted-serper"
    finally:
        config._clear_user_config_cache()


def test_grounding_request_config_preserves_explicit_disabled(monkeypatch):
    monkeypatch.setenv("WEB_GROUNDING_ENABLED", "1")
    token = config.set_request_tool_configs(
        {
            config.CREATOR_GROUNDING_CONFIG_TOOL: {
                "enabled": False,
                "reuse_llm": True,
            },
        },
    )
    try:
        assert config.get_web_grounding_enabled() is False
    finally:
        config.reset_request_tool_configs(token)


def test_grounding_reuses_creator_llm_by_default(monkeypatch):
    monkeypatch.setattr(config, "get_text_api_key", lambda: "llm-key")
    monkeypatch.setattr(
        config,
        "get_text_base_url",
        lambda: "https://llm.example.test/v1",
    )
    monkeypatch.setattr(config, "get_text_model_name", lambda: "qwen-test")
    token = config.set_request_tool_configs(
        {
            config.CREATOR_GROUNDING_CONFIG_TOOL: {
                "enabled": True,
                "reuse_llm": True,
            },
        },
    )
    try:
        assert config.get_web_grounding_model_api_key() == "llm-key"
        assert (
            config.get_web_grounding_model_base_url()
            == "https://llm.example.test/v1"
        )
        assert config.get_web_grounding_model_name() == "qwen-test"
    finally:
        config.reset_request_tool_configs(token)


def test_grounding_can_override_creator_llm():
    token = config.set_request_tool_configs(
        {
            config.CREATOR_GROUNDING_CONFIG_TOOL: {
                "enabled": True,
                "reuse_llm": False,
                "api_key": "grounding-key",
                "base_url": "https://grounding.example.test/v1",
                "model": "grounding-qwen",
            },
        },
    )
    try:
        assert config.get_web_grounding_model_api_key() == "grounding-key"
        assert (
            config.get_web_grounding_model_base_url()
            == "https://grounding.example.test/v1"
        )
        assert config.get_web_grounding_model_name() == "grounding-qwen"
    finally:
        config.reset_request_tool_configs(token)


def test_grounding_search_and_validation_models_are_independent(monkeypatch):
    monkeypatch.setattr(config, "get_vlm_api_key", lambda: "verifier-key")
    monkeypatch.setattr(
        config,
        "get_vlm_base_url",
        lambda: "https://vision.example.test/v1",
    )
    monkeypatch.setattr(config, "get_vlm_model_name", lambda: "generic-vlm")
    token = config.set_request_tool_configs(
        {
            config.CREATOR_GROUNDING_CONFIG_TOOL: {
                "enabled": True,
                "validation_source": "vlm",
                "search_reuse_llm": False,
                "search_api_key": "search-key",
                "search_base_url": (
                    "https://dashscope.aliyuncs.com/compatible-mode/v1"
                ),
                "search_model": "qwen3.7-plus",
                "search_protocol": "DashScope（百炼）",
            },
        },
    )
    try:
        assert config.get_web_grounding_model_api_key() == "verifier-key"
        assert config.get_web_grounding_model_name() == "generic-vlm"
        assert config.get_web_grounding_search_api_key() == "search-key"
        assert config.get_web_grounding_search_model_name() == "qwen3.7-plus"
    finally:
        config.reset_request_tool_configs(token)


def test_grounding_runtime_policy_does_not_read_environment(monkeypatch):
    policy = (
        (
            "WEB_GROUNDING_TIMEOUT_SECONDS",
            config.get_web_grounding_timeout_seconds,
            60,
        ),
        (
            "WEB_GROUNDING_MAX_SOURCES",
            config.get_web_grounding_max_sources,
            6,
        ),
        (
            "WEB_GROUNDING_MAX_ENTITIES",
            config.get_web_grounding_max_entities,
            3,
        ),
        (
            "WEB_GROUNDING_ENTITY_TIMEOUT_SECONDS",
            config.get_web_grounding_entity_timeout_seconds,
            20,
        ),
        (
            "WEB_GROUNDING_VISUAL_SEARCH_TIMEOUT_SECONDS",
            config.get_web_grounding_visual_search_timeout_seconds,
            120,
        ),
        (
            "WEB_GROUNDING_IMAGE_DOWNLOAD_TIMEOUT_SECONDS",
            config.get_web_grounding_image_download_timeout_seconds,
            30,
        ),
        (
            "WEB_GROUNDING_VERIFICATION_TIMEOUT_SECONDS",
            config.get_web_grounding_verification_timeout_seconds,
            120,
        ),
        (
            "WEB_GROUNDING_VERIFICATION_MAX_ATTEMPTS",
            config.get_web_grounding_verification_max_attempts,
            3,
        ),
        (
            "WEB_GROUNDING_VERIFICATION_TOTAL_BUDGET_SECONDS",
            config.get_web_grounding_verification_total_budget_seconds,
            300,
        ),
        (
            "WEB_GROUNDING_RETRY_BASE_SECONDS",
            config.get_web_grounding_retry_base_seconds,
            1,
        ),
        (
            "WEB_GROUNDING_RETRY_MAX_SECONDS",
            config.get_web_grounding_retry_max_seconds,
            8,
        ),
    )
    for env_name, _getter, _expected in policy:
        monkeypatch.setenv(env_name, "999")

    assert [
        (env_name, getter()) for env_name, getter, _expected in policy
    ] == [(env_name, expected) for env_name, _getter, expected in policy]
