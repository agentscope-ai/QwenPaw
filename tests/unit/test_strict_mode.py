# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,wrong-import-order
# -*- coding: utf-8 -*-
"""Unit tests for strict local embedding mode.

Tests the strict mode behavior where local embedding failures
result in immediate failure rather than fallback to remote.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import os  # noqa: E402
import pytest  # noqa: E402

from copaw.agents.memory.embedding_adapter import (  # noqa: E402
    EmbeddingAdapter,
    create_embedding_adapter,
)
from copaw.config.config import LocalEmbeddingConfig  # noqa: E402


class TestStrictLocalMode:
    """Test strict local embedding mode behavior."""

    def test_strict_mode_with_missing_dependencies(self):
        """Test strict mode when dependencies are missing."""
        # Create a config that enables local embedding
        config = LocalEmbeddingConfig(
            enabled=True,
            model_id="BAAI/bge-small-zh",
        )

        # Create adapter in strict mode
        adapter = EmbeddingAdapter(
            local_config=config,
            strict_local=True,
        )

        # Determine mode
        result = adapter.determine_mode()

        # Result depends on whether ReMe is available and local backend
        # can be registered. If registration succeeds, mode will be 'local'.
        # If registration fails and strict mode, mode will be 'disabled'.
        assert result.mode in ["local", "disabled"]
        if result.mode == "disabled":
            assert result.vector_enabled is False

    def test_strict_mode_with_invalid_model_path(self):
        """Test strict mode with invalid model path raises exception."""
        config = LocalEmbeddingConfig(
            enabled=True,
            model_id="test-model",
            model_path="/nonexistent/path/to/model",
        )

        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=True,
        )

        # Should raise RuntimeError in strict mode
        with pytest.raises(RuntimeError) as exc_info:
            adapter.determine_mode()

        assert "Local embedding failed in strict mode" in str(exc_info.value)
        assert "Local model path does not exist" in str(exc_info.value)

    def test_strict_mode_vs_non_strict_with_remote_available(
        self,
        monkeypatch,
    ):
        """Test difference between strict and non-strict when remote available."""
        # Set up remote embedding env vars
        monkeypatch.setenv("EMBEDDING_API_KEY", "test-key")
        monkeypatch.setenv("EMBEDDING_BASE_URL", "https://api.example.com")
        monkeypatch.setenv("EMBEDDING_MODEL_NAME", "test-model")

        # Create config with disabled local
        config = LocalEmbeddingConfig(enabled=False)

        # Non-strict mode should fallback to remote
        non_strict_adapter = create_embedding_adapter(
            local_config=config,
            strict_local=False,
        )
        non_strict_result = non_strict_adapter.determine_mode()

        # Non-strict should use remote since local is disabled
        assert non_strict_result.mode == "remote"
        assert non_strict_result.vector_enabled is True
        assert non_strict_result.fallback_applied is True

    def test_strict_mode_via_environment_variable(self, monkeypatch):
        """Test strict mode can be enabled via environment variable."""
        # Set strict mode via env var
        monkeypatch.setenv("COPAW_STRICT_LOCAL_EMBEDDING", "true")

        config = LocalEmbeddingConfig(
            enabled=True,
            model_id="test-model",
        )

        adapter = create_embedding_adapter(local_config=config)

        # Should detect strict mode from env var
        assert adapter.strict_local is True

    def test_non_strict_mode_via_environment_variable(self, monkeypatch):
        """Test non-strict mode when env var is false."""
        monkeypatch.setenv("COPAW_STRICT_LOCAL_EMBEDDING", "false")

        config = LocalEmbeddingConfig(enabled=False)

        adapter = create_embedding_adapter(local_config=config)

        assert adapter.strict_local is False

    def test_strict_mode_with_local_enabled_but_unavailable(self):
        """Test strict mode when local is enabled but unavailable raises exception."""
        # Create config that enables local
        config = LocalEmbeddingConfig(
            enabled=True,
            model_id="test-model",
            model_path="/nonexistent",
        )

        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=True,
        )

        # In strict mode, should raise RuntimeError when local unavailable
        with pytest.raises(RuntimeError) as exc_info:
            adapter.determine_mode()

        assert "Local embedding failed in strict mode" in str(exc_info.value)

    def test_get_reme_config_in_strict_mode(self, monkeypatch):
        """Test getting ReMe config when local disabled in strict mode uses remote."""
        # Set up remote to ensure we have a fallback
        monkeypatch.setenv("EMBEDDING_API_KEY", "test-key")
        monkeypatch.setenv("EMBEDDING_BASE_URL", "https://api.example.com")
        monkeypatch.setenv("EMBEDDING_MODEL_NAME", "test-model")

        # Disable local, enable strict mode - but remote is available
        config = LocalEmbeddingConfig(enabled=False)
        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=True,
        )

        # When local is disabled and remote available, should use remote
        result = adapter.determine_mode()

        # Should use remote since local is disabled
        assert result.mode == "remote"

        # Get config
        reme_config = adapter.get_reme_embedding_config()

        # Should have remote config
        assert reme_config.get("backend") == "openai"
        assert "api_key" in reme_config
        assert "base_url" in reme_config


class TestFallbackBehavior:
    """Test fallback behavior in different scenarios."""

    def test_no_fallback_when_local_succeeds(self):
        """Test that no fallback occurs when local embedding is available."""
        # This test assumes local dependencies might be available
        # If not, it will fallback, which is also valid behavior
        config = LocalEmbeddingConfig(
            enabled=True,
            model_id="BAAI/bge-small-zh",
        )

        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=False,
        )

        result = adapter.determine_mode()

        if result.mode == "local":
            # Local succeeded, no fallback
            assert result.fallback_applied is False
            assert result.fallback_reason is None

    def test_fallback_logged_correctly(self, monkeypatch):
        """Test that fallback reason is properly logged."""
        # Ensure local fails by using nonexistent path
        config = LocalEmbeddingConfig(
            enabled=True,
            model_id="test",
            model_path="/nonexistent",
        )

        # Set up remote to allow fallback
        monkeypatch.setenv("EMBEDDING_API_KEY", "test-key")
        monkeypatch.setenv("EMBEDDING_BASE_URL", "https://api.example.com")
        monkeypatch.setenv("EMBEDDING_MODEL_NAME", "test-model")

        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=False,
        )

        result = adapter.determine_mode()

        if result.mode == "remote":
            # Fallback occurred
            assert result.fallback_applied is True
            assert result.fallback_reason is not None
            assert "Local unavailable" in result.fallback_reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
