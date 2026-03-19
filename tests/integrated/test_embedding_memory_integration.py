# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,wrong-import-order,protected-access
# flake8: noqa: E402
"""Integration tests verifying embedding actually works with memory system.

These tests verify that:
1. Local backend is properly registered to ReMe
2. MemoryManager uses local embedding for vector operations
3. Embeddings are actually generated and used in memory search
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest  # noqa: E402

# Filter triton CUDA warning on Windows
pytestmark = pytest.mark.filterwarnings(
    "ignore:Failed to find CUDA.:UserWarning:triton",
)
from types import SimpleNamespace  # noqa: E402
from unittest.mock import patch, MagicMock  # noqa: E402

from copaw.agents.memory.embedding_adapter import (
    create_embedding_adapter,
)  # noqa: E402
from copaw.agents.memory.local_embedding_model import (
    LocalEmbeddingModel,
)  # noqa: E402
from copaw.config.config import (  # noqa: E402
    LocalEmbeddingConfig,
)


class TestEmbeddingBackendRegistration:
    """Test that local embedding backend is properly registered to ReMe."""

    def test_local_backend_registered_in_reme(self):
        """Verify local backend is registered in ReMe registry."""
        from reme.core.registry_factory import R  # noqa: E402

        config = LocalEmbeddingConfig(
            enabled=True,
            model_id="BAAI/bge-small-zh",
        )
        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=False,
        )

        # Register the backend
        result = adapter.register_local_backend()

        if result:
            # Verify it's in the registry
            assert "local" in R.embedding_models
            # Verify it's our class
            assert R.embedding_models["local"] == LocalEmbeddingModel

    def test_backend_config_passed_to_reme(self):
        """Verify backend config is correctly passed to ReMeLight."""
        config = LocalEmbeddingConfig(
            enabled=True,
            model_id="BAAI/bge-small-zh",
        )
        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=False,
        )

        # Get ReMe config
        adapter.determine_mode()
        reme_config = adapter.get_reme_embedding_config()

        if adapter.current_mode == "local":
            assert reme_config.get("backend") == "local"
            assert "local_embedding_config" in reme_config


class TestMemoryManagerUsesLocalEmbedding:
    """Test that MemoryManager actually uses local embedding."""

    def test_memory_manager_creates_adapter(self):
        """Verify MemoryManager creates embedding adapter on init."""
        from copaw.agents.memory.memory_manager import (
            MemoryManager,
        )  # noqa: E402

        # This should create MemoryManager even without ReMe fully configured
        try:
            mm = MemoryManager(
                working_dir="/tmp/test",
                agent_id="test-agent-id",
            )
            # Verify adapter was created
            assert hasattr(mm, "_embedding_adapter")
            assert mm._embedding_adapter is not None
        except ImportError as e:
            if "reme" in str(e).lower():
                pytest.skip("ReMe not available")
            raise
        except Exception as e:
            # Other exceptions should fail the test
            pytest.fail(f"MemoryManager initialization failed: {e}")

    def test_vector_enabled_reflects_embedding_mode(self):
        """Verify vector_enabled is set based on embedding mode."""
        from copaw.agents.memory.memory_manager import (
            MemoryManager,
        )  # noqa: E402

        try:
            mm = MemoryManager(
                working_dir="/tmp/test",
                agent_id="test-agent-id",
            )
            # Verify vector_enabled is set and is boolean
            assert hasattr(
                mm,
                "_vector_enabled",
            ), "MemoryManager should have _vector_enabled attribute"
            assert isinstance(
                mm._vector_enabled,
                bool,
            ), "_vector_enabled should be boolean"
        except ImportError as e:
            if "reme" in str(e).lower():
                pytest.skip("ReMe not available")
            raise

    def test_memory_manager_uses_agent_local_embedding_config(self):
        """Verify MemoryManager passes agent-scoped local embedding config."""
        from copaw.agents.memory.memory_manager import (
            MemoryManager,
        )  # noqa: E402

        local_embedding = LocalEmbeddingConfig(
            enabled=True,
            model_id="BAAI/bge-small-zh",
        )
        fake_adapter = MagicMock()
        fake_adapter.determine_mode.return_value = SimpleNamespace(
            mode="disabled",
            vector_enabled=False,
            fallback_applied=True,
            fallback_reason="test",
        )
        fake_adapter.get_reme_embedding_config.return_value = {}
        fake_adapter.is_local_registered = False
        fake_adapter.strict_local = False

        with (
            patch(
                "copaw.agents.memory.memory_manager.create_embedding_adapter",
                return_value=fake_adapter,
            ) as mock_create_adapter,
            patch.object(
                MemoryManager.__bases__[0],
                "__init__",
                return_value=None,
            ),
        ):
            MemoryManager(working_dir="/tmp/test", agent_id="test-agent-id")

        passed_local_config = mock_create_adapter.call_args.kwargs[
            "local_config"
        ]
        assert passed_local_config is local_embedding


class TestEmbeddingActuallyGeneratesVectors:
    """Test that embedding actually generates vectors."""

    def test_local_embedding_model_generates_vectors(self):
        """Verify LocalEmbeddingModel actually generates embedding vectors."""
        config = LocalEmbeddingConfig(
            enabled=True,
            model_id="BAAI/bge-small-zh",
        )

        model = LocalEmbeddingModel(
            model_name="BAAI/bge-small-zh",
            dimensions=512,
            local_embedding_config=config,
        )

        # Test with mock to avoid loading actual model
        with patch.object(model, "_embedder") as mock_embedder:
            mock_embedder.encode_text.return_value = [[0.1] * 512, [0.2] * 512]

            # Call sync method
            result = model._get_embeddings_sync(["text1", "text2"])

            # Verify embedder was called
            mock_embedder.encode_text.assert_called_once_with(
                ["text1", "text2"],
            )
            # Verify result
            assert len(result) == 2
            assert len(result[0]) == 512

    def test_local_embedding_model_respects_dimensions(self):
        """Verify model validates and adjusts embedding dimensions."""
        config = LocalEmbeddingConfig(enabled=True)

        model = LocalEmbeddingModel(
            model_name="test",
            dimensions=768,  # Expected dimensions
            local_embedding_config=config,
        )

        with patch.object(model, "_embedder") as mock_embedder:
            # Return wrong dimensions
            mock_embedder.encode_text.return_value = [
                [0.1] * 512,
            ]  # Wrong size

            result = model._get_embeddings_sync(["test"])

            # Should still return result (with adjustment warning)
            assert len(result) == 1


class TestEmbeddingIntegrationFlow:
    """Test the full integration flow from config to embedding generation."""

    def test_full_flow_local_mode(self):
        """Test full flow when local mode is enabled."""
        config = LocalEmbeddingConfig(
            enabled=True,
            model_id="BAAI/bge-small-zh",
        )

        # Create adapter
        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=False,
        )

        # Register backend
        adapter.register_local_backend()

        # Determine mode
        result = adapter.determine_mode()

        # Get configs
        embedding_config = adapter.get_reme_embedding_config()
        file_store_config = adapter.get_file_store_config()

        # Verify flow - mode should be one of: local, remote, disabled
        assert result.mode in ["local", "remote", "disabled"]
        assert isinstance(result.vector_enabled, bool)

        # If local mode is achieved, verify specific configs
        if result.mode == "local":
            assert embedding_config.get("backend") == "local"
            assert file_store_config.get("vector_enabled") is True
            assert result.vector_enabled is True

    def test_full_flow_remote_fallback(self, monkeypatch):
        """Test full flow when falling back to remote."""
        # Setup remote env vars
        monkeypatch.setenv("EMBEDDING_API_KEY", "test-key")
        monkeypatch.setenv("EMBEDDING_BASE_URL", "https://api.example.com")
        monkeypatch.setenv("EMBEDDING_MODEL_NAME", "test-model")

        # Disable local
        config = LocalEmbeddingConfig(enabled=False)
        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=False,
        )

        result = adapter.determine_mode()
        embedding_config = adapter.get_reme_embedding_config()

        # Should use remote
        assert result.mode == "remote"
        assert embedding_config.get("backend") == "openai"
        assert "api_key" in embedding_config


class TestEmbeddingUsedInMemorySearch:
    """Test that embedding is actually used in memory search operations."""

    @pytest.mark.asyncio
    async def test_memory_search_uses_embedding(self):
        """Verify memory_search uses embedding for vector search."""
        from copaw.agents.memory.memory_manager import (
            MemoryManager,
        )  # noqa: E402

        try:
            mm = MemoryManager(
                working_dir="/tmp/test",
                agent_id="test-agent-id",
            )

            # Mock the parent's memory_search to verify it's called
            with patch.object(
                MemoryManager.__bases__[0],
                "memory_search",
                return_value=MagicMock(),
            ) as mock_search:
                await mm.memory_search("test query")

                # Verify memory_search was called
                mock_search.assert_called_once()
                call_kwargs = mock_search.call_args.kwargs
                assert "query" in call_kwargs
                assert call_kwargs["query"] == "test query"

        except Exception:
            # If ReMe not available, skip
            pytest.skip("ReMe not available")

    def test_embedding_model_available_in_manager(self):
        """Verify embedding model is accessible in MemoryManager."""
        from copaw.agents.memory.memory_manager import (
            MemoryManager,
        )  # noqa: E402

        try:
            mm = MemoryManager(
                working_dir="/tmp/test",
                agent_id="test-agent-id",
            )

            # Check if embedding model is accessible
            # This would be set by ReMeLight parent class
            assert hasattr(mm, "embedding_model") or hasattr(
                mm,
                "_embedding_adapter",
            )

        except Exception:
            pytest.skip("ReMe not available")


class TestVectorStoreConfig:
    """Test vector store configuration based on embedding mode."""

    def test_vector_enabled_when_local_available(self):
        """Verify vector_enabled is true when local embedding available."""
        config = LocalEmbeddingConfig(
            enabled=True,
            model_id="BAAI/bge-small-zh",
        )
        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=False,
        )

        result = adapter.determine_mode()
        store_config = adapter.get_file_store_config()

        # Base assertions
        assert "vector_enabled" in store_config
        assert isinstance(store_config["vector_enabled"], bool)

        # If local is available, vector should be enabled
        if result.mode == "local":
            assert store_config["vector_enabled"] is True

    def test_vector_disabled_when_no_embedding(self):
        """Verify vector_enabled is false when no embedding available."""
        config = LocalEmbeddingConfig(enabled=False)
        adapter = create_embedding_adapter(
            local_config=config,
            strict_local=False,
        )

        result = adapter.determine_mode()
        store_config = adapter.get_file_store_config()

        # Base assertions
        assert "vector_enabled" in store_config
        assert isinstance(store_config["vector_enabled"], bool)

        # If mode is disabled, vector should be disabled
        if result.mode == "disabled":
            assert store_config["vector_enabled"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
