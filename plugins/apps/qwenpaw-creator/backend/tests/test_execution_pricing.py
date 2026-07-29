# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Local spend estimates shown on execution authorization cards."""

import pytest

from services.execution_pricing import (
    estimate_execution_cost,
    estimate_image_cost,
    estimate_video_cost,
)


class TestImageCost:
    def test_dashscope_catalog_price_is_exact(self):
        estimate = estimate_image_cost(
            backend="dashscope",
            model="qwen-image-2.0-pro",
            aspect_ratio="16:9",
        )
        assert estimate.estimated_cost == 0.5
        assert estimate.currency == "CNY"
        assert not estimate.approximate
        assert "0.5元/张" in estimate.formula

    def test_dashscope_unknown_model_falls_back_approximate(self):
        estimate = estimate_image_cost(
            backend="dashscope",
            model="my-custom-image-model",
        )
        assert estimate.approximate
        assert estimate.estimated_cost == pytest.approx(0.25)
        assert estimate.notes == ("本地估算，实际费用以服务商账单为准",)

    def test_dated_snapshot_version_keeps_exact_price(self):
        estimate = estimate_image_cost(
            backend="dashscope",
            model="qwen-image-2.0-pro-2026-06-22",
        )
        assert not estimate.approximate
        assert estimate.estimated_cost == 0.5

    def test_newer_version_suffix_is_flagged_approximate(self):
        estimate = estimate_image_cost(
            backend="dashscope",
            model="qwen-image-2.0-pro-max",
        )
        assert estimate.approximate
        assert estimate.estimated_cost == 0.5
        assert estimate.notes == ("本地估算，实际费用以服务商账单为准",)

    def test_longest_prefix_wins_over_shorter_family(self):
        # qwen-image-edit must not be captured by the shorter qwen-image tier.
        estimate = estimate_image_cost(
            backend="dashscope",
            model="qwen-image-edit",
        )
        assert estimate.estimated_cost == 0.3
        assert not estimate.approximate

    def test_dashscope_free_tier_displays_free(self):
        estimate = estimate_image_cost(
            backend="dashscope",
            model="qwen-image-3.0-pro",
        )
        assert estimate.estimated_cost == 0
        assert estimate.display_text == "限时免费"

    def test_openai_quality_and_size_pricing(self):
        estimate = estimate_image_cost(
            backend="openai",
            model="gpt-image-1",
            aspect_ratio="16:9",
            quality="high",
        )
        assert estimate.currency == "USD"
        assert estimate.estimated_cost == pytest.approx(0.25)
        assert not estimate.approximate

    def test_openai_unlisted_model_is_approximate(self):
        estimate = estimate_image_cost(
            backend="openai",
            model="gpt-image-2",
            aspect_ratio="1:1",
            quality="low",
        )
        assert estimate.approximate
        assert estimate.estimated_cost == pytest.approx(0.011)


