# -*- coding: utf-8 -*-
"""Embedding adapter layer for CoPaw-ReMe integration.

Handles local embedding backend registration, availability detection,
configuration generation, and fallback strategies.
"""

import importlib.util
import logging
import os
from dataclasses import dataclass
from typing import Optional, Dict, Any, Literal

from copaw.config.config import LocalEmbeddingConfig

logger = logging.getLogger(__name__)

# Environment variable names
ENV_EMBEDDING_API_KEY = "EMBEDDING_API_KEY"
ENV_EMBEDDING_BASE_URL = "EMBEDDING_BASE_URL"
ENV_EMBEDDING_MODEL_NAME = "EMBEDDING_MODEL_NAME"
ENV_EMBEDDING_DIMENSIONS = "EMBEDDING_DIMENSIONS"
ENV_STRICT_LOCAL = "COPAW_STRICT_LOCAL_EMBEDDING"

# Default values
DEFAULT_EMBEDDING_DIMENSIONS = 1024
DEFAULT_LOCAL_EMBEDDING_DIMENSIONS = 2048

# Lightweight local model dimension hints (kept import-free on purpose).
LOCAL_MODEL_DIMENSIONS: dict[str, int] = {
    "qwen/Qwen3-VL-Embedding-2B": 2048,
    "BAAI/bge-small-zh": 512,
    "BAAI/bge-large-zh-v1.5": 1024,
    "BAAI/bge-m3": 1024,
}


@dataclass
class EmbeddingModeResult:
    """Result of embedding mode detection."""

    mode: Literal["local", "remote", "disabled"]
    vector_enabled: bool
    backend_config: Dict[str, Any]
    fallback_applied: bool
    fallback_reason: Optional[str] = None


@dataclass
class RemoteEmbeddingConfig:
    """Configuration for remote embedding service."""

    api_key: str
    base_url: str
    model_name: str
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS


