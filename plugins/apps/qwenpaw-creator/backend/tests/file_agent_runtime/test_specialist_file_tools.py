# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

from domain.enums import SpecialistRole
from services.file_agent_runtime.subagents import specialist_system_prompt
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
from services.specialist_tools import FileSpecialistToolRegistry


def _names(manifest) -> set[str]:
    return {item["function"]["name"] for item in manifest}


def test_specialist_registry_owns_role_specific_media_tools(tmp_path) -> None:
    registry = FileSpecialistToolRegistry(
        CreatorFileServices.create(tmp_path.resolve()),
    )

    visual = _names(
        registry.manifest_for(
            SpecialistRole.VISUAL_DEVELOPMENT,
            admitted_target_refs=["asset:hero"],
        ),
    )
    r2v = _names(
        registry.manifest_for(
            SpecialistRole.R2V_GENERATION_DIRECTOR,
            admitted_target_refs=["element:r2v-1"],
        ),
    )
    editing = _names(
        registry.manifest_for(
            SpecialistRole.AI_EDITING_DIRECTOR,
            admitted_target_refs=["timeline:timeline:main"],
        ),
    )
    source = _names(
        registry.manifest_for(
            SpecialistRole.SOURCE_INTELLIGENCE,
            admitted_target_refs=["asset:source-1"],
        ),
    )

    assert "image_generation" in visual
    assert {"image_generation", "r2v_generation"} <= r2v
    # The editing director is a pure orchestration role: composition/export
    # is triggered directly by the user via HTTP endpoints.
    assert "ai_edit" not in editing
    assert "compose_final_video" not in editing
    assert {"read_project", "jq_project"} <= editing
    assert "transcribe_source_audio" in source
    assert "commit_source_intelligence" in source
    assert {"read_project", "read_project_file"} <= source
    assert "jq_project" not in source
    assert "elements_at" not in source
    assert "r2v_generation" not in visual
    assert "image_generation" not in editing


def test_source_intelligence_tools_separate_modules_from_outer_vlm_commit(
    tmp_path,
) -> None:
    registry = FileSpecialistToolRegistry(
        CreatorFileServices.create(tmp_path.resolve()),
    )
    manifest = registry.manifest_for(
        SpecialistRole.SOURCE_INTELLIGENCE,
        admitted_target_refs=["asset:source-1"],
    )
    commit = next(
        item
        for item in manifest
        if item["function"]["name"] == "commit_source_intelligence"
    )["function"]
    asr = next(
        item
        for item in manifest
        if item["function"]["name"] == "transcribe_source_audio"
    )["function"]

    assert "不会再次调用 VLM" in commit["description"]
    arguments = commit["parameters"]["properties"]["arguments"]
    assert set(arguments["required"]) == {
        "summary",
        "shots",
        "entities",
        "semanticEntries",
    }
    assert "startMs" in arguments["properties"]["shots"]["items"]["properties"]
    assert "opaque resultRef" in asr["description"]


def test_project_assets_scope_admits_image_asset_children(tmp_path) -> None:
    registry = FileSpecialistToolRegistry(
        CreatorFileServices.create(tmp_path.resolve()),
    )
    manifest = registry.manifest_for(
        SpecialistRole.VISUAL_DEVELOPMENT,
        admitted_target_refs=["project:assets"],
    )
    tool = next(
        item
        for item in manifest
        if item["function"]["name"] == "image_generation"
    )["function"]
    target = tool["parameters"]["properties"]["targetRef"]
    spec = registry.spec_for(
        SpecialistRole.VISUAL_DEVELOPMENT,
        "image_generation",
    )

    assert spec is not None
    assert "enum" not in target
    assert target["pattern"] == r"^asset:.+$"
    assert "不能直接使用 project:assets" in target["description"]
    assert spec.admits_target_ref(
        role=SpecialistRole.VISUAL_DEVELOPMENT,
        target_ref="asset:char-cat",
        admitted_target_refs=["project:assets"],
    )
    assert not spec.admits_target_ref(
        role=SpecialistRole.VISUAL_DEVELOPMENT,
        target_ref="project:assets",
        admitted_target_refs=["project:assets"],
    )
    assert not spec.admits_target_ref(
        role=SpecialistRole.VISUAL_DEVELOPMENT,
        target_ref="timeline:char-cat",
        admitted_target_refs=["project:assets"],
    )


def test_project_assets_scope_does_not_expand_for_r2v_image_tool(
    tmp_path,
) -> None:
    registry = FileSpecialistToolRegistry(
        CreatorFileServices.create(tmp_path.resolve()),
    )
    spec = registry.spec_for(
        SpecialistRole.R2V_GENERATION_DIRECTOR,
        "image_generation",
    )

    assert spec is not None
    assert not spec.admits_target_ref(
        role=SpecialistRole.R2V_GENERATION_DIRECTOR,
        target_ref="asset:char-cat",
        admitted_target_refs=["project:assets"],
    )


def test_ai_edit_rules_are_dynamic_specialist_prompt_not_runtime_state() -> (
    None
):
    project = Project.new(project_id="project-1", name="Interview")
    project.settings.content_type = "interview"
    project.settings.target_duration_seconds = 90

    prompt = specialist_system_prompt(
        SpecialistRole.AI_EDITING_DIRECTOR,
        project_id=project.project_id,
        project=project,
    )

    assert "当前内容类型是 `interview`" in prompt
    assert "60 至 120 秒" in prompt
    assert "interview_summary" in prompt
    assert "不超过 30 个汉字" in prompt
    # Pure orchestration role: the prompt must not mention removed
    # composition tools.
    assert "`ai_edit`" not in prompt
    assert "`compose_final_video`" not in prompt
    assert "operation=execute" not in prompt
    assert "本工具不生成 plan" not in prompt
