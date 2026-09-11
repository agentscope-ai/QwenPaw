# -*- coding: utf-8 -*-
"""Anthropic video inputs fail closed before media IO or provider calls."""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio

import pytest

from models import vlm_model
from utils.exceptions import ModelError

pytestmark = pytest.mark.unit


def _video_content(url: str) -> list[dict]:
    return [
        {"type": "video_url", "video_url": {"url": url}},
        {"type": "text", "text": "What happens in this video?"},
    ]


def test_anthropic_caller_rejects_video_before_io_or_http(
    monkeypatch,
) -> None:
    def unexpected_inline(*_args, **_kwargs):
        raise AssertionError("video bytes must not be read")

    class UnexpectedClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("provider must not be called")

    monkeypatch.setattr(vlm_model, "_inline_base64", unexpected_inline)
    monkeypatch.setattr(vlm_model.httpx, "AsyncClient", UnexpectedClient)

    with pytest.raises(ModelError, match="does not support video") as caught:
        asyncio.run(
            vlm_model._call_anthropic_vlm(
                _video_content("file:///tmp/clip.mp4"),
                system_prompt="",
                temperature=0.2,
                max_tokens=100,
                timeout=5.0,
                api_key="test-key",
                base_url="https://api.anthropic.com",
                model_name="claude-test",
            ),
        )

    assert caught.value.retryable is False
