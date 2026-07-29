# -*- coding: utf-8 -*-
from __future__ import annotations

from models.image.dashscope_provider import DashScopeImageModel


def test_dashscope_image_concurrency_accepts_generic_creator_fallback(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DASHSCOPE_IMAGE_CONCURRENCY", raising=False)
    monkeypatch.setenv("IMAGE_CONCURRENCY", "10")
    assert DashScopeImageModel.from_config().concurrency == 10


def test_dashscope_specific_image_concurrency_overrides_generic_fallback(
    monkeypatch,
) -> None:
    monkeypatch.setenv("IMAGE_CONCURRENCY", "10")
    monkeypatch.setenv("DASHSCOPE_IMAGE_CONCURRENCY", "3")
    assert DashScopeImageModel.from_config().concurrency == 3
