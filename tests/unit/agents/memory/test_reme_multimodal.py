# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Image opt-in applies to every host entry point and the actual memory LLM."""

from contextlib import asynccontextmanager
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from agentscope.message import Base64Source, DataBlock, UserMsg

from qwenpaw.agents.memory import reme_light_memory_manager as memory_module
from qwenpaw.agents.memory.reme_config import get_reme_app_config
from qwenpaw.config.config import AgentProfileConfig, ReMeLightMemoryConfig
from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.provider_manager import ProviderManager


def _image_message():
    return UserMsg(
        name="user",
        content=[
            DataBlock(
                source=Base64Source(data="aGk=", media_type="image/png"),
            ),
        ],
    )


@pytest.fixture
def memory_job(monkeypatch):
    """Keep host routing real; replace only config, model and the ReMe job."""
    config = ReMeLightMemoryConfig()
    model = SimpleNamespace(model="vision:v1", model_key="custom:vision:v1")
    metadata = ModelInfo(
        id="vision:v1",
        name="Custom vision model",
        supports_image=True,
        source="user",
    )
    # Include a different chat model to catch accidental global/session lookup.
    provider = SimpleNamespace(models=[], extra_models=[metadata])
    providers = SimpleNamespace(
        get_provider=lambda provider_id: (
            provider if provider_id == "custom" else None
        ),
        get_active_model=lambda: SimpleNamespace(
            provider_id="custom",
            model="chat-only",
        ),
    )
    monkeypatch.setattr(ProviderManager, "_instance", providers)
    factory = AsyncMock(return_value=(model, None))
    monkeypatch.setattr(
        memory_module,
        "create_model_and_formatter_async",
        factory,
    )
    parameters = get_reme_app_config(
        working_dir="/tmp/memory-image-test",
        agent_config=AgentProfileConfig(
            id="memory-agent",
            name="Memory Agent",
        ),
    )["jobs"]["auto_memory"]["parameters"]
    manager = object.__new__(memory_module.ReMeLightMemoryManager)
    manager.agent_id = "memory-agent"
    manager._llm_job_lock = asyncio.Lock()
    manager._load_memory_config = Mock(return_value=config)
    manager._append_reme_job_result_to_inbox = AsyncMock(return_value=False)
    manager._reme = SimpleNamespace(
        is_started=True,
        update_component=AsyncMock(),
        run_job=AsyncMock(
            return_value=SimpleNamespace(success=True, answer="saved"),
        ),
        context=SimpleNamespace(
            jobs={
                "auto_memory": SimpleNamespace(
                    enable_serve=True,
                    parameters=parameters,
                ),
            },
        ),
    )

    @asynccontextmanager
    async def lease():
        yield

    manager._reme_job_lease = lease
    return SimpleNamespace(
        manager=manager,
        config=config,
        model=model,
        metadata=metadata,
        factory=factory,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("entry_point", "enabled", "supports_image", "requested", "expected"),
    [
        ("auto_memory", False, True, True, False),
        ("auto_memory", True, True, True, True),
        ("auto_memory", True, False, True, False),
        ("auto_memory", True, None, True, False),
        ("auto_memory", True, True, False, False),
        ("run_action", False, True, True, False),
        ("run_action", True, True, True, True),
        ("run_action", True, True, False, False),
    ],
)
async def test_images_require_setting_and_actual_memory_model_support(
    memory_job,
    entry_point,
    enabled,
    supports_image,
    requested,
    expected,
):
    memory_job.config.auto_memory_include_images = enabled
    memory_job.metadata.supports_image = supports_image
    # Generic multimodal support can mean audio/video; it cannot allow images.
    memory_job.metadata.supports_multimodal = True
    manager = memory_job.manager
    message = _image_message()

    if entry_point == "auto_memory":
        await manager.auto_memory(
            [message],
            session_id="test-session",
            include_images=requested,
        )
    else:
        await manager.run_action(
            "auto_memory",
            messages=[message.model_dump(mode="json")],
            session_id="test-session",
            include_images=requested,
        )

    call = manager._reme.run_job.await_args
    assert call.args == ("auto_memory",)
    assert call.kwargs["include_images"] is expected
    assert call.kwargs["messages"][0]["content"][0]["type"] == "data"
    memory_job.factory.assert_awaited_once_with(
        "memory-agent",
        require_image_support=enabled and requested,
        resize_images_to_max_bytes=True,
    )
    manager._reme.update_component.assert_awaited_once_with(
        "as_llm",
        "default",
        model=memory_job.model,
    )


