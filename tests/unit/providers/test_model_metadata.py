# -*- coding: utf-8 -*-
# White-box assertions and pytest fixture parameters are intentional.
# pylint: disable=unused-argument,redefined-outer-name
"""Regression tests for automatic token metadata and model templates."""

import json
from unittest.mock import Mock

import pytest

from qwenpaw.providers import model_catalog, model_metadata
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider import ModelInfo
from qwenpaw.providers.model_resolution import resolve_model_info


@pytest.fixture
def metadata(monkeypatch, tmp_path):
    payload = {
        f"alibaba-cn": {
            f"api": f"https://dashscope.aliyuncs.com/compatible-mode/v1",
            f"models": {
                f"qwen3.8-max": {
                    f"limit": {f"context": 1_000_000, f"output": 131_072},
                },
            },
        },
        f"openai": {
            f"models": {
                f"test-model": {
                    f"limit": {f"context": 200_000, f"output": 32_768},
                },
            },
        },
    }
    providers = {}
    for key, entry in payload.items():
        providers[key] = {
            f"api_urls": [entry.get(f"api", f"https://api.openai.com/v1")],
            f"remote_id": key,
            f"template_owner": True,
            f"default_model_ids": [],
            f"models": [
                {
                    f"id": model_id,
                    f"name": model_id,
                    f"max_input_length": row[f"limit"][f"context"],
                    f"max_output_length": row[f"limit"][f"output"],
                }
                for model_id, row in entry[f"models"].items()
            ],
        }
    packaged = tmp_path / f"packaged.json"
    packaged.write_text(
        json.dumps(
            {
                f"schema_version": 2,
                f"catalog_version": f"2026.09.18",
                f"providers": providers,
            },
        ),
        encoding=f"utf-8",
    )
    monkeypatch.setattr(model_catalog, f"PACKAGED_CATALOG_PATH", packaged)
    monkeypatch.setattr(
        model_catalog,
        f"METADATA_CACHE_PATH",
        tmp_path / f"cache.json",
    )
    monkeypatch.setattr(
        model_catalog,
        f"OTA_CATALOG_PATH",
        tmp_path / f"ota.json",
    )
    monkeypatch.setattr(
        model_catalog,
        f"LOCAL_CATALOG_PATH",
        tmp_path / f"local.json",
    )
    return payload


def custom_provider(**model_fields):
    return OpenAIProvider(
        id=f"my-gateway",
        name=f"My gateway",
        is_custom=True,
        base_url=f"https://gateway.example/v1",
        extra_models=[
            ModelInfo(
                id=f"qwen3.8-max",
                name=f"Qwen",
                **model_fields,
            ),
        ],
    )


async def test_custom_endpoint_uses_named_template(metadata):
    provider = custom_provider()
    assert provider.get_context_size(f"qwen3.8-max") == 1_000_000
    info = (await provider.get_info()).extra_models[0]
    assert info.effective_max_input_length == 1_000_000
    assert info.context_length_source == f"template"
    assert info.max_output_length == 131_072
    assert info.max_output_length_source == f"template"
    assert info.generate_kwargs == {}
    assert not info.max_input_length_configured
    assert provider.extra_models[0].max_output_length is None


async def test_api_and_user_override_template(metadata):
    provider = custom_provider(
        max_input_length=16_384,
        max_input_length_configured=True,
        max_input_length_auto_detected=64_000,
        max_output_length=8192,
        max_output_length_source=f"api",
    )
    info = (await provider.get_info()).extra_models[0]
    assert info.effective_max_input_length == 16_384
    assert info.automatic_max_input_length == 64_000
    assert info.context_length_source == f"user"
    assert info.max_output_length == 8192
    provider.update_model_config(f"qwen3.8-max", {f"max_input_length": None})
    assert provider.get_context_size(f"qwen3.8-max") == 64_000
    info = (await provider.get_info()).extra_models[0]
    assert info.context_length_source == f"api"
    assert f"max_input_length" not in info.config_overrides


async def test_reset_restores_template_without_freezing_it(metadata):
    provider = custom_provider(
        max_input_length=16_384,
        max_input_length_configured=True,
        config_overrides=[f"max_input_length", f"max_input_length_configured"],
    )
    provider.update_model_config(f"qwen3.8-max", {f"max_input_length": None})
    assert provider.get_context_size(f"qwen3.8-max") == 1_000_000
    assert provider.extra_models[0].config_overrides == []


def test_endpoint_match_precedes_template(metadata):
    matches = model_metadata.model_metadata(
        f"custom",
        f"https://api.openai.com/v1/",
        f"test-model",
    )
    assert matches[0].model.max_input_length == 200_000
    assert matches[0].source == f"catalog"


def test_unknown_name_is_not_fuzzy_matched(metadata):
    assert (
        model_metadata.model_metadata(
            f"custom",
            f"https://gateway.example/v1",
            f"qwen3.8-max-fake",
        )
        == []
    )


