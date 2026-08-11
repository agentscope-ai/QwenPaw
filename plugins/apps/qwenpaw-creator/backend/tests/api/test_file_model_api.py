# -*- coding: utf-8 -*-
# pylint: disable=use-implicit-booleaness-not-comparison,protected-access
from __future__ import annotations

import asyncio
import errno
import json
import os
from pathlib import Path
import threading
import time

import httpx
from fastapi import FastAPI
import pytest

from api.dependencies import creator_error_handler
from api import model_routes
from domain.errors import CreatorError, ValidationError
from schemas.models import ModelConfigData

router = model_routes.router


def _config(model_name: str = "qwen-plus") -> dict:
    return {
        "llm": {
            "enabled": True,
            "model_name": model_name,
            "api_key": "secret",
            "base_url": "https://example.test/v1",
            "protocol": "OpenAI 协议",
            "custom_protocol": "",
            "multimodal": False,
        },
        "vlm": {
            "enabled": False,
            "model_name": "",
            "api_key": "",
            "base_url": "",
            "protocol": "OpenAI 协议",
            "custom_protocol": "",
            "use_llm": True,
            "multimodal": False,
        },
        "grounding": {
            "enabled": True,
            "model_name": "",
            "api_key": "",
            "base_url": "",
            "protocol": "OpenAI 协议",
            "custom_protocol": "",
            "reuse_llm": True,
            "tavily_api_key": "tvly-test",
            "serper_api_key": "serper-secret",
        },
        "asr": {
            "enabled": False,
            "model_name": "fun-asr",
            "api_key": "",
            "base_url": "https://example.test/asr",
            "protocol": "DashScope Fun-ASR",
            "custom_protocol": "",
            "provider": "fun-asr",
            "language": "",
            "reuse_llm_key": True,
        },
        "image": {
            "enabled": False,
            "model_name": "",
            "api_key": "",
            "base_url": "",
            "protocol": "OpenAI 协议",
            "custom_protocol": "",
        },
        "video": {
            "enabled": False,
            "model_name": "",
            "api_key": "",
            "base_url": "",
            "protocol": "OpenAI 协议",
            "custom_protocol": "",
        },
        "oss": {
            "enabled": False,
            "access_key_id": "oss-access-id",
            "access_key_secret": "oss-access-secret",
            "endpoint": "oss-cn-hangzhou.aliyuncs.com",
            "bucket": "creator-media",
            "public_base_url": "https://media.example.test",
            "policy_api_key": "oss-policy-secret",
        },
        "executionAuthorization": {"mode": "required"},
    }


def test_enabled_grounding_requires_global_or_override_llm() -> None:
    missing = _config()
    missing["llm"]["api_key"] = ""
    with pytest.raises(ValidationError, match="Grounding 默认启用"):
        model_routes._ensure_grounding_model_configured(
            ModelConfigData.model_validate(missing),
        )

    override = _config()
    override["llm"]["api_key"] = ""
    override["grounding"].update(
        {
            "reuse_llm": False,
            "api_key": "grounding-key",
            "base_url": "https://grounding.example.test/v1",
            "model_name": "grounding-qwen",
        },
    )
    model_routes._ensure_grounding_model_configured(
        ModelConfigData.model_validate(override),
    )

    disabled = _config()
    disabled["llm"]["api_key"] = ""
    disabled["grounding"]["enabled"] = False
    model_routes._ensure_grounding_model_configured(
        ModelConfigData.model_validate(disabled),
    )


def test_grounding_accepts_generic_vlm_validation_with_tavily_search() -> None:
    payload = _config()
    payload["llm"].update(
        {
            "model_name": "generic-text-model",
            "base_url": "https://text.example.test/v1",
            "protocol": "OpenAI 协议",
        },
    )
    payload["vlm"].update(
        {
            "enabled": True,
            "use_llm": False,
            "model_name": "generic-vision-model",
            "api_key": "vision-key",
            "base_url": "https://vision.example.test/v1",
        },
    )
    payload["grounding"]["validation_source"] = "vlm"

    model_routes._ensure_grounding_model_configured(
        ModelConfigData.model_validate(payload),
    )


def test_grounding_rejects_non_search_llm_when_tavily_is_absent() -> None:
    payload = _config()
    payload["grounding"]["tavily_api_key"] = ""
    payload["grounding"]["serper_api_key"] = ""
    payload["llm"].update(
        {
            "model_name": "generic-text-model",
            "base_url": "https://text.example.test/v1",
            "protocol": "OpenAI 协议",
        },
    )

    with pytest.raises(ValidationError, match="不支持.*原生 web_search"):
        model_routes._ensure_grounding_model_configured(
            ModelConfigData.model_validate(payload),
        )


