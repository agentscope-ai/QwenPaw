# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,wrong-import-order
# pylint: disable=protected-access,unused-import
"""Unit tests for embedding adapter."""

import importlib.util
import os
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(_SRC))

from copaw.config.config import EmbeddingConfig  # noqa: E402

_EMB_PATH = _SRC / "copaw" / "agents" / "memory" / "embedding_adapter.py"
_spec = importlib.util.spec_from_file_location(
    "copaw.agents.memory.embedding_adapter",
    _EMB_PATH,
)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Cannot load embedding_adapter module")
_emb = importlib.util.module_from_spec(_spec)
sys.modules["copaw.agents.memory.embedding_adapter"] = _emb
_spec.loader.exec_module(_emb)

EmbeddingAdapter = _emb.EmbeddingAdapter
DEFAULT_EMBEDDING_DIMENSIONS = _emb.DEFAULT_EMBEDDING_DIMENSIONS
EmbeddingModeResult = _emb.EmbeddingModeResult
RemoteEmbeddingConfig = _emb.RemoteEmbeddingConfig
create_embedding_adapter = _emb.create_embedding_adapter
get_reme_embedding_and_vector_enabled = (
    _emb.get_reme_embedding_and_vector_enabled
)


class TestEmbeddingAdapter:
    """Test EmbeddingAdapter functionality."""

    def test_create_adapter(self):
        """Test adapter creation."""
        config = EmbeddingConfig(enabled=False)
        adapter = create_embedding_adapter(config, strict_local=False)

        assert isinstance(adapter, EmbeddingAdapter)
        assert adapter._file_config.enabled is False
        assert adapter.strict_local is False

    def test_determine_mode_disabled(self):
        """Disabled in config yields disabled mode."""
        config = EmbeddingConfig(enabled=False)
        adapter = create_embedding_adapter(config, strict_local=False)

        result = adapter.determine_mode()

        assert result.mode == "disabled"
        assert result.vector_enabled is False
        assert result.fallback_applied is False

    def test_check_remote_available_no_env(self):
        """Remote availability check without env vars."""
        config = EmbeddingConfig(
            enabled=True,
            backend_type="openai",
            api_key="",
            base_url="",
            model_name="",
        )
        adapter = create_embedding_adapter(config, strict_local=False)

        for key in [
            "EMBEDDING_API_KEY",
            "EMBEDDING_BASE_URL",
            "EMBEDDING_MODEL_NAME",
        ]:
            os.environ.pop(key, None)

        available, reason = adapter._check_remote_available()

        assert available is False
        assert reason is not None
        assert "EMBEDDING_API_KEY" in reason

    def test_get_file_store_config(self):
        """Test file store config generation."""
        config = EmbeddingConfig(enabled=False)
        adapter = create_embedding_adapter(config, strict_local=False)

        store_config = adapter.get_file_store_config()

        assert "vector_enabled" in store_config
        assert store_config["vector_enabled"] is False

    def test_local_config_uses_preset_dimensions(self):
        """Local config dimensions are inferred from model presets."""
        config = EmbeddingConfig(
            enabled=True,
            backend_type="transformers",
            model_id="BAAI/bge-small-zh",
        )
        adapter = create_embedding_adapter(config, strict_local=False)
        adapter._current_mode = "local"

        embedding_config = adapter.get_reme_embedding_config()

        assert embedding_config["backend"] == "local"
        assert embedding_config["backend_type"] == "transformers"
        assert embedding_config["dimensions"] == 512

    def test_local_config_uses_2048_when_model_unknown(self):
        """Unknown local model falls back to 2048 dimensions."""
        config = EmbeddingConfig(
            enabled=True,
            backend_type="transformers",
            model_id="unknown/model",
        )
        adapter = create_embedding_adapter(config, strict_local=False)
        adapter._current_mode = "local"

        embedding_config = adapter.get_reme_embedding_config()

        assert embedding_config["backend"] == "local"
        assert embedding_config["backend_type"] == "transformers"
        assert embedding_config["dimensions"] == 2048

    def test_remote_file_config_without_env(self, monkeypatch):
        """Remote creds from agent JSON without embedding env vars."""
        for key in (
            "EMBEDDING_API_KEY",
            "EMBEDDING_BASE_URL",
            "EMBEDDING_MODEL_NAME",
        ):
            monkeypatch.delenv(key, raising=False)

        remote = EmbeddingConfig(
            enabled=True,
            backend_type="openai",
            backend="openai",
            api_key="file-key",
            base_url="https://api.example.com/v1",
            model_name="text-embedding-3-small",
        )
        adapter = create_embedding_adapter(remote)

        ok, _reason = adapter._check_remote_available()

        assert ok is True
        assert adapter._remote_config is not None
        assert adapter._remote_config.api_key == "file-key"
        assert adapter._remote_config.base_url == "https://api.example.com/v1"

    def test_get_reme_embedding_remote_from_file(self, monkeypatch):
        """Builder returns openai dict + vector when file remote is set."""
        for key in (
            "EMBEDDING_API_KEY",
            "EMBEDDING_BASE_URL",
            "EMBEDDING_MODEL_NAME",
        ):
            monkeypatch.delenv(key, raising=False)

        remote = EmbeddingConfig(
            enabled=True,
            backend_type="openai",
            backend="openai",
            api_key="k",
            base_url="https://api.openai.com/v1",
            model_name="text-embedding-3-small",
        )
        emb, vec = get_reme_embedding_and_vector_enabled(remote)

        assert vec is True
        assert emb["backend"] == "openai"
        assert emb["api_key"] == "k"
        assert emb["model_name"] == "text-embedding-3-small"

    def test_get_reme_embedding_ollama_contains_backend_type(self):
        """Ollama mode emits explicit backend_type for EmbeddingClient."""
        cfg = EmbeddingConfig(
            enabled=True,
            backend_type="ollama",
            base_url="http://127.0.0.1:11434",
            model_name="mxbai-embed-large",
            dimensions=1024,
        )
        adapter = create_embedding_adapter(cfg, strict_local=False)
        result = adapter.determine_mode()

        assert result.mode == "ollama"
        emb = adapter.get_reme_embedding_config()
        assert emb["backend"] == "ollama"
        assert emb["backend_type"] == "ollama"


class TestEmbeddingModeResult:
    """Test EmbeddingModeResult dataclass."""

    def test_result_creation(self):
        """Test result object creation."""
        result = EmbeddingModeResult(
            mode="local",
            vector_enabled=True,
            backend_config={"backend": "local"},
            fallback_applied=False,
            fallback_reason=None,
        )

        assert result.mode == "local"
        assert result.vector_enabled is True
        assert result.fallback_applied is False


class TestRemoteEmbeddingConfig:
    """Test RemoteEmbeddingConfig dataclass."""

    def test_config_creation(self):
        """Test remote config creation."""
        config = RemoteEmbeddingConfig(
            api_key="test_key",
            base_url="https://api.example.com",
            model_name="test-model",
            dimensions=1024,
        )

        assert config.api_key == "test_key"
        assert config.base_url == "https://api.example.com"
        assert config.model_name == "test-model"
        assert config.dimensions == 1024
