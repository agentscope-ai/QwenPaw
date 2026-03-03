# -*- coding: utf-8 -*-
"""Token counting utilities for managing context windows.

This module provides token counting functionality for estimating
message token usage with Qwen tokenizer.
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_token_counter = None


def _get_token_counter():
    """Get or initialize the global token counter instance.

    Returns:
        TokenCounterBase: The token counter instance for Qwen models.

    Raises:
        RuntimeError: If token counter initialization fails.
    """
    global _token_counter
    if _token_counter is None:
        from agentscope.token import HuggingFaceTokenCounter

        # Use Qwen tokenizer for DashScope models
        # Qwen3 series uses the same tokenizer as Qwen2.5

        # Try local tokenizer first, fall back to online if not found
        local_tokenizer_path = (
            Path(__file__).parent.parent.parent / "tokenizer"
        )

        if (
            local_tokenizer_path.exists()
            and (local_tokenizer_path / "tokenizer.json").exists()
        ):
            tokenizer_path = str(local_tokenizer_path)
            logger.info(f"Using local Qwen tokenizer from {tokenizer_path}")
        else:
            tokenizer_path = "Qwen/Qwen2.5-7B-Instruct"
            logger.info(
                "Local tokenizer not found, downloading from HuggingFace",
            )

        _token_counter = HuggingFaceTokenCounter(
            pretrained_model_name_or_path=tokenizer_path,
            use_mirror=True,  # Use HF mirror for users in China
            use_fast=True,
            trust_remote_code=True,
        )
        logger.debug("Token counter initialized with Qwen tokenizer")
    return _token_counter


def _extract_text_from_messages(messages: list[dict]) -> str:
    """Extract text content from messages and concatenate into a string.

    Handles various message formats:
    - Simple string content: {"role": "user", "content": "hello"}
    - List content with text blocks:
      {"role": "user", "content": [{"type": "text", "text": "hello"}]}

    Args:
        messages: List of message dictionaries in chat format.

    Returns:
        str: Concatenated text content from all messages.
    """
    parts = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    # Support {"type": "text", "text": "..."} format
                    text = block.get("text") or block.get("content", "")
                    if text:
                        parts.append(str(text))
                elif isinstance(block, str):
                    parts.append(block)
    return "\n".join(parts)


async def count_message_tokens(
    messages: list[dict],
) -> int:
    """Count tokens in messages using the tokenizer.

    Extracts text content from messages and uses the tokenizer to
    count tokens. This approach is more robust across different model
    types than using apply_chat_template directly.

    Args:
        messages: List of message dictionaries in chat format.

    Returns:
        int: The estimated number of tokens in the messages.

    Raises:
        RuntimeError: If token counter fails to initialize.
    """
    token_counter = _get_token_counter()
    text = _extract_text_from_messages(messages)
    token_ids = token_counter.tokenizer.encode(text)
    token_count = len(token_ids)
    logger.debug(
        "Counted %d tokens in %d messages",
        token_count,
        len(messages),
    )
    return token_count


async def safe_count_message_tokens(
    messages: list[dict],
) -> int:
    """Safely count tokens in messages with fallback estimation.

    This is a wrapper around count_message_tokens that catches exceptions
    and falls back to a character-based estimation (len // 4) if the
    tokenizer fails.

    Args:
        messages: List of message dictionaries in chat format.

    Returns:
        int: The estimated number of tokens in the messages.
    """
    try:
        return await count_message_tokens(messages)
    except Exception as e:
        # Fallback to character-based estimation
        text = _extract_text_from_messages(messages)
        estimated_tokens = len(text) // 4
        logger.warning(
            "Failed to count tokens: %s, using estimated_tokens=%d",
            e,
            estimated_tokens,
        )
        return estimated_tokens


def safe_count_str_tokens(text: str) -> int:
    """Safely count tokens in a string with fallback estimation.

    Uses the tokenizer to count tokens in the given text. If the tokenizer
    fails, falls back to a character-based estimation (len // 4).

    Args:
        text: The string to count tokens for.

    Returns:
        int: The estimated number of tokens in the string.
    """
    try:
        token_counter = _get_token_counter()
        token_ids = token_counter.tokenizer.encode(text)
        token_count = len(token_ids)
        logger.debug(
            "Counted %d tokens in string of length %d",
            token_count,
            len(text),
        )
        return token_count
    except Exception as e:
        # Fallback to character-based estimation
        estimated_tokens = len(text) // 4
        logger.warning(
            "Failed to count string tokens: %s, using estimated_tokens=%d",
            e,
            estimated_tokens,
        )
        return estimated_tokens
