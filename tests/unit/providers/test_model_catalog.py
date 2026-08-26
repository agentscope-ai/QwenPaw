# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for packaged and remotely updated model catalogs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from qwenpaw.providers import model_catalog
from qwenpaw.providers.provider import ModelInfo


def _write_catalog(
    path: Path,
    providers: dict[str, list[dict[str, object]]],
    *,
    schema_version: int = 1,
) -> bytes:
    payload = {
        "schema_version": schema_version,
        "catalog_version": "test",
        "providers": providers,
    }
    content = json.dumps(payload).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def test_packaged_catalog_snapshot() -> None:
    catalog = model_catalog.load_model_catalog()

    assert len(catalog) == 21
    assert sum(len(models) for models in catalog.values()) == 133
    assert catalog["DASHSCOPE_MODELS"][0].id == "qwen3.8-max"
    assert catalog["DASHSCOPE_MODELS"][0].supports_image is True
    assert catalog["DASHSCOPE_MODELS"][0].thinking_enabled is True
    assert [model.id for model in catalog["DEEPSEEK_MODELS"]] == [
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    ]
    assert catalog["GEMINI_MODELS"][0].id == "gemini-3.1-pro-preview"
    assert [model.id for model in catalog["MINIMAX_MODELS"]] == [
        "MiniMax-M3",
        "MiniMax-M2.7",
        "MiniMax-M2.7-highspeed",
        "MiniMax-M2.5",
        "MiniMax-M2.5-highspeed",
        "MiniMax-M2.1",
        "MiniMax-M2.1-highspeed",
        "MiniMax-M2",
    ]
    assert catalog["MINIMAX_MODELS"][0].supports_image is True
    assert catalog["MINIMAX_MODELS"][0].supports_video is True
    recommended = {
        (provider_id, model.id)
        for provider_id, models in catalog.items()
        for model in models
        if model.is_recommended
    }
    assert recommended == {
        ("DASHSCOPE_MODELS", "qwen3.7-max"),
        ("OPENAI_MODELS", "gpt-5.2"),
        ("MINIMAX_MODELS", "MiniMax-M3"),
        ("KIMI_MODELS", "kimi-k3"),
        ("DEEPSEEK_MODELS", "deepseek-chat"),
        ("GEMINI_MODELS", "gemini-3.1-pro-preview"),
    }
    assert {
        model.id: model.max_input_length
        for model in catalog["DASHSCOPE_MODELS"]
    } == {
        "qwen3.8-max": 131_072,
        "qwen3.7-max": 1_000_000,
        "qwen3.7-plus": 1_000_000,
        "qwen3.6-plus": 1_000_000,
        "deepseek-v4-pro": 131_072,
        "glm-5.2": 1_000_000,
    }
    assert all(
        model.max_input_length == 1_048_576
        for model in catalog["GEMINI_MODELS"]
    )
    assert {
        model.id: model.max_input_length
        for model in catalog["OPENAI_MODELS"]
        if model.id in {"gpt-5.2", "gpt-4.1", "o4-mini"}
    } == {
        "gpt-5.2": 272_000,
        "gpt-4.1": 1_047_576,
        "o4-mini": 200_000,
    }
    assert {
        model.id: model.max_input_length
        for model in catalog["VOLCENGINE_CODINGPLAN_MODELS"]
        if model.id
        in {"deepseek-v4-flash", "kimi-k2.7-code", "doubao-seed-2.1-turbo"}
    } == {
        "deepseek-v4-flash": 1_048_576,
        "kimi-k2.7-code": 262_144,
        "doubao-seed-2.1-turbo": 262_144,
    }
    assert {
        model.id: model.max_input_length
        for model in catalog["VOLCENGINE_AGENTPLAN_MODELS"]
        if model.id
        in {"deepseek-v4-flash", "kimi-k2.7-code", "ark-code-latest"}
    } == {
        "deepseek-v4-flash": 1_048_576,
        "kimi-k2.7-code": 262_144,
        "ark-code-latest": 262_144,
    }
    assert {
        model.id: model.max_input_length for model in catalog["MIMO_MODELS"]
    } == {
        "mimo-v2.5-pro": 1_048_576,
        "mimo-v2.5": 1_048_576,
    }


