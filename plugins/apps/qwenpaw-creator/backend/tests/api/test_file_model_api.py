# -*- coding: utf-8 -*-
# pylint: disable=use-implicit-booleaness-not-comparison,protected-access
# pylint: disable=redefined-outer-name
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import threading
import time

from fastapi import FastAPI
import pytest

from api.dependencies import creator_error_handler
from api import model_routes
from domain.errors import CreatorError, ValidationError
from models import config as model_config
from schemas.models import ModelConfigData

router = model_routes.router

_REVIEW_ENVS = (
    "CREATOR_SELF_REVIEW_ENABLED",
    "CREATOR_SYNC_REVIEW_ENABLED",
    "CREATOR_MEDIA_REVIEW_ENABLED",
)

_TTS = {
    "enabled": True,
    "api_key": "sk-tts",
    "base_url": "https://dashscope.aliyuncs.com/api/v1",
    "model_name": "qwen3-tts-flash",
    "voice": "Cherry",
}


def _section(**overrides) -> dict:
    section = {
        "enabled": False,
        "model_name": "",
        "api_key": "",
        "base_url": "",
        "protocol": "OpenAI 协议",
        "custom_protocol": "",
    }
    section.update(overrides)
    return section


def _config(model_name: str = "qwen-plus") -> dict:
    return {
        "llm": _section(
            enabled=True,
            model_name=model_name,
            api_key="secret",
            base_url="https://example.test/v1",
            multimodal=False,
        ),
        "vlm": _section(use_llm=True, multimodal=False),
        "grounding": _section(
            enabled=True,
            reuse_llm=True,
            tavily_api_key="tvly-test",
            serper_api_key="serper-secret",
        ),
        "asr": _section(
            model_name="fun-asr",
            base_url="https://example.test/asr",
            protocol="DashScope Fun-ASR",
            provider="fun-asr",
            language="",
            reuse_llm_key=True,
        ),
        "image": _section(),
        "video": _section(),
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


def _legacy_grounding_config() -> dict:
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
    return payload


@pytest.fixture()
def config_path(tmp_path, monkeypatch):
    """Point the model-config env vars at an isolated writable file."""

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    path = (tmp_path / "config" / "model_config.json").resolve()
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(path))
    path.parent.mkdir(parents=True)
    return path


def _write(config_path: Path, payload: dict) -> None:
    config_path.write_text(json.dumps(payload), encoding="utf-8")


def _model_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(router)
    return app


def _check_grounding(payload: dict) -> None:
    model_routes._ensure_grounding_model_configured(
        ModelConfigData.model_validate(payload),
    )


def test_enabled_grounding_requires_global_or_override_llm() -> None:
    missing = _config()
    missing["llm"]["api_key"] = ""
    with pytest.raises(ValidationError, match="Grounding 默认启用"):
        _check_grounding(missing)

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
    _check_grounding(override)


def test_grounding_rejects_non_search_llm_unless_a_search_key_exists() -> None:
    payload = _config()
    payload["grounding"].update({"tavily_api_key": "", "serper_api_key": ""})
    payload["llm"].update(
        {
            "model_name": "generic-text-model",
            "base_url": "https://text.example.test/v1",
        },
    )

    with pytest.raises(ValidationError, match="不支持.*原生 web_search"):
        _check_grounding(payload)

    # A Serper key alone satisfies the search requirement.
    payload["grounding"]["serper_api_key"] = "serper-secret"
    payload["grounding"]["native_search_enabled"] = False
    _check_grounding(payload)


def test_persisted_sections_survive_unrelated_config_mutations(
    config_path,
) -> None:
    # mutate_model_config rewrites the whole file from assembled sections;
    # a section missing from the contract would silently reset checkpoint
    # mode or erase speech-synthesis credentials.
    payload = _config()
    payload["creation_checkpoints"] = {"mode": "skip"}
    payload["tts"] = dict(_TTS)
    _write(config_path, payload)

    loaded = model_routes.load_model_config(include_environment=False)
    assert loaded.creation_checkpoints.mode == "skip"
    assert loaded.tts.voice == "Cherry"

    model_routes.mutate_model_config(lambda config: config)

    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["tts"]["model_name"] == "qwen3-tts-flash"
    assert persisted["tts"]["voice"] == "Cherry"


def test_load_drops_unknown_persisted_fields_instead_of_500(
    config_path,
) -> None:
    # Incident regression: an unknown key persisted by another plugin build
    # used to escape as a raw pydantic error — an opaque 500 on every route.
    payload = _config()
    payload["llm"]["field_from_the_future"] = "surprise"
    payload["tts"] = {"model_name": "qwen3-tts-flash", "speed": 1.2}
    payload["self_review"] = {"sync_enabled": True, "retired_tier": False}
    _write(config_path, payload)

    loaded = model_routes.load_model_config(include_environment=False)
    assert loaded.llm.model_name == "qwen-plus"
    assert loaded.tts.model_name == "qwen3-tts-flash"
    assert loaded.self_review.sync_enabled is True

    # Saves go through the same assembly and drop the unknown fields.
    model_routes.mutate_model_config(lambda config: config)
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert "field_from_the_future" not in persisted["llm"]
    assert "speed" not in persisted["tts"]


