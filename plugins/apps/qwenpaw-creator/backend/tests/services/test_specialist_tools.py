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


# ---------------------------------------------------------------------------
# S2V specialist tool registration
# ---------------------------------------------------------------------------


def _s2v_registry() -> FileSpecialistToolRegistry:
    return FileSpecialistToolRegistry.__new__(FileSpecialistToolRegistry)


def _s2v_tool_names(registry, role, refs) -> list[str]:
    return [
        item["function"]["name"]
        for item in registry.manifest_for(role, admitted_target_refs=refs)
    ]


def _clear_keys(monkeypatch) -> None:
    monkeypatch.delenv("S2V_API_KEY", raising=False)
    monkeypatch.delenv("TEXT_API_KEY", raising=False)
    monkeypatch.delenv("CREATOR_DATA_ROOT", raising=False)
    monkeypatch.delenv("CREATOR_MODEL_CONFIG_PATH", raising=False)


def test_s2v_tool_absent_without_configuration(monkeypatch) -> None:
    _clear_keys(monkeypatch)
    registry = _s2v_registry()
    names = _s2v_tool_names(
        registry,
        SpecialistRole.R2V_GENERATION_DIRECTOR,
        ("element:r2v-1",),
    )
    assert "s2v_generation" not in names
    # Unregistered tools resolve as unknown, not as a permission error.
    assert (
        registry.spec_for(
            SpecialistRole.R2V_GENERATION_DIRECTOR,
            "s2v_generation",
        )
        is None
    )


def test_s2v_tool_registered_with_key(monkeypatch) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setenv("S2V_API_KEY", "sk-test")
    registry = _s2v_registry()
    names = _s2v_tool_names(
        registry,
        SpecialistRole.R2V_GENERATION_DIRECTOR,
        ("element:r2v-1",),
    )
    assert "s2v_generation" in names

    spec = registry.spec_for(
        SpecialistRole.R2V_GENERATION_DIRECTOR,
        "s2v_generation",
    )
    assert spec is not None
    assert spec.requires_execution_authorization is True
    assert spec.long_running is True
    assert spec.wait.value == "TASK"
    assert spec.provider_kind == "s2v"
    arguments = spec.parameters["properties"]["arguments"]
    # Refs default from the s2v element's declared portrait/audio, so the
    # tool call itself has no required arguments.
    assert set(arguments["required"]) == set()
    assert arguments["properties"]["resolution"]["enum"] == ["480P", "720P"]


def test_s2v_tool_registers_via_reused_llm_key(monkeypatch) -> None:
    """The TTS gating pattern: the shared DashScope credential unlocks it."""

    _clear_keys(monkeypatch)
    monkeypatch.setenv("TEXT_API_KEY", "sk-shared")
    registry = _s2v_registry()
    names = _s2v_tool_names(
        registry,
        SpecialistRole.R2V_GENERATION_DIRECTOR,
        ("element:r2v-1",),
    )
    assert "s2v_generation" in names


def test_s2v_tool_stays_role_scoped(monkeypatch) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setenv("S2V_API_KEY", "sk-test")
    registry = _s2v_registry()
    for role, refs in (
        (SpecialistRole.VISUAL_DEVELOPMENT, ("project:assets",)),
        (SpecialistRole.AI_EDITING_DIRECTOR, ("timeline:t1",)),
        (SpecialistRole.SOURCE_INTELLIGENCE, ("asset:source-1",)),
    ):
        assert "s2v_generation" not in _s2v_tool_names(registry, role, refs)
    with pytest.raises(PermissionDeniedError):
        registry.spec_for(SpecialistRole.VISUAL_DEVELOPMENT, "s2v_generation")
