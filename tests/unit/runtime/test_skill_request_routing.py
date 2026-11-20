# -*- coding: utf-8 -*-
from types import SimpleNamespace

from agentscope.message import Msg, TextBlock

from qwenpaw.runtime.skill_routing import prepare_skill_request
from qwenpaw.agents.skill_runtime import SkillMeta
import pytest


def test_slash_command_injection_does_not_preload_the_skill_body(tmp_path):
    from qwenpaw.runtime.builtin_commands import _build_skill_injection
    prompt=_build_skill_injection('/custom do work','custom','Custom workflow',tmp_path,'SECRET_SKILL_BODY')
    assert 'SECRET_SKILL_BODY' not in prompt
    assert 'load_skill' in prompt


@pytest.mark.parametrize("query", ["/skills", "/imagegen"])
def test_non_invocation_routes_return_a_real_response(tmp_path, monkeypatch, query):
    from qwenpaw.runtime import skill_routing

    skills = [
        SkillMeta(
            name,
            name,
            "Generate raster images.",
            tmp_path / name,
            tmp_path / name / "SKILL.md",
        )
        for name in ["imagegen", "poster"]
    ]
    monkeypatch.setattr(skill_routing, "discover_enabled_skills", lambda *_: skills)
    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.resolve_effective_skills",
        lambda *_: ["imagegen", "poster"],
    )
    ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        request=SimpleNamespace(channel="console"),
        input_msgs=[Msg(name="user", role="user", content=[TextBlock(text=query)])],
    )
    response = skill_routing.skill_routing_response(ctx)
    assert response is not None
    text = response.get_text_content()
    assert "imagegen" in text


def test_poster_request_loads_enabled_skill_in_actual_runtime(tmp_path, monkeypatch):
    directory = tmp_path / "skills" / "imagegen"
    directory.mkdir(parents=True)
    markdown = directory / "SKILL.md"
    markdown.write_text(
        "---\nname: imagegen\ndescription: Generate raster images and posters.\n---\nRun scripts/image_gen.py and send the image.\n",
        encoding="utf-8",
    )
    meta = SkillMeta(
        "imagegen",
        "imagegen",
        "Generate raster images and posters.",
        directory,
        markdown,
    )
    monkeypatch.setattr(
        "qwenpaw.runtime.skill_routing.discover_enabled_skills", lambda *_: [meta]
    )
    injections = []
    ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        input_msgs=[
            Msg(name="user", role="user", content=[TextBlock(text="帮我生成一张成都市的宣传海报")])
        ],
        request=SimpleNamespace(channel="console"),
        inject_context=lambda content, **_: injections.append(content),
    )
    guard = prepare_skill_request(ctx, ["imagegen"])
    assert guard is not None
    assert "load_skill" in injections[0]
    assert "enabled skill" in injections[0]
    assert "scripts/image_gen.py" not in injections[0]
    assert str(directory) not in injections[0]


def test_disabled_skill_is_not_injected(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.runtime.skill_routing.discover_enabled_skills", lambda *_: []
    )
    ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        input_msgs=[
            Msg(name="user", role="user", content=[TextBlock(text="/imagegen")])
        ],
        request=SimpleNamespace(channel="console"),
        inject_context=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("disabled skill loaded")
        ),
    )
    assert prepare_skill_request(ctx, []) is None


def test_default_agent_file_request_still_requires_actual_delivery(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "qwenpaw.runtime.skill_routing.discover_enabled_skills", lambda *_: []
    )
    injections = []
    ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        input_msgs=[
            Msg(name="user", role="user", content=[TextBlock(text="生成一份PDF报告并发送给我")])
        ],
        request=SimpleNamespace(channel="console"),
        inject_context=lambda text, **_: injections.append(text),
    )
    guard = prepare_skill_request(ctx, [])
    assert guard is not None
    assert not guard.delivered
    assert "send_file_to_user" in injections[0]


@pytest.mark.parametrize(
    "is_subtask,allowed,expected",
    [(True, ("read_file", "view_image"), False), (True, ("send_file_to_user",), True),
     (False, ("read_file",), True), (True, None, True)],
)
def test_delegated_worker_can_return_an_intermediate_path(tmp_path, monkeypatch, is_subtask, allowed, expected):
    from qwenpaw.app.console_delegation import current_delegation

    monkeypatch.setattr("qwenpaw.runtime.skill_routing.discover_enabled_skills", lambda *_: [])
    ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        input_msgs=[Msg(name="user", role="user", content=[TextBlock(text="Generate slide 1 using slide_07.png")])],
        request=SimpleNamespace(channel="console", request_context={"_spawn_subagent": True}),
        inject_context=lambda *_args, **_kwargs: None,
    )
    token = current_delegation.set(SimpleNamespace(is_subtask=is_subtask, tools=allowed))
    try:
        assert (prepare_skill_request(ctx, []) is not None) is expected
    finally:
        current_delegation.reset(token)


