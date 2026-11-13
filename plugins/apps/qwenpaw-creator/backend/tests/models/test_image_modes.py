# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,unused-argument
"""qwen-image mode semantics: generate / edit / translate.

All provider HTTP traffic is stubbed (respx); no real model is ever called.
"""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import respx

from models import config as model_config
from models.image import dashscope_provider
from models.image.base import image_reference_capability, image_reference_limit
from models.image.dashscope_provider import DashScopeImageModel
from models.image.openai_provider import OpenAIImageModel
from utils.exceptions import ModelError

_BASE_URL = "https://dashscope.test/api/v1/services/aigc/multimodal-generation/generation"
_TRANSLATE_URL = (
    "https://dashscope.test/api/v1/services/aigc/image2image/image-synthesis"
)


def _dashscope_model() -> DashScopeImageModel:
    return DashScopeImageModel(
        model_name="qwen-image-2.0-pro",
        api_key="sk-test",
        base_url=_BASE_URL,
        timeout=30,
    )


def _openai_model() -> OpenAIImageModel:
    return OpenAIImageModel(
        model_name="gpt-image-2",
        api_key="sk-test",
        base_url="https://openai.test/v1",
        quality="low",
        timeout=30,
    )


@contextmanager
def _tool_configs(configs: dict | None = None):
    token = model_config.set_request_tool_configs(configs or {})
    try:
        yield
    finally:
        model_config.reset_request_tool_configs(token)


def _run_translate(**kwargs) -> str:
    with _tool_configs():
        return asyncio.run(
            _dashscope_model().generate(
                "translate",
                mode="translate",
                reference_image_urls=["https://cdn.test/poster.png"],
                **kwargs,
            ),
        )


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ModelError, match="Unknown image mode"):
        asyncio.run(_dashscope_model().generate("cat", mode="remix"))


def test_mode_reference_count_validation() -> None:
    model = _dashscope_model()
    with pytest.raises(ModelError, match="1-3 reference images"):
        asyncio.run(model.generate("make it red", mode="edit"))
    with pytest.raises(ModelError, match="exactly 1 reference image"):
        asyncio.run(model.generate("translate", mode="translate"))


def test_openai_provider_rejects_edit_and_translate() -> None:
    model = _openai_model()
    for mode in ("edit", "translate"):
        with pytest.raises(ModelError, match="does not support"):
            asyncio.run(
                model.generate(
                    "poster",
                    mode=mode,
                    reference_image_urls=["https://cdn.test/poster.png"],
                ),
            )


def test_edit_body_keeps_images_first_and_disables_watermark() -> None:
    body = asyncio.run(
        _dashscope_model()._build_body(
            "convert to watercolor style",
            "16:9",
            ["https://cdn.test/a.png", "https://cdn.test/b.png"],
        ),
    )
    assert body["model"] == "qwen-image-2.0-pro"
    assert body["input"]["messages"][0]["content"] == [
        {"image": "https://cdn.test/a.png"},
        {"image": "https://cdn.test/b.png"},
        {"text": "convert to watercolor style"},
    ]
    assert body["parameters"] == {"size": "1664*928", "watermark": False}


def test_token_plan_reference_inlines_base64_not_upload(
    tmp_path,
    monkeypatch,
) -> None:
    """A Token Plan endpoint has no upload route: the public dashscope
    uploads answer its sk-sp- key 401 and the token-plan host serves no
    /api/v1/uploads, so a local reference is inlined as a Base64 data URL
    (which the multimodal-generation endpoint accepts) instead of uploaded.
    """
    from PIL import Image

    async def refuse_upload(*args, **kwargs):
        raise AssertionError("Token Plan reference reached the upload API")

    monkeypatch.setattr(
        dashscope_provider,
        "upload_reference_bytes_to_dashscope_temp",
        refuse_upload,
    )
    reference = tmp_path / "ref.png"
    Image.new("RGB", (8, 8), "red").save(reference, format="PNG")
    model = DashScopeImageModel(
        model_name="qwen-image-2.0-pro",
        api_key="sk-sp-test",
        base_url="https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1",
        timeout=30,
    )
    resolved = asyncio.run(model._public_reference_url(reference.as_uri()))
    assert resolved.startswith("data:image/png;base64,")


def _token_plan_image_model() -> DashScopeImageModel:
    return DashScopeImageModel(
        model_name="qwen-image-2.0-pro",
        api_key="sk-sp-test",
        base_url="https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1",
        timeout=30,
    )