async def test_local_models_do_not_use_cloud_templates(metadata):
    provider = custom_provider()
    provider.is_local = True
    info = (await provider.get_info()).extra_models[0]
    assert info.max_output_length is None
    assert info.context_length_source != f"template"


def test_refresh_is_cached_and_failed_refresh_keeps_last_good(
    metadata,
    monkeypatch,
):
    download = Mock(return_value=json.dumps(metadata).encode())
    monkeypatch.setattr(model_catalog, f"_download_bytes", download)
    model_catalog.update_model_metadata()
    model_catalog.update_model_metadata()
    download.assert_called_once()
    cached = model_catalog.METADATA_CACHE_PATH.read_bytes()
    monkeypatch.setattr(model_catalog, f"METADATA_REFRESH_INTERVAL", 0)
    download.return_value = b"{}"
    with pytest.raises(ValueError):
        model_catalog.update_model_metadata()
    assert model_catalog.METADATA_CACHE_PATH.read_bytes() == cached
    assert model_metadata.model_metadata(f"custom", f"", f"qwen3.8-max")


def test_corrupt_cache_falls_back_to_packaged(metadata):
    model_catalog.METADATA_CACHE_PATH.write_text(f"broken", encoding=f"utf-8")
    assert model_metadata.model_metadata(f"custom", f"", f"qwen3.8-max")


def test_invalid_limits_are_not_used(metadata, monkeypatch):
    download = Mock(
        return_value=json.dumps(
            {
                f"openai": {
                    f"models": {
                        f"bad": {
                            f"limit": {
                                f"context": True,
                                f"output": -1,
                            },
                        },
                    },
                },
            },
        ).encode(),
    )
    monkeypatch.setattr(model_catalog, f"_download_bytes", download)
    with pytest.raises(ValueError):
        model_catalog.update_model_metadata()


async def test_deployment_alias_can_select_template(metadata):
    provider = OpenAIProvider(
        id=f"gateway",
        name=f"Gateway",
        is_custom=True,
        base_url=f"https://gateway.example/v1",
        extra_models=[
            ModelInfo(
                id=f"deployment-123",
                name=f"Deployment",
                template_id=f"alibaba-cn/qwen3.8-max",
            ),
        ],
    )
    info = (await provider.get_info()).extra_models[0]
    assert info.id == f"deployment-123"
    assert info.effective_max_input_length == 1_000_000
    assert info.max_output_length == 131_072
    assert info.billing == f"unknown"
    assert not info.is_free


def test_ambiguous_template_does_not_pick_first_owner(metadata):
    path = model_catalog.PACKAGED_CATALOG_PATH
    document = json.loads(path.read_text())
    document[f"providers"][f"openai"][f"models"].append(
        {
            f"id": f"qwen3.8-max",
            f"name": f"Conflicting name",
            f"max_input_length": 32_000,
        },
    )
    path.write_text(json.dumps(document))
    assert (
        model_metadata.model_metadata(
            f"gateway",
            f"https://gateway.example/v1",
            f"qwen3.8-max",
        )
        == []
    )


async def test_input_limit_constrains_total_context(metadata):
    provider = custom_provider(
        input_token_limit=80_000,
        input_token_limit_source=f"api",
    )
    info = (await provider.get_info()).extra_models[0]
    assert info.automatic_max_input_length == 80_000
    assert info.context_length_source == f"api"
    assert info.input_token_limit == 80_000
    assert info.effective_max_input_length == 80_000
    assert provider.get_context_size(info.id) == 80_000


async def test_preview_api_output_beats_template_for_unconfigured_model(
    metadata,
):
    provider = custom_provider()
    provider.extra_models = []
    provider.discovered_models = [
        ModelInfo(
            id=f"qwen3.8-max",
            name=f"Qwen",
            max_output_length=4096,
            max_output_length_source=f"api",
        ),
    ]
    resolved = resolve_model_info(
        provider,
        ModelInfo(id=f"qwen3.8-max", name=f"Qwen"),
        provider.discovered_models[0],
    )
    assert resolved.max_output_length == 4096
    assert resolved.max_output_length_source == f"api"


def test_remote_update_keeps_documented_provider_limits(metadata, monkeypatch):
    path = model_catalog.PACKAGED_CATALOG_PATH
    document = json.loads(path.read_text())
    model = document[f"providers"][f"alibaba-cn"][f"models"][0]
    model[f"max_input_length"] = 200_000
    model[f"capability_provenance"] = {
        f"max_input_length": {
            f"source": f"documentation",
            f"reference": f"https://docs.example",
        },
    }
    path.write_text(json.dumps(document))
    monkeypatch.setattr(
        model_catalog,
        f"_download_bytes",
        lambda *args: json.dumps(metadata).encode(),
    )
    model_catalog.update_model_metadata()
    provider = custom_provider()
    assert provider.get_context_size(f"qwen3.8-max") == 200_000
    provider.extra_models[0].max_input_length_auto_detected = 64_000
    assert provider.get_context_size(f"qwen3.8-max") == 64_000
