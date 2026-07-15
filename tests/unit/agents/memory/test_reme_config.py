# -*- coding: utf-8 -*-
"""Tests for embedded ReMe configuration mapping."""

from qwenpaw.agents.memory.reme_config import get_reme_app_config
from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentsRunningConfig,
    EmbeddingModelConfig,
    ReMeLightMemoryConfig,
)


def _config_for_embedding(embedding: EmbeddingModelConfig) -> dict:
    agent_config = AgentProfileConfig(
        id="agent-1",
        name="Agent One",
        running=AgentsRunningConfig(
            reme_light_memory_config=ReMeLightMemoryConfig(
                embedding_model_config=embedding,
            ),
        ),
    )
    return get_reme_app_config(
        working_dir="/tmp/qwenpaw-agent",
        agent_config=agent_config,
    )


def test_memory_search_indexes_only_memory_markdown() -> None:
    cfg = _config_for_embedding(EmbeddingModelConfig())

    for job_name in ("index_update_loop", "reindex"):
        job = cfg["jobs"][job_name]
        assert job["watch_dirs"] == ["daily_dir", "digest_dir"]
        assert job["watch_suffixes"] == ["md"]


def test_reme_file_processing_is_limited_to_10_mb() -> None:
    cfg = _config_for_embedding(EmbeddingModelConfig())

    for job_name in ("index_update_loop", "resource_watch_loop", "reindex"):
        assert cfg["jobs"][job_name]["max_file_bytes"] == 10 * 1024 * 1024


def test_status_job_reports_reme_memory_usage() -> None:
    cfg = _config_for_embedding(EmbeddingModelConfig())

    assert cfg["jobs"]["status"] == {
        "backend": "base",
        "description": (
            "report memory estimates for stateful data components and "
            "process RSS"
        ),
        "parameters": {"type": "object", "properties": {}},
        "steps": [{"backend": "status_step"}],
    }


def test_openai_compatible_embedding_requires_api_key() -> None:
    cfg = _config_for_embedding(
        EmbeddingModelConfig(
            backend="openai",
            api_key="",
            base_url="http://localhost:1234/v1",
            model_name="local-embedding",
        ),
    )

    assert cfg["components"]["file_store"]["default"]["embedding_store"] == ""


def test_openai_compatible_embedding_keeps_base_url_credential() -> None:
    cfg = _config_for_embedding(
        EmbeddingModelConfig(
            backend="openai",
            api_key="local-key",
            base_url="http://localhost:1234/v1",
            model_name="local-embedding",
        ),
    )

    assert (
        cfg["components"]["file_store"]["default"]["embedding_store"]
        == "default"
    )
    as_embedding = cfg["components"]["as_embedding"]["default"]
    assert as_embedding["backend"] == "openai"
    assert as_embedding["credential"] == {
        "api_key": "local-key",
        "base_url": "http://localhost:1234/v1",
    }
    assert as_embedding["pass_dimensions"] is False


def test_openai_compatible_embedding_can_pass_dimensions() -> None:
    cfg = _config_for_embedding(
        EmbeddingModelConfig(
            backend="openai",
            api_key="local-key",
            base_url="http://localhost:1234/v1",
            model_name="local-embedding",
            dimensions=768,
            use_dimensions=True,
        ),
    )

    as_embedding = cfg["components"]["as_embedding"]["default"]
    assert as_embedding["dimensions"] == 768
    assert as_embedding["pass_dimensions"] is True


def test_openai_compatible_embedding_omits_blank_base_url() -> None:
    cfg = _config_for_embedding(
        EmbeddingModelConfig(
            backend="openai",
            api_key="openai-key",
            base_url="",
            model_name="text-embedding-3-small",
        ),
    )

    assert cfg["components"]["as_embedding"]["default"]["credential"] == {
        "api_key": "openai-key",
    }


def test_gemini_embedding_uses_api_key_without_base_url() -> None:
    cfg = _config_for_embedding(
        EmbeddingModelConfig(
            backend="gemini",
            api_key="gemini-key",
            base_url="https://ignored.example",
            model_name="gemini-embedding-001",
        ),
    )

    assert (
        cfg["components"]["file_store"]["default"]["embedding_store"]
        == "default"
    )
    assert cfg["components"]["as_embedding"]["default"]["credential"] == {
        "api_key": "gemini-key",
    }
    assert (
        "pass_dimensions" not in cfg["components"]["as_embedding"]["default"]
    )


def test_gemini_embedding_without_api_key_is_disabled() -> None:
    cfg = _config_for_embedding(
        EmbeddingModelConfig(
            backend="gemini",
            api_key="",
            base_url="",
            model_name="gemini-embedding-001",
        ),
    )

    assert cfg["components"]["file_store"]["default"]["embedding_store"] == ""


def test_ollama_embedding_maps_base_url_to_host() -> None:
    cfg = _config_for_embedding(
        EmbeddingModelConfig(
            backend="ollama",
            api_key="ignored",
            base_url="http://localhost:11434",
            model_name="nomic-embed-text",
        ),
    )

    assert (
        cfg["components"]["file_store"]["default"]["embedding_store"]
        == "default"
    )
    assert cfg["components"]["as_embedding"]["default"]["credential"] == {
        "host": "http://localhost:11434",
    }


def test_ollama_embedding_without_host_still_enables_with_model() -> None:
    cfg = _config_for_embedding(
        EmbeddingModelConfig(
            backend="ollama",
            base_url="",
            model_name="nomic-embed-text",
        ),
    )

    assert (
        cfg["components"]["file_store"]["default"]["embedding_store"]
        == "default"
    )
    assert cfg["components"]["as_embedding"]["default"]["credential"] == {}
