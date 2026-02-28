from __future__ import annotations

import pytest
from agentscope.agent import ReActAgent
from agentscope.message import Msg, TextBlock

from copaw.agents.image_understanding import (
    run_media_understanding_prepass,
    select_media_blocks_for_prepass,
)
from copaw.agents.react_agent import CoPawAgent
from copaw.providers.models import ResolvedModelConfig, VisionSettings


def _image_block(url: str = "https://example.com/a.png") -> dict:
    return {"type": "image", "image": {"url": url}}


def _msg_with_images(count: int = 1) -> Msg:
    blocks = [TextBlock(type="text", text="describe")] + [_image_block() for _ in range(count)]
    return Msg(name="user", role="user", content=blocks)


def _msg_with_audio() -> Msg:
    blocks = [
        TextBlock(type="text", text="transcribe"),
        {"type": "audio", "source": {"type": "url", "url": "https://example.com/a.mp3"}},
    ]
    return Msg(name="user", role="user", content=blocks)


def _msg_with_video() -> Msg:
    blocks = [
        TextBlock(type="text", text="analyze"),
        {"type": "video", "source": {"type": "url", "url": "https://example.com/a.mp4"}},
    ]
    return Msg(name="user", role="user", content=blocks)


def test_select_image_blocks_for_prepass_modes() -> None:
    blocks = [_image_block("a"), _image_block("b"), _image_block("c")]
    assert len(select_media_blocks_for_prepass(blocks, mode="first", max_items=3)) == 1
    assert len(select_media_blocks_for_prepass(blocks, mode="all", max_items=2)) == 2


@pytest.mark.asyncio
async def test_run_image_understanding_prepass_uses_fallback() -> None:
    msg = _msg_with_images(2)
    primary_cfg = ResolvedModelConfig(provider_id="p1", model="m1")
    fallback_cfg = ResolvedModelConfig(provider_id="p2", model="m2")

    async def _run_with_runtime_model(runtime_model, _msg, _timeout) -> str:
        if runtime_model == "primary":
            raise RuntimeError("primary failed")
        return "The image shows a cat sitting on a desk."

    result = await run_media_understanding_prepass(
        msg=msg,
        capability="image",
        enabled=True,
        attachments_mode="all",
        max_items=2,
        prompt_override="",
        timeout_seconds=30,
        max_output_chars=4000,
        active_vlm_cfg=primary_cfg,
        vlm_fallback_models=[(fallback_cfg, "fallback")],
        active_vlm_model="primary",
        run_with_runtime_model=_run_with_runtime_model,
    )
    assert result.decision.outcome == "success"
    assert result.used is not None
    assert result.used.provider_id == "p2"
    assert result.decision.selected_item_count == 2
    assert "cat" in (result.analysis or "")


@pytest.mark.asyncio
async def test_run_image_understanding_prepass_disabled() -> None:
    async def _dummy_runtime(_runtime_model, _msg, _timeout):
        return ""

    result = await run_media_understanding_prepass(
        msg=_msg_with_images(1),
        capability="image",
        enabled=False,
        attachments_mode="first",
        max_items=1,
        prompt_override="",
        timeout_seconds=30,
        max_output_chars=4000,
        active_vlm_cfg=None,
        vlm_fallback_models=[],
        active_vlm_model=None,
        run_with_runtime_model=_dummy_runtime,
    )
    assert result.decision.outcome == "disabled"


@pytest.mark.asyncio
async def test_run_audio_video_understanding_prepass_success() -> None:
    async def _runtime_ok(_runtime_model, _msg, _timeout):
        return "Audio/video content transcribed successfully."

    cfg = ResolvedModelConfig(provider_id="p1", model="m1")
    audio_result = await run_media_understanding_prepass(
        msg=_msg_with_audio(),
        capability="audio",
        enabled=True,
        attachments_mode="first",
        max_items=1,
        prompt_override="",
        timeout_seconds=30,
        max_output_chars=4000,
        active_vlm_cfg=cfg,
        vlm_fallback_models=[],
        active_vlm_model="primary",
        run_with_runtime_model=_runtime_ok,
    )
    assert audio_result.decision.outcome == "success"

    video_result = await run_media_understanding_prepass(
        msg=_msg_with_video(),
        capability="video",
        enabled=True,
        attachments_mode="first",
        max_items=1,
        prompt_override="",
        timeout_seconds=30,
        max_output_chars=4000,
        active_vlm_cfg=cfg,
        vlm_fallback_models=[],
        active_vlm_model="primary",
        run_with_runtime_model=_runtime_ok,
    )
    assert video_result.decision.outcome == "success"


@pytest.mark.asyncio
async def test_reply_entry_runs_prepass_and_injects(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = CoPawAgent.__new__(CoPawAgent)
    agent.command_handler = type(
        "Cmd",
        (),
        {
            "is_command": staticmethod(lambda _q: False),
            "handle_command": staticmethod(lambda _q: None),
        },
    )()
    agent._active_llm_cfg = ResolvedModelConfig(provider_id="p0", model="text-only")
    agent._active_vlm_cfg = ResolvedModelConfig(provider_id="p1", model="m1")
    agent._active_vlm_fallback_cfgs = []
    agent._vision_settings = VisionSettings()
    agent._vlm_model = "primary-model"
    agent._vlm_fallback_models = []
    agent._instance_pre_reply_hooks = {}
    agent._instance_post_reply_hooks = {}

    class _FakeMemory:
        content = []
    object.__setattr__(agent, "memory", _FakeMemory())

    async def _noop_process(_msg):
        return None

    async def _fake_runtime(_runtime_model, _msg, _timeout):
        return "A document with text visible."

    async def _fake_super_reply(self, msg=None, structured_model=None):  # noqa: ARG001
        assert isinstance(msg, Msg)
        text = msg.get_text_content()
        assert "[Image]" in text or "Description" in text
        return msg

    import copaw.agents.react_agent as react_agent_module

    monkeypatch.setattr(
        react_agent_module,
        "process_file_and_media_blocks_in_message",
        _noop_process,
    )
    monkeypatch.setattr(agent, "_run_runtime_prepass", _fake_runtime)
    monkeypatch.setattr(ReActAgent, "reply", _fake_super_reply)
    monkeypatch.setattr(CoPawAgent, "_class_pre_reply_hooks", {}, raising=False)
    monkeypatch.setattr(CoPawAgent, "_class_post_reply_hooks", {}, raising=False)

    out = await agent.reply(msg=_msg_with_images(1))
    assert isinstance(out, Msg)
    text = out.get_text_content()
    assert "[Image]" in text or "Description" in text


def test_reply_injects_failure_on_non_success() -> None:
    agent = CoPawAgent.__new__(CoPawAgent)
    msg = _msg_with_images(1)
    updated = agent._inject_vlm_failure_for_llm(msg, "disabled")
    assert isinstance(updated, Msg) or isinstance(updated, list) or updated is not None
    text = msg.get_text_content()
    assert "VisionPrepassFailed" in text
