# -*- coding: utf-8 -*-
"""Token counting utilities using HuggingFace tokenizers.

This module provides a configurable token counter that supports dynamic
switching between different tokenizer models based on runtime configuration.
"""
import logging
import os
from pathlib import Path
from typing import Any, TYPE_CHECKING
import json
from agentscope.token import HuggingFaceTokenCounter

if TYPE_CHECKING:
    from qwenpaw.config.config import AgentProfileConfig

logger = logging.getLogger(__name__)


class TokenCounter(HuggingFaceTokenCounter):
    """Token counter with configurable tokenizer support.

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
            mirror = "https://hf-mirror.com"
        else:
            mirror = "https://huggingface.co"

        os.environ["HF_ENDPOINT"] = mirror

        # if the huggingface is already imported in other dependencies,
        # we need to set the endpoint manually
        import huggingface_hub.constants

        huggingface_hub.constants.ENDPOINT = mirror
        huggingface_hub.constants.HUGGINGFACE_CO_URL_TEMPLATE = (
            mirror + "/{repo_id}/resolve/{revision}/{filename}"
        )

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


class EstimateTokenCounter(HuggingFaceTokenCounter):
    """Lightweight token counter using only character-based estimation.

    This class extends HuggingFaceTokenCounter but skips tokenizer
    loading entirely, relying solely on estimate_tokens for all token
    counting. Suitable when low overhead is preferred over precision.

    Attributes:
        token_count_estimate_divisor: Divisor for character-based token
            estimation.
    """

    def __init__(
        self,
        token_count_estimate_divisor: float = 3.75,
        **_kwargs,
    ):
        """Initialize the estimate-only token counter.

        Args:
            token_count_estimate_divisor: Divisor for character-based token
                estimation (default: 3.75).
            **_kwargs: Accepted but not forwarded (no tokenizer is loaded).
        """
        self.token_count_estimate_divisor = token_count_estimate_divisor
        self._tokenizer_available = False

    async def count(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        text: str | None = None,
        **_kwargs: Any,
    ) -> int:
        """Count tokens using character-based estimation only.

        Args:
            messages: List of message dictionaries in chat format.
            tools: Optional list of tool definitions (included in estimate).
            text: Optional text string to count tokens directly.
            **kwargs: Ignored.

        Returns:
            The estimated number of tokens.
        """
        if text:
            return self.estimate_tokens(text)

        parts: list[str] = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        parts.append(block.get("text", ""))
                    else:
                        parts.append(str(block))
            else:
                parts.append(str(content))

        if tools:
            parts.append(json.dumps(tools, ensure_ascii=False))

        return self.estimate_tokens(" ".join(parts))

    def estimate_tokens(self, text: str) -> int:
        """Estimate the number of tokens in a text string.

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
_token_counter_cache: dict[
    tuple,
    TokenCounter | EstimateTokenCounter,
] = {}


def get_token_counter(
    agent_config: "AgentProfileConfig",
    use_estimate: bool = True,
) -> TokenCounter | EstimateTokenCounter:
    """Get or create a token counter instance for the given agent conf.

    This function implements a cache based on token counter configuration.
    If a token counter with the same configuration already exists, it will be
    reused. Otherwise, a new instance will be created.

    Args:
        agent_config: Agent profile configuration containing running
            settings including token_count_model, token_count_use_mirror,
            and token_count_estimate_divisor.
        use_estimate: If True (default), returns an EstimateTokenCounter
            that uses only character-based estimation without loading a
            tokenizer. If False, returns a full TokenCounter backed
            by a HuggingFace tokenizer.

    Returns:
        A token counter instance for the given configuration.

    Note:
        Token counters are cached by their configuration tuple and counter
        type to enable reuse across agents with identical settings.
    """
    cc = agent_config.running.context_compact

    if use_estimate:
        return EstimateTokenCounter(
            token_count_estimate_divisor=cc.token_count_estimate_divisor,
        )
    else:
        config_key = (
            "hf",
            cc.token_count_model,
            cc.token_count_use_mirror,
        )
        if config_key not in _token_counter_cache:
            _token_counter_cache[config_key] = TokenCounter(
                token_count_model=cc.token_count_model,
                token_count_use_mirror=cc.token_count_use_mirror,
                token_count_estimate_divisor=cc.token_count_estimate_divisor,
            )
            logger.info(
                f"Token counter created with "
                f"model={cc.token_count_model}, "
                f"mirror={cc.token_count_use_mirror}, "
                f"divisor={cc.token_count_estimate_divisor}",
            )
        else:
            _token_counter_cache[
                config_key
            ].token_count_estimate_divisor = cc.token_count_estimate_divisor

    return _token_counter_cache[config_key]
