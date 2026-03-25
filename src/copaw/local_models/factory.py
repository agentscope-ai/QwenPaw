# -*- coding: utf-8 -*-
"""Singleton factory for local model instances."""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from .schema import BackendType, LocalModelInfo
from .manager import get_local_model
from .backends.base import LocalBackend
from .chat_model import LocalChatModel

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_active_backend: Optional[LocalBackend] = None
_active_model_id: Optional[str] = None


def get_active_local_model() -> (
    Optional[tuple[Optional[str], LocalBackend]] | None
):
    """Return (model_id, backend) if a local model is currently loaded."""
    with _lock:
        if _active_backend is not None and _active_backend.is_loaded:
            return _active_model_id, _active_backend
        return None


def unload_active_model() -> None:
    """Unload the currently loaded local model, freeing resources."""
    global _active_backend, _active_model_id
    with _lock:
        if _active_backend is not None:
            _active_backend.unload()
            _active_backend = None
            _active_model_id = None


def create_local_chat_model(
    model_id: str,
    stream: bool = True,
    backend_kwargs: Optional[dict[str, Any]] = None,
    generate_kwargs: Optional[dict[str, Any]] = None,
) -> LocalChatModel:
    """Create a LocalChatModel for the given model_id.

    Uses singleton pattern: if the same model is already loaded, reuses it.
    If a different model is loaded, unloads it first.

    Args:
        model_id: ID of a downloaded local model (from manifest).
        stream: Whether to use streaming output.
        backend_kwargs: Extra kwargs passed to the backend constructor
                       (e.g., n_ctx, n_gpu_layers for llama.cpp).
        generate_kwargs: Extra kwargs passed to every generate call
                        (e.g., temperature, top_p).

    Returns:
        A LocalChatModel instance ready for use.

    Raises:
        ValueError: If model_id is not found in the manifest.
        ImportError: If the required backend library is not installed.
    """
    global _active_backend, _active_model_id

    info = get_local_model(model_id)
    if info is None:
        raise ValueError(
            f"Local model '{model_id}' not found. "
            "Download it first with 'copaw models download'.",
        )

    with _lock:
        # Reuse if same model already loaded
        if (
            _active_model_id == model_id
            and _active_backend is not None
            and _active_backend.is_loaded
        ):
            logger.debug("Reusing already-loaded model: %s", model_id)
            return LocalChatModel(
                model_name=model_id,
                backend=_active_backend,
                stream=stream,
                generate_kwargs=generate_kwargs,
            )

        # Unload previous model
        if _active_backend is not None:
            logger.info("Unloading previous model: %s", _active_model_id)
            _active_backend.unload()

        # Load new model
        backend = _create_backend(info, backend_kwargs or {})
        _active_backend = backend
        _active_model_id = model_id

        return LocalChatModel(
            model_name=model_id,
            backend=_active_backend,
            stream=stream,
            generate_kwargs=generate_kwargs,
        )


def _create_backend(
    info: LocalModelInfo,
    kwargs: dict[str, Any],
) -> LocalBackend:
    """Instantiate the appropriate backend for a model."""
    if info.backend == BackendType.LLAMACPP:
        from .backends.llamacpp_backend import LlamaCppBackend

        return LlamaCppBackend(model_path=info.local_path, **kwargs)
    elif info.backend == BackendType.MLX:
        from .backends.mlx_backend import MlxBackend

        return MlxBackend(model_path=info.local_path, **kwargs)
    else:
        raise ValueError(f"Unknown backend: {info.backend}")
