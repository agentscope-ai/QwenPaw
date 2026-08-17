# -*- coding: utf-8 -*-
"""Tests for visual_model_service fallback, caching, and fail-fast policy."""

# pylint: disable=protected-access
from types import SimpleNamespace

import pytest
from agentscope.message import DataBlock, Msg, TextBlock, URLSource
from agentscope.model import ChatResponse

from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.providers import visual_model_service as vms

_HINT = (
    "[Note: the current model does not support multimodal input — "
    "you cannot see this image, but it has been shown to the user. "
    "Inform the user that you cannot analyze the image content.]"
)
_SLOT = ModelSlotConfig(provider_id="dashscope", model="qwen-vl")


@pytest.fixture(autouse=True)
def _clear_transcription_caches() -> None:
    vms._TX_CACHE.clear()
    vms._TX_FAIL_CACHE.clear()


def _image_block(url: str = "https://example.com/demo.png") -> DataBlock:
    return DataBlock(source=URLSource(url=url, media_type="image/png"))


def _tool_result(output: list) -> SimpleNamespace:
    return SimpleNamespace(
        type="tool_result",
        id="call_1",
        name="view_image",
        output=output,
    )


def _running(**overrides: float | int) -> SimpleNamespace:
    values = {
        "llm_backoff_base": 1.0,
        "llm_backoff_cap": 30.0,
        "llm_max_concurrent": 5,
        "llm_max_qpm": 60,
        "llm_rate_limit_pause": 10.0,
        "llm_rate_limit_jitter": 2.0,
        "llm_acquire_timeout": 120.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_is_multimodal_fallback_hint_matches_main_text() -> None:
    assert vms._is_multimodal_fallback_hint(
        TextBlock(type="text", text=_HINT),
    )
    assert not vms._is_multimodal_fallback_hint(
        TextBlock(type="text", text="Image loaded: demo.png"),
    )
    assert not vms._is_multimodal_fallback_hint(_image_block())


def test_default_prompt_constrains_final_description_length() -> None:
    prompt = vms._DEFAULT_PROMPT.lower()
    assert "150 words" in prompt
    assert "only the description" in prompt


def test_retry_configs_are_fail_fast_and_preserve_rate_limits() -> None:
    retry, rate = vms._retry_configs_from_running(_running())
    assert retry.enabled is True
    assert retry.max_retries == 1
    assert retry.backoff_base == 1.0
    assert retry.backoff_cap == 30.0
    assert rate.max_concurrent == 5
    assert rate.max_qpm == 60
    assert rate.pause_seconds == 10.0
    assert rate.jitter_range == 2.0
    assert rate.acquire_timeout == 20.0


def test_retry_configs_keep_lower_acquire_timeout() -> None:
    _, rate = vms._retry_configs_from_running(
        _running(llm_acquire_timeout=15.0),
    )
    assert rate.acquire_timeout == 15.0


def test_wrap_visual_chat_model_preserves_thinking_and_max_tokens() -> None:
    params = SimpleNamespace(max_tokens=4096, thinking_enable=True)
    chat_model = SimpleNamespace(
        max_retries=3,
        parameters=params,
        _provider_id=None,
    )
    wrapped = vms._wrap_visual_chat_model(
        chat_model,
        "dashscope",
        running=_running(),
    )
    assert chat_model.parameters.max_tokens == 4096
    assert chat_model.parameters.thinking_enable is True
    assert chat_model.max_retries == 0
    assert chat_model._provider_id == "dashscope"
    assert wrapped._retry_config.max_retries == 1
    assert wrapped._rate_limit_config.acquire_timeout == 20.0


@pytest.mark.asyncio
async def test_apply_visual_fallback_skips_media_scan_for_multimodal(
    monkeypatch,
) -> None:
    scanned = {"called": False}

    def _boom(_msg: object) -> bool:
        scanned["called"] = True
        raise AssertionError("media scan should be skipped")

    monkeypatch.setattr(
        "qwenpaw.agents.prompt.get_active_model_supports_multimodal",
        lambda: True,
    )
    monkeypatch.setattr(vms, "_msg_has_media", _boom)

    msgs = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="hello")],
        ),
    ]
    assert await vms.apply_visual_fallback_to_messages(msgs) is msgs
    assert scanned["called"] is False


@pytest.mark.asyncio
async def test_rewrite_removes_hint_when_transcription_succeeds(
    monkeypatch,
) -> None:
    async def _fake_transcribe(*_args, **_kwargs):
        return "a cat on a sofa"

    monkeypatch.setattr(vms, "_transcribe", _fake_transcribe)

    content = [
        _tool_result(
            [
                _image_block(),
                TextBlock(type="text", text=_HINT),
            ],
        ),
    ]
    rewritten = await vms._rewrite_content(content, _SLOT)
    output = rewritten[0].output
    assert len(output) == 1
    assert output[0].type == "text"
    assert "Image description: a cat on a sofa" in output[0].text
    assert not any(vms._is_multimodal_fallback_hint(item) for item in output)


