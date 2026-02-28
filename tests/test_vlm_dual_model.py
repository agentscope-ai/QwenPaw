from __future__ import annotations

import json
from pathlib import Path

import pytest

from copaw.agents.model_capabilities import supports_vision
from copaw.agents.model_capabilities import supports_input_capability
from copaw.agents.model_fallback import run_with_vlm_fallback
from copaw.providers.models import (
    ModelInfo,
    ModelSlotConfig,
    ProviderSettings,
    ResolvedModelConfig,
)
from copaw.providers.store import load_providers_json, save_providers_json
from copaw.providers.store import update_vision_audio_settings
from copaw.providers.store import update_vision_image_settings
from copaw.providers.store import update_vision_video_settings


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def test_load_providers_json_defaults_vlm_fields(tmp_path: Path) -> None:
    providers_path = tmp_path / "providers.json"
    _write_json(
        providers_path,
        {
            "providers": {},
            "custom_providers": {},
            "active_llm": {"provider_id": "", "model": ""},
        },
    )

    data = load_providers_json(path=providers_path)
    assert data.active_vlm.provider_id == ""
    assert data.active_vlm.model == ""
    assert data.active_vlm_fallbacks == []
    assert data.vision.image.enabled is True
    assert data.vision.image.attachments_mode == "first"
    assert data.vision.audio.enabled is False
    assert data.vision.video.enabled is False


def test_save_and_reload_vlm_fields(tmp_path: Path) -> None:
    providers_path = tmp_path / "providers.json"
    data = load_providers_json(path=providers_path)
    data.providers["dashscope"] = ProviderSettings(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="test-key",
    )
    data.active_vlm = ModelSlotConfig(provider_id="dashscope", model="qwen-vl-max")
    data.active_vlm_fallbacks = [
        ModelSlotConfig(provider_id="dashscope", model="qwen-vl-plus"),
    ]
    save_providers_json(data, path=providers_path)

    reloaded = load_providers_json(path=providers_path)
    assert reloaded.active_vlm.provider_id == "dashscope"
    assert reloaded.active_vlm.model == "qwen-vl-max"
    assert len(reloaded.active_vlm_fallbacks) == 1
    assert reloaded.active_vlm_fallbacks[0].model == "qwen-vl-plus"


def test_update_vision_image_settings_persists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    providers_path = tmp_path / "providers.json"

    import copaw.providers.store as store

    monkeypatch.setattr(store, "get_providers_json_path", lambda: providers_path)
    updated = update_vision_image_settings(
        enabled=False,
        attachments_mode="all",
        max_images=3,
        timeout_seconds=42,
        max_output_chars=1200,
    )
    assert updated.vision.image.enabled is False
    assert updated.vision.image.attachments_mode == "all"
    assert updated.vision.image.max_images == 3
    assert updated.vision.image.timeout_seconds == 42
    assert updated.vision.image.max_output_chars == 1200

    reloaded = load_providers_json(path=providers_path)
    assert reloaded.vision.image.enabled is False
    assert reloaded.vision.image.attachments_mode == "all"


def test_update_vision_audio_video_settings_persist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers_path = tmp_path / "providers.json"

    import copaw.providers.store as store

    monkeypatch.setattr(store, "get_providers_json_path", lambda: providers_path)
    updated = update_vision_audio_settings(
        enabled=True,
        attachments_mode="all",
        max_items=2,
    )
    assert updated.vision.audio.enabled is True
    assert updated.vision.audio.max_items == 2

    updated = update_vision_video_settings(
        enabled=True,
        attachments_mode="first",
        max_items=1,
    )
    assert updated.vision.video.enabled is True
    assert updated.vision.video.max_items == 1

    reloaded = load_providers_json(path=providers_path)
    assert reloaded.vision.audio.enabled is True
    assert reloaded.vision.video.enabled is True


@pytest.mark.asyncio
async def test_run_with_vlm_fallback_uses_next_candidate() -> None:
    primary = ResolvedModelConfig(provider_id="p1", model="m1")
    fallback = ResolvedModelConfig(provider_id="p2", model="m2")
    calls: list[str] = []

    async def _runner(cfg: ResolvedModelConfig) -> str:
        calls.append(f"{cfg.provider_id}/{cfg.model}")
        if cfg.provider_id == "p1":
            raise RuntimeError("primary failed")
        return "ok"

    result = await run_with_vlm_fallback(primary, [fallback], _runner)
    assert result.result == "ok"
    assert result.used.provider_id == "p2"
    assert calls == ["p1/m1", "p2/m2"]
    assert len(result.attempts) == 1


def test_supports_vision_heuristics() -> None:
    assert supports_vision(ResolvedModelConfig(model="qwen-vl-max")) is True
    assert supports_vision(ResolvedModelConfig(model="deepseek-v3")) is False
    assert supports_input_capability(ResolvedModelConfig(model="whisper-large"), "audio") is True
    assert supports_input_capability(ResolvedModelConfig(model="gemini-2.5-pro"), "video") is True


def test_supports_vision_from_model_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Provider:
        def __init__(self):
            self.models = [
                ModelInfo(
                    id="plain-model",
                    name="plain-model",
                    input_capabilities=[],
                ),
                ModelInfo(
                    id="vision-model",
                    name="vision-model",
                    input_capabilities=["image"],
                ),
            ]

    class _ProvidersData:
        providers = {}
        custom_providers = {}

    import copaw.agents.model_capabilities as mc

    monkeypatch.setattr(mc, "load_providers_json", lambda: _ProvidersData())
    monkeypatch.setattr(mc, "get_provider", lambda _pid: _Provider())

    assert (
        supports_vision(
            ResolvedModelConfig(provider_id="dashscope", model="vision-model"),
        )
        is True
    )
    assert (
        supports_vision(
            ResolvedModelConfig(provider_id="dashscope", model="plain-model"),
        )
        is False
    )