def _noise_png_bytes() -> bytes:
    """Deterministic noise PNG: ~31KB raw, ~11KB as an optimised JPEG.

    The gap lets a test put the inline ceiling between the two, so the
    downscale path is exercised without building a 7MB fixture.
    """
    import io

    from PIL import Image

    output = io.BytesIO()
    Image.effect_noise((128, 128), 128).convert("RGB").save(
        output,
        format="PNG",
    )
    return output.getvalue()


def test_token_plan_reference_over_inline_ceiling_errors(
    tmp_path,
    monkeypatch,
) -> None:
    """A generate reference that cannot shrink under the 7MB Base64 ceiling
    fails with guidance rather than sending a doomed upload, and fails fast:
    the ceiling is a provider constant, so retrying cannot help."""
    from PIL import Image

    async def refuse_upload(*args, **kwargs):
        raise AssertionError("Token Plan reference reached the upload API")

    monkeypatch.setattr(
        dashscope_provider,
        "upload_reference_bytes_to_dashscope_temp",
        refuse_upload,
    )
    # Force the tiny test image over the ceiling without building a 7MB file.
    # 16 bytes is below even the smallest ladder rung, so no downscale can
    # rescue it and the refusal path is what runs.
    monkeypatch.setattr(
        dashscope_provider,
        "TOKEN_PLAN_INLINE_IMAGE_MAX_BYTES",
        16,
    )
    reference = tmp_path / "big.png"
    Image.new("RGB", (8, 8), "red").save(reference, format="PNG")
    model = _token_plan_image_model()
    with pytest.raises(ModelError, match="7MB") as excinfo:
        asyncio.run(model._public_reference_url(reference.as_uri()))
    assert excinfo.value.retryable is False


def test_token_plan_generate_reference_downscales_under_ceiling(
    tmp_path,
    monkeypatch,
) -> None:
    """A generate reference only carries subject and style, so shrinking it
    beats failing a request the provider could have served.

    The re-encoded payload is JPEG whatever the source was, so the data URL
    must not keep the source's PNG MIME: ``reference_media_data_url`` reads
    the type from the filename suffix first.
    """
    import base64

    async def refuse_upload(*args, **kwargs):
        raise AssertionError("Token Plan reference reached the upload API")

    monkeypatch.setattr(
        dashscope_provider,
        "upload_reference_bytes_to_dashscope_temp",
        refuse_upload,
    )
    monkeypatch.setattr(
        dashscope_provider,
        "TOKEN_PLAN_INLINE_IMAGE_MAX_BYTES",
        20_000,
    )
    raw = _noise_png_bytes()
    reference = tmp_path / "big.png"
    reference.write_bytes(raw)
    assert len(raw) > 20_000

    model = _token_plan_image_model()
    resolved = asyncio.run(model._public_reference_url(reference.as_uri()))

    assert resolved.startswith("data:image/jpeg;base64,")
    payload = base64.b64decode(resolved.split(",", 1)[1])
    assert len(payload) <= 20_000
    assert len(payload) < len(raw)


@pytest.mark.parametrize("mode", ["edit", "translate"])
def test_token_plan_edit_and_translate_references_never_downscale(
    tmp_path,
    monkeypatch,
    mode,
) -> None:
    """An edit/translate reference *is* the canvas the instruction operates
    on, so its pixels are never silently resampled even when the ladder
    could fit them: the request fails fast with guidance instead."""

    async def refuse_upload(*args, **kwargs):
        raise AssertionError("Token Plan reference reached the upload API")

    monkeypatch.setattr(
        dashscope_provider,
        "upload_reference_bytes_to_dashscope_temp",
        refuse_upload,
    )
    # The same bytes do downscale under mode=generate (see the test above),
    # so a refusal here can only come from the mode gate.
    monkeypatch.setattr(
        dashscope_provider,
        "TOKEN_PLAN_INLINE_IMAGE_MAX_BYTES",
        20_000,
    )
    reference = tmp_path / "big.png"
    reference.write_bytes(_noise_png_bytes())

    model = _token_plan_image_model()
    with pytest.raises(ModelError, match="7MB") as excinfo:
        asyncio.run(
            model._public_reference_url(reference.as_uri(), mode=mode),
        )
    assert excinfo.value.retryable is False
    assert f"mode={mode}" in str(excinfo.value)
    assert "不会被自动" in str(excinfo.value)


