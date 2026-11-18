# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Local WAN references must preserve native paths and encoded filenames."""

import asyncio

import pytest

from models import media_transport, video_model


@pytest.mark.parametrize("name", ["cat.jpg", "猫咪 photo #1.jpg"])
def test_wan_upload_receives_native_file_path(tmp_path, monkeypatch, name):
    photo = tmp_path / name
    photo.write_bytes(b"photo-reference")
    monkeypatch.setattr(
        video_model.model_config,
        "get_video_model_name",
        lambda: "wan3.0-video-prime",
    )
    monkeypatch.setattr(
        video_model.model_config,
        "get_video_api_key",
        lambda: "test-key",
    )

    monkeypatch.setattr(video_model.model_config, "get_video_base_url", lambda: "https://dashscope.aliyuncs.com/api/v1")

    def upload(path, **_kwargs):
        assert path == photo
        assert path.read_bytes() == b"photo-reference"
        return "oss://test/cat.jpg"

    monkeypatch.setattr(
        media_transport,
        "_upload_local_file_to_dashscope_temp_sync",
        upload,
    )
    assert asyncio.run(
        video_model._resolve_reference_media_url(photo.as_uri(), "wan"),
    ) == (
        "oss://test/cat.jpg",
        "image",
    )
