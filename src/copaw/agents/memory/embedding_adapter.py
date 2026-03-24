# -*- coding: utf-8 -*-
"""Embedding adapter layer for CoPaw-ReMe integration.

Handles embedding backend registration, configuration generation, and
``vector_enabled`` for file store (ADR-003).

ReMe-facing dict contract (``reme-ai``): values merged into
``service_config.embedding_models["default"]``; ``backend`` must match a name
registered on ``R.embedding_models`` — built-in remote uses ``"openai"``;
CoPaw registers ``"local"`` (transformers via :class:`EmbeddingClient`) and
``"ollama"`` (:class:`OllamaEmbeddingModel`).
Use :func:`get_reme_embedding_and_vector_enabled` as the **single builder** for
``default_embedding_model_config`` and restart (TASK T-R01).
"""

import importlib.util
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

from copaw.config.config import EmbeddingConfig, LocalEmbeddingConfig

logger = logging.getLogger(__name__)

ENV_EMBEDDING_API_KEY = "EMBEDDING_API_KEY"
ENV_EMBEDDING_BASE_URL = "EMBEDDING_BASE_URL"
ENV_EMBEDDING_MODEL_NAME = "EMBEDDING_MODEL_NAME"
ENV_STRICT_LOCAL = "COPAW_STRICT_LOCAL_EMBEDDING"

DEFAULT_EMBEDDING_DIMENSIONS = 1024
DEFAULT_LOCAL_EMBEDDING_DIMENSIONS = 2048

LOCAL_MODEL_DIMENSIONS: dict[str, int] = {
    "qwen/Qwen3-VL-Embedding-2B": 2048,
    "BAAI/bge-small-zh": 512,
    "BAAI/bge-large-zh-v1.5": 1024,
    "BAAI/bge-m3": 1024,
}

# ReMe registry is process-global; register each backend name at most once.
_GLOBAL_COPAW_EMBEDDING_BACKENDS_REGISTERED: bool = False


def _legacy_merge_embedding_config(
    file_config: Optional[EmbeddingConfig],
    local_config: Optional[LocalEmbeddingConfig],
    remote_file_config: Optional[EmbeddingConfig],
) -> EmbeddingConfig:
    """Merge legacy local_config / remote_file_config into one model."""
    if file_config is not None and remote_file_config is not None:
        base = file_config.model_copy(
            update=remote_file_config.model_dump(exclude_unset=True),
        )
    elif remote_file_config is not None:
        base = remote_file_config.model_copy(deep=True)
    elif file_config is not None:
        base = file_config.model_copy(deep=True)
    else:
        base = EmbeddingConfig()

    if local_config is None:
        return base

    updates: Dict[str, Any] = {
        "model_id": local_config.model_id,
        "model_path": local_config.model_path,
        "device": local_config.device,
        "dtype": local_config.dtype,
        "download_source": local_config.download_source,
    }
    if local_config.enabled:
        updates["backend_type"] = "transformers"
        updates["enabled"] = True
    else:
        updates["backend_type"] = "openai"
        updates["enabled"] = True
    return base.model_copy(update=updates)


@dataclass
class EmbeddingModeResult:
    """Result of embedding mode detection."""

    mode: Literal["local", "remote", "ollama", "disabled"]
    vector_enabled: bool
    backend_config: Dict[str, Any]
    fallback_applied: bool
    fallback_reason: Optional[str] = None


@dataclass
class RemoteEmbeddingConfig:
    """Resolved remote embedding service fields."""

    api_key: str
    base_url: str
    model_name: str
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS


