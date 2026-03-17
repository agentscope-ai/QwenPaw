# -*- coding: utf-8 -*-
"""Token counting utilities for CoPaw using HuggingFace tokenizers.

This module provides a configurable token counter that supports dynamic
switching between different tokenizer models based on runtime configuration.
"""
import logging
import os
from pathlib import Path
from typing import Any

from agentscope.token import HuggingFaceTokenCounter

from ...config import load_config

logger = logging.getLogger(__name__)


class CopawTokenCounter(HuggingFaceTokenCounter):
    """Token counter for CoPaw with configurable tokenizer support.

    This class extends HuggingFaceTokenCounter to provide token counting
    functionality with support for both local and remote tokenizers,
    as well as HuggingFace mirror for users in China.

    Attributes:
        token_count_model: The tokenizer model path or "default" for local tokenizer.
        token_count_use_mirror: Whether to use HuggingFace mirror.
    """

    def __init__(self, token_count_model: str, token_count_use_mirror: bool, **kwargs):
        """Initialize the token counter with the specified configuration.

        Args:
            token_count_model: The tokenizer model path. Use "default" for the
                bundled local tokenizer, or provide a HuggingFace model identifier
                or path to a custom tokenizer.
            token_count_use_mirror: Whether to use the HuggingFace mirror
                (https://hf-mirror.com) for downloading tokenizers. Useful for
                users in China.
            **kwargs: Additional keyword arguments passed to HuggingFaceTokenCounter.
        """
        self.token_count_model = token_count_model
        self.token_count_use_mirror = token_count_use_mirror

        # Set HuggingFace endpoint for mirror support
        if token_count_use_mirror:
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        else:
            os.environ.pop("HF_ENDPOINT", None)

        # Resolve tokenizer path
        if token_count_model == "default":
            tokenizer_path = str(
                Path(__file__).parent.parent.parent / "tokenizer"
            )
        else:
            tokenizer_path = token_count_model

        try:
            super().__init__(
                pretrained_model_name_or_path=tokenizer_path,
                use_mirror=token_count_use_mirror,
                use_fast=True,
                trust_remote_code=True,
                **kwargs,
            )
            self._tokenizer_available = True

        except Exception as e:
            logger.exception("Failed to initialize tokenizer: %s", e)
            self._tokenizer_available = False

    async def count(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        text: str | None = None,
        **kwargs: Any,
    ) -> int:
        """Count tokens in messages or text.

        If text is provided, counts tokens directly in the text string.
        Otherwise, counts tokens in the messages using the parent class method.

        Args:
            messages: List of message dictionaries in chat format.
            tools: Optional list of tool definitions for token counting.
            text: Optional text string to count tokens directly.
            **kwargs: Additional keyword arguments passed to parent count method.

        Returns:
            The number of tokens, guaranteed to be at least the estimated minimum.
        """
        if text:
            if self._tokenizer_available:
                try:
                    token_ids = self.tokenizer.encode(text)
                    return max(len(token_ids), self.estimate_tokens(text))
                except Exception as e:
                    logger.exception("Failed to encode text with tokenizer: %s", e)
                    return self.estimate_tokens(text)
            else:
                return self.estimate_tokens(text)
        else:
            return await super().count(messages, tools, **kwargs)

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate the number of tokens in a text string.

        Provides a fast character-based estimation as a fallback or lower bound.
        Uses the configured divisor from agent settings.

        Args:
            text: The text string to estimate tokens for.

        Returns:
            The estimated number of tokens in the text string.
        """
        agent_config = load_config()
        agent_running_config = agent_config.agents.running
        token_count_estimate_divisor: float = agent_running_config.token_count_estimate_divisor
        return int(len(text.encode("utf-8")) / token_count_estimate_divisor + 0.5)


# Global token counter instance and its configuration cache
_token_counter: CopawTokenCounter | None = None
_token_counter_config: dict | None = None


def _get_copaw_token_counter() -> CopawTokenCounter:
    """Get or initialize the global token counter instance.

    This function implements a singleton pattern with configuration change detection.
    If the configuration has changed since the last initialization, a new instance
    will be created to reflect the updated settings.

    Returns:
        CopawTokenCounter: The global token counter instance.

    Note:
        The configuration is cached to avoid unnecessary re-initialization.
        Changes to token_count_model or token_count_use_mirror will trigger
        creation of a new token counter instance.
    """
    global _token_counter, _token_counter_config

    agent_config = load_config()
    agent_running_config = agent_config.agents.running
    current_config = {
        "token_count_model": agent_running_config.token_count_model,
        "token_count_use_mirror": agent_running_config.token_count_use_mirror,
    }

    if _token_counter is None or _token_counter_config != current_config:
        _token_counter = CopawTokenCounter(
            token_count_model=current_config["token_count_model"],
            token_count_use_mirror=current_config["token_count_use_mirror"],
        )
        _token_counter_config = current_config
        logger.debug(
            "Token counter initialized with model=%s, mirror=%s",
            current_config["token_count_model"],
            current_config["token_count_use_mirror"],
        )
    return _token_counter