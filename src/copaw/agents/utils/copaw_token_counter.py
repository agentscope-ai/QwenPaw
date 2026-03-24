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


def _extract_text_from_blocks(blocks: list) -> str:
    """Extract text from a list of content blocks.

    Args:
        blocks: List of content blocks (dicts with "text" key, TextBlock
            objects with .text attribute, or plain strings).

    Returns:
        Concatenated text from all blocks.
    """
    parts = []
    for block in blocks:
        if isinstance(block, dict):
            t = block.get("text", "")
            if t:
                parts.append(str(t))
        elif hasattr(block, "text"):
            t = block.text
            if t:
                parts.append(str(t))
        elif isinstance(block, str):
            parts.append(block)
    return "\n".join(parts)


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
        if text is not None:
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
            normalized = self._normalize_messages(messages)
            try:
                return await super().count(normalized, tools, **kwargs)
            except (TypeError, Exception) as e:
                # Fallback: estimate from concatenated text
                total_text = " ".join(
                    m.get("content", "")
                    if isinstance(m, dict)
                    else str(getattr(m, "content", m))
                    for m in normalized
                )
                logger.debug(
                    "Token count fallback to estimation: %s",
                    e,
                )
                return self.estimate_tokens(total_text)

    @staticmethod
    def _normalize_messages(messages: list) -> list[dict]:
        """Normalize messages so that content is always a string.

        Some LLM providers return Msg.content as a list of content blocks
        (e.g. [{"type": "text", "text": "..."}, {"type": "tool_use", ...}]).
        HuggingFace tokenizer's apply_chat_template expects content to be
        a plain string, causing TypeError otherwise.

        Args:
            messages: List of message dicts or Msg objects.

        Returns:
            List of message dicts with string content.
        """
        normalized = []
        for msg in messages:
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, list):
                    m = dict(msg)
                    m["content"] = _extract_text_from_blocks(content)
                    normalized.append(m)
                else:
                    normalized.append(msg)
            elif hasattr(msg, "content"):
                content = msg.content
                if isinstance(content, list):
                    normalized.append(
                        {
                            "role": getattr(msg, "role", "user"),
                            "content": _extract_text_from_blocks(content),
                            **(
                                {"name": msg.name}
                                if hasattr(msg, "name")
                                else {}
                            ),
                        },
                    )
                else:
                    normalized.append(msg)
            else:
                normalized.append(msg)
        return normalized

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


def get_copaw_token_counter(
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
    )

    if config_key not in _token_counter_cache:
        _token_counter_cache[config_key] = CopawTokenCounter(
            token_count_model=running_config.token_count_model,
            token_count_use_mirror=running_config.token_count_use_mirror,
            token_count_estimate_divisor=(
                running_config.token_count_estimate_divisor
            ),
        )
        logger.info(
            f"Token counter created with "
            f"model={running_config.token_count_model}, "
            f"mirror={running_config.token_count_use_mirror}, "
            f"divisor={running_config.token_count_estimate_divisor}",
        )
    else:
        # Update estimate divisor for cached counter
        _token_counter_cache[
            config_key
        ].token_count_estimate_divisor = (
            running_config.token_count_estimate_divisor
        )

    return _token_counter_cache[config_key]