def test_grounding_accepts_serper_only_search() -> None:
    payload = _config()
    payload["grounding"]["tavily_api_key"] = ""
    payload["grounding"]["serper_api_key"] = "serper-secret"
    payload["grounding"]["native_search_enabled"] = False

    model_routes._ensure_grounding_model_configured(
        ModelConfigData.model_validate(payload),
    )


def test_creation_checkpoints_mode_round_trips_through_assembly(
    tmp_path,
    monkeypatch,
) -> None:
    """A persisted skip mode must survive load and unrelated mutations."""

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    config_path = (tmp_path / "config" / "model_config.json").resolve()
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))
    payload = _config()
    payload["creation_checkpoints"] = {"mode": "skip"}
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = model_routes.load_model_config(include_environment=False)
    assert loaded.creation_checkpoints.mode == "skip"

    # An unrelated read-modify-write transaction must not silently
    # reset the persisted checkpoint mode back to the default.
    model_routes.mutate_model_config(lambda config: config)
    reloaded = model_routes.load_model_config(include_environment=False)
    assert reloaded.creation_checkpoints.mode == "skip"


def test_tts_section_survives_unrelated_config_mutations(
    tmp_path,
    monkeypatch,
) -> None:
    """TTS credentials must not be dropped by an unrelated config write.

    ``mutate_model_config`` rewrites the whole file from the assembled
    sections, so a section missing from the contract would be erased and the
    deployment would silently lose speech synthesis.
    """

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    config_path = (tmp_path / "config" / "model_config.json").resolve()
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))
    payload = _config()
    payload["tts"] = {
        "enabled": True,
        "api_key": "sk-tts",
        "base_url": "https://dashscope.aliyuncs.com/api/v1",
        "model_name": "qwen3-tts-flash",
        "voice": "Cherry",
    }
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = model_routes.load_model_config(include_environment=False)
    assert loaded.tts.model_name == "qwen3-tts-flash"
    assert loaded.tts.voice == "Cherry"

    model_routes.mutate_model_config(lambda config: config)

    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["tts"]["model_name"] == "qwen3-tts-flash"
    assert persisted["tts"]["voice"] == "Cherry"
    reloaded = model_routes.load_model_config(include_environment=False)
    assert reloaded.tts.api_key == "sk-tts"


def test_load_drops_unknown_persisted_fields_instead_of_500(
    tmp_path,
    monkeypatch,
) -> None:
    """model_config.json written by another plugin version must still load.

    The schema forbids extra fields, so an unknown key persisted by a newer
    (or older) build used to escape as a raw pydantic error — an opaque 500
    on every model-config route, locking users out of the config modal.
    """

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    config_path = (tmp_path / "config" / "model_config.json").resolve()
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))
    payload = _config()
    payload["llm"]["field_from_the_future"] = "surprise"
    payload["tts"] = {"model_name": "qwen3-tts-flash", "speed": 1.2}
    payload["self_review"] = {"sync_enabled": True, "retired_tier": False}
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = model_routes.load_model_config(include_environment=False)
    assert loaded.llm.model_name == "qwen-plus"
    assert loaded.tts.model_name == "qwen3-tts-flash"
    assert loaded.self_review.sync_enabled is True

    # A read-modify-write transaction must also survive (saves go through
    # the same assembly) and rewrite the file without the unknown fields.
    model_routes.mutate_model_config(lambda config: config)
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert "field_from_the_future" not in persisted["llm"]
    assert "speed" not in persisted["tts"]


def test_load_surfaces_invalid_persisted_value_as_validation_error(
    tmp_path,
    monkeypatch,
) -> None:
    """A wrong-typed persisted value must raise the structured 422 error."""

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    config_path = (tmp_path / "config" / "model_config.json").resolve()
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))
    payload = _config()
    payload["llm"]["enabled"] = "definitely-not-a-bool"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="llm.enabled"):
        model_routes.load_model_config(include_environment=False)