@pytest.mark.asyncio
async def test_setting_and_model_changes_apply_without_restart(memory_job):
    """Each memory job resolves fresh settings and the LLM it will inject."""
    manager = memory_job.manager
    memory_job.config.auto_memory_include_images = True
    message = _image_message()

    await manager.auto_memory([message], session_id="first")
    assert manager._reme.run_job.await_args.kwargs["include_images"] is True

    # A different (e.g. newly inherited global) memory model is now text-only.
    next_model = SimpleNamespace(
        model_key="custom:chat-only",
        model="chat-only",
    )
    memory_job.factory.return_value = (next_model, None)
    await manager.auto_memory([message], session_id="second")
    assert manager._reme.run_job.await_args.kwargs["include_images"] is False

    memory_job.factory.return_value = (memory_job.model, None)
    memory_job.config.auto_memory_include_images = False
    await manager.auto_memory([message], session_id="third")
    assert manager._reme.run_job.await_args.kwargs["include_images"] is False
    assert memory_job.factory.await_count == 3
    assert manager._load_memory_config.call_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_point", ["auto_memory", "run_action"])
async def test_tag_generation_follows_live_setting_without_enabling_images(
    memory_job,
    entry_point,
):
    for enabled in (False, True, False):
        memory_job.config.auto_memory_generate_tags = enabled
        if entry_point == "auto_memory":
            await memory_job.manager.auto_memory(
                [_image_message()],
                session_id="tag-test",
            )
        else:
            await memory_job.manager.run_action(
                "auto_memory",
                messages=[],
                session_id="tag-test",
            )
        call = memory_job.manager._reme.run_job.await_args
        assert call.args == (
            "auto_memory_with_tags" if enabled else "auto_memory",
        )
        assert call.kwargs["include_images"] is False
        notification = (
            memory_job.manager._append_reme_job_result_to_inbox.await_args
        )
        assert notification.args == ("auto_memory",)


@pytest.mark.asyncio
async def test_image_decision_is_visible_without_logging_payloads(
    memory_job,
    caplog,
):
    with caplog.at_level("INFO", logger=memory_module.__name__):
        await memory_job.manager.auto_memory(
            [_image_message()],
            session_id="test-session",
        )
    assert (
        "include_images=False enabled=False model_supports_images=True"
        in caplog.text
    )
    assert "model=custom:vision:v1" in caplog.text
    assert "aGk=" not in caplog.text


@pytest.mark.asyncio
async def test_action_image_control_rejects_non_boolean_values(memory_job):
    with pytest.raises(ValueError, match="is not of type 'boolean'"):
        await memory_job.manager.run_action(
            "auto_memory",
            messages=[],
            include_images="true",
        )
    memory_job.factory.assert_not_awaited()
    memory_job.manager._reme.run_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_jobs_keep_injected_model_until_completion(memory_job):
    manager = memory_job.manager
    entered, release = asyncio.Event(), asyncio.Event()

    async def run_job(name, **_kwargs):
        if name == "auto_memory":
            entered.set()
            await release.wait()
        return SimpleNamespace(success=True, answer="done")

    manager._reme.run_job.side_effect = run_job
    first = asyncio.create_task(
        manager._run_reme_job("auto_memory", messages=[]),
    )
    await entered.wait()
    second = asyncio.create_task(
        manager._run_reme_job("auto_dream", needs_llm=True),
    )
    try:
        await asyncio.sleep(0)
        assert not second.done()
        assert manager._reme.update_component.await_count == 1
        # Searches still run while the LLM-backed job holds its model lease.
        found = await manager._run_reme_job("search", query="Orion")
        assert found.success
    finally:
        release.set()
        await asyncio.gather(first, second)
    assert manager._reme.update_component.await_count == 2
    memory_job.factory.assert_awaited_with(
        "memory-agent",
        require_image_support=False,
        resize_images_to_max_bytes=True,
    )
