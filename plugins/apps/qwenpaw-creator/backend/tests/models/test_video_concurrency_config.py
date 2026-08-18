# -*- coding: utf-8 -*-
from __future__ import annotations

from models import config as model_config


def test_video_concurrency_env_override_wins(monkeypatch) -> None:
    monkeypatch.setenv("VIDEO_CONCURRENCY", "2")
    assert model_config.get_video_concurrency() == 2


def test_unconfigured_video_concurrency_follows_the_scheduler_dispatch_cap(
    monkeypatch,
) -> None:
    """The video semaphore must not default below media_parallelism.

    The old module-level VIDEO_CONCURRENCY snapshot defaulted to 1,
    serializing renders behind model_slot("video") exactly like the
    image 1-slot default did; the fix couples the default to the
    scheduler's cap.
    """

    monkeypatch.delenv("VIDEO_CONCURRENCY", raising=False)
    expected = model_config.get_media_parallelism()
    assert expected >= 5  # the dispatch-cap default
    assert model_config.get_video_concurrency() == expected
