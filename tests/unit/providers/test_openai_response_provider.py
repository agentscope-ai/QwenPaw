# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import time
from types import SimpleNamespace

import httpx
from agentscope.model import OpenAIResponseModel
from openai import BadRequestError

from qwenpaw.providers.multimodal_prober import _PROBE_VIDEO_URL
from qwenpaw.providers.openai_response_provider import (
    OpenAIResponseProvider,
    _extract_reasoning_text,
    _extract_response_text,
)


def _make_provider() -> OpenAIResponseProvider:
    return OpenAIResponseProvider(
        id="openai-response",
        name="OpenAI Responses",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        chat_model="OpenAIResponseModel",
    )


def _fake_response(text: str) -> SimpleNamespace:
    """Build a minimal Responses API result with one
    output_text part."""
    return SimpleNamespace(
        output=[
            SimpleNamespace(
                type="message",
                content=[
                    SimpleNamespace(
                        type="output_text",
                        text=text,
                    ),
                ],
            ),
        ],
    )


def _bad_request(message: str) -> BadRequestError:
    return BadRequestError(
        message=message,
        response=httpx.Response(
            status_code=400,
            request=httpx.Request("POST", "http://x"),
        ),
        body=None,
    )


# ------ _extract_response_text ----------------------------


def test_extract_response_text_basic() -> None:
    res = _fake_response("blue")
    assert _extract_response_text(res) == "blue"


def test_extract_response_text_prefers_output_text_attr() -> None:
    """When the SDK response has an output_text property,
    use it instead of manual traversal."""
    res = SimpleNamespace(output_text="aggregated text")
    assert _extract_response_text(res) == "aggregated text"


def test_extract_reasoning_text() -> None:
    res = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="reasoning",
                summary=[
                    SimpleNamespace(text="thinking about"),
                    SimpleNamespace(text="red color"),
                ],
            ),
        ],
    )
    assert _extract_reasoning_text(res) == "thinking about red color"


# ------ _probe_image_support -----------------------------


async def test_image_probe_uses_responses_api(
    monkeypatch,
) -> None:
    """Ensure image probe calls responses.create with
    input_image."""
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return _fake_response("red")

    provider = _make_provider()
    mock_client = SimpleNamespace(
        responses=SimpleNamespace(create=fake_create),
    )
    monkeypatch.setattr(
        provider,
        "_client",
        lambda **_kw: mock_client,
    )

    ok, msg = await provider._probe_image_support("test-model")

    assert ok is True
    assert "red" in msg.lower()

    inp = captured["input"]
    assert inp[0]["role"] == "user"
    types = [c["type"] for c in inp[0]["content"]]
    assert "input_image" in types
    assert "input_text" in types
    assert "max_output_tokens" in captured


async def test_image_probe_400_returns_not_supported(
    monkeypatch,
) -> None:
    """A 400 from responses.create means image not supported."""
    provider = _make_provider()

    async def fake_create(**_kwargs):
        raise _bad_request("image not supported")

    mock_client = SimpleNamespace(
        responses=SimpleNamespace(create=fake_create),
    )
    monkeypatch.setattr(
        provider,
        "_client",
        lambda **_kw: mock_client,
    )

    ok, msg = await provider._probe_image_support("test-model")
    assert ok is False
    assert "not supported" in msg.lower()


async def test_image_probe_reasoning_fallback(
    monkeypatch,
) -> None:
    """When answer is empty but reasoning mentions 'red',
    the evaluator still detects support."""
    provider = _make_provider()

    async def fake_create(**_kwargs):
        return SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="reasoning",
                    summary=[
                        SimpleNamespace(
                            text="The image shows a red square",
                        ),
                    ],
                ),
            ],
        )

    mock_client = SimpleNamespace(
        responses=SimpleNamespace(create=fake_create),
    )
    monkeypatch.setattr(
        provider,
        "_client",
        lambda **_kw: mock_client,
    )

    ok, msg = await provider._probe_image_support("test-model")
    assert ok is True
    assert "reasoning" in msg.lower()


# ------ _try_video_url -----------------------------------


