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

import asyncio

import pytest

from models.image.openai_provider import (
    OpenAIImageModel,
    build_reference_image_files,
)


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


def test_reference_files_use_the_array_field_for_multiple_images(
    tmp_path,
) -> None:
    """Two or more references upload as image[]; a single one stays image.

    The provider gateway now enforces the Images edits contract and
    rejects a repeated bare ``image`` field with 400 "Duplicate
    parameter: 'image'" (nine consecutive storyboard failures observed
    in production).
    """

    first = tmp_path / "ref-a.png"
    second = tmp_path / "ref-b.png"
    first.write_bytes(b"\x89PNG\r\n\x1a\na")
    second.write_bytes(b"\x89PNG\r\n\x1a\nb")

    multiple = asyncio.run(
        build_reference_image_files(
            [first.as_uri(), second.as_uri(), first.as_uri(), " "],
        ),
    )
    assert [name for name, _ in multiple] == ["image[]", "image[]"]

    single = asyncio.run(build_reference_image_files([first.as_uri()]))
    assert [name for name, _ in single] == ["image"]
