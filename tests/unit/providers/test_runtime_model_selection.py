# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Runtime media capabilities follow the selected model across tasks."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents import prompt
from qwenpaw.agents.tools import view_media
from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.model_selection import (
    current_model_slot,
    runtime_model_context,
)
from qwenpaw.runtime.prompt_contributors import MultimodalHintContributor
from qwenpaw.utils.io_utils import run_sync_io


@pytest.fixture
def models(monkeypatch):
    models_by_provider = {
        "default": ModelInfo(
            id="text",
            name="Text",
            supports_image=False,
            supports_video=False,
            supports_multimodal=False,
        ),
        "session": ModelInfo(
            id="vision",
            name="Vision",
            supports_image=True,
            supports_video=True,
            supports_multimodal=True,
        ),
        "unknown": ModelInfo(
            id="new",
            name="New",
            supports_image=None,
            supports_video=None,
            supports_multimodal=None,
        ),
    }
    config = AgentProfileConfig(
        id="agent",
        name="Agent",
        active_model=ModelSlotConfig(provider_id="default", model="text"),
    )
    manager = SimpleNamespace(
        get_provider=lambda pid: SimpleNamespace(
            all_models=lambda: [models_by_provider[pid]],
        ),
        get_active_model=lambda: config.active_model,
        probe_model_multimodal=AsyncMock(
            return_value={
                "supports_image": True,
                "supports_video": True,
            },
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _: config,
    )
    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
        lambda: manager,
    )
    return config, manager


async def test_concurrent_media_checks_use_each_executing_model(models):
    async def check(key):
        with runtime_model_context(SimpleNamespace(model_key=key)):
            await asyncio.sleep(0)
            return await run_sync_io(view_media._check_multimodal_support)

    assert await asyncio.gather(
        check("default:text"),
        check("session:vision"),
    ) == [False, True]
    assert current_model_slot() is None


def test_media_checks_follow_runtime_fallback_and_restore_context(models):
    model = SimpleNamespace(model_key="session:vision")
    with pytest.raises(RuntimeError, match="interrupted"):
        with runtime_model_context(model):
            assert view_media._check_multimodal_support() is True
            model.model_key = "default:text"
            assert view_media._check_multimodal_support() is False
            raise RuntimeError("interrupted")
    assert current_model_slot() is None


def test_prompt_capability_uses_explicit_config_over_parent_model(models):
    config, _manager = models
    config = config.model_copy(
        update={
            "active_model": ModelSlotConfig(
                provider_id="session",
                model="vision",
            ),
        },
    )
    ctx = SimpleNamespace(extras={"agent_config": config})
    with runtime_model_context(SimpleNamespace(model_key="default:text")):
        assert prompt.build_multimodal_hint()
        assert MultimodalHintContributor().contribute_sync(ctx) is None


@pytest.mark.parametrize("media_type", ["image", "video"])
async def test_capability_probe_targets_executing_model(models, media_type):
    _config, manager = models
    with runtime_model_context(SimpleNamespace(model_key="unknown:new")):
        assert await view_media._probe_multimodal_if_needed(media_type) is True
        await asyncio.sleep(0)
    assert manager.probe_model_multimodal.await_args_list
    assert all(
        call.args == ("unknown", "new")
        for call in manager.probe_model_multimodal.await_args_list
    )


@pytest.mark.parametrize("known", [False, True])
async def test_hub_token_wrapper_preserves_executing_identity(
    models,
    monkeypatch,
    known,
):
    from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper

    _config, manager = models
    slot = ModelSlotConfig(provider_id="hub-managed", model="selected:tag")
    info = ModelInfo(
        id=slot.model,
        name="Managed vision",
        supports_image=True if known else None,
        supports_video=True if known else None,
        supports_multimodal=True if known else None,
    )
    monkeypatch.setattr(
        manager,
        "get_provider",
        lambda pid: SimpleNamespace(all_models=lambda: [info])
        if pid == slot.provider_id
        else None,
    )
    # This is the wrapper returned directly by the Hub model factory,
    # without the RetryChatModel that exposes model_key on personal models.
    model = TokenRecordingModelWrapper(
        slot.provider_id,
        SimpleNamespace(model=slot.model),
    )
    with runtime_model_context(model):
        assert await run_sync_io(current_model_slot) == slot
        if known:
            assert view_media._check_multimodal_support() is True
            manager.probe_model_multimodal.assert_not_awaited()
        else:
            assert (
                await view_media._probe_multimodal_if_needed("video") is True
            )
            manager.probe_model_multimodal.assert_awaited_once_with(
                slot.provider_id,
                slot.model,
            )