class TestVideoCost:
    def test_wan_r2v_per_second_pricing(self):
        estimate = estimate_video_cost(
            backend="wan",
            model="wan2.7-r2v",
            duration_seconds=5,
            resolution="720P",
        )
        assert estimate.currency == "CNY"
        assert estimate.estimated_cost == pytest.approx(3.0)
        assert "0.6元/秒 × 5秒" in estimate.formula
        assert not estimate.approximate

    def test_wan_flash_muted_discount(self):
        priced = estimate_video_cost(
            backend="wan",
            model="wan2.6-r2v-flash",
            duration_seconds=10,
            resolution="1080P",
            audio=False,
        )
        assert priced.estimated_cost == pytest.approx(2.5)

    def test_wan_version_variant_is_flagged_approximate(self):
        estimate = estimate_video_cost(
            backend="wan",
            model="wan2.7-r2v-turbo",
            duration_seconds=5,
            resolution="720P",
        )
        assert estimate.approximate
        assert estimate.estimated_cost == pytest.approx(3.0)
        assert estimate.notes == ("本地估算，实际费用以服务商账单为准",)

    def test_wan_dated_snapshot_keeps_exact_price(self):
        estimate = estimate_video_cost(
            backend="wan",
            model="wan2.7-r2v-2026-06-12",
            duration_seconds=5,
            resolution="720P",
        )
        assert not estimate.approximate
        assert estimate.estimated_cost == pytest.approx(3.0)

    def test_wan_unsupported_resolution_uses_top_tier(self):
        estimate = estimate_video_cost(
            backend="wan",
            model="wanx2.1-t2v-plus",
            duration_seconds=4,
            resolution="1080P",
        )
        assert estimate.approximate
        assert estimate.estimated_cost == pytest.approx(0.7 * 4)

    def test_happyhorse_r2v_catalog_price_is_exact(self):
        estimate = estimate_video_cost(
            backend="wan",
            model="happyhorse-1.1-r2v",
            duration_seconds=5,
            resolution="720P",
        )
        assert estimate.currency == "CNY"
        assert estimate.estimated_cost == pytest.approx(4.5)
        assert "0.9元/秒 × 5秒" in estimate.formula
        assert not estimate.approximate

    def test_happyhorse_1080p_tiers_differ_by_version(self):
        latest = estimate_video_cost(
            backend="wan",
            model="happyhorse-1.1-r2v",
            duration_seconds=10,
            resolution="1080P",
        )
        legacy = estimate_video_cost(
            backend="wan",
            model="happyhorse-1.0-r2v",
            duration_seconds=10,
            resolution="1080P",
        )
        assert latest.estimated_cost == pytest.approx(12.0)
        assert legacy.estimated_cost == pytest.approx(16.0)

    def test_happyhorse_has_no_muted_discount(self):
        muted = estimate_video_cost(
            backend="wan",
            model="happyhorse-1.1-r2v",
            duration_seconds=5,
            resolution="720P",
            audio=False,
        )
        assert muted.estimated_cost == pytest.approx(4.5)

    def test_seedance_token_formula(self):
        estimate = estimate_video_cost(
            backend="seedance2",
            model="doubao-seedance-2.0",
            duration_seconds=5,
            resolution="1080P",
        )
        # 1920×1080×24fps×5s ÷ 1024 = 243,000 tokens × CNY 46/million ≈ ¥11.18
        assert estimate.estimated_cost == pytest.approx(11.178, abs=0.01)
        assert "tokens" in estimate.formula
        assert estimate.notes == ("本地估算，实际费用以服务商账单为准",)
        assert not estimate.approximate

    def test_seedance_mini_uses_cheaper_tier(self):
        full = estimate_video_cost(
            backend="seedance2",
            model="doubao-seedance-2.0",
            duration_seconds=5,
            resolution="720P",
        )
        mini = estimate_video_cost(
            backend="seedance2",
            model="doubao-seedance-2.0-mini",
            duration_seconds=5,
            resolution="720P",
        )
        # Official site example: 2.0 without video input, 720P/5s ≈ CNY 4.97.
        assert full.estimated_cost == pytest.approx(4.97, abs=0.01)
        assert mini.estimated_cost == pytest.approx(
            full.estimated_cost * 23 / 46,
            abs=0.01,
        )
        assert not mini.approximate


class TestExecutionEntryPoint:
    def test_image_arguments_are_mapped(self):
        estimate = estimate_execution_cost(
            provider_kind="image",
            provider="dashscope",
            model="qwen-image-2.0-pro",
            arguments={"prompt": "一只猫", "aspectRatio": "1:1"},
        )
        assert estimate is not None
        assert estimate.estimated_cost == 0.5

    def test_video_arguments_are_mapped(self):
        estimate = estimate_execution_cost(
            provider_kind="video",
            provider="wan",
            model="wan2.7-r2v",
            arguments={
                "prompt": "海边日落",
                "durationSeconds": 8,
                "resolution": "1080p",
                "ratio": "16:9",
                "watermark": False,
            },
        )
        assert estimate is not None
        assert estimate.estimated_cost == pytest.approx(8.0)

    def test_non_media_tools_have_no_estimate(self):
        assert (
            estimate_execution_cost(
                provider_kind="local_media",
                provider="creator-tool",
                model="configured",
                arguments={},
            )
            is None
        )
