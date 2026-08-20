# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
from __future__ import annotations

import asyncio
import io

import pytest
from PIL import Image

from models import config as model_config
from models import video_model
from models.video_capabilities import video_reference_capability
from utils.exceptions import ModelError


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 8), color="red").save(output, format="PNG")
    return output.getvalue()


@pytest.mark.parametrize(
    ("model_name", "expected"),
    [
        ("happyhorse-1.1-r2v", (9, 0, 9)),
        ("wan2.7-r2v-2026-06-12", (5, 5, 5)),
        ("wan2.6-r2v-flash", (5, 3, 5)),
        ("doubao-seedance-2.0-pro", (9, 3, 12)),
    ],
)
def test_video_reference_capabilities_follow_official_model_limits(
    model_name,
    expected,
) -> None:
    capability = video_reference_capability(model_name)

    assert capability is not None
    assert (
        capability.max_reference_images,
        capability.max_reference_videos,
        capability.max_reference_media,
    ) == expected
    assert capability.documentation_url.startswith("https://")

    assert video_reference_capability("") is None
    assert video_reference_capability("private-video-gateway") is None
    assert video_reference_capability("wan2.8-r2v") is None


@pytest.mark.parametrize(
    ("model_name", "backend", "references", "message"),
    [
        (
            "wan2.7-r2v",
            "wan",
            [f"https://cdn.test/image-{index}.png" for index in range(6)],
            "参考图像最多 5",
        ),
        (
            "wan2.6-r2v",
            "wan",
            [f"https://cdn.test/video-{index}.mp4" for index in range(4)],
            "参考视频最多 3",
        ),
        (
            "doubao-seedance-2.0-pro",
            "seedance2",
            [f"https://cdn.test/video-{index}.mp4" for index in range(4)],
            "参考视频最多 3",
        ),
    ],
)
def test_provider_rejects_video_reference_overflow_before_upload(
    monkeypatch,
    model_name,
    backend,
    references,
    message,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: model_name,
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: backend)
    monkeypatch.setattr(model_config, "get_video_api_key", lambda: "sk-test")

    async def unexpected_upload(*_args, **_kwargs):
        raise AssertionError("reference upload must not run")

    monkeypatch.setattr(
        video_model,
        "_resolve_reference_media_url",
        unexpected_upload,
    )

    with pytest.raises(ModelError, match=message):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                reference_image_url_list=references,
            ),
        )


def test_provider_fails_closed_for_unknown_video_model_alias(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "private-video-gateway",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    monkeypatch.setattr(model_config, "get_video_api_key", lambda: "sk-test")

    with pytest.raises(ModelError, match="VIDEO_MODEL_CAPABILITY_UNKNOWN"):
        asyncio.run(
            video_model.submit_video_task(
                "prompt",
                reference_image_url="https://cdn.test/reference.png",
            ),
        )


def test_seedance_reference_media_becomes_base64_data_url(
    monkeypatch,
    tmp_path,
) -> None:
    image = tmp_path / "ref.png"
    image.write_bytes(_png_bytes())
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "seedance-2.0",
    )

    url, kind = asyncio.run(
        video_model._resolve_reference_media_url(image.as_uri(), "seedance2"),
    )

    assert url.startswith("data:image/png;base64,")
    assert kind == "image"


def test_seedance_public_reference_video_passes_through(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "seedance-2.0",
    )

    url, kind = asyncio.run(
        video_model._resolve_reference_media_url(
            "https://cdn.test/clip.mp4",
            "seedance2",
        ),
    )

    assert url == "https://cdn.test/clip.mp4"
    assert kind == "video"


def test_seedance_local_reference_video_is_rejected(
    monkeypatch,
    tmp_path,
) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"mp4")
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "seedance-2.0",
    )

    with pytest.raises(ModelError, match="public HTTP\\(S\\) URLs"):
        asyncio.run(
            video_model._resolve_reference_media_url(
                clip.as_uri(),
                "seedance2",
            ),
        )


def test_wan_reference_media_uses_dashscope_temp_upload(
    monkeypatch,
    tmp_path,
) -> None:
    image = tmp_path / "ref.png"
    image.write_bytes(_png_bytes())
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "wan2.7-r2v",
    )
    monkeypatch.setattr(model_config, "get_video_api_key", lambda: "video-key")

    observed = {}

    async def fake_upload(
        path,
        *,
        api_key: str,
        model_name: str,
        media_type: str,
    ) -> str:
        assert path.read_bytes() == _png_bytes()
        observed["call"] = (path.name, api_key, model_name, media_type)
        return "oss://dashscope-instant/ref.png"

    monkeypatch.setattr(
        video_model,
        "upload_local_file_to_dashscope_temp",
        fake_upload,
    )

    url, kind = asyncio.run(
        video_model._resolve_reference_media_url(image.as_uri(), "wan"),
    )

    assert url == "oss://dashscope-instant/ref.png"
    assert kind == "image"
    assert observed["call"] == (
        "ref.png",
        "video-key",
        "wan2.7-r2v",
        "image/png",
    )


def test_wan_local_reference_video_uploads_and_keeps_video_kind(
    monkeypatch,
    tmp_path,
) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"mp4")
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "wan2.7-r2v",
    )
    monkeypatch.setattr(model_config, "get_video_api_key", lambda: "video-key")

    async def fake_upload(path, *, api_key, model_name, media_type):
        del path, api_key, model_name, media_type
        return "oss://dashscope-instant/clip.mp4"

    monkeypatch.setattr(
        video_model,
        "upload_local_file_to_dashscope_temp",
        fake_upload,
    )

    url, kind = asyncio.run(
        video_model._resolve_reference_media_url(clip.as_uri(), "wan"),
    )

    assert url == "oss://dashscope-instant/clip.mp4"
    assert kind == "video"


def test_wan_remote_reference_streams_through_safe_temporary_file(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "wan2.7-r2v",
    )
    monkeypatch.setattr(model_config, "get_video_api_key", lambda: "video-key")
    observed = {}

    def fake_download(url, destination, *, max_bytes, timeout):
        destination.write_bytes(b"remote-video")
        observed["download"] = (url, max_bytes, timeout)
        return len(b"remote-video"), "video/mp4", url

    async def fake_upload(path, *, api_key, model_name, media_type):
        observed["upload"] = (
            path.read_bytes(),
            path.name,
            api_key,
            model_name,
            media_type,
        )
        return "oss://dashscope-instant/remote.mp4"

    monkeypatch.setattr(video_model, "safe_download_to_file", fake_download)
    monkeypatch.setattr(
        video_model,
        "upload_local_file_to_dashscope_temp",
        fake_upload,
    )

    url, kind = asyncio.run(
        video_model._resolve_reference_media_url(
            "https://public.example/remote.mp4",
            "wan",
        ),
    )

    assert url == "oss://dashscope-instant/remote.mp4"
    assert kind == "video"
    assert observed["download"][0] == "https://public.example/remote.mp4"
    assert observed["download"][1] == 1024 * 1024 * 1024
    assert observed["upload"] == (
        b"remote-video",
        "remote.mp4",
        "video-key",
        "wan2.7-r2v",
        "video/mp4",
    )