def test_real_api_key_supports_every_speech_section(
    tmp_path,
    monkeypatch,
) -> None:
    """``tts`` must resolve like ``asr``: the UI fetches the real key for a
    connection test whenever the section stores its own credential."""

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    config_path = (tmp_path / "config" / "model_config.json").resolve()
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))
    payload = _config()
    payload["tts"] = {
        "enabled": True,
        "api_key": "sk-tts-own",
        "base_url": "https://dashscope.aliyuncs.com/api/v1",
        "model_name": "qwen3-tts-flash",
        "voice": "Cherry",
    }
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(router)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            tts = await client.get("/models/real-api-key/tts")
            bogus = await client.get("/models/real-api-key/bogus")
        return tts, bogus

    tts, bogus = asyncio.run(scenario())
    assert tts.status_code == 200
    assert tts.json() == {"api_key": "sk-tts-own"}
    assert bogus.status_code == 422


def test_permission_mode_patch_is_atomic(tmp_path, monkeypatch) -> None:
    """One PATCH persists all three ladder fields in a single transaction.

    Split per-field PATCHes could strand a mixed state when one call
    fails (worst case: media_review=auto_approve hiding behind a
    conservative-looking slider position).
    """

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    config_path = (tmp_path / "config" / "model_config.json").resolve()
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(_config()), encoding="utf-8")

    asyncio.run(
        model_routes.patch_permission_mode(
            {
                "execution_authorization": "allow_all",
                "creation_checkpoints": "skip",
                "media_review": "auto_approve",
            },
        ),
    )

    loaded = model_routes.load_model_config(include_environment=False)
    assert loaded.execution_authorization.mode == "allow_all"
    assert loaded.creation_checkpoints.mode == "skip"
    assert loaded.media_review.mode == "auto_approve"

    # Any invalid field rejects the whole request before mutation.
    with pytest.raises(ValidationError, match="media_review"):
        asyncio.run(
            model_routes.patch_permission_mode(
                {
                    "execution_authorization": "required",
                    "creation_checkpoints": "required",
                    "media_review": "yes-please",
                },
            ),
        )
    unchanged = model_routes.load_model_config(include_environment=False)
    assert unchanged.execution_authorization.mode == "allow_all"
    assert unchanged.media_review.mode == "auto_approve"


def test_self_review_patch_merges_tiers(tmp_path, monkeypatch) -> None:
    """Each PATCH merges into the section so tiers never clobber each other,
    and the runtime switches follow the persisted values when the
    corresponding environment variables are not explicitly set."""

    from models import config as model_config

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    config_path = (tmp_path / "config" / "model_config.json").resolve()
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))
    for env in (
        "CREATOR_SELF_REVIEW_ENABLED",
        "CREATOR_SYNC_REVIEW_ENABLED",
        "CREATOR_MEDIA_REVIEW_ENABLED",
    ):
        monkeypatch.delenv(env, raising=False)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(_config()), encoding="utf-8")

    asyncio.run(model_routes.patch_self_review({"render_enabled": True}))
    asyncio.run(model_routes.patch_self_review({"sync_enabled": True}))

    loaded = model_routes.load_model_config(include_environment=False)
    assert loaded.self_review.render_enabled is True
    assert loaded.self_review.sync_enabled is True
    assert loaded.self_review.media_enabled is False

    # Runtime switches follow the persisted tiers without env overrides.
    assert model_config.is_self_review_enabled() is True
    assert model_config.is_sync_review_enabled() is True
    assert model_config.is_media_review_enabled() is False

    # An explicitly set env var wins in both directions.
    monkeypatch.setenv("CREATOR_SELF_REVIEW_ENABLED", "0")
    assert model_config.is_self_review_enabled() is False
    monkeypatch.setenv("CREATOR_MEDIA_REVIEW_ENABLED", "1")
    assert model_config.is_media_review_enabled() is True

    # Invalid payloads reject before mutation.
    with pytest.raises(ValidationError, match="布尔值"):
        asyncio.run(model_routes.patch_self_review({"sync_enabled": "yes"}))
    with pytest.raises(ValidationError, match="不支持的字段"):
        asyncio.run(model_routes.patch_self_review({"bogus": True}))
    with pytest.raises(ValidationError, match="至少提供"):
        asyncio.run(model_routes.patch_self_review({}))
    unchanged = model_routes.load_model_config(include_environment=False)
    assert unchanged.self_review.render_enabled is True
    assert unchanged.self_review.sync_enabled is True


