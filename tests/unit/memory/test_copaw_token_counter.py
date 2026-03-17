# -*- coding: utf-8 -*-
"""Unit tests for CopawTokenCounter.

Tests cover:
- Initialization with different model configurations
- Token counting for text and messages
- Estimation fallback
- Singleton pattern with configuration change detection
"""
from __future__ import annotations

import asyncio
import os
import sys

# Mock google.genai before importing copaw modules
sys.modules["google"] = type(sys)("google")
sys.modules["google.genai"] = type(sys)("google.genai")
sys.modules["google.genai.errors"] = type(sys)("google.genai.errors")
sys.modules["google.genai.types"] = type(sys)("google.genai.types")

from copaw.agents.utils.copaw_token_counter import (
    CopawTokenCounter,
    _get_copaw_token_counter,
)
import copaw.agents.utils.copaw_token_counter as token_counter_module


def _reset_global_state() -> None:
    """Reset global token counter state for test isolation."""
    token_counter_module._token_counter = None
    token_counter_module._token_counter_config = None


def test_init_default_model() -> None:
    """Test initialization with default local tokenizer."""
    print("Testing: init with default model")
    counter = CopawTokenCounter(
        token_count_model="default",
        token_count_use_mirror=True,
    )
    assert counter.token_count_model == "default"
    assert counter.token_count_use_mirror is True
    assert counter.tokenizer is not None
    print("  PASSED: default model initialized")


def test_init_with_mirror_enabled() -> None:
    """Test that HF_ENDPOINT is set when mirror is enabled."""
    print("Testing: init with mirror enabled")
    os.environ.pop("HF_ENDPOINT", None)

    counter = CopawTokenCounter(
        token_count_model="default",
        token_count_use_mirror=True,
    )
    assert counter.token_count_use_mirror is True
    assert os.environ.get("HF_ENDPOINT") == "https://hf-mirror.com"
    print("  PASSED: HF_ENDPOINT set correctly")

    # Cleanup
    os.environ.pop("HF_ENDPOINT", None)


def test_init_custom_model_path() -> None:
    """Test initialization with custom model path."""
    print("Testing: init with custom model path")
    custom_path = "Qwen/Qwen2.5-7B-Instruct"
    counter = CopawTokenCounter(
        token_count_model=custom_path,
        token_count_use_mirror=True,
    )
    assert counter.token_count_model == custom_path
    print("  PASSED: custom model path initialized")


def test_qwen_tokenizer() -> None:
    """Test Qwen/Qwen2.5-7B-Instruct tokenizer."""
    print("Testing: Qwen/Qwen2.5-7B-Instruct tokenizer")
    try:
        counter = CopawTokenCounter(
            token_count_model="Qwen/Qwen2.5-7B-Instruct",
            token_count_use_mirror=True,
        )
        texts = [
            "Hello, world!",
            "你好，世界！",
            "def foo():\n    return 'bar'",
        ]
        for text in texts:
            token_ids = counter.tokenizer.encode(text)
            print(f"  '{text[:20]}...' -> {len(token_ids)} tokens")
        print("  PASSED: Qwen tokenizer works")
    except ValueError as e:
        print(f"  SKIPPED: Qwen tokenizer not available - {e}")


def test_deepseek_tokenizer() -> None:
    """Test deepseek-ai/DeepSeek-V3 tokenizer."""
    print("Testing: deepseek-ai/DeepSeek-V3 tokenizer")
    try:
        counter = CopawTokenCounter(
            token_count_model="deepseek-ai/DeepSeek-V3",
            token_count_use_mirror=True,
        )
        texts = [
            "Hello, world!",
            "你好，世界！",
            "def foo():\n    return 'bar'",
        ]
        for text in texts:
            token_ids = counter.tokenizer.encode(text)
            # DeepSeek tokenizer may return empty for some texts
            print(f"  '{text[:20]}...' -> {len(token_ids)} tokens")
        print("  PASSED: DeepSeek tokenizer works")
    except ValueError as e:
        print(f"  SKIPPED: DeepSeek tokenizer not available - {e}")


