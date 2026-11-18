# -*- coding: utf-8 -*-
"""PawApp-managed DataBridge configuration.

The plugin stores DataBridge model/Neo4j settings and the selected datasource
ID in ``config.json``. It translates model and Neo4j settings into the runtime
files the managed context service expects:

* ``.env`` for Neo4j and model environment variables (SQL datasource
  credentials are registered through the context service's datasource
  API instead).
* ``models.json`` for LLM and embedding model settings.

Analysis-agent model preferences are managed separately by the engine API.
These files live in the app working directory so the context service can
pick them up via ``QWENPAW_DATA_ENV_FILE`` and ``MODEL_CONFIG_PATH``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping

from qwenpaw.constant import WORKING_DIR

APP_DATA_DIR = WORKING_DIR / "apps" / "qwenpaw-data"
CONFIG_JSON_PATH = APP_DATA_DIR / "config.json"
ENV_FILE_PATH = APP_DATA_DIR / ".env"
MODELS_JSON_PATH = APP_DATA_DIR / "models.json"


@dataclass
class LLMConfig:
    provider: str = "openai"
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    # When true the fields above are a snapshot of the QwenPaw host's active
    # model and get refreshed from it on every save/start.
    reuse_host: bool = False
    host_provider_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "api_key": self.api_key,
            "reuse_host": self.reuse_host,
            "host_provider_name": self.host_provider_name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> LLMConfig:
        if not data:
            return cls()
        return cls(
            provider=str(data.get("provider", "openai")).strip(),
            base_url=str(data.get("base_url", "")).strip(),
            model=str(data.get("model", "")).strip(),
            api_key=str(data.get("api_key", "")).strip(),
            reuse_host=bool(data.get("reuse_host", False)),
            host_provider_name=str(data.get("host_provider_name", "")).strip(),
        )


@dataclass
class EmbeddingConfig:
    base_url: str = ""
    model: str = ""
    dim: int = 1024
    api_key: str = ""
    # The host has no "active embedding model" concept, so reuse shares the
    # active provider's endpoint and key while the model stays local.
    reuse_host: bool = False
    host_provider_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "dim": self.dim,
            "api_key": self.api_key,
            "reuse_host": self.reuse_host,
            "host_provider_name": self.host_provider_name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> EmbeddingConfig:
        if not data:
            return cls()
        try:
            dim = int(data.get("dim", 1024))
        except (TypeError, ValueError):
            dim = 1024
        return cls(
            base_url=str(data.get("base_url", "")).strip(),
            model=str(data.get("model", "")).strip(),
            dim=dim,
            api_key=str(data.get("api_key", "")).strip(),
            reuse_host=bool(data.get("reuse_host", False)),
            host_provider_name=str(data.get("host_provider_name", "")).strip(),
        )


@dataclass
class Neo4jConfig:
    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = ""
    database: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "user": self.user,
            "password": self.password,
            "database": self.database,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Neo4jConfig:
        if not data:
            return cls()
        return cls(
            uri=str(data.get("uri", "bolt://localhost:7687")).strip(),
            user=str(data.get("user", "neo4j")).strip(),
            password=str(data.get("password", "")).strip(),
            database=str(data.get("database", "")).strip(),
        )


@dataclass
class DatasourcesConfig:
    """Pointer into the context service's semantic-config datasource registry.

    Datasource credentials themselves live in the context service's SQLite
    semantic_config.db (managed via its REST API); only the active selection
    is persisted here because the service keeps it in memory only and loses
    it on restart.
    """

    active_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"active_id": self.active_id}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DatasourcesConfig:
        if not data:
            return cls()
        return cls(
            active_id=str(data.get("active_id", "")).strip(),
        )


@dataclass
class DataAppConfig:
    """DataBridge settings and datasource selection persisted by the PawApp."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    neo4j: Neo4jConfig = field(default_factory=Neo4jConfig)
    datasources: DatasourcesConfig = field(default_factory=DatasourcesConfig)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "llm": self.llm.to_dict(),
            "embedding": self.embedding.to_dict(),
            "neo4j": self.neo4j.to_dict(),
            "datasources": self.datasources.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DataAppConfig:
        if not data:
            return cls()
        return cls(
            llm=LLMConfig.from_dict(data.get("llm")),
            embedding=EmbeddingConfig.from_dict(data.get("embedding")),
            neo4j=Neo4jConfig.from_dict(data.get("neo4j")),
            datasources=DatasourcesConfig.from_dict(data.get("datasources")),
        )