def test_catalog_overlays_merge_fields_in_priority_order(
    tmp_path: Path,
) -> None:
    packaged = tmp_path / "packaged.json"
    ota = tmp_path / "ota.json"
    local = tmp_path / "local.json"
    _write_catalog(
        packaged,
        {
            "MODELS": [
                {
                    "id": "model-a",
                    "name": "Packaged",
                    "max_tokens": 100,
                    "supports_image": False,
                    "is_free": True,
                },
            ],
        },
    )
    _write_catalog(
        ota,
        {
            "MODELS": [
                {
                    "id": "model-a",
                    "name": "OTA",
                    "max_tokens": 200,
                },
                {"id": "model-b", "name": "Remote"},
            ],
        },
    )
    _write_catalog(
        local,
        {
            "MODELS": [
                {
                    "id": "model-a",
                    "name": "Local",
                    "supports_image": True,
                    "is_free": False,
                },
            ],
        },
    )

    models = model_catalog.load_model_catalog(packaged, ota, local)["MODELS"]

    assert [model.id for model in models] == ["model-a", "model-b"]
    assert models[0].name == "Local"
    assert models[0].max_tokens == 200
    assert models[0].supports_image is True
    assert models[0].is_free is False


@pytest.mark.parametrize(
    "content",
    [b"not-json", b'{"schema_version": 2}'],
)
def test_invalid_optional_overlay_is_ignored(
    tmp_path: Path,
    content: bytes,
) -> None:
    packaged = tmp_path / "packaged.json"
    ota = tmp_path / "ota.json"
    local = tmp_path / "missing.json"
    _write_catalog(
        packaged,
        {"MODELS": [{"id": "model-a", "name": "Packaged"}]},
    )
    ota.write_bytes(content)

    models = model_catalog.load_model_catalog(packaged, ota, local)["MODELS"]

    assert [model.name for model in models] == ["Packaged"]


def test_models_for_catalog_key_returns_independent_copies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = ModelInfo(id="model-a", name="Original")
    monkeypatch.setattr(
        model_catalog,
        "load_model_catalog",
        lambda: {"MODELS": [source]},
    )

    first = model_catalog.models_for_catalog_key("MODELS")
    second = model_catalog.models_for_catalog_key("MODELS")
    first[0].name = "Changed"

    assert source.name == "Original"
    assert second[0].name == "Original"


def test_catalog_update_validates_hash_and_replaces_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.json"
    destination = tmp_path / "cache" / "catalog.json"
    payload = _write_catalog(
        source,
        {"MODELS": [{"id": "model-a", "name": "Remote"}]},
    )
    monkeypatch.setattr(
        model_catalog,
        "_download_bytes",
        lambda _url, _timeout: payload,
    )

    document = model_catalog.update_model_catalog(
        url="https://example.invalid/catalog.json",
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        destination=destination,
    )

    assert document.catalog_version == "test"
    assert destination.read_bytes() == payload
    assert not list(destination.parent.glob("*.tmp"))


def test_catalog_update_hash_mismatch_preserves_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "catalog.json"
    destination.write_bytes(b"previous")
    monkeypatch.setattr(
        model_catalog,
        "_download_bytes",
        lambda _url, _timeout: b"replacement",
    )

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        model_catalog.update_model_catalog(
            url="https://example.invalid/catalog.json",
            expected_sha256="0" * 64,
            destination=destination,
        )

    assert destination.read_bytes() == b"previous"


def test_replace_retries_transient_windows_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.write_text("new", encoding="utf-8")
    destination.write_text("old", encoding="utf-8")
    original_replace = model_catalog.os.replace
    attempts = 0

    def flaky_replace(source_path: Path, destination_path: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("locked")
        original_replace(source_path, destination_path)

    monkeypatch.setattr(model_catalog.os, "replace", flaky_replace)
    monkeypatch.setattr(model_catalog.time, "sleep", lambda _delay: None)

    model_catalog._replace_with_retry(source, destination)

    assert attempts == 2
    assert destination.read_text(encoding="utf-8") == "new"
