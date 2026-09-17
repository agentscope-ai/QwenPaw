# -*- coding: utf-8 -*-
import json
import asyncio

from qwenpaw.agents.skill_runtime import (
    SkillIntentRouter,
    discover_enabled_skills,
    load_skill,
)
from qwenpaw.config.context import (
    set_current_channel_name,
    set_current_workspace_dir,
)


def _write_skill(
    workspace,
    name,
    description,
    *,
    enabled=True,
    channels=None,
):
    skill_dir = workspace / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        (
            "---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            "---\n\n"
            f"# {name}\n\nFollow {name} instructions.\n"
        ),
        encoding="utf-8",
    )
    manifest = workspace / "skill.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
    else:
        data = {"version": 1, "skills": {}}
    data["skills"][name] = {
        "enabled": enabled,
        "channels": channels or ["all"],
    }
    manifest.write_text(
        json.dumps(data, ensure_ascii=False),
        encoding="utf-8",
    )


def _router(workspace):
    skills = discover_enabled_skills(workspace, "console")
    return SkillIntentRouter(skills)


def test_slash_skills_invocation_matches_enabled_skill(tmp_path):
    _write_skill(tmp_path, "imagegen", "Generate or edit raster images.")

    route = _router(tmp_path).route("/skills imagegen 画小猫")

    assert route is not None
    assert route.kind == "invoke"
    assert route.skill.name == "imagegen"
    assert route.args == "画小猫"
    assert route.reason == "skills_invoke"


def test_bare_skill_name_matches_enabled_skill(tmp_path):
    _write_skill(tmp_path, "imagegen", "Generate or edit raster images.")

    route = _router(tmp_path).route("imagegen 帮我画一张小猫")

    assert route is not None
    assert route.kind == "invoke"
    assert route.skill.name == "imagegen"
    assert route.args == "帮我画一张小猫"
    assert route.reason == "bare_skill_name"


def test_explicit_chinese_invocation_matches_enabled_skill(tmp_path):
    _write_skill(tmp_path, "imagegen", "Generate or edit raster images.")

    route = _router(tmp_path).route("调用 imagegen 帮我生成图片")

    assert route is not None
    assert route.kind == "invoke"
    assert route.skill.name == "imagegen"
    assert route.reason == "explicit_skill_name"


def test_inline_slash_skill_selection_bypasses_semantic_ambiguity(tmp_path):
    _write_skill(
        tmp_path,
        "docx",
        "Create or edit professional documents and artifacts.",
    )
    _write_skill(tmp_path, "imagegen", "Generate or edit raster images.")
    _write_skill(
        tmp_path,
        "nano-banana-pro-1.0.1",
        "Generate and edit images with Nano Banana Pro.",
    )

    route = _router(tmp_path).route("调用 /imagegen 帮我生成一张小猫的图片")

    assert route is not None
    assert route.kind == "invoke"
    assert route.skill.name == "imagegen"
    assert route.args == "帮我生成一张小猫的图片"
    assert route.reason == "inline_slash_skill"


def test_semantic_image_request_matches_image_skill_description(tmp_path):
    _write_skill(tmp_path, "imagegen", "Generate or edit raster images.")

    route = _router(tmp_path).route("我想画一张小猫的图片")

    assert route is not None
    assert route.kind == "invoke"
    assert route.skill.name == "imagegen"
    assert route.reason == "semantic_description"


def test_image_semantic_does_not_promote_document_skill_by_weak_image_terms(
    tmp_path,
):
    _write_skill(
        tmp_path,
        "docx",
        (
            "Create Word documents. Also supports inserting or replacing "
            "images in documents."
        ),
    )
    _write_skill(tmp_path, "imagegen", "Generate or edit raster images.")
    _write_skill(
        tmp_path,
        "nano-banana-pro-1.0.1",
        "Generate and edit images with Nano Banana Pro.",
    )

    route = _router(tmp_path).route("帮我画一只小猫的图片")

    assert route is not None
    assert route.kind == "clarify"
    assert route.reason == "semantic_ambiguous"
    assert {skill.name for skill in route.skills} == {
        "imagegen",
        "nano-banana-pro-1.0.1",
    }


def test_document_image_request_can_still_match_docx(tmp_path):
    _write_skill(
        tmp_path,
        "docx",
        (
            "Create Word documents. Also supports inserting or replacing "
            "images in documents."
        ),
    )
    _write_skill(tmp_path, "imagegen", "Generate or edit raster images.")

    route = _router(tmp_path).route("在 Word 文档里替换图片")

    assert route is not None
    assert route.kind == "invoke"
    assert route.skill.name == "docx"


def test_semantic_presentation_request_matches_pptx(tmp_path):
    _write_skill(tmp_path, "pptx", "Create PowerPoint presentations.")
    _write_skill(tmp_path, "docx", "Create Word documents.")

    route = _router(tmp_path).route("帮我做一个 20 页 PPT")

    assert route is not None
    assert route.kind == "invoke"
    assert route.skill.name == "pptx"


def test_semantic_spreadsheet_request_matches_xlsx(tmp_path):
    _write_skill(tmp_path, "xlsx", "Create and edit Excel spreadsheets.")
    _write_skill(tmp_path, "docx", "Create Word documents.")

    route = _router(tmp_path).route("读取这个表格并生成统计图")

    assert route is not None
    assert route.kind == "invoke"
    assert route.skill.name == "xlsx"


def test_ambiguous_semantic_match_asks_user_to_choose(tmp_path):
    _write_skill(tmp_path, "imagegen", "Generate or edit raster images.")
    _write_skill(tmp_path, "poster", "Generate image posters.")

    route = _router(tmp_path).route("我想画一张小猫的图片")

    assert route is not None
    assert route.kind == "clarify"
    assert route.reason == "semantic_ambiguous"
    assert {skill.name for skill in route.skills} == {"imagegen", "poster"}


def test_load_skill_rejects_disabled_skill(tmp_path):
    _write_skill(
        tmp_path,
        "imagegen",
        "Generate or edit raster images.",
        enabled=False,
    )
    set_current_workspace_dir(tmp_path)
    set_current_channel_name("console")

    response = asyncio.run(load_skill("imagegen", "画小猫"))
    text = response.content[0].text

    assert "not enabled" in text


def test_load_skill_includes_skill_relative_runtime_context(tmp_path):
    _write_skill(tmp_path, "imagegen", "Generate or edit raster images.")
    set_current_workspace_dir(tmp_path)
    set_current_channel_name("console")

    response = asyncio.run(load_skill("imagegen", "画小猫"))
    payload = json.loads(response.content[0].text)

    assert payload["skill_dir"].endswith("imagegen")
    assert "Relative paths in SKILL.md are resolved from skill_dir" in payload[
        "runtime_note"
    ]
    assert "This skill is installed at" in payload["prompt"]
    assert "relative to that skill directory" in payload["prompt"]