class EmbeddingAdapter:
    """Adapter for embedding configuration and ReMe integration.

    Responsibilities:
    1. Register local backend to ReMe before ReMeLight initialization
    2. Detect local/remote embedding availability
    3. Generate appropriate configuration for ReMeLight
    4. Handle fallback from local to remote
    """

    def __init__(
        self,
        local_config: Optional[LocalEmbeddingConfig] = None,
        strict_local: bool = False,
    ):
        self.local_config = local_config or LocalEmbeddingConfig()
        self.strict_local = strict_local or os.getenv(
            ENV_STRICT_LOCAL,
            "",
        ).lower() in (
            "true",
            "1",
            "yes",
        )
        self._local_backend_registered = False
        self._reme_available = False
        self._current_mode: Optional[
            Literal["local", "remote", "disabled"]
        ] = None
        self._remote_config: Optional[RemoteEmbeddingConfig] = None

    def _check_reme_compatibility(self) -> tuple[bool, Optional[str]]:
        """Check if ReMe is available and compatible.

        Returns:
            (is_compatible, error_reason)
        """
        try:
            # Try to import ReMe registry
            from reme.core.registry_factory import R  # type: ignore[import]

            # Check if embedding_models registry exists
            if not hasattr(R, "embedding_models"):
                return (
                    False,
                    "ReMe registry does not have embedding_models attribute",
                )

            # Check if register method exists
            if not hasattr(R.embedding_models, "register"):
                return (
                    False,
                    "ReMe embedding_models registry "
                    "does not have register method",
                )

            return True, None
        except ImportError as e:
            return False, f"ReMe not installed: {e}"
        except (RuntimeError, AttributeError, TypeError) as e:
            return False, f"ReMe compatibility check failed: {e}"

    def register_local_backend(self) -> bool:
        """Register local backend to ReMe registry.

        Returns:
            True if registration successful, False otherwise.
        """
        if self._local_backend_registered:
            logger.debug("Local backend already registered")
            return True

        # Check ReMe compatibility
        is_compatible, error_reason = self._check_reme_compatibility()
        if not is_compatible:
            logger.warning(
                "ReMe compatibility check failed",
                extra={
                    "error_reason": error_reason,
                },
            )
            return False

        # Import LocalEmbeddingModel
        try:
            from copaw.agents.memory.local_embedding_model import (
                LocalEmbeddingModel,
            )
        except ImportError as e:
            logger.warning(
                "LocalEmbeddingModel not available",
                extra={"error": str(e)},
            )
            return False

        # Register to ReMe registry
        try:
            from reme.core.registry_factory import R  # type: ignore[import]

            R.embedding_models.register("local")(LocalEmbeddingModel)
            self._local_backend_registered = True
            self._reme_available = True

            logger.info(
                "Local embedding backend registered to ReMe",
                extra={
                    "backend": "local",
                    "model_class": LocalEmbeddingModel.__name__,
                },
            )
            return True
        except (RuntimeError, AttributeError, TypeError) as e:
            logger.error(
                "Failed to register local backend to ReMe",
                extra={"error": str(e)},
            )
            return False

    def _check_dependencies(self) -> tuple[bool, Optional[str]]:
        """Check if required dependencies are available.

        Returns:
            (has_dependencies, error_reason)
        """
        if importlib.util.find_spec("torch") is None:
            return False, "torch not installed"

        if importlib.util.find_spec("transformers") is None:
            return False, "transformers not installed"

        return True, None

    def _check_model_available(self) -> tuple[bool, Optional[str]]:
        """Check if the configured model is available.

        Returns:
            (is_available, error_reason)
        """
        # If local path is specified, check if it exists
        if self.local_config.model_path:
            if not os.path.exists(self.local_config.model_path):
                return (
                    False,
                    "Local model path does not exist: "
                    f"{self.local_config.model_path}",
                )
            return True, None

        # Otherwise, assume it can be downloaded
        # (we'll verify during actual load)
        # The LocalEmbedder will handle model download/checking
        # We just do basic validation here
        if not self.local_config.model_id:
            return False, "Model ID not configured"

        logger.debug(
            "Model availability will be checked during initialization",
            extra={"model_id": self.local_config.model_id},
        )
        return True, None

    def _check_local_available(self) -> tuple[bool, Optional[str]]:
        """Check if local embedding is available.

        Returns:
            (is_available, error_reason)
        """
        # Check if enabled in config
        if not self.local_config.enabled:
            return False, "Local embedding not enabled in config"

        # Check dependencies
        has_deps, dep_error = self._check_dependencies()
        if not has_deps:
            return False, f"Missing dependencies: {dep_error}"

        # Check model availability
        model_available, model_error = self._check_model_available()
        if not model_available:
            return False, f"Model not available: {model_error}"

        return True, None

    def _check_remote_available(self) -> tuple[bool, Optional[str]]:
        """Check if remote embedding is available.

        Returns:
            (is_available, error_reason)
        """
        api_key = os.getenv(ENV_EMBEDDING_API_KEY)
        base_url = os.getenv(ENV_EMBEDDING_BASE_URL)
        model_name = os.getenv(ENV_EMBEDDING_MODEL_NAME)

        if not api_key:
            return False, f"{ENV_EMBEDDING_API_KEY} not set"

        if not base_url:
            return False, f"{ENV_EMBEDDING_BASE_URL} not set"

        if not model_name:
            return False, f"{ENV_EMBEDDING_MODEL_NAME} not set"

        # Store the config for later use
        dimensions_raw = os.getenv(
            ENV_EMBEDDING_DIMENSIONS,
            str(DEFAULT_EMBEDDING_DIMENSIONS),
        )
        try:
            dimensions = int(dimensions_raw)
        except ValueError:
            logger.warning(
                "Invalid embedding dimensions, using default",
                extra={
                    "env_key": ENV_EMBEDDING_DIMENSIONS,
                    "env_value": dimensions_raw,
                    "default_dimensions": DEFAULT_EMBEDDING_DIMENSIONS,
                },
            )
            dimensions = DEFAULT_EMBEDDING_DIMENSIONS
        self._remote_config = RemoteEmbeddingConfig(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            dimensions=dimensions,
        )

        return True, None

    def determine_mode(self) -> EmbeddingModeResult:
        """Determine embedding mode and configuration.

        This is the main entry point for mode detection and fallback logic.
        Following ADR-002: Local -> Remote (fallback) -> Disabled (fallback)

        Returns:
            EmbeddingModeResult with mode, config, and fallback info.
        """
        fallback_reason = None

        # Step 1: Try local mode (if enabled)
        local_available, local_error = self._check_local_available()
        if local_available:
            # Try to register local backend
            if self.register_local_backend():
                self._current_mode = "local"
                result = EmbeddingModeResult(
                    mode="local",
                    vector_enabled=True,
                    backend_config=self.get_reme_embedding_config(),
                    fallback_applied=False,
                    fallback_reason=None,
                )
                self._log_mode_result(result)
                return result
            else:
                local_error = "Failed to register local backend to ReMe"

        # Local failed - determine if we should fallback
        # Strict mode: only fail if local was explicitly enabled but failed
        if self.strict_local and self.local_config.enabled:
            # Strict mode: fail immediately (fail-fast per ADR-002)
            error_msg = (
                f"Local embedding failed in strict mode: "
                f"{local_error}. To enable fallback to remote, "
                "set COPAW_STRICT_LOCAL_EMBEDDING=false"
            )
            logger.error(
                "Embedding initialization failed in strict mode",
                extra={
                    "error": local_error,
                    "strict_local": self.strict_local,
                    "local_enabled": self.local_config.enabled,
                },
            )
            raise RuntimeError(error_msg)

        # Step 2: Fallback to remote mode
        fallback_reason = f"Local unavailable: {local_error}"

        remote_available, remote_error = self._check_remote_available()
        if remote_available:
            self._current_mode = "remote"
            result = EmbeddingModeResult(
                mode="remote",
                vector_enabled=True,
                backend_config=self.get_reme_embedding_config(),
                fallback_applied=True,
                fallback_reason=fallback_reason,
            )
            self._log_mode_result(result)
            return result

        # Step 3: Fallback to disabled
        fallback_reason = (
            f"{fallback_reason}; Remote unavailable: {remote_error}"
        )
        self._current_mode = "disabled"
        result = EmbeddingModeResult(
            mode="disabled",
            vector_enabled=False,
            backend_config={},
            fallback_applied=True,
            fallback_reason=fallback_reason,
        )
        self._log_mode_result(result)
        logger.warning(
            "Embedding disabled: both local and remote unavailable",
            extra={"fallback_reason": fallback_reason},
        )
        return result

    def _log_mode_result(self, result: EmbeddingModeResult) -> None:
        """Log mode result with structured fields per ADR-002.

        Args:
            result: The mode result to log.
        """
        # Get ReMe version if available
        reme_version = "unknown"
        try:
            import reme

            reme_version = getattr(reme, "__version__", "unknown")
        except Exception:
            pass

        log_data = {
            "embedding_mode": result.mode,
            "effective_embedding_backend": result.mode,
            "reme_version": reme_version,
            "local_backend_registered": self.is_local_registered,
            "vector_enabled": result.vector_enabled,
            "strict_local_embedding": self.strict_local,
            "fallback_applied": result.fallback_applied,
            "fallback_reason": result.fallback_reason,
        }

        if result.mode == "disabled":
            logger.warning("Embedding mode determined", extra=log_data)
        else:
            logger.info("Embedding mode determined", extra=log_data)

    def _get_local_dimensions(self) -> int:
        """Infer local embedding dimensions from model metadata.

        Uses preset metadata first and falls back to a local-safe default.
        """
        preset_dims = LOCAL_MODEL_DIMENSIONS.get(self.local_config.model_id)
        if preset_dims is not None:
            return preset_dims
        return DEFAULT_LOCAL_EMBEDDING_DIMENSIONS

    def get_reme_embedding_config(self) -> Dict[str, Any]:
        """Generate embedding model config for ReMeLight.

        Returns:
            Configuration dict for default_embedding_model_config parameter.
        """
        if self._current_mode is None:
            # Determine mode if not already done
            self.determine_mode()

        if self._current_mode == "local":
            # LocalEmbeddingConfig does not expose dimensions as public field.
            # Infer by model preset and keep a local-safe fallback.
            dimensions = self._get_local_dimensions()

            # Build config for ReMe
            config = {
                "backend": "local",
                "model_name": self.local_config.model_id,
                "dimensions": dimensions,
                "local_embedding_config": self.local_config,
            }

            # Add optional parameters if present in config
            if hasattr(self.local_config, "device"):
                config["device"] = self.local_config.device
            if hasattr(self.local_config, "dtype"):
                config["dtype"] = self.local_config.dtype

            return config

        elif self._current_mode == "remote" and self._remote_config:
            return {
                "backend": "openai",  # ReMe uses openai backend for remote
                "api_key": self._remote_config.api_key,
                "base_url": self._remote_config.base_url,
                "model_name": self._remote_config.model_name,
                "dimensions": self._remote_config.dimensions,
            }

        else:
            # Disabled mode - return empty config
            return {}

    def get_file_store_config(self) -> Dict[str, Any]:
        """Generate file store config with vector_enabled.

        Returns:
            Configuration dict for default_file_store_config parameter.
        """
        if self._current_mode is None:
            # Determine mode if not already done
            result = self.determine_mode()
            vector_enabled = result.vector_enabled
        else:
            vector_enabled = self._current_mode in ("local", "remote")

        return {
            "vector_enabled": vector_enabled,
        }

    @property
    def current_mode(self) -> Optional[Literal["local", "remote", "disabled"]]:
        """Get current embedding mode.

        Returns:
            Current mode or None if not determined yet.
        """
        return self._current_mode

    @property
    def is_local_registered(self) -> bool:
        """Check if local backend is registered.

        Returns:
            True if local backend is registered.
        """
        return self._local_backend_registered


def create_embedding_adapter(
    local_config: Optional[LocalEmbeddingConfig] = None,
    strict_local: bool = False,
) -> EmbeddingAdapter:
    """Factory function to create and initialize EmbeddingAdapter.

    This is the main entry point for MemoryManager to use.

    Args:
        local_config: Optional local embedding configuration.
        strict_local: If True, fail when local is unavailable
            instead of fallback.

    Returns:
        Initialized EmbeddingAdapter instance.

    Example:
        >>> adapter = create_embedding_adapter(
        ...     local_config=LocalEmbeddingConfig(enabled=True),
        ...     strict_local=False,
        ... )
        >>> result = adapter.determine_mode()
        >>> print(f"Mode: {result.mode}, "
        ...       f"Vector enabled: {result.vector_enabled}")
    """
    adapter = EmbeddingAdapter(local_config, strict_local)
    # Note: We don't auto-register here to allow lazy registration
    # The determine_mode() call will trigger registration if needed
    return adapter
