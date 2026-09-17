# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Dynamic registration of the TTS specialist tools."""

from __future__ import annotations

import pytest

from domain.enums import SpecialistRole
from domain.errors import PermissionDeniedError
from services.specialist_tools import FileSpecialistToolRegistry


def _registry() -> FileSpecialistToolRegistry:
    return FileSpecialistToolRegistry.__new__(FileSpecialistToolRegistry)


def _tool_names(registry, role, refs) -> list[str]:
    return [
        item["function"]["name"]
        for item in registry.manifest_for(role, admitted_target_refs=refs)
    ]


def test_tts_tools_absent_without_configuration(monkeypatch) -> None:
    monkeypatch.delenv("TTS_API_KEY", raising=False)
    registry = _registry()
    names = _tool_names(
        registry,
        SpecialistRole.VISUAL_DEVELOPMENT,
        ("project:assets",),
    )
    assert "tts_generation" not in names
    assert "create_character_voice" not in names
    # Unregistered tools resolve as unknown, not as a permission error.
    assert (
        registry.spec_for(SpecialistRole.VISUAL_DEVELOPMENT, "tts_generation")
        is None
    )


def test_tts_tools_registered_per_role_with_key(monkeypatch) -> None:
    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    registry = _registry()
    visual = _tool_names(
        registry,
        SpecialistRole.VISUAL_DEVELOPMENT,
        ("project:assets",),
    )
    assert "tts_generation" in visual
    assert "create_character_voice" in visual

    editing = _tool_names(
        registry,
        SpecialistRole.AI_EDITING_DIRECTOR,
        ("timeline:t1",),
    )
    assert "tts_generation" in editing
    assert "create_character_voice" not in editing

    spec = registry.spec_for(
        SpecialistRole.VISUAL_DEVELOPMENT,
        "tts_generation",
    )
    assert spec is not None
    assert spec.requires_execution_authorization is True
    assert spec.provider_kind == "tts"


def test_tts_tools_stay_role_scoped(monkeypatch) -> None:
    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    registry = _registry()
    names = _tool_names(
        registry,
        SpecialistRole.SOURCE_INTELLIGENCE,
        ("asset:a1",),
    )
    assert "tts_generation" not in names
    with pytest.raises(PermissionDeniedError):
        registry.spec_for(
            SpecialistRole.SOURCE_INTELLIGENCE,
            "create_character_voice",
        )


def test_voice_enrollment_admits_asset_children_of_project_assets(
    monkeypatch,
) -> None:
    """A project:assets-scoped visual run must reach asset:<char> targets."""

    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    registry = _registry()
    spec = registry.spec_for(
        SpecialistRole.VISUAL_DEVELOPMENT,
        "create_character_voice",
    )
    assert spec is not None
    assert spec.admits_target_ref(
        role=SpecialistRole.VISUAL_DEVELOPMENT,
        target_ref="asset:char:crow",
        admitted_target_refs=("project:assets",),
    )
    assert not spec.admits_target_ref(
        role=SpecialistRole.VISUAL_DEVELOPMENT,
        target_ref="project:assets",
        admitted_target_refs=("project:assets",),
    )
    params = spec.parameters["properties"]["arguments"]["properties"]
    assert "characterRef" in params
