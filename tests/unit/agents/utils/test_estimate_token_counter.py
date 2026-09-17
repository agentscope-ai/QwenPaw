# -*- coding: utf-8 -*-
"""Tests for qwenpaw.agents.utils.estimate_token_counter."""
# pylint: disable=protected-access

import pytest

from qwenpaw.agents.utils.estimate_token_counter import (
    EstimatedTokenCounter,
)


class TestEstimatedTokenCounterInit:
    """Tests for EstimatedTokenCounter.__init__."""

    def test_default_divisor(self):
        counter = EstimatedTokenCounter()
        assert counter.estimate_divisor == 4.0

    def test_custom_divisor(self):
        counter = EstimatedTokenCounter(estimate_divisor=2.0)
        assert counter.estimate_divisor == 2.0

    def test_zero_divisor_raises(self):
        with pytest.raises(ValueError, match="cannot be zero"):
            EstimatedTokenCounter(estimate_divisor=0)

    def test_negative_divisor_raises(self):
        with pytest.raises(ValueError, match="cannot be zero"):
            EstimatedTokenCounter(estimate_divisor=-1)


class TestEstimatedTokenCounterCount:
    """Tests for EstimatedTokenCounter.count."""

    @pytest.mark.asyncio
    async def test_empty_string(self):
        counter = EstimatedTokenCounter()
        result = await counter.count("")
        assert result == 0

    @pytest.mark.asyncio
    async def test_ascii_text(self):
        counter = EstimatedTokenCounter(estimate_divisor=4)
        # "hello" = 5 bytes / 4 = 1.25 -> round(1.25) = 1
        result = await counter.count("hello")
        assert result == 1

    @pytest.mark.asyncio
    async def test_longer_text(self):
        counter = EstimatedTokenCounter(estimate_divisor=4)
        # 16 bytes / 4 = 4.0 -> round(4.0) = 4
        result = await counter.count("a" * 16)
        assert result == 4

    @pytest.mark.asyncio
    async def test_chinese_text_uses_utf8_bytes(self):
        counter = EstimatedTokenCounter(estimate_divisor=2)
        # Each CJK char is 3 bytes in UTF-8
        text = "你好"  # 6 bytes
        result = await counter.count(text)
        # 6 / 2 = 3.0 -> round(3.0) = 3
        assert result == 3

    @pytest.mark.asyncio
    async def test_custom_divisor_affects_count(self):
        text = "test text here"
        counter_d4 = EstimatedTokenCounter(estimate_divisor=4)
        counter_d2 = EstimatedTokenCounter(estimate_divisor=2)
        r4 = await counter_d4.count(text)
        r2 = await counter_d2.count(text)
        assert r2 > r4

    @pytest.mark.asyncio
    async def test_kwargs_ignored(self):
        counter = EstimatedTokenCounter()
        result = await counter.count("hello", extra_arg="ignored")
        assert result > 0
