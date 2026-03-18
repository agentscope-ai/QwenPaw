# -*- coding: utf-8 -*-
"""Token counting utilities for CoPaw using HuggingFace tokenizers.

This module provides a configurable token counter that supports dynamic
switching between different tokenizer models based on runtime configuration.
"""
import logging
import os
from pathlib import Path
from typing import Any, TYPE_CHECKING

from agentscope.token import HuggingFaceTokenCounter

if TYPE_CHECKING:
    from copaw.config.config import AgentProfileConfig

logger = logging.getLogger(__name__)


class CopawTokenCounter(HuggingFaceTokenCounter):
    """Token counter for CoPaw with configurable tokenizer support.

    This class extends HuggingFaceTokenCounter to provide token counting
    functionality with support for both local and remote tokenizers,
    as well as HuggingFace mirror for users in China.

    Attributes:
        token_count_model: The tokenizer model path or "default" for
            local tokenizer.
        token_count_use_mirror: Whether to use HuggingFace mirror.
        token_count_estimate_divisor: Divisor for character-based token
            estimation.
    """

    def __init__(
        self,
        token_count_model: str,
        token_count_use_mirror: bool,
        token_count_estimate_divisor: float = 3.75,
        **kwargs,
    ):
        """Initialize the token counter with the specified configuration.

        Args:
            token_count_model: The tokenizer model path. Use "default"
                for the bundled local tokenizer, or provide a HuggingFace
                model identifier or path to a custom tokenizer.
            token_count_use_mirror: Whether to use the HuggingFace mirror
                (https://hf-mirror.com) for downloading tokenizers.
                Useful for users in China.
            token_count_estimate_divisor: Divisor for character-based token
                estimation (default: 3.75).
            **kwargs: Additional keyword arguments passed to
                HuggingFaceTokenCounter.
        """
        self.token_count_model = token_count_model
        self.token_count_use_mirror = token_count_use_mirror
        self.token_count_estimate_divisor = token_count_estimate_divisor

        # Set HuggingFace endpoint for mirror support
        if token_count_use_mirror:
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        else:
            os.environ.pop("HF_ENDPOINT", None)

        # Resolve tokenizer path
        if token_count_model == "default":
            tokenizer_path = str(
                Path(__file__).parent.parent.parent / "tokenizer",
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
            **kwargs: Additional keyword arguments passed to parent
                count method.

        Returns:
            The number of tokens, guaranteed to be at least the
            estimated minimum.
        """
        if text:
            if self._tokenizer_available:
                try:
                    token_ids = self.tokenizer.encode(text)
                    return max(len(token_ids), self.estimate_tokens(text))
                except Exception as e:
                    logger.exception(
                        "Failed to encode text with tokenizer: %s",
                        e,
                    )
                    return self.estimate_tokens(text)
            else:
                return self.estimate_tokens(text)
        else:
            return await super().count(messages, tools, **kwargs)

    def estimate_tokens(self, text: str) -> int:
        """Estimate the number of tokens in a text string.

        Provides a fast character-based estimation as a fallback
        or lower bound. Uses the configured divisor from agent settings.

        Args:
            text: The text string to estimate tokens for.

        Returns:
            The estimated number of tokens in the text string.
        """
        return int(
            len(text.encode("utf-8")) / self.token_count_estimate_divisor
            + 0.5,
        )


# Global token counter instance cache (keyed by configuration tuple)
_token_counter_cache: dict[tuple, CopawTokenCounter] = {}


def _get_copaw_token_counter(
    agent_config: "AgentProfileConfig",
) -> CopawTokenCounter:
    """Get or create a token counter instance for the given agent conf.

    This function implements a cache based on token counter configuration.
    If a token counter with the same configuration already exists, it will be
    reused. Otherwise, a new instance will be created.

    Args:
        agent_config: Agent profile configuration containing running
            settings including token_count_model, token_count_use_mirror,
            and token_count_estimate_divisor.

    Returns:
        CopawTokenCounter: A token counter instance for the given
        configuration.

    Note:
        Token counters are cached by their configuration tuple to enable
        reuse across agents with identical settings.
    """
    running_config = agent_config.running
    config_key = (
        running_config.token_count_model,
        running_config.token_count_use_mirror,
        running_config.token_count_estimate_divisor,
    )

    if config_key not in _token_counter_cache:
        _token_counter_cache[config_key] = CopawTokenCounter(
            token_count_model=running_config.token_count_model,
            token_count_use_mirror=running_config.token_count_use_mirror,
            token_count_estimate_divisor=(
                running_config.token_count_estimate_divisor
            ),
        )
        logger.debug(
            "Token counter created with model=%s, mirror=%s, divisor=%s",
            running_config.token_count_model,
            running_config.token_count_use_mirror,
            running_config.token_count_estimate_divisor,
        )
    return _token_counter_cache[config_key]