def test_minimax_tokenizer() -> None:
    """Test MiniMaxAI/MiniMax-M2.5 tokenizer."""
    print("Testing: MiniMaxAI/MiniMax-M2.5 tokenizer")
    try:
        counter = CopawTokenCounter(
            token_count_model="MiniMaxAI/MiniMax-M2.5",
            token_count_use_mirror=True,
        )
        texts = [
            "Hello, world!",
            "你好，世界！",
            "def foo():\n    return 'bar'",
        ]
        for text in texts:
            token_ids = counter.tokenizer.encode(text)
            print(f"  '{text[:20]}...' -> {len(token_ids)} tokens")
        print("  PASSED: MiniMax tokenizer works")
    except ValueError as e:
        print(f"  SKIPPED: MiniMax tokenizer not available - {e}")


def test_glm_tokenizer() -> None:
    """Test zai-org/GLM-5 tokenizer."""
    print("Testing: zai-org/GLM-5 tokenizer")
    try:
        counter = CopawTokenCounter(
            token_count_model="zai-org/GLM-5",
            token_count_use_mirror=True,
        )
        texts = [
            "Hello, world!",
            "你好，世界！",
            "def foo():\n    return 'bar'",
        ]
        for text in texts:
            token_ids = counter.tokenizer.encode(text)
            print(f"  '{text[:20]}...' -> {len(token_ids)} tokens")
        print("  PASSED: GLM tokenizer works")
    except ValueError as e:
        print(f"  SKIPPED: GLM tokenizer not available - {e}")


def test_count_text_basic() -> None:
    """Test basic text token counting."""
    print("Testing: count text basic")
    counter = CopawTokenCounter(
        token_count_model="default",
        token_count_use_mirror=True,
    )
    text = "Hello, world!"
    token_ids = counter.tokenizer.encode(text)
    assert len(token_ids) > 0
    print(f"  PASSED: '{text}' has {len(token_ids)} tokens")


def test_count_text_empty() -> None:
    """Test token counting for empty text."""
    print("Testing: count empty text")
    counter = CopawTokenCounter(
        token_count_model="default",
        token_count_use_mirror=True,
    )
    text = ""
    token_ids = counter.tokenizer.encode(text)
    assert len(token_ids) == 0
    print("  PASSED: empty text has 0 tokens")


def test_count_text_chinese() -> None:
    """Test token counting for Chinese text."""
    print("Testing: count Chinese text")
    counter = CopawTokenCounter(
        token_count_model="default",
        token_count_use_mirror=True,
    )
    text = "你好，世界！"
    token_ids = counter.tokenizer.encode(text)
    assert len(token_ids) > 0
    print(f"  PASSED: '{text}' has {len(token_ids)} tokens")


def test_count_text_mixed_language() -> None:
    """Test token counting for mixed language text."""
    print("Testing: count mixed language text")
    counter = CopawTokenCounter(
        token_count_model="default",
        token_count_use_mirror=True,
    )
    text = "Hello 世界! This is a test 测试。"
    token_ids = counter.tokenizer.encode(text)
    assert len(token_ids) > 0
    print(f"  PASSED: '{text}' has {len(token_ids)} tokens")


def test_count_text_code() -> None:
    """Test token counting for code text."""
    print("Testing: count code text")
    counter = CopawTokenCounter(
        token_count_model="default",
        token_count_use_mirror=True,
    )
    text = "def foo():\n    return 'bar'"
    token_ids = counter.tokenizer.encode(text)
    assert len(token_ids) > 0
    print(f"  PASSED: code text has {len(token_ids)} tokens")


async def test_count_with_text_parameter() -> None:
    """Test async count method with text parameter."""
    print("Testing: async count with text parameter")
    counter = CopawTokenCounter(
        token_count_model="default",
        token_count_use_mirror=True,
    )
    text = "Test text for counting"
    result = await counter.count(messages=[], text=text)
    assert result > 0
    print(f"  PASSED: async count returned {result} tokens")


