# -*- coding: utf-8 -*-
"""Abstract base class for local model inference backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterator, Optional, Type

from pydantic import BaseModel


class LocalBackend(ABC):
    """Abstract interface for a local model inference backend.

    Each backend wraps a specific library (llama-cpp-python, mlx-lm, etc.)
    and exposes a unified chat-completion interface that returns
    OpenAI-compatible dicts.
    """

    @abstractmethod
    def __init__(self, model_path: str, **kwargs: Any) -> None:
        """Load the model from disk into memory.

        Args:
            model_path: Absolute path to the model file.
            **kwargs: Backend-specific parameters (n_ctx, n_gpu_layers, etc.)
        """

    @abstractmethod
    def chat_completion(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
        structured_model: Optional[Type[BaseModel]] = None,
        **kwargs: Any,
    ) -> dict:
        """Non-streaming chat completion.

        Returns an OpenAI-compatible dict with ``choices`` and ``usage``.
        """

    @abstractmethod
    def chat_completion_stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> Iterator[dict]:
        """Streaming chat completion.

        Yields OpenAI-compatible chunk dicts.
        """

    @abstractmethod
    def unload(self) -> None:
        """Release all resources (VRAM, RAM) held by the model."""

    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        """Whether a model is currently loaded and ready for inference."""