async def test_video_probe_uses_responses_api(
    monkeypatch,
) -> None:
    """Ensure video probe calls responses.create with
    input_video."""
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return _fake_response("blue")

    provider = _make_provider()
    mock_client = SimpleNamespace(
        responses=SimpleNamespace(create=fake_create),
    )
    monkeypatch.setattr(
        provider,
        "_client",
        lambda **_kw: mock_client,
    )

    result = await provider._try_video_url(
        "test-model",
        "data:video/mp4;base64,AAAA",
        timeout=10,
        start_time=time.monotonic(),
    )

    assert result is not None
    ok, msg = result
    assert ok is True
    assert "blue" in msg.lower()

    inp = captured["input"]
    types = [c["type"] for c in inp[0]["content"]]
    assert "input_video" in types
    assert "input_text" in types


async def test_video_probe_400_returns_none(
    monkeypatch,
) -> None:
    """A 400 means this video format was rejected; return
    None so the caller tries the next format."""
    provider = _make_provider()

    async def fake_create(**_kwargs):
        raise _bad_request("video too short")

    mock_client = SimpleNamespace(
        responses=SimpleNamespace(create=fake_create),
    )
    monkeypatch.setattr(
        provider,
        "_client",
        lambda **_kw: mock_client,
    )

    result = await provider._try_video_url(
        "test-model",
        "data:video/mp4;base64,AAAA",
        timeout=10,
        start_time=time.monotonic(),
    )
    assert result is None


async def test_video_probe_no_color_match(
    monkeypatch,
) -> None:
    """Model returns non-blue answer -> not supported."""

    async def fake_create(**_kwargs):
        return _fake_response("I cannot see any video")

    provider = _make_provider()
    mock_client = SimpleNamespace(
        responses=SimpleNamespace(create=fake_create),
    )
    monkeypatch.setattr(
        provider,
        "_client",
        lambda **_kw: mock_client,
    )

    result = await provider._try_video_url(
        "test-model",
        "data:video/mp4;base64,AAAA",
        timeout=10,
        start_time=time.monotonic(),
    )

    assert result is not None
    ok, _ = result
    assert ok is False


async def test_video_probe_http_fallback_accepts_any(
    monkeypatch,
) -> None:
    """When using the HTTP probe URL, any non-empty answer
    is accepted as evidence of video support."""

    async def fake_create(**_kwargs):
        return _fake_response("something unrelated")

    provider = _make_provider()
    mock_client = SimpleNamespace(
        responses=SimpleNamespace(create=fake_create),
    )
    monkeypatch.setattr(
        provider,
        "_client",
        lambda **_kw: mock_client,
    )

    result = await provider._try_video_url(
        "test-model",
        _PROBE_VIDEO_URL,
        timeout=10,
        start_time=time.monotonic(),
    )

    assert result is not None
    ok, msg = result
    assert ok is True
    assert "http" in msg.lower()


async def test_video_probe_reasoning_fallback(
    monkeypatch,
) -> None:
    """When answer is empty but reasoning mentions 'blue',
    the evaluator still detects support."""
    provider = _make_provider()

    async def fake_create(**_kwargs):
        return SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="reasoning",
                    summary=[
                        SimpleNamespace(
                            text="The video is blue",
                        ),
                    ],
                ),
            ],
        )

    mock_client = SimpleNamespace(
        responses=SimpleNamespace(create=fake_create),
    )
    monkeypatch.setattr(
        provider,
        "_client",
        lambda **_kw: mock_client,
    )

    result = await provider._try_video_url(
        "test-model",
        "data:video/mp4;base64,AAAA",
        timeout=10,
        start_time=time.monotonic(),
    )

    assert result is not None
    ok, msg = result
    assert ok is True
    assert "reasoning" in msg.lower()


# ------ existing test -----------------------------------


async def test_summary_limit_is_adapted_for_responses_api(
    monkeypatch,
) -> None:
    captured: dict = {}

    async def fake_call_api(self, *args, **kwargs):
        del self, args
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(
        OpenAIResponseModel,
        "_call_api",
        fake_call_api,
    )
    provider = _make_provider()
    model = provider.get_chat_model_instance("gpt-5")

    result = await model._call_api(
        "gpt-5",
        [],
        max_tokens=256,
        disable_thinking=True,
    )

    assert result == "ok"
    assert captured["max_output_tokens"] == 256
    assert "max_tokens" not in captured
