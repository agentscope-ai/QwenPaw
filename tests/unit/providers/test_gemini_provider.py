# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
from __future__ import annotations

from types import SimpleNamespace

from google.genai import errors as genai_errors

from copaw.providers.gemini_provider import GeminiProvider


def _make_provider() -> GeminiProvider:
    return GeminiProvider(
        id="gemini",
        name="Gemini",
        base_url="https://generativelanguage.googleapis.com",
        api_key="gem-test",
        chat_model="GeminiChatModel",
    )


class _AsyncIter:
    """Helper that turns a list into an async iterator."""

    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


# -- check_connection --------------------------------------------------------


async def test_check_connection_success(monkeypatch) -> None:
    provider = _make_provider()

    class FakeModels:
        async def list(self):
            return _AsyncIter(
                [SimpleNamespace(name="models/gemini-2.5-flash")],
            )

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    ok, msg = await provider.check_connection(timeout=2.0)

    assert ok is True
    assert msg == ""


async def test_check_connection_api_error_returns_false(monkeypatch) -> None:
    provider = _make_provider()

    class FakeModels:
        async def list(self):
            raise genai_errors.APIError(403, {"error": "forbidden"})

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    ok, msg = await provider.check_connection(timeout=1.0)

    assert ok is False
    assert "Failed to connect to Google Gemini API" in msg


async def test_check_connection_generic_exception_returns_false(
    monkeypatch,
) -> None:
    provider = _make_provider()

    class FakeModels:
        async def list(self):
            raise ConnectionError("DNS resolution failed")

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    ok, msg = await provider.check_connection(timeout=1.0)

    assert ok is False
    assert "Unknown exception" in msg


# -- fetch_models ------------------------------------------------------------


async def test_fetch_models_normalizes_and_deduplicates(monkeypatch) -> None:
    provider = _make_provider()
    rows = [
        SimpleNamespace(
            name="models/gemini-2.5-flash",
            display_name="Gemini 2.5 Flash",
        ),
        SimpleNamespace(
            name="models/gemini-2.5-flash",
            display_name="duplicate",
        ),
        SimpleNamespace(
            name="models/gemini-2.5-pro",
            display_name="",
        ),
        SimpleNamespace(name="   ", display_name="invalid"),
    ]

    class FakeModels:
        async def list(self):
            return _AsyncIter(rows)

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    models = await provider.fetch_models(timeout=3.0)

    assert [m.id for m in models] == ["gemini-2.5-flash", "gemini-2.5-pro"]
    assert [m.name for m in models] == ["Gemini 2.5 Flash", "gemini-2.5-pro"]
    assert provider.models == []


async def test_fetch_models_api_error_returns_empty(monkeypatch) -> None:
    provider = _make_provider()

    class FakeModels:
        async def list(self):
            raise genai_errors.APIError(500, {"error": "internal"})

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    models = await provider.fetch_models(timeout=3.0)

    assert models == []


async def test_fetch_models_generic_exception_returns_empty(
    monkeypatch,
) -> None:
    provider = _make_provider()

    class FakeModels:
        async def list(self):
            raise OSError("network unreachable")

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    models = await provider.fetch_models(timeout=3.0)

    assert models == []


# -- check_model_connection ---------------------------------------------------


async def test_check_model_connection_success(monkeypatch) -> None:
    provider = _make_provider()
    captured: list[dict] = []

    class FakeModels:
        async def generate_content_stream(self, **kwargs):
            captured.append(kwargs)
            return _AsyncIter([])

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    ok, msg = await provider.check_model_connection(
        "gemini-2.5-flash",
        timeout=4.0,
    )

    assert ok is True
    assert msg == ""
    assert len(captured) == 1
    assert captured[0]["model"] == "gemini-2.5-flash"
    assert captured[0]["contents"] == "ping"


async def test_check_model_connection_empty_model_id_returns_false() -> None:
    provider = _make_provider()

    ok, msg = await provider.check_model_connection("   ", timeout=4.0)

    assert ok is False
    assert msg == "Empty model ID"


