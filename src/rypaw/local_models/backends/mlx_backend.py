# -*- coding: utf-8 -*-
"""MLX backend using mlx-lm for Apple Silicon."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterator, Optional, Type

from pydantic import BaseModel

from .base import LocalBackend

logger = logging.getLogger(__name__)


def _normalize_messages(messages: list[dict]) -> list[dict]:
    """Normalise messages for MLX tokenizer chat templates.

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

        if "tool_calls" in msg and not msg["tool_calls"]:
            msg = {k: v for k, v in msg.items() if k != "tool_calls"}

        out.append(msg)
    return out


def _resolve_model_dir(model_path: str) -> str:
    """Return the model directory from a file or directory path.

    MLX models are directory-based (safetensors + config files), but
    ``LocalModelInfo.local_path`` may point to a specific file within that
    directory.
    """
    p = Path(model_path)
    if p.is_file():
        return str(p.parent)
    return str(p)


class MlxBackend(LocalBackend):
    """Backend implementation using mlx-lm for Apple Silicon."""

    def __init__(
        self,
        model_path: str,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> None:
        try:
            import mlx_lm
        except ImportError as e:
            raise ImportError(
                "mlx-lm is required for the MLX backend. "
                "Install it with: pip install 'copaw[mlx]'",
            ) from e

        model_dir = _resolve_model_dir(model_path)
        logger.info("Loading MLX model from %s", model_dir)

        self._model, self._tokenizer = mlx_lm.load(model_dir)
        self._model_path = model_path
        self._model_dir = model_dir
        self._max_tokens = max_tokens
        self._kwargs = kwargs
        logger.info("MLX model loaded successfully: %s", model_dir)

    def _build_prompt(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
    ) -> str:
        """Apply the tokenizer chat template to produce a prompt string."""
        kwargs: dict[str, Any] = {
            "tokenize": False,
            "add_generation_prompt": True,
        }
        if tools and getattr(self._tokenizer, "has_tool_calling", False):
            kwargs["tools"] = tools
        return self._tokenizer.apply_chat_template(messages, **kwargs)

    def chat_completion(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
        structured_model: Optional[Type[BaseModel]] = None,
        **kwargs: Any,
    ) -> dict:
        import mlx_lm

        prompt = self._build_prompt(_normalize_messages(messages), tools=tools)

        max_tokens = kwargs.pop("max_tokens", self._max_tokens)
        merged = {**self._kwargs, **kwargs}

        # Build sampler kwargs from merged params
        sampler_kwargs = {}
        for key in ("temp", "temperature", "top_p", "min_p", "top_k"):
            if key in merged:
                val = merged.pop(key)
                # mlx-lm uses "temp" not "temperature"
                sampler_key = "temp" if key == "temperature" else key
                sampler_kwargs[sampler_key] = val

        generate_kwargs: dict[str, Any] = {}
        if sampler_kwargs:
            from mlx_lm.sample_utils import make_sampler

            generate_kwargs["sampler"] = make_sampler(**sampler_kwargs)

        if structured_model:
            schema = structured_model.model_json_schema()
            # Append JSON instruction to prompt — MLX doesn't have native
            # structured output, so we rely on the model
            # following instructions.
            prompt += (
                f"\nRespond with a JSON object matching this schema: "
                f"{schema}\n"
            )

        # Accumulate all tokens via stream_generate
        text_parts: list[str] = []
        prompt_tokens = 0
        generation_tokens = 0
        finish_reason: Optional[str] = None

        for response in mlx_lm.stream_generate(
            self._model,
            self._tokenizer,
            prompt=prompt,
            max_tokens=max_tokens if max_tokens is not None else 2048,
            **generate_kwargs,
        ):
            text_parts.append(response.text)
            prompt_tokens = response.prompt_tokens
            generation_tokens = response.generation_tokens
            if response.finish_reason is not None:
                finish_reason = response.finish_reason

        full_text = "".join(text_parts)

        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": full_text,
                    },
                    "finish_reason": finish_reason or "stop",
                },
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": generation_tokens,
            },
        }

    def chat_completion_stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> Iterator[dict]:
        import mlx_lm

        prompt = self._build_prompt(_normalize_messages(messages), tools=tools)

        max_tokens = kwargs.pop("max_tokens", self._max_tokens)
        merged = {**self._kwargs, **kwargs}

        sampler_kwargs = {}
        for key in ("temp", "temperature", "top_p", "min_p", "top_k"):
            if key in merged:
                val = merged.pop(key)
                sampler_key = "temp" if key == "temperature" else key
                sampler_kwargs[sampler_key] = val

        generate_kwargs: dict[str, Any] = {}
        if sampler_kwargs:
            from mlx_lm.sample_utils import make_sampler

            generate_kwargs["sampler"] = make_sampler(**sampler_kwargs)

        for response in mlx_lm.stream_generate(
            self._model,
            self._tokenizer,
            prompt=prompt,
            max_tokens=max_tokens if max_tokens is not None else 2048,
            **generate_kwargs,
        ):
            is_final = response.finish_reason is not None
            chunk: dict[str, Any] = {
                "choices": [
                    {
                        "delta": {"content": response.text},
                        "finish_reason": response.finish_reason,
                    },
                ],
            }
            if is_final:
                chunk["usage"] = {
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.generation_tokens,
                }
            yield chunk

    def unload(self) -> None:
        if self._model is not None:
            del self._model
            del self._tokenizer
            self._model = None
            self._tokenizer = None
            logger.info("MLX model unloaded: %s", self._model_dir)

    @property
    def is_loaded(self) -> bool:
        return self._model is not None