def test_self_review_env_overrides_reported_never_persisted(
    tmp_path,
    monkeypatch,
) -> None:
    """GET badges env-shadowed tiers; PATCH never writes the report to disk.

    Field incident: review ran with the settings-center toggles off
    because stale env vars stayed injected — the UI needs the override
    to be visible, and the persisted file must stay clean.
    """

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    config_path = (tmp_path / "config" / "model_config.json").resolve()
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))
    for env in (
        "CREATOR_SELF_REVIEW_ENABLED",
        "CREATOR_SYNC_REVIEW_ENABLED",
        "CREATOR_MEDIA_REVIEW_ENABLED",
    ):
        monkeypatch.delenv(env, raising=False)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(_config()), encoding="utf-8")

    silent = asyncio.run(model_routes.get_model_config())
    assert silent.self_review.env_overrides == {}

    monkeypatch.setenv("CREATOR_MEDIA_REVIEW_ENABLED", "1")
    monkeypatch.setenv("CREATOR_SELF_REVIEW_ENABLED", "0")
    loaded = asyncio.run(model_routes.get_model_config())
    assert loaded.self_review.env_overrides == {
        "media_enabled": "1",
        "render_enabled": "0",
    }

    # A tier PATCH while overrides are active must not persist the report.
    asyncio.run(model_routes.patch_self_review({"sync_enabled": True}))
    on_disk = json.loads(config_path.read_text(encoding="utf-8"))
    assert "env_overrides" not in (on_disk.get("self_review") or {})


def test_video_api_key_reuses_llm_for_dashscope(tmp_path, monkeypatch) -> None:
    """Without a video key the DashScope (wan/happyhorse) backend reuses the
    text credential by default; opting out or running on Volcano never
    borrows the Bailian key."""

    from models import config as model_config

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    config_path = (tmp_path / "config" / "model_config.json").resolve()
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))
    for env in ("VIDEO_API_KEY", "TEXT_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    payload = _config()
    payload["video"] = {
        "enabled": True,
        "model_name": "wan2.7",
        "base_url": "https://dashscope.aliyuncs.com/api/v1",
        "protocol": "DashScope（百炼）",
    }
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    model_config._clear_user_config_cache()
    assert model_config.get_video_api_key() == "secret"

    payload["video"]["reuse_llm_key"] = False
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    model_config._clear_user_config_cache()
    assert model_config.get_video_api_key() == ""

    payload["video"] = {
        "enabled": True,
        "model_name": "doubao-seedance-2.0-pro",
        "base_url": "https://ark.cn-beijing.volces.com",
        "protocol": "Volcano Engine（火山引擎）",
    }
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    model_config._clear_user_config_cache()
    assert model_config.get_video_api_key() == ""


def test_load_migrates_legacy_grounding_model_to_search_and_validation(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    config_path = (tmp_path / "config" / "model_config.json").resolve()
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))
    payload = _config()
    payload["grounding"].update(
        {
            "reuse_llm": False,
            "model_name": "legacy-qwen",
            "api_key": "legacy-key",
            "base_url": ("https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "protocol": "DashScope（百炼）",
        },
    )
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = model_routes.load_model_config(include_environment=False)

    assert loaded.grounding.validation_source == "custom"
    assert loaded.grounding.search_reuse_llm is False
    assert loaded.grounding.search_model_name == "legacy-qwen"
    assert loaded.grounding.search_api_key == "legacy-key"


def test_persisted_only_load_ignores_grounding_env_overrides(
    tmp_path,
    monkeypatch,
) -> None:
    """``include_environment=False`` must not let env vars skew migration.

    With a legacy ``reuse_llm=false`` file and the validation-source env
    var set, the persisted-only view previously skipped the reuse_llm
    migration (because the env var existed) without applying the env value
    either — reporting validation_source=llm/reuse_llm=true to the UI.
    """

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    config_path = (tmp_path / "config" / "model_config.json").resolve()
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("WEB_GROUNDING_VALIDATION_SOURCE", "vlm")
    monkeypatch.setenv("WEB_GROUNDING_SEARCH_REUSE_LLM", "0")
    payload = _config()
    payload["grounding"].update(
        {
            "reuse_llm": False,
            "model_name": "legacy-qwen",
            "api_key": "legacy-key",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "protocol": "DashScope（百炼）",
        },
    )
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    persisted_only = model_routes.load_model_config(include_environment=False)
    assert persisted_only.grounding.validation_source == "custom"
    assert persisted_only.grounding.reuse_llm is False

    # The runtime view still lets the environment win.
    with_environment = model_routes.load_model_config()
    assert with_environment.grounding.validation_source == "vlm"


def test_host_legacy_reuse_llm_survives_merge_with_local_config(
    tmp_path,
    monkeypatch,
) -> None:
    """A portal that only exposes reuse_llm must still beat local defaults.

    The local config always carries validation_source, so without the
    legacy migration in ``bind_creator_tool_config`` the merged runtime
    config would keep validating with the LLM even though the portal
    explicitly selected a custom verifier.
    """

    from models import config as creator_model_config

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    config_path = (tmp_path / "config" / "model_config.json").resolve()
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(_config()), encoding="utf-8")

    host_grounding = {
        "reuse_llm": "false",
        "api_key": "host-verifier-key",
        "model": "host-verifier-model",
        "base_url": "https://host.example.test/v1",
    }
    monkeypatch.setattr(
        model_routes,
        "_qwenpaw_tool_configs",
        lambda _request: {
            creator_model_config.CREATOR_GROUNDING_CONFIG_TOOL: dict(
                host_grounding,
            ),
        },
    )

    async def scenario():
        generator = model_routes.bind_creator_tool_config(object())
        await generator.__anext__()
        try:
            source = creator_model_config.get_web_grounding_validation_source()
            api_key = creator_model_config.get_web_grounding_model_api_key()
            model_name = creator_model_config.get_web_grounding_model_name()
        finally:
            await generator.aclose()
        return source, api_key, model_name

    source, api_key, model_name = asyncio.run(scenario())

    assert source == "custom"
    assert api_key == "host-verifier-key"
    assert model_name == "host-verifier-model"

    # An explicit host validation_source is honored as-is.
    host_grounding["validation_source"] = "vlm"
    assert asyncio.run(scenario())[0] == "vlm"