async def test_check_model_connection_api_error_returns_false(
    monkeypatch,
) -> None:
    provider = _make_provider()

    class FakeModels:
        async def generate_content_stream(self, **kwargs):
            raise genai_errors.APIError(404, {"error": "not found"})

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    ok, msg = await provider.check_model_connection(
        "gemini-2.5-flash",
        timeout=4.0,
    )

    assert ok is False
    assert "not reachable or usable" in msg


async def test_check_model_connection_generic_exception_returns_false(
    monkeypatch,
) -> None:
    provider = _make_provider()

    class FakeModels:
        async def generate_content_stream(self, **kwargs):
            raise TimeoutError("connection timed out")

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=5: fake_client)

    ok, msg = await provider.check_model_connection(
        "gemini-2.5-flash",
        timeout=4.0,
    )

    assert ok is False
    assert "Unknown exception" in msg


# -- _normalize_models_payload ------------------------------------------------


def test_normalize_models_strips_prefix_and_deduplicates() -> None:
    rows = [
        SimpleNamespace(
            name="models/gemini-2.5-flash",
            display_name="Gemini 2.5 Flash",
        ),
        SimpleNamespace(
            name="models/gemini-2.5-flash",
            display_name="dup",
        ),
        SimpleNamespace(
            name="gemini-2.0-flash",
            display_name="No Prefix",
        ),
    ]

    models = GeminiProvider._normalize_models_payload(rows)

    assert [m.id for m in models] == ["gemini-2.5-flash", "gemini-2.0-flash"]
    assert [m.name for m in models] == [
        "Gemini 2.5 Flash",
        "No Prefix",
    ]


def test_normalize_models_empty_and_none() -> None:
    assert not GeminiProvider._normalize_models_payload(None)
    assert not GeminiProvider._normalize_models_payload([])


def test_normalize_models_display_name_with_models_prefix() -> None:
    rows = [
        SimpleNamespace(
            name="models/gemini-2.5-pro",
            display_name="models/gemini-2.5-pro",
        ),
    ]

    models = GeminiProvider._normalize_models_payload(rows)

    assert models[0].id == "gemini-2.5-pro"
    assert models[0].name == "gemini-2.5-pro"


# -- update_config ------------------------------------------------------------


async def test_update_config_updates_non_none_values() -> None:
    provider = _make_provider()

    provider.update_config(
        {
            "name": "Gemini Custom",
            "base_url": "https://new.example",
            "api_key": "gem-new",
            "chat_model": "GeminiChatModel",
            "api_key_prefix": "gem-",
            "generate_kwargs": {"temperature": 0.5},
        },
    )

    info = await provider.get_info(mock_secret=False)

    assert provider.name == "Gemini Custom"
    assert provider.api_key == "gem-new"
    assert provider.generate_kwargs == {"temperature": 0.5}
    assert info.name == "Gemini Custom"
    assert info.api_key == "gem-new"


async def test_update_config_skips_none_values() -> None:
    provider = _make_provider()

    provider.update_config(
        {
            "name": None,
            "api_key": None,
        },
    )

    assert provider.name == "Gemini"
    assert provider.api_key == "gem-test"


# -- probe_model_multimodal ---------------------------------------------------

# Valid base64 for tests (avoids decode errors with placeholder)
_VALID_IMAGE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAGUlEQVR4"
    "nGP4z8DwnxLMMGrAqAGjBgwXAwAwxP4QHCfkAAAAAABJRU5ErkJggg=="
)
_VALID_VIDEO_URL = "https://example.com/test.mp4"


def _patch_probe_constants(monkeypatch):
    """Patch probe constants for testing."""
    import copaw.providers.gemini_provider as gp_mod

    monkeypatch.setattr(gp_mod, "_PROBE_IMAGE_B64", _VALID_IMAGE_B64)
    monkeypatch.setattr(gp_mod, "_PROBE_VIDEO_URL", _VALID_VIDEO_URL)


