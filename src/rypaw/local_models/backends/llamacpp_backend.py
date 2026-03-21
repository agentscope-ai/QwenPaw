# -*- coding: utf-8 -*-
"""llama.cpp backend using llama-cpp-python."""

from __future__ import annotations

import logging
from typing import Any, Iterator, Optional, Type

from pydantic import BaseModel

from .base import LocalBackend

logger = logging.getLogger(__name__)


def _normalize_messages(messages: list[dict]) -> list[dict]:
    """Normalise messages for llama-cpp-python's Jinja chat templates.

    * Content must be a plain string (never ``None`` or a list of blocks).
    * ``tool_calls`` must be a proper list or absent (never ``None``).
    """
    out: list[dict] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            msg = {**msg, "content": "\n".join(parts)}
        elif content is None:
            msg = {**msg, "content": ""}

        # Ensure tool_calls is a proper list or absent — Jinja templates
        # crash when iterating or checking containment on None.
        if "tool_calls" in msg and not msg["tool_calls"]:
            msg = {k: v for k, v in msg.items() if k != "tool_calls"}

        out.append(msg)
    return out


class LlamaCppBackend(LocalBackend):
    """Backend implementation using llama-cpp-python."""

    def __init__(
        self,
        model_path: str,
        n_ctx: int = 32768,
        n_gpu_layers: int = -1,
        verbose: bool = False,
        chat_format: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        try:
            from llama_cpp import Llama
        except ImportError as e:
            raise ImportError(
                "llama-cpp-python is required for the llamacpp backend. "
                "Install it with: pip install 'copaw[llamacpp]'",
            ) from e

        logger.info(
            "Loading model from %s (n_ctx=%d, n_gpu_layers=%d)",
            model_path,
            n_ctx,
            n_gpu_layers,
        )

        init_kwargs: dict[str, Any] = {
            "model_path": model_path,
            "n_ctx": n_ctx,
            "n_gpu_layers": n_gpu_layers,
            "verbose": verbose,
            **kwargs,
        }
        if chat_format is not None:
            init_kwargs["chat_format"] = chat_format

        self._llm = Llama(**init_kwargs)
        self._model_path = model_path
        logger.info("Model loaded successfully: %s", model_path)

    def chat_completion(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
        structured_model: Optional[Type[BaseModel]] = None,
        **kwargs: Any,
    ) -> dict:
        call_kwargs: dict[str, Any] = {
            "messages": _normalize_messages(messages),
            "stream": False,
            **kwargs,
        }

        if tools:
            call_kwargs["tools"] = tools
            call_kwargs["tool_choice"] = tool_choice or "auto"

        if structured_model:
            schema = structured_model.model_json_schema()
            call_kwargs["response_format"] = {
                "type": "json_object",
                "schema": schema,
            }

        return self._llm.create_chat_completion(**call_kwargs)

    def chat_completion_stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> Iterator[dict]:
        call_kwargs: dict[str, Any] = {
            "messages": _normalize_messages(messages),
            "stream": True,
            **kwargs,
        }
        if tools:
            call_kwargs["tools"] = tools
            call_kwargs["tool_choice"] = tool_choice or "auto"

        yield from self._llm.create_chat_completion(**call_kwargs)

    def unload(self) -> None:
        if self._llm is not None:
            del self._llm
            self._llm = None
            logger.info("Model unloaded: %s", self._model_path)

    @property
    def is_loaded(self) -> bool:
        return self._llm is not None
