# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONFIG_FILE = (
    REPOSITORY_ROOT
    / "plugins"
    / "apps"
    / "qwenpaw-data"
    / "backend"
    / "config.py"
)


def _load_config_module():
    module_name = "qwenpaw_data_app_config_under_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        CONFIG_FILE,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def config_module(tmp_path: Path, monkeypatch):
    module = _load_config_module()
    monkeypatch.setattr(module, "APP_DATA_DIR", tmp_path / "qwenpaw-data")
    monkeypatch.setattr(
        module,
        "CONFIG_JSON_PATH",
        module.APP_DATA_DIR / "config.json",
    )
    monkeypatch.setattr(module, "ENV_FILE_PATH", module.APP_DATA_DIR / ".env")
    monkeypatch.setattr(
        module,
        "MODELS_JSON_PATH",
        module.APP_DATA_DIR / "models.json",
    )
    # Snapshot app-managed env keys so tests that trigger load_app_env()
    # cannot leak rewritten values into the surrounding pytest process.
    for key in (
        *module._APP_MANAGED_ENV_KEYS,
        "QWENPAW_DATA_ENV_FILE",
        "MODEL_CONFIG_PATH",
    ):
        if key in os.environ:
            monkeypatch.setenv(key, os.environ[key])
        else:
            monkeypatch.delenv(key, raising=False)
    return module


def test_default_config_round_trip(config_module) -> None:
    config = config_module.DataAppConfig()
    restored = config_module.DataAppConfig.from_dict(config.to_dict())
    assert restored.to_dict() == config.to_dict()


def test_load_config_creates_defaults_when_missing(config_module) -> None:
    loaded = config_module.load_config()
    assert loaded.llm.provider == "openai"
    assert loaded.neo4j.uri == "bolt://localhost:7687"


def test_save_config_writes_config_and_runtime_files(config_module) -> None:
    config = config_module.DataAppConfig(
        llm=config_module.LLMConfig(
            provider="openai",
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
            api_key="sk-test",
        ),
        neo4j=config_module.Neo4jConfig(
            uri="bolt://localhost:7687",
            user="neo4j",
            password="secret",
            database="neo4j",
        ),
    )
    config_module.save_config(config)

    assert config_module.CONFIG_JSON_PATH.is_file()
    assert config_module.ENV_FILE_PATH.is_file()
    assert config_module.MODELS_JSON_PATH.is_file()

    stored = json.loads(
        config_module.CONFIG_JSON_PATH.read_text(encoding="utf-8"),
    )
    assert stored["llm"]["model"] == "gpt-4o-mini"

    env_text = config_module.ENV_FILE_PATH.read_text(encoding="utf-8")
    assert "NEO4J_URI=bolt://localhost:7687" in env_text
    assert "NEO4J_PASSWORD=secret" in env_text
    assert "OPENAI_API_KEY=sk-test" in env_text

    models = json.loads(
        config_module.MODELS_JSON_PATH.read_text(encoding="utf-8"),
    )
    assert models["llm"]["model"] == "gpt-4o-mini"
    assert models["embedding"]["api_key"] == "sk-test"


def test_env_file_omits_empty_optional_values(config_module) -> None:
    config = config_module.DataAppConfig(
        llm=config_module.LLMConfig(
            provider="openai",
            model="gpt-4o-mini",
            api_key="sk-test",
        ),
        neo4j=config_module.Neo4jConfig(
            uri="bolt://localhost:7687",
            user="neo4j",
            password="secret",
        ),
    )
    config_module.save_config(config)
    env_text = config_module.ENV_FILE_PATH.read_text(encoding="utf-8")
    assert "NEO4J_DATABASE" not in env_text
    assert "OPENAI_BASE_URL" not in env_text