def test_load_surfaces_invalid_persisted_value_as_validation_error(
    config_path,
) -> None:
    # A wrong-typed persisted value must raise the structured 422 error.
    payload = _config()
    payload["llm"]["enabled"] = "definitely-not-a-bool"
    _write(config_path, payload)

    with pytest.raises(ValidationError, match="llm.enabled"):
        model_routes.load_model_config(include_environment=False)


def test_permission_mode_patch_is_atomic(config_path) -> None:
    # One PATCH persists all three ladder fields in a single transaction; a
    # partial failure could strand media_review=auto_approve behind a
    # conservative-looking slider position.
    _write(config_path, _config())

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


def test_self_review_patch_merges_tiers(config_path, monkeypatch) -> None:
    # Each PATCH merges into the section so tiers never clobber each other;
    # runtime switches follow persisted values when env vars are unset.
    for env in _REVIEW_ENVS:
        monkeypatch.delenv(env, raising=False)
    _write(config_path, _config())

    asyncio.run(model_routes.patch_self_review({"render_enabled": True}))
    asyncio.run(model_routes.patch_self_review({"sync_enabled": True}))

    loaded = model_routes.load_model_config(include_environment=False)
    assert loaded.self_review.render_enabled is True
    assert loaded.self_review.sync_enabled is True
    assert loaded.self_review.media_enabled is False

    assert model_config.is_self_review_enabled() is True
    assert model_config.is_sync_review_enabled() is True
    assert model_config.is_media_review_enabled() is False

    # Invalid payloads reject before mutation.
    with pytest.raises(ValidationError, match="布尔值"):
        asyncio.run(model_routes.patch_self_review({"sync_enabled": "yes"}))
    unchanged = model_routes.load_model_config(include_environment=False)
    assert unchanged.self_review.render_enabled is True
    assert unchanged.self_review.sync_enabled is True


def test_self_review_env_overrides_reported_never_persisted(
    config_path,
    monkeypatch,
) -> None:
    # Field incident: review ran with the settings-center toggles off
    # because stale env vars stayed injected — GET must badge the override
    # and PATCH must never write the report to disk.
    for env in _REVIEW_ENVS:
        monkeypatch.delenv(env, raising=False)
    _write(config_path, _config())

    silent = asyncio.run(model_routes.get_model_config())
    assert silent.self_review.env_overrides == {}

    monkeypatch.setenv("CREATOR_MEDIA_REVIEW_ENABLED", "1")
    monkeypatch.setenv("CREATOR_SELF_REVIEW_ENABLED", "0")
    loaded = asyncio.run(model_routes.get_model_config())
    assert loaded.self_review.env_overrides == {
        "media_enabled": "1",
        "render_enabled": "0",
    }

    asyncio.run(model_routes.patch_self_review({"sync_enabled": True}))
    on_disk = json.loads(config_path.read_text(encoding="utf-8"))
    assert "env_overrides" not in (on_disk.get("self_review") or {})


def test_self_review_operator_switches_contract(
    config_path,
    monkeypatch,
) -> None:
    """Per-operator switches: merge, restore-to-auto, reject, never leak.

    The resolved ``operator_status`` report is response-only state (like
    ``env_overrides``): the UI needs it, the config file must never see
    it.
    """
    for env in _REVIEW_ENVS:
        monkeypatch.delenv(env, raising=False)
    _write(config_path, _config())

    asyncio.run(
        model_routes.patch_self_review(
            {"operators": {"defect_bank": False, "challenge": True}},
        ),
    )
    asyncio.run(
        model_routes.patch_self_review({"operators": {"ocr_text": True}}),
    )
    loaded = model_routes.load_model_config(include_environment=False)
    assert loaded.self_review.operators == {
        "defect_bank": False,
        "challenge": True,
        "ocr_text": True,
    }

    # Explicit user choices win over the capability-based auto default.
    from services.run_review.operator_registry import is_operator_enabled

    assert is_operator_enabled("defect_bank") is False
    assert is_operator_enabled("challenge") is True

    # null removes the entry, restoring the auto resolution.
    asyncio.run(
        model_routes.patch_self_review({"operators": {"defect_bank": None}}),
    )
    restored = model_routes.load_model_config(include_environment=False)
    assert "defect_bank" not in restored.self_review.operators
    assert is_operator_enabled("defect_bank") is True

    # Unknown keys and non-boolean values are rejected before mutation.
    with pytest.raises(ValidationError, match="不支持的算子"):
        asyncio.run(
            model_routes.patch_self_review({"operators": {"bogus": True}}),
        )
    with pytest.raises(ValidationError, match="布尔值或 null"):
        asyncio.run(
            model_routes.patch_self_review({"operators": {"ocr_text": "on"}}),
        )
    with pytest.raises(ValidationError, match="必须是对象"):
        asyncio.run(model_routes.patch_self_review({"operators": []}))
    survived = model_routes.load_model_config(include_environment=False)
    assert survived.self_review.operators == {
        "challenge": True,
        "ocr_text": True,
    }

    # GET reports resolved state; the file never carries it.
    reported = asyncio.run(model_routes.get_model_config())
    rows = {row["key"]: row for row in reported.self_review.operator_status}
    assert rows["challenge"]["source"] == "user"
    assert rows["video_index"]["source"] == "auto"
    assert {"tier", "dependency", "capability_ok", "enabled"} <= set(
        rows["av_sync"],
    )
    on_disk = json.loads(config_path.read_text(encoding="utf-8"))
    assert "operator_status" not in (on_disk.get("self_review") or {})