@pytest.mark.parametrize(
    "override",
    ["invalid\r\nforged", {"model": ["forged\r\n"]}],
)
def test_invalid_override_logs_escape_line_breaks(caplog, override):
    from qwenpaw.providers.model_selection import resolve_model_slot_override

    assert resolve_model_slot_override(override) is None
    assert caplog.records
    for record in caplog.records:
        assert "forged" in record.getMessage()
        assert "\r" not in record.getMessage()
        assert "\n" not in record.getMessage()


@pytest.mark.parametrize(
    "outcome",
    ["complete", "error", "cross-task-close", "cancel"],
)
async def test_runtime_exposes_model_to_tools_and_cleans_up(
    monkeypatch,
    outcome,
):
    from qwenpaw.runtime import runtime as runtime_module
    from qwenpaw.runtime.hooks import HookResult

    slot = ModelSlotConfig(provider_id="session", model="vision")
    agent = SimpleNamespace(model=SimpleNamespace(model_key="session:vision"))
    ctx = SimpleNamespace(
        agent=None,
        session_id="s",
        input_msgs=[],
        extras={},
        error=None,
    )
    workspace = SimpleNamespace(
        plugins=SimpleNamespace(
            hook_registry=SimpleNamespace(
                run=AsyncMock(return_value=HookResult()),
            ),
            slash_command_registry=SimpleNamespace(
                dispatch=AsyncMock(return_value=None),
            ),
        ),
    )
    runtime = runtime_module.Runtime(workspace=workspace, app_services=None)
    monkeypatch.setattr(runtime, "_normalize", lambda request: request)
    monkeypatch.setattr(runtime, "_build_context", lambda _: ctx)
    monkeypatch.setattr(runtime, "_start_modes", AsyncMock())
    monkeypatch.setattr(runtime, "_apply_context_injections", lambda _: None)
    monkeypatch.setattr(runtime, "_try_save_on_cancel", AsyncMock())
    monkeypatch.setattr(
        runtime_module,
        "AgentBuilder",
        lambda **_: SimpleNamespace(build=AsyncMock(return_value=agent)),
    )
    monkeypatch.setattr(runtime_module, "record_agent_activity", AsyncMock())

    async def empty_events(*_):
        for event in ():
            yield event

    monkeypatch.setattr(
        runtime_module,
        "Envelope",
        lambda **_: SimpleNamespace(
            emit_response_created=empty_events,
            finalize=empty_events,
            error_envelope=empty_events,
            cancel_envelope=empty_events,
        ),
    )

    async def tool_events(_messages):
        assert await run_sync_io(current_model_slot) == slot
        if outcome == "error":
            raise RuntimeError("tool interrupted")
        yield "tool completed"
        if outcome == "cancel":
            raise asyncio.CancelledError

    monkeypatch.setattr(
        runtime_module,
        "AgentExecutor",
        lambda *_: SimpleNamespace(run=tool_events),
    )
    stream = runtime.run(object())
    if outcome == "cross-task-close":
        assert await asyncio.create_task(anext(stream)) == "tool completed"
        assert current_model_slot() is None
        await stream.aclose()
    elif outcome == "error":
        with pytest.raises(RuntimeError, match="tool interrupted"):
            async for _event in stream:
                pass
    elif outcome == "cancel":
        with pytest.raises(asyncio.CancelledError):
            async for _event in stream:
                pass
    else:
        assert [event async for event in stream] == [
            "tool completed",
        ]
    assert current_model_slot() is None