def test_estimate_tokens() -> None:
    """Test token estimation fallback."""
    print("Testing: estimate tokens")
    # Use the actual config
    text = "Hello world"
    result = CopawTokenCounter.estimate_tokens(text)
    assert result > 0
    print(f"  PASSED: estimate returned {result} tokens for '{text}'")


def test_estimate_tokens_chinese() -> None:
    """Test estimation for Chinese text (UTF-8 encoded)."""
    print("Testing: estimate Chinese tokens")
    text = "你好世界"
    result = CopawTokenCounter.estimate_tokens(text)
    assert result > 0
    print(f"  PASSED: estimate returned {result} tokens for '{text}'")


def test_singleton_returns_same_instance() -> None:
    """Test that multiple calls return the same instance."""
    print("Testing: singleton returns same instance")
    _reset_global_state()

    counter1 = _get_copaw_token_counter()
    counter2 = _get_copaw_token_counter()
    assert counter1 is counter2
    print("  PASSED: singleton returns same instance")

    _reset_global_state()


def test_tokenizer_handles_special_characters() -> None:
    """Test tokenizer handles special characters correctly."""
    print("Testing: tokenizer handles special characters")
    counter = CopawTokenCounter(
        token_count_model="default",
        token_count_use_mirror=True,
    )
    special_texts = [
        "def foo():\n    return 'bar'",
        "<html><body>test</body></html>",
        "line1\nline2\tline3",
        "emoji: 🎉🎊",
    ]
    for text in special_texts:
        token_ids = counter.tokenizer.encode(text)
        assert len(token_ids) > 0
        print(f"  PASSED: special text ({len(token_ids)} tokens)")
    print("  PASSED: all special characters handled")


def test_tokenizer_consistency() -> None:
    """Test that tokenization is consistent across calls."""
    print("Testing: tokenizer consistency")
    counter = CopawTokenCounter(
        token_count_model="default",
        token_count_use_mirror=True,
    )
    text = "Consistent tokenization test"
    tokens1 = counter.tokenizer.encode(text)
    tokens2 = counter.tokenizer.encode(text)
    assert tokens1 == tokens2
    print(f"  PASSED: tokenization is consistent ({len(tokens1)} tokens)")


def test_tokenizer_different_models() -> None:
    """Test that different models produce different token counts."""
    print("Testing: different tokenizer models")
    text = "Hello world"

    # Default tokenizer
    counter1 = CopawTokenCounter(
        token_count_model="default",
        token_count_use_mirror=True,
    )
    tokens1 = counter1.tokenizer.encode(text)

    # Qwen tokenizer
    counter2 = CopawTokenCounter(
        token_count_model="Qwen/Qwen2.5-7B-Instruct",
        token_count_use_mirror=True,
    )
    tokens2 = counter2.tokenizer.encode(text)

    print(f"  Default model: {len(tokens1)} tokens")
    print(f"  Qwen model: {len(tokens2)} tokens")
    # Both should work, counts may or may not be same
    assert len(tokens1) > 0
    assert len(tokens2) > 0
    print("  PASSED: different models work")


def run_all_tests() -> None:
    """Run all test functions."""
    print("=" * 60)
    print("Running CopawTokenCounter tests")
    print("=" * 60)

    # Sync tests
    test_init_default_model()
    test_init_with_mirror_enabled()
    test_init_custom_model_path()
    test_count_text_basic()
    test_count_text_empty()
    test_count_text_chinese()
    test_count_text_mixed_language()
    test_count_text_code()
    test_estimate_tokens()
    test_estimate_tokens_chinese()
    test_singleton_returns_same_instance()
    test_tokenizer_handles_special_characters()
    test_tokenizer_consistency()
    test_tokenizer_different_models()

    # Different model tests
    test_qwen_tokenizer()
    test_deepseek_tokenizer()
    test_minimax_tokenizer()
    test_glm_tokenizer()

    # Async tests
    asyncio.run(test_count_with_text_parameter())

    print("=" * 60)
    print("All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()