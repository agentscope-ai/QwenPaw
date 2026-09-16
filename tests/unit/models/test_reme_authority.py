"""Request-bound ReMe model authority and shared-runtime isolation."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents.memory.reme_light_memory_manager import ReMeLightMemoryManager
from qwenpaw.runtime.builder import AgentBuilder
from tests.unit.models.test_governance import actor


@pytest.fixture
def memory(monkeypatch):
    monkeypatch.setattr(ReMeLightMemoryManager, "_initialize_reme", lambda self: None)
    monkeypatch.setattr("qwenpaw.identity.runtime.is_multi_user_enabled", lambda: True)
    manager = ReMeLightMemoryManager(
        "unused-fixture", "agent", enable_scoped_runtime=False
    )
    manager._reme = SimpleNamespace(is_started=True)
    manager._append_reme_job_result_to_inbox = AsyncMock()
    return manager


def authority(model):
    return (actor(), "agent", {"provider_id": "p", "model": model})


@pytest.mark.asyncio
async def test_reme_requires_trusted_authority(memory):
    with pytest.raises(ValueError, match="authority_unavailable"):
        await memory._run_reme_job("auto_memory", needs_llm=True, raise_on_error=True)


@pytest.mark.asyncio
async def test_reme_concurrent_jobs_keep_their_own_effective_model(memory, monkeypatch):
    checked = []

    async def require_model(_actor, agent, provider, model):
        checked.append((agent, provider, model))

    monkeypatch.setattr(
        "qwenpaw.models.runtime.get_model_service",
        lambda _: SimpleNamespace(require_model=require_model),
    )
    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
        lambda: object(),
    )
    monkeypatch.setattr(
        "qwenpaw.agents.memory.reme_light_memory_manager.create_model_and_formatter",
        lambda agent, model_slot_override=None: (model_slot_override.model, None),
    )
    injected = None
    observed = []

    async def update(*args, model):
        nonlocal injected
        injected = model

    async def run(name, **kwargs):
        before = injected
        await asyncio.sleep(0)
        observed.append((before, injected))
        return SimpleNamespace(success=True, answer="ok")

    memory._reme.update_component = update
    memory._reme.run_job = run
    await asyncio.gather(
        *(
            memory._run_reme_job(
                "auto_memory",
                needs_llm=True,
                raise_on_error=True,
                _model_authority=authority(model),
            )
            for model in ("explicit-session", "explicit-agent")
        )
    )
    assert observed == [
        ("explicit-session", "explicit-session"),
        ("explicit-agent", "explicit-agent"),
    ]
    assert [item[2] for item in checked] == ["explicit-session", "explicit-agent"]


def test_builder_binds_authority_outside_untrusted_request_context(memory):
    trusted = authority("session")
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(memory_manager=memory),
        request=SimpleNamespace(_model_authority=trusted, request_context={}),
    )
    view = AgentBuilder._get_memory_manager(ctx)
    assert view._model_authority == trusted


@pytest.mark.asyncio
async def test_reme_does_not_inject_a_revoked_model(memory, monkeypatch):
    async def denied(*args):
        raise ValueError("model_forbidden")

    monkeypatch.setattr(
        "qwenpaw.models.runtime.get_model_service",
        lambda _: SimpleNamespace(require_model=denied),
    )
    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
        lambda: object(),
    )
    memory._reme.update_component = AsyncMock()
    with pytest.raises(ValueError, match="model_forbidden"):
        await memory._run_reme_job(
            "auto_memory",
            needs_llm=True,
            raise_on_error=True,
            _model_authority=authority("revoked"),
        )
    memory._reme.update_component.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_view_preserves_authority_through_reused_summary_worker(memory):
    from agentscope.message import Msg, TextBlock

    messages = [
        Msg(name="user", role="user", content=[TextBlock(text="remember this")])
    ]
    memory._require_private_memory_access = AsyncMock()
    memory._scoped_runtime_pool = SimpleNamespace(
        get_private=AsyncMock(return_value=memory)
    )
    memory._run_reme_job = AsyncMock(return_value=SimpleNamespace(answer="saved"))
    views = [
        memory.for_model_request({"user_id": str(actor().user_id)}, authority(model))
        for model in ("first", "second")
    ]
    try:
        for index, view in enumerate(views):
            await view.auto_memory(messages, session_id=f"session-{index}")
        for _ in range(100):
            if all(
                info["status"] == "completed"
                for info in memory._summary_task_info.values()
            ):
                break
            await asyncio.sleep(0)
        assert len(memory._summary_task_info) == 2
        assert all(
            info["status"] == "completed" for info in memory._summary_task_info.values()
        )
        assert [
            call.kwargs["_model_authority"][2]["model"]
            for call in memory._run_reme_job.await_args_list
        ] == ["first", "second"]
    finally:
        memory._worker_task.cancel()
        await asyncio.gather(memory._worker_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_missing_authority_marks_background_summary_failed(memory):
    from agentscope.message import Msg, TextBlock

    try:
        await memory.auto_memory(
            [Msg(name="user", role="user", content=[TextBlock(text="remember")])],
            session_id="s",
        )
        for _ in range(100):
            if memory._summary_task_info["task_1"]["status"] == "failed":
                break
            await asyncio.sleep(0)
        assert memory._summary_task_info["task_1"]["status"] == "failed"
        assert memory._summary_task_info["task_1"]["error"] == "authority_unavailable"
    finally:
        if memory._worker_task is not None:
            memory._worker_task.cancel()
            await asyncio.gather(memory._worker_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_console_channel_real_builder_preserves_and_rechecks_authority(
    monkeypatch,
):
    from qwenpaw.app.routers.console import _extract_session_and_payload
    from qwenpaw.app.channels.console.channel import ConsoleChannel
    from qwenpaw.models.runtime import prepare_console_model

    checks = []
    revoked = False

    async def require_model(_actor, agent, provider, model):
        if revoked:
            raise ValueError("revoked")
        checks.append((agent, provider, model))
        return {"max_input_length": 12345}

    provider_manager = object()
    service = SimpleNamespace(manager=provider_manager, require_model=require_model)
    config = SimpleNamespace(
        active_model={"provider_id": "p", "model": "agent-default"}
    )
    monkeypatch.setattr("qwenpaw.models.runtime.get_model_service", lambda _: service)
    monkeypatch.setattr("qwenpaw.models.runtime.load_agent_config", lambda _: config)
    monkeypatch.setattr("qwenpaw.models.runtime.is_multi_user_enabled", lambda: False)
    monkeypatch.setattr("qwenpaw.config.config.load_agent_config", lambda _: config)
    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
        lambda: provider_manager,
    )
    workspace = SimpleNamespace(
        agent_id="agent",
        chat_manager=SimpleNamespace(set_legacy_model_override=AsyncMock()),
    )
    http_request = SimpleNamespace(
        state=SimpleNamespace(actor=actor()),
        app=SimpleNamespace(state=SimpleNamespace(provider_manager=provider_manager)),
    )
    body = {
        "session_id": "s",
        "user_id": "",
        "requested_model": {"provider_id": "p", "model": "session"},
    }
    native = _extract_session_and_payload(body)
    await prepare_console_model(
        http_request, workspace, SimpleNamespace(id="chat"), body, native
    )
    channel = ConsoleChannel(process=AsyncMock(), enabled=True, bot_prefix="")
    request = channel.build_agent_request_from_native(native)
    assert request._model_authority == native["_model_authority"]
    workspace.chat_manager.set_legacy_model_override.assert_awaited_once_with(
        "chat", body["requested_model"]
    )
    builder = AgentBuilder()
    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.ensure_skills_initialized", lambda _: None
    )
    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.resolve_effective_skills", lambda *args: []
    )
    monkeypatch.setattr(builder, "_init_governor", lambda *args: None)
    monkeypatch.setattr(builder, "_get_local_workspace", lambda _: None)
    monkeypatch.setattr(builder, "_collect_coding_mode_tools", lambda *args: [])
    monkeypatch.setattr(builder, "_collect_visual_compression_tools", lambda *args: [])
    monkeypatch.setattr(
        builder, "_collect_driver_tools_and_prompts", AsyncMock(return_value=([], []))
    )
    monkeypatch.setattr(
        builder, "_inject_selected_personal_library_documents", lambda *args: None
    )

    class ConstructionReached(Exception):
        pass

    def construct(*args, model_slot_override=None, **kwargs):
        assert model_slot_override.model == "session"
        raise ConstructionReached

    monkeypatch.setattr(builder, "build_model", construct)
    ctx = SimpleNamespace(request=request, agent_id="agent", workspace=workspace)
    with pytest.raises(ConstructionReached):
        await builder.build(ctx)
    assert checks == [("agent", "p", "session")] * 4
    revoked = True
    with pytest.raises(ValueError, match="revoked"):
        await builder.build(ctx)