def test_models_json_falls_back_to_env_vars(
    config_module,
    monkeypatch,
) -> None:
    # An unconfigured config.json must not blank out env-derived values that
    # the context service would otherwise have initialized itself.
    monkeypatch.setenv("OPENAI_BASE_URL", "https://dashscope.example.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    monkeypatch.setenv("LLM_MODEL", "qwen3.8-max")
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    monkeypatch.delenv("EMBED_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("EMBED_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("EMBED_DIM", raising=False)

    config_module.prepare_runtime_files(config_module.DataAppConfig())

    models = json.loads(
        config_module.MODELS_JSON_PATH.read_text(encoding="utf-8"),
    )
    assert models["llm"]["base_url"] == "https://dashscope.example.com/v1"
    assert models["llm"]["model"] == "qwen3.8-max"
    assert models["llm"]["api_key"] == "sk-from-env"
    # Embedding falls back to the shared LLM endpoint/key and defaults.
    assert models["embedding"]["model"] == "text-embedding-v3"
    assert (
        models["embedding"]["base_url"] == "https://dashscope.example.com/v1"
    )
    assert models["embedding"]["api_key"] == "sk-from-env"
    assert models["embedding"]["dim"] == 1024


def test_models_json_prefers_config_values_over_env(
    config_module,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")

    config = config_module.DataAppConfig(
        llm=config_module.LLMConfig(
            base_url="https://configured.example.com/v1",
            model="configured-model",
            api_key="sk-configured",
        ),
        embedding=config_module.EmbeddingConfig(
            model="configured-embed",
            base_url="https://embed.example.com/v1",
            api_key="sk-embed",
            dim=768,
        ),
    )
    config_module.prepare_runtime_files(config)

    models = json.loads(
        config_module.MODELS_JSON_PATH.read_text(encoding="utf-8"),
    )
    assert models["llm"]["api_key"] == "sk-configured"
    assert models["llm"]["model"] == "configured-model"
    assert models["embedding"]["model"] == "configured-embed"
    assert models["embedding"]["dim"] == 768


def test_seed_from_env_fills_empty_fields(config_module, monkeypatch) -> None:
    monkeypatch.setenv("NEO4J_PASSWORD", "env-password")
    monkeypatch.setenv("NEO4J_DATABASE", "graphdb")
    monkeypatch.setenv("EMBED_MODEL", "env-embed-model")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")

    config = config_module.seed_from_env(config_module.DataAppConfig())

    assert config.neo4j.password == "env-password"
    assert config.neo4j.database == "graphdb"
    assert config.embedding.model == "env-embed-model"
    assert config.embedding.api_key == "sk-env"
    # Defaults stay intact when the env has nothing to say.
    assert config.neo4j.uri == "bolt://localhost:7687"


def test_seed_from_env_keeps_existing_values(
    config_module,
    monkeypatch,
) -> None:
    monkeypatch.setenv("NEO4J_PASSWORD", "env-password")
    monkeypatch.setenv("LLM_MODEL", "env-model")

    config = config_module.seed_from_env(
        config_module.DataAppConfig(
            llm=config_module.LLMConfig(model="configured-model"),
            neo4j=config_module.Neo4jConfig(password="configured-password"),
        ),
    )

    assert config.llm.model == "configured-model"
    assert config.neo4j.password == "configured-password"


def test_from_dict_ignores_legacy_sql_section(config_module) -> None:
    # config.json files written before datasource credentials moved into
    # the context service's semantic-config registry still carry a "sql"
    # section; loading must ignore it and saving must drop it.
    legacy = config_module.DataAppConfig().to_dict()
    legacy["sql"] = {
        "enabled": True,
        "host": "warehouse.local",
        "port": 6543,
        "user": "etl",
        "password": "secret",
        "db": "analytics",
        "schema": "public",
    }
    config = config_module.DataAppConfig.from_dict(legacy)

    assert "sql" not in config.to_dict()
    assert config.datasources.active_id == ""

    config_module.save_config(config)
    stored = json.loads(
        config_module.CONFIG_JSON_PATH.read_text(encoding="utf-8"),
    )
    assert "sql" not in stored


def test_env_file_drops_legacy_warehouse_lines(config_module) -> None:
    # An .env left behind by an older build may contain DW_* lines; the
    # regenerated file must not carry them anymore.
    config_module.ensure_config_dir()
    config_module.ENV_FILE_PATH.write_text(
        "DW_HOST=warehouse.local\n",
        encoding="utf-8",
    )

    config_module.prepare_runtime_files(config_module.DataAppConfig())

    env_text = config_module.ENV_FILE_PATH.read_text(encoding="utf-8")
    assert "DW_" not in env_text


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows does not expose complete POSIX permission bits",
)
def test_save_config_restricts_file_permissions(config_module) -> None:
    config_module.save_config(config_module.DataAppConfig())
    mode = config_module.CONFIG_JSON_PATH.stat().st_mode & 0o777
    assert mode == 0o600


def test_set_context_env_vars_points_at_generated_files(
    config_module,
) -> None:
    config_module.ensure_config_dir()
    config_module.prepare_runtime_files(config_module.DataAppConfig())
    config_module.set_context_env_vars()

    assert os.environ["QWENPAW_DATA_ENV_FILE"] == str(
        config_module.ENV_FILE_PATH,
    )
    assert os.environ["MODEL_CONFIG_PATH"] == str(
        config_module.MODELS_JSON_PATH,
    )


def test_set_context_env_vars_loads_app_env_with_authority(
    config_module,
    monkeypatch,
) -> None:
    # A user-level ~/.qwenpaw/.env (loaded by the framework at import time)
    # must not survive underneath values saved from the Configure page: the
    # context service reads Neo4j settings from inherited env vars, and
    # its own dotenv pass does not override pre-existing keys.
    monkeypatch.setenv("NEO4J_PASSWORD", "stale-user-level-password")
    config = config_module.DataAppConfig(
        neo4j=config_module.Neo4jConfig(password="configured-password"),
    )
    config_module.save_config(config)

    config_module.set_context_env_vars()

    assert os.environ["NEO4J_PASSWORD"] == "configured-password"


def test_set_context_env_vars_clears_emptied_managed_keys(
    config_module,
    monkeypatch,
) -> None:
    # Keys the app leaves blank are omitted from the generated .env; the
    # stale inherited value must be cleared so emptying a field sticks.
    monkeypatch.setenv("NEO4J_DATABASE", "stale-database")
    config_module.save_config(config_module.DataAppConfig())

    config_module.set_context_env_vars()

    assert "NEO4J_DATABASE" not in os.environ


def test_load_app_env_preserves_unmanaged_neo4j_keys(
    config_module,
    monkeypatch,
) -> None:
    # Dataset-pipeline role databases (NEO4J_DATABASE_DEMO/MCP) are not owned
    # by the Configure page and must survive the managed-key cleanup.
    monkeypatch.setenv("NEO4J_DATABASE_DEMO", "demo-db")
    config_module.save_config(config_module.DataAppConfig())

    config_module.load_app_env()

    assert os.environ["NEO4J_DATABASE_DEMO"] == "demo-db"


def test_password_value_is_quoted_when_it_contains_spaces(
    config_module,
) -> None:
    config = config_module.DataAppConfig(
        neo4j=config_module.Neo4jConfig(password="has spaces"),
    )
    config_module.save_config(config)
    env_text = config_module.ENV_FILE_PATH.read_text(encoding="utf-8")
    assert 'NEO4J_PASSWORD="has spaces"' in env_text


async def test_on_before_start_regenerates_runtime_files(
    config_module,
) -> None:
    config = config_module.DataAppConfig(
        llm=config_module.LLMConfig(api_key="sk-restart"),
    )
    config_module.save_config(config)

    # Pretend a stale runtime file exists.
    config_module.MODELS_JSON_PATH.write_text("{}", encoding="utf-8")

    await config_module.on_before_start()

    models = json.loads(
        config_module.MODELS_JSON_PATH.read_text(encoding="utf-8"),
    )
    assert models["llm"]["api_key"] == "sk-restart"
    assert os.environ["QWENPAW_DATA_ENV_FILE"] == str(
        config_module.ENV_FILE_PATH,
    )