async def test_probe_model_multimodal_both_supported(monkeypatch) -> None:
    provider = _make_provider()
    _patch_probe_constants(monkeypatch)
    captured: list[dict] = []

    class FakeModels:
        async def generate_content(self, **kwargs):
            captured.append(kwargs)
            # Image probe expects "red", video probe expects "yes"
            if len(captured) == 1:
                return SimpleNamespace(text="red")
            return SimpleNamespace(text="yes")

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=10: fake_client)

    result = await provider.probe_model_multimodal("gemini-2.5-flash")

    assert result.supports_image is True
    assert result.supports_video is True
    assert result.supports_multimodal is True
    assert len(captured) == 2
    assert captured[0]["model"] == "gemini-2.5-flash"
    assert captured[1]["model"] == "gemini-2.5-flash"


async def test_probe_image_support_api_error_400(monkeypatch) -> None:
    provider = _make_provider()
    _patch_probe_constants(monkeypatch)
    call_count = 0

    class FakeModels:
        async def generate_content(self, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Image probe → 400
                raise genai_errors.APIError(
                    400,
                    {"error": "image not supported"},
                )
            # Video probe → success
            return SimpleNamespace(text="yes")

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=10: fake_client)

    result = await provider.probe_model_multimodal("gemini-2.5-flash")

    assert result.supports_image is False
    assert result.supports_video is True
    assert result.supports_multimodal is True
    assert "Image not supported" in result.image_message


async def test_probe_video_support_api_error_400(monkeypatch) -> None:
    provider = _make_provider()
    _patch_probe_constants(monkeypatch)
    call_count = 0

    class FakeModels:
        async def generate_content(self, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Image probe → success (red)
                return SimpleNamespace(text="red")
            # Video probe → 400
            raise genai_errors.APIError(
                400,
                {"error": "video not supported"},
            )

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=10: fake_client)

    result = await provider.probe_model_multimodal("gemini-2.5-flash")

    assert result.supports_image is True
    assert result.supports_video is False
    assert result.supports_multimodal is True
    assert "Video not supported" in result.video_message


async def test_probe_both_unsupported(monkeypatch) -> None:
    provider = _make_provider()
    _patch_probe_constants(monkeypatch)

    class FakeModels:
        async def generate_content(self, **kwargs):
            raise genai_errors.APIError(
                400,
                {"error": "does not support"},
            )

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=10: fake_client)

    result = await provider.probe_model_multimodal("gemini-text-only")

    assert result.supports_image is False
    assert result.supports_video is False
    assert result.supports_multimodal is False


async def test_probe_timeout_returns_false(monkeypatch) -> None:
    provider = _make_provider()
    _patch_probe_constants(monkeypatch)

    class FakeModels:
        async def generate_content(self, **kwargs):
            raise TimeoutError("connection timed out")

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=10: fake_client)

    result = await provider.probe_model_multimodal("gemini-2.5-flash")

    assert result.supports_image is False
    assert result.supports_video is False
    assert result.supports_multimodal is False
    assert "Probe failed" in result.image_message
    assert "Probe failed" in result.video_message


async def test_probe_media_keyword_error(monkeypatch) -> None:
    provider = _make_provider()
    _patch_probe_constants(monkeypatch)

    class FakeModels:
        async def generate_content(self, **kwargs):
            raise genai_errors.APIError(
                500,
                {"error": "model does not support vision"},
            )

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=10: fake_client)

    result = await provider.probe_model_multimodal("gemini-2.5-flash")

    assert result.supports_image is False
    assert result.supports_video is False


async def test_probe_inconclusive_api_error(monkeypatch) -> None:
    """Non-400, non-media-keyword API error → inconclusive (False)."""
    provider = _make_provider()
    _patch_probe_constants(monkeypatch)

    class FakeModels:
        async def generate_content(self, **kwargs):
            raise genai_errors.APIError(
                503,
                {"error": "service unavailable"},
            )

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=FakeModels()),
    )
    monkeypatch.setattr(provider, "_client", lambda timeout=10: fake_client)

    result = await provider.probe_model_multimodal("gemini-2.5-flash")

    assert result.supports_image is False
    assert result.supports_video is False
    assert "Probe inconclusive" in result.image_message
    assert "Probe inconclusive" in result.video_message