@pytest.mark.asyncio
async def test_rewrite_keeps_media_and_hint_when_transcription_fails(
    monkeypatch,
) -> None:
    async def _fake_transcribe(*_args, **_kwargs):
        return None

    monkeypatch.setattr(vms, "_transcribe", _fake_transcribe)

    media = _image_block()
    hint = TextBlock(type="text", text=_HINT)
    content = [_tool_result([media, hint])]
    rewritten = await vms._rewrite_content(content, _SLOT)
    output = rewritten[0].output
    assert len(output) == 2
    assert output[0] is media
    assert output[1] is hint


@pytest.mark.asyncio
async def test_rewrite_keeps_ordinary_text_when_transcription_succeeds(
    monkeypatch,
) -> None:
    async def _fake_transcribe(*_args, **_kwargs):
        return "sunset over the ocean"

    monkeypatch.setattr(vms, "_transcribe", _fake_transcribe)

    ordinary = TextBlock(type="text", text="Image loaded: demo.png")
    content = [_tool_result([_image_block(), ordinary])]
    rewritten = await vms._rewrite_content(content, _SLOT)
    output = rewritten[0].output
    assert len(output) == 2
    assert "Image description: sunset over the ocean" in output[0].text
    assert output[1].text == "Image loaded: demo.png"


def _patch_provider(monkeypatch, chat_callable) -> None:
    class _ChatModel:
        max_retries = 3
        _provider_id = None

        async def __call__(self, messages):
            return await chat_callable(messages)

    chat_model = _ChatModel()

    class _Provider:
        def get_chat_model_instance(self, _model: str):
            return chat_model

    class _Manager:
        @staticmethod
        def get_instance():
            return _Manager()

        def get_provider(self, _provider_id: str):
            return _Provider()

    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager",
        _Manager,
    )
    monkeypatch.setattr(
        vms,
        "_wrap_visual_chat_model",
        lambda model, _pid, running=None: model,
    )
    monkeypatch.setattr(vms, "_record_visual_usage", lambda *_a, **_k: None)


@pytest.mark.asyncio
async def test_failure_negative_cache_skips_repeat_calls(monkeypatch) -> None:
    calls = {"n": 0}

    async def _fail(_messages):
        calls["n"] += 1
        raise RuntimeError("visual unavailable")

    _patch_provider(monkeypatch, _fail)
    source = {"type": "url", "url": "https://example.com/a.png"}

    assert await vms._transcribe(source, _SLOT, "image") is None
    assert await vms._transcribe(source, _SLOT, "image") is None
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_failure_negative_cache_expires_after_ttl(monkeypatch) -> None:
    calls = {"n": 0}
    now = {"t": 1000.0}

    async def _fail(_messages):
        calls["n"] += 1
        raise RuntimeError("visual unavailable")

    _patch_provider(monkeypatch, _fail)
    monkeypatch.setattr(vms.time, "monotonic", lambda: now["t"])
    source = {"type": "url", "url": "https://example.com/b.png"}

    assert await vms._transcribe(source, _SLOT, "image") is None
    assert calls["n"] == 1

    now["t"] += vms._TX_FAIL_TTL_SECONDS + 0.1
    assert await vms._transcribe(source, _SLOT, "image") is None
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_success_clears_failure_negative_cache(monkeypatch) -> None:
    calls = {"n": 0}
    now = {"t": 1000.0}

    async def _chat(_messages):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("temporary failure")
        return ChatResponse(
            content=[TextBlock(type="text", text="a red balloon")],
            is_last=True,
        )

    _patch_provider(monkeypatch, _chat)
    monkeypatch.setattr(vms.time, "monotonic", lambda: now["t"])
    source = {"type": "url", "url": "https://example.com/c.png"}
    cache_key = vms._cache_key(_SLOT, source, "image")

    assert await vms._transcribe(source, _SLOT, "image") is None
    assert cache_key in vms._TX_FAIL_CACHE

    # Expire the negative cache so the next call can succeed and clear it.
    now["t"] += vms._TX_FAIL_TTL_SECONDS + 0.1
    text = await vms._transcribe(source, _SLOT, "image")
    assert text == "a red balloon"
    assert cache_key not in vms._TX_FAIL_CACHE
    assert cache_key in vms._TX_CACHE

    # Cached success must not re-call the model.
    assert await vms._transcribe(source, _SLOT, "image") == "a red balloon"
    assert calls["n"] == 2