class EmbeddingAdapter:
    """Adapter for canonical :class:`EmbeddingConfig` and ReMe integration."""

    def __init__(
        self,
        file_config: Optional[EmbeddingConfig] = None,
        strict_local: bool = False,
        *,
        local_config: Optional[LocalEmbeddingConfig] = None,
        remote_file_config: Optional[EmbeddingConfig] = None,
    ) -> None:
        if local_config is not None or remote_file_config is not None:
            self._file_config = _legacy_merge_embedding_config(
                file_config,
                local_config,
                remote_file_config,
            )
        else:
            self._file_config = file_config or EmbeddingConfig()
        self.strict_local = strict_local or os.getenv(
            ENV_STRICT_LOCAL,
            "",
        ).lower() in (
            "true",
            "1",
            "yes",
        )
        self._copaw_backends_registered = False
        self._current_mode: Optional[
            Literal["local", "remote", "ollama", "disabled"]
        ] = None
        self._remote_config: Optional[RemoteEmbeddingConfig] = None

    @property
    def _local(self) -> LocalEmbeddingConfig:
        return self._file_config.to_local_embedding_config()

    def _check_reme_compatibility(self) -> tuple[bool, Optional[str]]:
        try:
            from reme.core.registry_factory import R  # type: ignore[import]

            if not hasattr(R, "embedding_models"):
                return (
                    False,
                    "ReMe registry does not have embedding_models attribute",
                )
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

    def register_copaw_embedding_backends(self) -> bool:
        """Register CoPaw ``local`` (transformers) and ``ollama`` backends."""
        global _GLOBAL_COPAW_EMBEDDING_BACKENDS_REGISTERED
        if (
            self._copaw_backends_registered
            or _GLOBAL_COPAW_EMBEDDING_BACKENDS_REGISTERED
        ):
            self._copaw_backends_registered = True
            return True

        is_compatible, error_reason = self._check_reme_compatibility()
        if not is_compatible:
            logger.warning(
                "ReMe compatibility check failed",
                extra={"error_reason": error_reason},
            )
            return False

        try:
            from copaw.agents.memory.embedding_client import EmbeddingClient
            from copaw.agents.memory.ollama_embedding_model import (
                OllamaEmbeddingModel,
            )
            from reme.core.registry_factory import R  # type: ignore[import]
        except ImportError as e:
            logger.warning(
                "Embedding client/backends not available",
                extra={"error": str(e)},
            )
            return False

        try:
            R.embedding_models.register("local")(EmbeddingClient)
            R.embedding_models.register("ollama")(OllamaEmbeddingModel)
            self._copaw_backends_registered = True
            _GLOBAL_COPAW_EMBEDDING_BACKENDS_REGISTERED = True
            logger.info(
                "CoPaw embedding backends registered to ReMe",
                extra={"backends": ("local", "ollama")},
            )
            return True
        except (RuntimeError, AttributeError, TypeError) as e:
            logger.error(
                "Failed to register CoPaw embedding backends",
                extra={"error": str(e)},
            )
            return False

    def register_local_backend(self) -> bool:
        """Alias for :meth:`register_copaw_embedding_backends`."""
        return self.register_copaw_embedding_backends()

    def _check_dependencies(self) -> tuple[bool, Optional[str]]:
        if importlib.util.find_spec("torch") is None:
            return False, "torch not installed"
        if importlib.util.find_spec("transformers") is None:
            return False, "transformers not installed"
        return True, None

    def _check_model_available(self) -> tuple[bool, Optional[str]]:
        lc = self._local
        if lc.model_path:
            if not os.path.exists(lc.model_path):
                return (
                    False,
                    "Local model path does not exist: " f"{lc.model_path}",
                )
            return True, None
        if not lc.model_id:
            return False, "Model ID not configured"
        logger.debug(
            "Model availability will be checked during initialization",
            extra={"model_id": lc.model_id},
        )
        return True, None

    def _check_local_available(self) -> tuple[bool, Optional[str]]:
        lc = self._local
        if not lc.enabled:
            return False, "Local transformers embedding not enabled in config"
        has_deps, dep_error = self._check_dependencies()
        if not has_deps:
            return False, f"Missing dependencies: {dep_error}"
        model_available, model_error = self._check_model_available()
        if not model_available:
            return False, f"Model not available: {model_error}"
        return True, None

    def _merge_remote_credentials(self) -> tuple[str, str, str, int]:
        file_cfg = self._file_config
        api_key = (file_cfg.api_key or "") or os.getenv(
            ENV_EMBEDDING_API_KEY,
            "",
        )
        base_url = (file_cfg.base_url or "") or os.getenv(
            ENV_EMBEDDING_BASE_URL,
            "",
        )
        model_name = (file_cfg.model_name or "") or os.getenv(
            ENV_EMBEDDING_MODEL_NAME,
            "",
        )
        dimensions = file_cfg.dimensions
        return api_key, base_url, model_name, dimensions

    def _check_remote_available(self) -> tuple[bool, Optional[str]]:
        (
            api_key,
            base_url,
            model_name,
            dimensions,
        ) = self._merge_remote_credentials()
        if not api_key:
            return (
                False,
                f"{ENV_EMBEDDING_API_KEY} not set and empty in config",
            )
        if not base_url:
            return (
                False,
                f"{ENV_EMBEDDING_BASE_URL} not set and empty in config",
            )
        if not model_name:
            return (
                False,
                f"{ENV_EMBEDDING_MODEL_NAME} not set and empty in config",
            )
        self._remote_config = RemoteEmbeddingConfig(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            dimensions=dimensions,
        )
        return True, None

    def _check_ollama_available(self) -> tuple[bool, Optional[str]]:
        base = (self._file_config.base_url or "").strip()
        model = (self._file_config.model_name or "").strip()
        if not base:
            return False, "Ollama base_url is empty"
        if not model:
            return False, "Ollama model_name is empty"
        return True, None

    def _result_success(
        self,
        mode: Literal["local", "remote", "ollama"],
    ) -> EmbeddingModeResult:
        """Set mode and build a successful :class:`EmbeddingModeResult`."""
        self._current_mode = mode
        result = EmbeddingModeResult(
            mode=mode,
            vector_enabled=True,
            backend_config=self.get_reme_embedding_config(),
            fallback_applied=False,
            fallback_reason=None,
        )
        self._log_mode_result(result)
        return result

    def _result_disabled(
        self,
        *,
        fallback_applied: bool,
        fallback_reason: str,
    ) -> EmbeddingModeResult:
        """Set mode to disabled and log."""
        self._current_mode = "disabled"
        result = EmbeddingModeResult(
            mode="disabled",
            vector_enabled=False,
            backend_config={},
            fallback_applied=fallback_applied,
            fallback_reason=fallback_reason,
        )
        self._log_mode_result(result)
        return result

    # pylint: disable-next=too-many-return-statements
    def determine_mode(self) -> EmbeddingModeResult:
        """Resolve embedding mode from explicit ``backend_type``."""
        fc = self._file_config
        if not fc.enabled:
            return self._result_disabled(
                fallback_applied=False,
                fallback_reason="Embedding disabled in config",
            )

        if fc.backend_type == "transformers":
            local_ok, local_err = self._check_local_available()
            if local_ok:
                if self.register_copaw_embedding_backends():
                    return self._result_success("local")
                local_err = "Failed to register CoPaw embedding backends"
            if self.strict_local:
                msg = (
                    f"Local embedding failed in strict mode: {local_err}. "
                    f"Set {ENV_STRICT_LOCAL}=false to allow "
                    "returning disabled instead of raising."
                )
                logger.error(
                    "Embedding initialization failed in strict mode",
                    extra={
                        "error": local_err,
                        "strict_local": self.strict_local,
                    },
                )
                raise RuntimeError(msg)
            return self._result_disabled(
                fallback_applied=True,
                fallback_reason=f"Local unavailable: {local_err}",
            )

        if fc.backend_type == "openai":
            remote_ok, remote_err = self._check_remote_available()
            if remote_ok:
                return self._result_success("remote")
            return self._result_disabled(
                fallback_applied=True,
                fallback_reason=f"Remote unavailable: {remote_err}",
            )

        if fc.backend_type == "ollama":
            ollama_ok, ollama_err = self._check_ollama_available()
            if ollama_ok:
                if self.register_copaw_embedding_backends():
                    return self._result_success("ollama")
                ollama_err = "Failed to register CoPaw embedding backends"
            return self._result_disabled(
                fallback_applied=True,
                fallback_reason=f"Ollama unavailable: {ollama_err}",
            )

        return self._result_disabled(
            fallback_applied=True,
            fallback_reason="Unknown backend_type",
        )

    def _log_mode_result(self, result: EmbeddingModeResult) -> None:
        reme_version = "unknown"
        try:
            import reme

            reme_version = getattr(reme, "__version__", "unknown")
        except ImportError:
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
        preset_dims = LOCAL_MODEL_DIMENSIONS.get(self._file_config.model_id)
        if preset_dims is not None:
            return preset_dims
        return DEFAULT_LOCAL_EMBEDDING_DIMENSIONS

    def get_reme_embedding_config(self) -> Dict[str, Any]:
        if self._current_mode is None:
            self.determine_mode()

        if self._current_mode == "local":
            lc = self._local
            dimensions = self._get_local_dimensions()
            config: Dict[str, Any] = {
                "backend": "local",
                "model_name": lc.model_id,
                "dimensions": dimensions,
                "local_embedding_config": lc,
            }
            config["device"] = lc.device
            config["dtype"] = lc.dtype
            return config

        if self._current_mode == "remote" and self._remote_config:
            out: Dict[str, Any] = {
                "backend": "openai",
                "api_key": self._remote_config.api_key,
                "base_url": self._remote_config.base_url,
                "model_name": self._remote_config.model_name,
                "dimensions": self._remote_config.dimensions,
            }
            fc = self._file_config
            out.update(
                {
                    "enable_cache": fc.enable_cache,
                    "use_dimensions": fc.use_dimensions,
                    "max_cache_size": fc.max_cache_size,
                    "max_input_length": fc.max_input_length,
                    "max_batch_size": fc.max_batch_size,
                },
            )
            return out

        if self._current_mode == "ollama":
            fc = self._file_config
            return {
                "backend": "ollama",
                "api_key": "",
                "base_url": fc.base_url.rstrip("/"),
                "model_name": fc.model_name,
                "dimensions": fc.dimensions,
                "enable_cache": fc.enable_cache,
                "max_input_length": fc.max_input_length,
                "max_batch_size": fc.max_batch_size,
            }

        return {}

    def get_file_store_config(self) -> Dict[str, Any]:
        if self._current_mode is None:
            result = self.determine_mode()
            vector_enabled = result.vector_enabled
        else:
            vector_enabled = self._current_mode in (
                "local",
                "remote",
                "ollama",
            )
        return {"vector_enabled": vector_enabled}

    @property
    def current_mode(
        self,
    ) -> Optional[Literal["local", "remote", "ollama", "disabled"]]:
        return self._current_mode

    @property
    def is_local_registered(self) -> bool:
        return self._copaw_backends_registered


def create_embedding_adapter(
    file_config: Optional[EmbeddingConfig] = None,
    strict_local: bool = False,
    *,
    local_config: Optional[LocalEmbeddingConfig] = None,
    remote_file_config: Optional[EmbeddingConfig] = None,
) -> EmbeddingAdapter:
    """Create an :class:`EmbeddingAdapter` for a canonical embedding config.

    Legacy keyword-only arguments ``local_config`` and ``remote_file_config``
    are merged into a single :class:`EmbeddingConfig` for compatibility with
    older call sites.
    """
    return EmbeddingAdapter(
        file_config,
        strict_local,
        local_config=local_config,
        remote_file_config=remote_file_config,
    )


def get_reme_embedding_and_vector_enabled(
    embedding_config: Optional[EmbeddingConfig] = None,
    strict_local: bool = False,
) -> tuple[Dict[str, Any], bool]:
    """Build ReMe embedding dict and ``vector_enabled`` (T-R01)."""
    adapter = create_embedding_adapter(embedding_config, strict_local)
    result = adapter.determine_mode()
    return adapter.get_reme_embedding_config(), result.vector_enabled


build_reme_embedding_dict_for_running = get_reme_embedding_and_vector_enabled