@respx.mock
def test_translate_submits_async_task_polls_and_downloads_result(
    monkeypatch,
) -> None:
    monkeypatch.delenv("IMAGE_TRANSLATE_MODEL_NAME", raising=False)
    monkeypatch.setattr(
        dashscope_provider,
        "_TRANSLATE_POLL_INTERVAL_SECONDS",
        0.0,
    )
    submit_route = respx.post(_TRANSLATE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "output": {"task_id": "task-mt-1", "task_status": "PENDING"},
            },
        ),
    )
    respx.get("https://dashscope.test/api/v1/tasks/task-mt-1").mock(
        side_effect=[
            httpx.Response(200, json={"output": {"task_status": "RUNNING"}}),
            httpx.Response(
                200,
                json={
                    "output": {
                        "task_status": "SUCCEEDED",
                        "image_url": "https://oss.test/translated.png",
                    },
                    "request_id": "req-1",
                },
            ),
        ],
    )
    downloaded: list[str] = []

    async def fake_download(url: str, model_name: str) -> str:
        downloaded.append(url)
        assert model_name == "qwen-mt-image"
        return "/generated/translated.png"

    monkeypatch.setattr(
        dashscope_provider,
        "download_remote_image",
        fake_download,
    )

    result = _run_translate(source_lang="zh", target_lang="en")

    assert result == {"url": "/generated/translated.png", "source_url": ""}
    assert downloaded == ["https://oss.test/translated.png"]
    request = submit_route.calls.last.request
    assert request.headers["X-DashScope-Async"] == "enable"
    assert request.headers["Authorization"] == "Bearer sk-test"
    assert json.loads(request.content) == {
        "model": "qwen-mt-image",
        "input": {
            "image_url": "https://cdn.test/poster.png",
            "source_lang": "zh",
            "target_lang": "en",
            "ext": {"config": {"imageSegment": False}},
        },
    }


@pytest.mark.parametrize(
    ("model_name", "expected"),
    [
        ("wan2.7-image-pro", 9),
        ("wan2.7-image", 9),
        ("wan2.6-image", 4),
        ("z-image-turbo", 0),
        (" WAN2.7-IMAGE-PRO ", 9),
        ("wan2.7", None),
        ("wan2.7-r2v", None),
        ("wan2.7-i2v", None),
        ("wan2.7-image-pro-unknown", None),
        ("qwen-image-3.0-pro", 3),
        ("qwen-image-2.0-pro-2026-06-22", 3),
        ("qwen-image-edit-plus-2025-12-15", 3),
        ("qwen-mt-image", 1),
        ("qwen-image-plus", 0),
        ("gpt-image-2-2026-04-21", 16),
        ("gpt-image-1-mini", 16),
        ("dall-e-2", 1),
        ("dall-e-3", 0),
        ("gemini-3-pro-image", 14),
        ("gemini-3.1-flash-image", 14),
        ("gemini-2.5-flash-image", 3),
        ("doubao-seedream-5-0-pro-260628", 10),
        ("doubao-seedream-4-5-251128", 14),
        ("flux-2-pro", 8),
        ("flux-2-klein-4b", 4),
        ("flux-2-klein-9b", 4),
        ("ideogram-v3", 1),
        ("ideogram-v4", 0),
        ("gemini-42-image", None),
        ("private-gateway-alias", None),
    ],
)
def test_official_reference_limits_are_model_specific(model_name, expected):
    assert image_reference_limit(model_name) == expected
    capability = image_reference_capability(model_name)
    if expected is None:
        assert capability is None
    else:
        assert capability is not None
        assert capability.documentation_url.startswith("https://")


def test_every_ui_image_preset_has_a_reference_contract() -> None:
    """A selectable model must not fail later as an unknown capability."""
    app_root = Path(__file__).resolve().parents[3]
    source = (
        app_root / "ui/src/components/creator/ModelConfigModal.tsx"
    ).read_text(encoding="utf-8")
    presets = source.split("const IMAGE_PRESETS:", 1)[1].split(
        "const VIDEO_PRESETS:",
        1,
    )[0]
    arrays = re.findall(r"models:\s*(\[[^\]]*\])", presets)
    assert arrays, "No image presets found; update this contract test"
    model_names = set(re.findall(r'"([^"\n]+)"', "".join(arrays)))
    missing = sorted(
        name
        for name in model_names
        if image_reference_capability(name) is None
    )
    assert (
        not missing
    ), f"Image presets missing reference capabilities: {missing}"