def test_load_migrates_legacy_grounding_model_to_search_and_validation(
    config_path,
) -> None:
    _write(config_path, _legacy_grounding_config())

    loaded = model_routes.load_model_config(include_environment=False)

    assert loaded.grounding.validation_source == "custom"
    assert loaded.grounding.search_reuse_llm is False
    assert loaded.grounding.search_model_name == "legacy-qwen"
    assert loaded.grounding.search_api_key == "legacy-key"


def test_persisted_only_load_ignores_grounding_env_overrides(
    config_path,
    monkeypatch,
) -> None:
    # Incident regression: with a legacy reuse_llm=false file and the env
    # var set, the persisted-only view skipped the migration (env existed)
    # without applying the env value — reporting reuse_llm=true to the UI.
    monkeypatch.setenv("WEB_GROUNDING_VALIDATION_SOURCE", "vlm")
    monkeypatch.setenv("WEB_GROUNDING_SEARCH_REUSE_LLM", "0")
    _write(config_path, _legacy_grounding_config())

    persisted_only = model_routes.load_model_config(include_environment=False)
    assert persisted_only.grounding.validation_source == "custom"
    assert persisted_only.grounding.reuse_llm is False

    # The runtime view still lets the environment win.
    with_environment = model_routes.load_model_config()
    assert with_environment.grounding.validation_source == "vlm"


def test_model_config_is_single_file_native_and_idempotent(
    config_path,
    run_scenario,
) -> None:
    async def scenario(client):
        def post(body):
            return client.post(
                "/models/config",
                headers={"Idempotency-Key": "config-1"},
                json=body,
            )

        first = await post(_config())
        replay = await post(_config())
        drift = await post(_config("other-model"))
        loaded = await client.get("/models/config")
        return first, replay, drift, loaded

    first, replay, drift, loaded = run_scenario(_model_app(), scenario)
    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.headers["x-idempotent-replay"] == "true"
    assert drift.status_code == 409
    assert loaded.status_code == 200
    assert loaded.json()["llm"]["model_name"] == "qwen-plus"
    # GET never returns persisted secrets; it returns the keep-placeholder.
    assert loaded.json()["llm"]["api_key"] == model_routes.SECRET_MASK
    oss = loaded.json()["oss"]
    assert oss["access_key_id"] == "oss-access-id"
    assert oss["access_key_secret"] == model_routes.SECRET_MASK

    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    # Secrets are encrypted at rest when the QwenPaw secret store is
    # available; verify that, then decrypt before comparing the round-trip.
    if model_routes.QWENPAW_SECRET_AVAILABLE:
        assert persisted["llm"]["api_key"] != "secret"
    model_routes._decrypt_secret_fields(persisted)
    assert persisted["llm"]["api_key"] == "secret"
    assert persisted["oss"]["access_key_secret"] == "oss-access-secret"
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert not config_path.with_name("model_config.secrets.json").exists()


def test_concurrent_single_file_save_is_atomic_and_last_writer_wins(
    config_path,
    monkeypatch,
) -> None:
    model_routes.save_model_config(ModelConfigData.model_validate(_config()))

    updater_payload = _config("secret-updater")
    updater_payload["oss"]["access_key_secret"] = "latest-secret"
    updater = ModelConfigData.model_validate(updater_payload)
    second_payload = _config("second-writer")
    second_payload["llm"]["api_key"] = "second-api-key"
    second_payload["oss"]["access_key_secret"] = "second-oss-secret"
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
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    # Same as the single-file test: decrypt at-rest secrets before comparing.
    model_routes._decrypt_secret_fields(persisted)
    assert persisted["llm"]["api_key"] == "second-api-key"
    assert persisted["oss"]["access_key_secret"] == "second-oss-secret"
    assert model_routes.load_model_config().llm.model_name == "second-writer"


def test_video_capability_route_exposes_wan3_all_in_one_contract(
    app,
    api_request,
) -> None:
    response = api_request(
        app,
        "GET",
        "/models/video-capabilities",
        params={
            "modelName": "wan3.0-video-prime",
            "protocol": "DashScope（百炼）",
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "provider": "wan",
        "model": "wan3.0-video-prime",
        "known": True,
        "supportedModes": ["r2v", "t2v", "i2v"],
        "effectiveModels": {
            "r2v": "wan3.0-video-prime",
            "t2v": "wan3.0-video-prime",
            "i2v": "wan3.0-video-prime",
        },
        "derivesModeModel": False,
        "documentationUrl": (
            "https://help.aliyun.com/zh/model-studio/"
            "wan3-video-generation-api-reference"
        ),
    }
