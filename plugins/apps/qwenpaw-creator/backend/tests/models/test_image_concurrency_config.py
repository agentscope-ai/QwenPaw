# -*- coding: utf-8 -*-
from __future__ import annotations

from models import config as model_config
from models.image.dashscope_provider import DashScopeImageModel
from models.image.openai_provider import OpenAIImageModel


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


def test_unconfigured_concurrency_follows_the_scheduler_dispatch_cap(
    monkeypatch,
) -> None:
    """The provider semaphore must not default below media_parallelism.

    A silent 1-slot default serialized renders behind model_slot("image")
    while the work graph showed parallel RUNNING nodes (field runs
    2026-08-06/07); the fix couples the default to the scheduler's cap.
    """

    for name in (
        "DASHSCOPE_IMAGE_CONCURRENCY",
        "OPENAI_IMAGE_CONCURRENCY",
        "IMAGE_CONCURRENCY",
    ):
        monkeypatch.delenv(name, raising=False)
    expected = model_config.get_media_parallelism()
    assert expected >= 5  # the new dispatch-cap default
    assert DashScopeImageModel.from_config().concurrency == expected
    assert OpenAIImageModel.from_config().concurrency == expected
