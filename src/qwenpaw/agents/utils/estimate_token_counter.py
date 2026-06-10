# -*- coding: utf-8 -*-
"""Estimated token counter implementation."""

from agentscope.token import TokenCounterBase


class EstimatedTokenCounter(TokenCounterBase):
    """Token counter that estimates tokens using character-based calculation.

    This is a lightweight approximation suitable for cases where exact token
    counting is not critical. For accurate counts, use tiktoken or the
    model's tokenizer directly.
    """

    def __init__(self, estimate_divisor: float = 4):
        """Initialize the estimated token counter.

        Args:
            estimate_divisor: The divisor for character-to-token estimation.
                Default 4 assumes roughly 4 characters per token.
                Use 2-3 for Chinese/Japanese text, 4-5 for English.
        """
        if estimate_divisor <= 0:
            raise ValueError("estimate_divisor cannot be zero")
        self.estimate_divisor: float = estimate_divisor

    async def count(self, text: str, **_kwargs) -> int:
        """Count tokens in the given messages.

        Args:
            text: The text to count tokens.
            **kwargs: Additional arguments.

        Returns:
            Estimated number of tokens in all messages.
        """
        if not text:
            return 0
        return int(len(text.encode("utf-8")) / self.estimate_divisor + 0.5)