def test_model_config_is_single_file_native_and_idempotent(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    monkeypatch.setenv(
        "CREATOR_MODEL_CONFIG_PATH",
        str((tmp_path / "config" / "model_config.json").resolve()),
    )

    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(router)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            first = await client.post(
                "/models/config",
                headers={"Idempotency-Key": "config-1"},
                json=_config(),
            )
            replay = await client.post(
                "/models/config",
                headers={"Idempotency-Key": "config-1"},
                json=_config(),
            )
            drift = await client.post(
                "/models/config",
                headers={"Idempotency-Key": "config-1"},
                json=_config("other-model"),
            )
            loaded = await client.get("/models/config")
        return first, replay, drift, loaded

    first, replay, drift, loaded = asyncio.run(scenario())
    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.headers["x-idempotent-replay"] == "true"
    assert drift.status_code == 409
    assert loaded.status_code == 200
    assert loaded.json()["llm"]["model_name"] == "qwen-plus"
    # GET never returns persisted secrets; it returns the keep-placeholder.
    assert loaded.json()["llm"]["api_key"] == model_routes.SECRET_MASK
    assert loaded.json()["grounding"] == {
        "enabled": True,
        "model_name": "",
        "api_key": "",
        "base_url": "",
        "protocol": "OpenAI 协议",
        "custom_protocol": "",
        "reuse_llm": True,
        "validation_source": "llm",
        # Search-provider keys are secret fields: GET returns the
        # keep-placeholder instead of the persisted credentials.
        "tavily_api_key": model_routes.SECRET_MASK,
        "serper_api_key": model_routes.SECRET_MASK,
        "native_search_enabled": True,
        "search_provider": "dashscope_qwen",
        "search_reuse_llm": True,
        "search_model_name": "",
        "search_api_key": "",
        "search_base_url": "",
        "search_protocol": "DashScope（百炼）",
    }
    assert loaded.json()["oss"] == {
        "enabled": False,
        "access_key_id": "oss-access-id",
        "access_key_secret": model_routes.SECRET_MASK,
        "endpoint": "oss-cn-hangzhou.aliyuncs.com",
        "bucket": "creator-media",
        "public_base_url": "https://media.example.test",
        "policy_api_key": model_routes.SECRET_MASK,
    }

    config_path = tmp_path / "config" / "model_config.json"
    secrets_path = tmp_path / "config" / "model_config.secrets.json"
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    # Secrets are encrypted at rest when the QwenPaw secret store is
    # available; verify that, then decrypt before comparing the round-trip.
    if model_routes.QWENPAW_SECRET_AVAILABLE:
        assert persisted["llm"]["api_key"] != "secret"
    model_routes._decrypt_secret_fields(persisted)
    assert persisted["llm"]["api_key"] == "secret"
    assert persisted["oss"] == {
        "enabled": False,
        "access_key_id": "oss-access-id",
        "access_key_secret": "oss-access-secret",
        "bucket": "creator-media",
        "endpoint": "oss-cn-hangzhou.aliyuncs.com",
        "policy_api_key": "oss-policy-secret",
        "public_base_url": "https://media.example.test",
    }
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert not secrets_path.exists()
    assert list(
        (tmp_path / "config" / "runtime" / "idempotency").rglob("*.json"),
    )
    assert not any(
        path.suffix.casefold() in {".db", ".sqlite", ".sqlite3"}
        for path in tmp_path.rglob("*")
    )


def test_model_config_save_tolerates_windows_like_private_file_surface(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    monkeypatch.setenv(
        "CREATOR_MODEL_CONFIG_PATH",
        str((tmp_path / "config" / "model_config.json").resolve()),
    )
    real_open = os.open

    def windows_like_open(target, flags, mode=0o600, *args, **kwargs):
        if Path(target).is_dir():
            raise PermissionError(errno.EACCES, "Permission denied", target)
        return real_open(target, flags, mode, *args, **kwargs)

    monkeypatch.delattr(model_routes.os, "fchmod", raising=False)
    monkeypatch.setattr(model_routes.os, "open", windows_like_open)

    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(router)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/models/config",
                headers={"Idempotency-Key": "config-windows-like"},
                json=_config(),
            )

    response = asyncio.run(scenario())

    assert response.status_code == 200
    persisted = json.loads(
        (tmp_path / "config" / "model_config.json").read_text(
            encoding="utf-8",
        ),
    )
    model_routes._decrypt_secret_fields(persisted)
    assert persisted["llm"]["api_key"] == "secret"


def test_concurrent_single_file_save_is_atomic_and_last_writer_wins(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    monkeypatch.setenv(
        "CREATOR_MODEL_CONFIG_PATH",
        str((tmp_path / "config" / "model_config.json").resolve()),
    )
    model_routes.save_model_config(ModelConfigData.model_validate(_config()))

    updater_payload = _config("secret-updater")
    updater_payload["oss"]["access_key_secret"] = "latest-secret"
    updater = ModelConfigData.model_validate(updater_payload)
    second_payload = _config("second-writer")
    second_payload["llm"]["api_key"] = "second-api-key"
    second_payload["oss"]["access_key_secret"] = "second-oss-secret"
    second_payload["oss"]["policy_api_key"] = "second-policy-secret"
    second_writer = ModelConfigData.model_validate(second_payload)

    updater_holds_lock = threading.Event()
    allow_updater_to_finish = threading.Event()
    original_atomic_replace = model_routes.atomic_replace_bytes

    def delayed_atomic_replace(target, payload, **kwargs):
        original_atomic_replace(target, payload, **kwargs)
        if (
            threading.current_thread().name == "secret-updater"
            and Path(target).name == "model_config.json"
        ):
            updater_holds_lock.set()
            assert allow_updater_to_finish.wait(timeout=3)

    monkeypatch.setattr(
        model_routes,
        "atomic_replace_bytes",
        delayed_atomic_replace,
    )
    failures: list[BaseException] = []

    def save(data: ModelConfigData) -> None:
        try:
            model_routes.save_model_config(data)
        except BaseException as error:  # pragma: no cover - asserted below
            failures.append(error)

    first = threading.Thread(
        target=save,
        args=(updater,),
        name="secret-updater",
    )
    second = threading.Thread(
        target=save,
        args=(second_writer,),
        name="second-writer",
    )
    first.start()
    assert updater_holds_lock.wait(timeout=3)
    second.start()
    time.sleep(0.05)
    allow_updater_to_finish.set()
    first.join(timeout=3)
    second.join(timeout=3)

    assert not first.is_alive()
    assert not second.is_alive()
    assert failures == []
    persisted = json.loads(
        (tmp_path / "config" / "model_config.json").read_text(
            encoding="utf-8",
        ),
    )
    # Same as the single-file test: decrypt at-rest secrets before comparing.
    model_routes._decrypt_secret_fields(persisted)
    assert persisted["llm"]["api_key"] == "second-api-key"
    assert persisted["oss"]["access_key_secret"] == "second-oss-secret"
    assert persisted["oss"]["policy_api_key"] == "second-policy-secret"
    assert model_routes.load_model_config().llm.model_name == "second-writer"