def test_slash_skill_body_cannot_turn_information_request_into_generation(
    tmp_path, monkeypatch
):
    directory = tmp_path / "imagegen"
    directory.mkdir()
    (directory / "SKILL.md").write_text(
        "---\nname: imagegen\n---\nGenerate images.", encoding="utf-8"
    )
    meta = SkillMeta(
        "imagegen", "imagegen", "Generate images.", directory, directory / "SKILL.md"
    )
    monkeypatch.setattr(
        "qwenpaw.runtime.skill_routing.discover_enabled_skills", lambda *_: [meta]
    )
    ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        request=SimpleNamespace(channel="console"),
        input_msgs=[
            Msg(
                name="user",
                role="user",
                content=[
                    TextBlock(
                        text="/imagegen 解释功能\n\n<skill>\n<content>生成海报并发送图片</content>\n</skill>"
                    )
                ],
            )
        ],
        inject_context=lambda *_a, **_k: None,
    )
    assert prepare_skill_request(ctx, ["imagegen"]) is None


def test_continuation_preserves_pending_skill_and_delivery_requirement(
    tmp_path, monkeypatch
):
    directory = tmp_path / "imagegen"
    directory.mkdir()
    (directory / "SKILL.md").write_text(
        "---\nname: imagegen\n---\nGenerate images.", encoding="utf-8"
    )
    meta = SkillMeta(
        "imagegen", "imagegen", "Generate images.", directory, directory / "SKILL.md"
    )
    monkeypatch.setattr(
        "qwenpaw.runtime.skill_routing.discover_enabled_skills", lambda *_: [meta]
    )
    injections = []
    ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        request=SimpleNamespace(channel="console"),
        mode_state={},
        input_msgs=[Msg(name="user", role="user", content=[TextBlock(text="生成宣传海报")])],
        inject_context=lambda text, **_: injections.append(text),
    )
    first = prepare_skill_request(ctx, ["imagegen"])
    assert first is not None
    assert ctx.mode_state["skill_routing"]["skill"] is None
    # Only a successful load_skill response records the agent's selection.
    ctx.mode_state["skill_routing"]["skill"] = "imagegen"
    ctx.input_msgs = [Msg(name="user", role="user", content=[TextBlock(text="继续")])]
    assert prepare_skill_request(ctx, ["imagegen"]) is not None
    assert "imagegen" in injections[-1]
    # A disabled skill cannot be recovered from a prior turn's state.
    assert prepare_skill_request(ctx, []) is None


def test_approval_continuation_recovers_ppt_intent_after_outline_only_turn(
    tmp_path, monkeypatch
):
    directory = tmp_path / "codex-ppt"
    directory.mkdir()
    (directory / "SKILL.md").write_text(
        "---\nname: codex-ppt\n---\nGenerate PPT after outline approval.",
        encoding="utf-8",
    )
    meta = SkillMeta(
        "codex-ppt",
        "codex-ppt",
        "Generate PPT presentations.",
        directory,
        directory / "SKILL.md",
    )
    monkeypatch.setattr(
        "qwenpaw.runtime.skill_routing.discover_enabled_skills", lambda *_: [meta]
    )
    ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        request=SimpleNamespace(channel="console"),
        mode_state={},
        input_msgs=[
            Msg(
                name="user",
                role="user",
                content=[TextBlock(text="制作2页PPT演示文稿。此轮先整理大纲，不要生成成品，等待确认。")],
            )
        ],
        inject_context=lambda *_a, **_k: None,
    )
    assert prepare_skill_request(ctx, ["codex-ppt"]) is None
    ctx.input_msgs = [Msg(name="user", role="user", content=[TextBlock(text="确认")])]
    assert prepare_skill_request(ctx, ["codex-ppt"]) is not None
    assert ctx.skill_load_required


def test_explicit_image_skill_invocation_without_format_word_still_requires_image(
    tmp_path, monkeypatch
):
    directory = tmp_path / "imagegen"
    directory.mkdir()
    (directory / "SKILL.md").write_text(
        "---\nname: imagegen\n---\nGenerate or edit images.", encoding="utf-8"
    )
    meta = SkillMeta(
        "imagegen",
        "imagegen",
        "Generate or edit images.",
        directory,
        directory / "SKILL.md",
    )
    monkeypatch.setattr(
        "qwenpaw.runtime.skill_routing.discover_enabled_skills", lambda *_: [meta]
    )
    ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        request=SimpleNamespace(channel="console"),
        input_msgs=[
            Msg(name="user", role="user", content=[TextBlock(text="/imagegen 画小猫")])
        ],
        inject_context=lambda *_a, **_k: None,
    )
    assert prepare_skill_request(ctx, ["imagegen"]) is not None
