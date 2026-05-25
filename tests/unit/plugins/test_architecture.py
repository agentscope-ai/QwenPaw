# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.plugins.architecture``.

Covers the Pydantic-based ``PluginManifest`` model:
- All real ``plugin.json`` files in ``plugins/`` parse successfully.
- Explicit ``type`` wins over inference.
- ``type`` inference from ``meta`` / ``entry`` for legacy manifests.
- Required-field validation (``id``, ``version``).
- Localised ``name`` / ``description`` are coerced to display strings.
- Legacy ``entry_point`` is mapped to ``entry.backend``.
- Unknown top-level fields (``description_i18n``, ``publish``) are
  silently ignored.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from qwenpaw.plugins.architecture import (
    PluginEntryPoints,
    PluginManifest,
    PluginType,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGINS_DIR = REPO_ROOT / "plugins"


def _discover_plugin_manifests() -> list[Path]:
    """Return every ``plugin.json`` shipped under ``plugins/``."""
    if not PLUGINS_DIR.is_dir():
        return []
    return sorted(PLUGINS_DIR.glob("**/plugin.json"))


@pytest.mark.parametrize(
    "manifest_path",
    _discover_plugin_manifests(),
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_real_plugin_json_parses(manifest_path: Path) -> None:
    """Every shipped ``plugin.json`` must parse without error."""
    with manifest_path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)

    manifest = PluginManifest.from_dict(data)

    assert manifest.id == data["id"]
    assert manifest.version == data["version"]
    # At least one entry point must end up populated.
    assert manifest.entry.backend or manifest.entry.frontend


def test_explicit_type_wins_over_inference() -> None:
    """A declared ``type`` is used verbatim even if ``meta`` disagrees."""
    manifest = PluginManifest.from_dict(
        {
            "id": "demo",
            "version": "1.0.0",
            "type": "general",
            "entry": {"backend": "plugin.py"},
            # meta hints at a tool but `type` says general
            "meta": {"tools": [{"name": "do_it"}]},
        },
    )
    assert manifest.plugin_type is PluginType.GENERAL


@pytest.mark.parametrize(
    ("meta", "entry", "expected"),
    [
        ({"tools": [{"name": "x"}]}, {"backend": "p.py"}, PluginType.TOOL),
        ({"tool_name": "x"}, {"backend": "p.py"}, PluginType.TOOL),
        (
            {"chat_model": "OpenAIChatModel", "provider_id": "x"},
            {"backend": "p.py"},
            PluginType.PROVIDER,
        ),
        ({"hook_type": "startup"}, {"backend": "p.py"}, PluginType.HOOK),
        ({"command_name": "/x"}, {"backend": "p.py"}, PluginType.COMMAND),
        ({}, {"frontend": "dist/index.js"}, PluginType.FRONTEND),
        ({}, {"backend": "p.py"}, PluginType.GENERAL),
    ],
)
def test_type_inference_from_meta(
    meta: dict,
    entry: dict,
    expected: PluginType,
) -> None:
    """When ``type`` is missing, the model infers from meta/entry."""
    manifest = PluginManifest.from_dict(
        {
            "id": "demo",
            "version": "1.0.0",
            "entry": entry,
            "meta": meta,
        },
    )
    assert manifest.plugin_type is expected


def test_invalid_type_falls_back_to_inference() -> None:
    """An unknown ``type`` value falls back to meta-based inference."""
    manifest = PluginManifest.from_dict(
        {
            "id": "demo",
            "version": "1.0.0",
            "type": "not-a-real-type",
            "entry": {"backend": "p.py"},
            "meta": {"hook_type": "startup"},
        },
    )
    assert manifest.plugin_type is PluginType.HOOK


def test_missing_id_raises_validation_error() -> None:
    """``id`` is required."""
    with pytest.raises(ValidationError):
        PluginManifest.from_dict(
            {
                "version": "1.0.0",
                "entry": {"backend": "p.py"},
            },
        )


def test_missing_version_raises_validation_error() -> None:
    """``version`` is required."""
    with pytest.raises(ValidationError):
        PluginManifest.from_dict(
            {
                "id": "demo",
                "entry": {"backend": "p.py"},
            },
        )


def test_empty_id_raises_validation_error() -> None:
    """Empty ``id`` is rejected (must have positive length)."""
    with pytest.raises(ValidationError):
        PluginManifest.from_dict(
            {
                "id": "",
                "version": "1.0.0",
                "entry": {"backend": "p.py"},
            },
        )


def test_dependencies_wrong_type_raises() -> None:
    """``dependencies`` must be a list of strings, not a single string."""
    with pytest.raises(ValidationError):
        PluginManifest.from_dict(
            {
                "id": "demo",
                "version": "1.0.0",
                "entry": {"backend": "p.py"},
                "dependencies": "httpx>=0.24.0",
            },
        )


def test_localised_name_and_description_are_coerced() -> None:
    """i18n dicts are reduced to a single display string (English first)."""
    manifest = PluginManifest.from_dict(
        {
            "id": "demo",
            "version": "1.0.0",
            "name": {"zh-CN": "中文名", "en-US": "English Name"},
            "description": {"zh-CN": "中文描述", "en-US": "English desc"},
            "author": {"zh-CN": "作者", "en-US": "Author"},
            "entry": {"backend": "p.py"},
        },
    )
    assert manifest.name == "English Name"
    assert manifest.description == "English desc"
    assert manifest.author == "Author"


def test_localised_falls_back_to_chinese_when_english_missing() -> None:
    """Without an English value, the Chinese one is used."""
    manifest = PluginManifest.from_dict(
        {
            "id": "demo",
            "version": "1.0.0",
            "name": {"zh-CN": "仅中文"},
            "entry": {"backend": "p.py"},
        },
    )
    assert manifest.name == "仅中文"


def test_legacy_entry_point_maps_to_backend() -> None:
    """``entry_point`` (legacy) populates ``entry.backend``."""
    manifest = PluginManifest.from_dict(
        {
            "id": "demo",
            "version": "1.0.0",
            "entry_point": "plugin.py",
        },
    )
    assert manifest.entry.backend == "plugin.py"
    assert manifest.entry.frontend is None


def test_entry_block_takes_precedence_over_entry_point() -> None:
    """Explicit ``entry.backend`` is not overwritten by legacy field."""
    manifest = PluginManifest.from_dict(
        {
            "id": "demo",
            "version": "1.0.0",
            "entry": {"backend": "new.py"},
            "entry_point": "old.py",
        },
    )
    assert manifest.entry.backend == "new.py"


def test_unknown_top_level_fields_are_ignored() -> None:
    """Display-only / packaging-only fields don't trip validation."""
    manifest = PluginManifest.from_dict(
        {
            "id": "demo",
            "version": "1.0.0",
            "entry": {"backend": "p.py"},
            "description_i18n": {"zh-CN": "中文", "en-US": "English"},
            "publish": False,
            "totally_unknown": 123,
        },
    )
    assert manifest.id == "demo"
    # And the model exposes no such attributes.
    assert not hasattr(manifest, "description_i18n")
    assert not hasattr(manifest, "publish")


def test_name_defaults_to_id_when_missing() -> None:
    """Missing ``name`` falls back to ``id``."""
    manifest = PluginManifest.from_dict(
        {
            "id": "fallback-id",
            "version": "1.0.0",
            "entry": {"backend": "p.py"},
        },
    )
    assert manifest.name == "fallback-id"


def test_plugin_entry_points_default_empty() -> None:
    """Both entry slots default to ``None`` on an empty mapping."""
    entry = PluginEntryPoints()
    assert entry.backend is None
    assert entry.frontend is None
