# -*- coding: utf-8 -*-
"""Unified QwenPaw-Data configuration.

The plugin stores all user-editable configuration in ``config.json`` and
translates it into the runtime files the managed context service expects:

* ``.env`` for Neo4j and SQL datasource environment variables.
* ``models.json`` for LLM and embedding model settings.

These files live in the app working directory so the context service can
pick them up via ``QWENPAW_DATA_ENV_FILE`` and ``MODEL_CONFIG_PATH``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

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
    """Single source of truth for the qwenpaw-data plugin."""

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


def seed_from_env(config: DataAppConfig) -> DataAppConfig:
    """Fill empty fields from the standard environment variables.

    Applied on first run so config.json reflects the values the context
    service would otherwise read from the environment, keeping the
    Configure page and its connection tests truthful from the start.
    """
    if not config.llm.base_url:
        config.llm.base_url = _env_default(
            "OPENAI_BASE_URL",
            "https://api.openai.com/v1",
        )
    if not config.llm.model:
        config.llm.model = _env_default("LLM_MODEL", "gpt-4o-mini")
    if not config.llm.api_key:
        config.llm.api_key = _env_default("OPENAI_API_KEY")
    if not config.embedding.model:
        config.embedding.model = _env_default(
            "EMBED_MODEL",
            "text-embedding-v3",
        )
    if not config.embedding.base_url:
        config.embedding.base_url = (
            _env_default("EMBED_OPENAI_BASE_URL") or config.llm.base_url
        )
    if not config.embedding.api_key:
        config.embedding.api_key = (
            _env_default("EMBED_OPENAI_API_KEY") or config.llm.api_key
        )
    if not config.embedding.dim:
        try:
            config.embedding.dim = int(_env_default("EMBED_DIM", "1024"))
        except ValueError:
            config.embedding.dim = 1024
    if not config.neo4j.password:
        config.neo4j.password = _env_default("NEO4J_PASSWORD")
    if not config.neo4j.database:
        config.neo4j.database = _env_default("NEO4J_DATABASE")
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
    lines: list[str] = [
        "# Auto-generated by QwenPaw-Data. Do not edit manually.",
    ]
    for key, value in (
        ("NEO4J_URI", config.neo4j.uri),
        ("NEO4J_USER", config.neo4j.user),
        ("NEO4J_PASSWORD", config.neo4j.password),
        ("NEO4J_DATABASE", config.neo4j.database),
    ):
        if value:
            lines.append(f"{key}={_quote_env(value)}")
    if config.llm.api_key:
        lines.append(f"OPENAI_API_KEY={_quote_env(config.llm.api_key)}")
    if config.llm.base_url:
        lines.append(f"OPENAI_BASE_URL={_quote_env(config.llm.base_url)}")
    if config.llm.model:
        lines.append(f"LLM_MODEL={_quote_env(config.llm.model)}")
    if config.embedding.api_key:
        lines.append(
            f"EMBED_OPENAI_API_KEY={_quote_env(config.embedding.api_key)}",
        )
    if config.embedding.base_url:
        lines.append(
            f"EMBED_OPENAI_BASE_URL={_quote_env(config.embedding.base_url)}",
        )
    if config.embedding.model:
        lines.append(f"EMBED_MODEL={_quote_env(config.embedding.model)}")
    if config.embedding.dim:
        lines.append(f"EMBED_DIM={config.embedding.dim}")
    return lines


def _env_default(key: str, fallback: str = "") -> str:
    """Resolve an unset config field from the environment.

    Mirrors the context service's env-based initialization so an unconfigured
    config.json still yields the same models.json the service would have
    created on its own instead of overriding valid env vars with blanks.
    """
    return (os.getenv(key) or "").strip() or fallback


def _models_json(config: DataAppConfig) -> dict[str, Any]:
    """Build the context service models.json payload.

    Empty fields fall back to the standard env vars, then to the context
    service's own defaults, matching ``_initial_from_env()`` semantics.
    """
    llm_base_url = config.llm.base_url or _env_default(
        "OPENAI_BASE_URL",
        "https://api.openai.com/v1",
    )
    llm_model = config.llm.model or _env_default("LLM_MODEL", "gpt-4o-mini")
    llm_api_key = config.llm.api_key or _env_default("OPENAI_API_KEY")
    embed_model = config.embedding.model or _env_default(
        "EMBED_MODEL",
        "text-embedding-v3",
    )
    # The embedding endpoint falls back to the shared LLM endpoint/key, the
    # same way the context service resolves EMBED_OPENAI_*.
    embed_base_url = (
        config.embedding.base_url
        or _env_default("EMBED_OPENAI_BASE_URL")
        or llm_base_url
    )
    embed_api_key = (
        config.embedding.api_key
        or _env_default("EMBED_OPENAI_API_KEY")
        or llm_api_key
    )
    if config.embedding.dim:
        embed_dim = config.embedding.dim
    else:
        try:
            embed_dim = int(_env_default("EMBED_DIM", "1024"))
        except ValueError:
            embed_dim = 1024
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


# Keys the Configure page owns. The generated .env is the authority for
# them: values from ~/.qwenpaw/.env or the shell must never survive
# underneath, while unrelated keys (e.g. NEO4J_DATABASE_DEMO/MCP used by
# dataset pipelines) stay untouched.
_APP_MANAGED_ENV_KEYS = frozenset(
    {
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "NEO4J_DATABASE",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "LLM_MODEL",
        "EMBED_OPENAI_API_KEY",
        "EMBED_OPENAI_BASE_URL",
        "EMBED_MODEL",
        "EMBED_DIM",
    },
)


def set_context_env_vars() -> None:
    """Point the managed context service at the generated runtime files.

    The context service reads Neo4j/SQL settings straight from process env
    vars (its frozen Config has no file or API channel for them, unlike
    LLM/embedding which also get models.json plus the model-config API), so
    the generated .env must be loaded into *this* process as well: managed
    children inherit os.environ, and without this step a user-level
    ~/.qwenpaw/.env or a shell export would silently win over values saved
    from the Configure page.
    """
    os.environ["QWENPAW_DATA_ENV_FILE"] = str(ENV_FILE_PATH)
    os.environ["MODEL_CONFIG_PATH"] = str(MODELS_JSON_PATH)
    load_app_env()


def load_app_env() -> None:
    """Load the app-scoped .env into this process with app authority.

    Managed keys are cleared before loading so values inherited from
    ~/.qwenpaw/.env or the shell cannot outlive a Configure-page save;
    keys the app leaves empty (and therefore omits from the .env) are
    cleared too, which makes emptying a field in the UI stick.
    """
    for key in _APP_MANAGED_ENV_KEYS:
        os.environ.pop(key, None)
    if ENV_FILE_PATH.is_file():
        load_dotenv(ENV_FILE_PATH, override=True)


async def on_before_start() -> None:
    """Hook invoked before every managed context service start.

    Reloads persisted framework envs and regenerates runtime files from the
    latest config.json so restarting the app always picks up new settings.
    """
    from qwenpaw.envs import load_envs_into_environ

    load_envs_into_environ()
    config = load_config()
    prepare_runtime_files(config)
    set_context_env_vars()