def ensure_config_dir() -> None:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> DataAppConfig:
    """Load the plugin's unified configuration, creating defaults if absent."""
    if not CONFIG_JSON_PATH.is_file():
        return DataAppConfig()
    try:
        data = json.loads(CONFIG_JSON_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return DataAppConfig()
    return DataAppConfig.from_dict(data)


def save_config(config: DataAppConfig) -> None:
    """Persist the configuration and regenerate runtime files."""
    ensure_config_dir()
    tmp_path = CONFIG_JSON_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(config.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp_path.replace(CONFIG_JSON_PATH)
    # The file stores credentials; keep it readable by the owner only.
    try:
        os.chmod(CONFIG_JSON_PATH, 0o600)
    except OSError:
        pass
    prepare_runtime_files(config)


def seed_from_env(
    config: DataAppConfig,
    environment: Mapping[str, str] | None = None,
) -> DataAppConfig:
    """Fill empty fields from the standard environment variables.

    Applied on first run so config.json reflects the values the context
    service would otherwise read from the environment, keeping the
    DataBridge Configuration page and its connection tests truthful.
    """
    environment = os.environ if environment is None else environment

    def env_default(key: str, fallback: str = "") -> str:
        return (environment.get(key) or "").strip() or fallback

    if not config.llm.base_url:
        config.llm.base_url = env_default(
            "OPENAI_BASE_URL",
            "https://api.openai.com/v1",
        )
    if not config.llm.model:
        config.llm.model = env_default("LLM_MODEL", "gpt-4o-mini")
    if not config.llm.api_key:
        config.llm.api_key = env_default("OPENAI_API_KEY")
    if not config.embedding.model:
        config.embedding.model = env_default(
            "EMBED_MODEL",
            "text-embedding-v3",
        )
    if not config.embedding.base_url:
        config.embedding.base_url = (
            env_default("EMBED_OPENAI_BASE_URL") or config.llm.base_url
        )
    if not config.embedding.api_key:
        config.embedding.api_key = (
            env_default("EMBED_OPENAI_API_KEY") or config.llm.api_key
        )
    if not config.embedding.dim:
        try:
            config.embedding.dim = int(env_default("EMBED_DIM", "1024"))
        except ValueError:
            config.embedding.dim = 1024
    if not config.neo4j.password:
        config.neo4j.password = env_default("NEO4J_PASSWORD")
    if not config.neo4j.database:
        config.neo4j.database = env_default("NEO4J_DATABASE")
    return config


def _quote_env(value: str) -> str:
    """Quote values that contain whitespace or shell metacharacters."""
    if not value:
        return ""
    if any(ch in value for ch in " \t\n\"'"):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _env_lines(config: DataAppConfig) -> list[str]:
    """Build key=value lines for the context service .env file."""
    return [
        "# Auto-generated by QwenPaw-Data. Do not edit manually.",
        *(
            f"{key}={_quote_env(value)}"
            for key, value in _context_env_values(config).items()
        ),
    ]


def _context_env_values(config: DataAppConfig) -> dict[str, str]:
    """Build child values from saved settings, without dotenv parsing."""
    values = {
        "NEO4J_URI": config.neo4j.uri,
        "NEO4J_USER": config.neo4j.user,
        "NEO4J_PASSWORD": config.neo4j.password,
        "NEO4J_DATABASE": config.neo4j.database,
        "OPENAI_API_KEY": config.llm.api_key,
        "OPENAI_BASE_URL": config.llm.base_url,
        "LLM_MODEL": config.llm.model,
        "EMBED_OPENAI_API_KEY": config.embedding.api_key,
        "EMBED_OPENAI_BASE_URL": config.embedding.base_url,
        "EMBED_MODEL": config.embedding.model,
        "EMBED_DIM": str(config.embedding.dim) if config.embedding.dim else "",
    }
    return {key: value for key, value in values.items() if value}


def _models_json(config: DataAppConfig) -> dict[str, Any]:
    """Build the context service models.json payload.

    Environment defaults are imported once by ``seed_from_env``. After that,
    config.json is authoritative, including deliberately cleared credentials.
    """
    llm_base_url = config.llm.base_url or "https://api.openai.com/v1"
    llm_model = config.llm.model or "gpt-4o-mini"
    llm_api_key = config.llm.api_key
    embed_model = config.embedding.model or "text-embedding-v3"
    # The embedding endpoint falls back to the shared LLM endpoint/key, the
    # same way the context service resolves EMBED_OPENAI_*.
    embed_base_url = config.embedding.base_url or llm_base_url
    embed_api_key = config.embedding.api_key or llm_api_key
    embed_dim = config.embedding.dim or 1024
    return {
        "llm": {
            "provider": config.llm.provider or "openai",
            "base_url": llm_base_url,
            "model": llm_model,
            "api_key": llm_api_key,
        },
        "embedding": {
            "model": embed_model,
            "base_url": embed_base_url,
            "api_key": embed_api_key,
            "dim": embed_dim,
        },
    }


def prepare_runtime_files(config: DataAppConfig) -> None:
    """Write the .env and models.json files the context service consumes."""
    ensure_config_dir()
    env_text = "\n".join(_env_lines(config)) + "\n"
    env_tmp = ENV_FILE_PATH.with_suffix(".tmp")
    env_tmp.write_text(env_text, encoding="utf-8")
    env_tmp.replace(ENV_FILE_PATH)

    models_text = json.dumps(
        _models_json(config),
        indent=2,
        ensure_ascii=False,
    )
    models_tmp = MODELS_JSON_PATH.with_suffix(".tmp")
    models_tmp.write_text(models_text + "\n", encoding="utf-8")
    models_tmp.replace(MODELS_JSON_PATH)


def context_service_env() -> dict[str, str]:
    """Build literal Context overrides from the latest saved settings.

    Managed keys are never inherited from the Host. Empty fields stay absent
    on the next start; no keys are set or cleared in the Host process.
    """
    return {
        **_context_env_values(load_config()),
        "QWENPAW_DATA_ENV_FILE": str(ENV_FILE_PATH),
        "MODEL_CONFIG_PATH": str(MODELS_JSON_PATH),
    }


async def on_before_start() -> None:
    """Hook invoked before every managed context service start.

    Regenerates runtime files from the latest config.json. Global environment
    management remains the Host's responsibility.
    """
    config = load_config()
    prepare_runtime_files(config)
