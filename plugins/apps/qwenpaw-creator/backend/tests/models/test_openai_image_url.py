# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
"""OpenAI image provider URL construction must tolerate /v1-suffixed base URLs.

The UI saves official OpenAI endpoints as ``https://api.openai.com/v1``
(matching the connection probe, which appends ``/models/{name}``), while the
routify default carries no version segment. Both styles must resolve to a
single ``/v1/images/...`` path — never ``/v1/v1/images/...``.
"""
from __future__ import annotations

import pytest

from models.image.openai_provider import OpenAIImageModel


def _model(base_url: str) -> OpenAIImageModel:
    return OpenAIImageModel(
        model_name="gpt-image-2",
        api_key="test-key",
        base_url=base_url,
        quality="low",
        timeout=120,
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.openai.com/v1",
        "https://api.openai.com/v1/",
    ],
)
def test_v1_suffixed_base_url_is_not_duplicated(base_url: str) -> None:
    model = _model(base_url)
    assert (
        model.generation_url == "https://api.openai.com/v1/images/generations"
    )
    assert model._url(["ref.png"]) == "https://api.openai.com/v1/images/edits"


def test_versionless_base_url_gains_v1_segment() -> None:
    model = _model("https://routify.alibaba-inc.com/protocol/openai")
    assert model.generation_url == (
        "https://routify.alibaba-inc.com/protocol/openai/v1/images/generations"
    )
    assert model._url(["ref.png"]) == (
        "https://routify.alibaba-inc.com/protocol/openai/v1/images/edits"
    )
