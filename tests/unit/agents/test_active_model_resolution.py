# -*- coding: utf-8 -*-
"""Capability helpers must follow the model serving the current turn.

A conversation can select a model that differs from the persisted
``agent.json`` pointer.  The guarded tool wrapper publishes that model for
the duration of one tool call, and prompt construction passes it
explicitly, so ``view_image`` and the multimodal hint stop reading a stale
agent-level default (issue #8378).
"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument

from types import SimpleNamespace

import pytest
from PIL import Image

from qwenpaw.agents.prompt import (
    _get_active_model_info,
    build_multimodal_hint,
    get_active_model_multimodal_raw,
)
from qwenpaw.agents.tools.view_media import (
    _check_multimodal_support,
    view_image,
)
from qwenpaw.app.workspace.local_workspace import QwenPawLocalWorkspace
from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.config.context import scoped_effective_model
from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.provider_manager import ProviderManager
from qwenpaw.runtime.prompt_contributors import MultimodalHintContributor

TEXT_ONLY = ModelInfo(
    id="legacy-text",
    name="Legacy Text",
    supports_multimodal=False,
    supports_image=False,
    supports_video=False,
)
VISION = ModelInfo(
    id="vision-pro",
    name="Vision Pro",
    supports_multimodal=True,
    supports_image=True,
    supports_video=False,
)

TEXT_ONLY_SLOT = ModelSlotConfig(provider_id="p", model=TEXT_ONLY.id)
VISION_SLOT = ModelSlotConfig(provider_id="p", model=VISION.id)
GLOBAL_SLOT = ModelSlotConfig(provider_id="g", model="global-model")
GLOBAL_MODEL = ModelInfo(id="global-model", name="Global", supports_image=True)


@pytest.fixture
def stale_agent_model(monkeypatch):
    """Persisted agent model is text-only while the session chose vision."""
    provider = SimpleNamespace(
        id="p",
        all_models=lambda: [TEXT_ONLY, VISION],
    )
    global_provider = SimpleNamespace(
        id="g",
        all_models=lambda: [GLOBAL_MODEL],
    )
    providers = {"p": provider, "g": global_provider}
    manager = SimpleNamespace(
        get_provider=providers.get,
        get_active_model=lambda: GLOBAL_SLOT,
        active_model=GLOBAL_SLOT,
    )
    monkeypatch.setattr(ProviderManager, "_instance", manager)
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: SimpleNamespace(active_model=TEXT_ONLY_SLOT),
    )
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_current_agent_id",
        lambda: "agent",
    )
    return manager


def test_persisted_agent_model_is_the_default(stale_agent_model):
    model_info, model_name = _get_active_model_info()

    assert (model_name, model_info.id) == (TEXT_ONLY.id, TEXT_ONLY.id)
    assert _check_multimodal_support("image") is False
    assert get_active_model_multimodal_raw() is False
    assert "You can only understand text content" in build_multimodal_hint()


def test_tool_scope_overrides_persisted_agent_model(stale_agent_model):
    with scoped_effective_model(VISION_SLOT):
        model_info, model_name = _get_active_model_info()

        assert (model_name, model_info.id) == (VISION.id, VISION.id)
        assert _check_multimodal_support("image") is True
        assert get_active_model_multimodal_raw() is True
        assert build_multimodal_hint() == ""

    # The scope is per tool call; the persisted model comes back after it.
    assert _get_active_model_info()[1] == TEXT_ONLY.id


def test_explicit_slot_wins_over_tool_scope(stale_agent_model):
    with scoped_effective_model(TEXT_ONLY_SLOT):
        assert build_multimodal_hint(VISION_SLOT) == ""

    assert "You can only understand text content" in build_multimodal_hint(
        TEXT_ONLY_SLOT,
    )


@pytest.mark.asyncio
async def test_view_image_follows_tool_scope(stale_agent_model, tmp_path):
    image_path = tmp_path / "photo.png"
    Image.new("RGB", (2, 2), color="red").save(image_path)

    with scoped_effective_model(VISION_SLOT):
        result = await view_image(str(image_path))

    texts = [
        block.text
        for block in result.content
        if getattr(block, "type", None) == "text"
    ]
    assert not any(
        "does not support multimodal input" in text for text in texts
    )
    assert any(
        getattr(block, "type", None) == "data" for block in result.content
    )


@pytest.mark.asyncio
async def test_view_image_without_scope_reports_persisted_model(
    stale_agent_model,
    tmp_path,
):
    image_path = tmp_path / "photo.png"
    Image.new("RGB", (2, 2), color="red").save(image_path)

    result = await view_image(str(image_path))

    texts = [
        block.text
        for block in result.content
        if getattr(block, "type", None) == "text"
    ]
    assert any("does not support multimodal input" in text for text in texts)


@pytest.mark.asyncio
async def test_guarded_view_image_end_to_end(stale_agent_model, tmp_path):
    """Drive the real workspace -> guard -> view_image chain."""
    image_path = tmp_path / "photo.png"
    Image.new("RGB", (2, 2), color="red").save(image_path)
    registry = SimpleNamespace(
        get=lambda _name: None,
        filter=lambda **_kwargs: [SimpleNamespace(func=view_image)],
    )

    async def guarded_call(request_context):
        workspace = QwenPawLocalWorkspace(registry, workdir=str(tmp_path))
        tools = await workspace.list_tools(request_context=request_context)
        return await tools[0](image_path=str(image_path))

    stale_result = await guarded_call({})
    stale_texts = [
        block.text
        for block in stale_result.content
        if getattr(block, "type", None) == "text"
    ]
    assert any(
        "does not support multimodal input" in text for text in stale_texts
    )

    scoped_result = await guarded_call({"effective_model": VISION_SLOT})
    scoped_texts = [
        block.text
        for block in scoped_result.content
        if getattr(block, "type", None) == "text"
    ]
    assert not any(
        "does not support multimodal input" in text for text in scoped_texts
    )
    assert any(
        getattr(block, "type", None) == "data"
        for block in scoped_result.content
    )


def test_prompt_contributor_prefers_effective_model(stale_agent_model):
    ctx = SimpleNamespace(
        extras={
            "effective_model": VISION_SLOT,
            "agent_config": SimpleNamespace(active_model=TEXT_ONLY_SLOT),
        },
    )

    assert MultimodalHintContributor().contribute_sync(ctx) is None


def test_prompt_contributor_uses_agent_config_from_extras(stale_agent_model):
    ctx = SimpleNamespace(
        extras={"agent_config": SimpleNamespace(active_model=VISION_SLOT)},
    )

    assert MultimodalHintContributor().contribute_sync(ctx) is None


def test_prompt_contributor_reports_text_only_config(stale_agent_model):
    ctx = SimpleNamespace(
        extras={"agent_config": SimpleNamespace(active_model=TEXT_ONLY_SLOT)},
    )

    assert "You can only understand text content" in (
        MultimodalHintContributor().contribute_sync(ctx) or ""
    )
