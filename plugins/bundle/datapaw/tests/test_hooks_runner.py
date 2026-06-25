# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,using-constant-test
# Test stubs override signatures for monkeypatch targets (unused-argument);
# ``if False: yield`` is the standard idiom for an async-generator no-op.
"""Tests for hooks.setup_runner_hooks and the smart agent factory."""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_smart_factory_routes_datapaw_to_adapter():
    """factory(request_context={agent_id: 'datapaw'}) → DataPawAgent."""
    from plugin_datapaw.hooks import _SmartAgentFactory

    fake_qwen = MagicMock(name="QwenPawAgent")
    fake_dp_agent = MagicMock(name="DataPawAgent")
    factory = _SmartAgentFactory(fake_qwen)

    with patch(
        "plugin_datapaw.hooks._import_data_paw_agent",
        return_value=lambda *a, **kw: fake_dp_agent,
    ):
        result = factory(
            agent_config=MagicMock(),
            request_context={"agent_id": "datapaw"},
        )

    assert result is fake_dp_agent
    fake_qwen.assert_not_called()


def test_smart_factory_routes_other_to_qwenpaw():
    """factory(request_context={agent_id: 'other'}) → QwenPawAgent."""
    from plugin_datapaw.hooks import _SmartAgentFactory

    fake_qwen = MagicMock(name="QwenPawAgent")
    factory = _SmartAgentFactory(fake_qwen)

    factory(
        agent_config=MagicMock(),
        request_context={"agent_id": "default"},
    )

    fake_qwen.assert_called_once()


def test_smart_factory_handles_missing_request_context():
    """factory(no request_context) → falls back to QwenPawAgent."""
    from plugin_datapaw.hooks import _SmartAgentFactory

    fake_qwen = MagicMock(name="QwenPawAgent")
    factory = _SmartAgentFactory(fake_qwen)

    factory(agent_config=MagicMock())

    fake_qwen.assert_called_once()


def test_factory_accepts_main_runner_kwargs_without_typeerror():
    """Regression: when host's runner.py calls QwenPawAgent(...) with main's
    9 kwargs (incl. context_manager, plan_notebook, no enable_memory_manager),
    routing to DataPawAgent must not raise TypeError on signature mismatch.

    Reproduces the runtime crash: TypeError on `enable_memory_manager`.
    """
    from plugin_datapaw.hooks import _SmartAgentFactory

    fake_qwen = MagicMock(name="QwenPawAgent")
    factory = _SmartAgentFactory(fake_qwen)

    # Match host runner.py:594 call shape exactly
    host_kwargs = {
        "agent_config": MagicMock(),
        "env_context": "ctx",
        "mcp_clients": [],
        "memory_manager": MagicMock(),
        "context_manager": MagicMock(),
        "request_context": {
            "agent_id": "datapaw",
            "session_id": "s1",
            "user_id": "u1",
        },
        "workspace_dir": "/tmp/ws",
        "task_tracker": MagicMock(),
        "plan_notebook": MagicMock(),
    }

    # If DataPawAgent.__init__ chains super() with kwargs that the host's
    # QwenPawAgent doesn't accept (e.g., enable_memory_manager), this raises
    # TypeError. Acceptable: any exception that isn't a TypeError on the
    # signature mismatch (e.g., downstream init failure due to mocks isn't
    # the bug under test).
    try:
        factory(**host_kwargs)
    except TypeError as e:
        msg = str(e)
        if (
            "enable_memory_manager" in msg
            or "got an unexpected keyword argument" in msg
        ):
            raise AssertionError(
                f"Adapter passes unknown kwarg(s) to QwenPawAgent: {msg}",
            ) from e
    except Exception:
        # Other failures (e.g. agentscope wiring with MagicMocks) are fine —
        # we only assert about the signature mismatch.
        pass


def _build_fake_runner_module():
    """Construct a self-contained fake `qwenpaw.app.runner.runner` module."""
    fake_runner_module = type("M", (), {})()

    class FakeQwen:
        pass

    async def orig_query_handler(self, msgs, request=None, **kwargs):
        if False:  # make it a generator
            yield None

    class FakeAgentRunner:
        query_handler = orig_query_handler

    fake_runner_module.QwenPawAgent = FakeQwen
    fake_runner_module.AgentRunner = FakeAgentRunner
    return fake_runner_module, FakeAgentRunner, orig_query_handler


def test_setup_runner_hooks_swaps_qwenpaw_and_wraps_query_handler():
    """After setup: QwenPawAgent is the factory; query_handler is patched."""
    (
        fake_runner_module,
        FakeAgentRunner,
        orig_query_handler,
    ) = _build_fake_runner_module()

    from plugin_datapaw.hooks import setup_runner_hooks

    setup_runner_hooks(_runner_module=fake_runner_module)

    assert callable(fake_runner_module.QwenPawAgent)
    assert (
        getattr(fake_runner_module.QwenPawAgent, "_datapaw_factory", False)
        is True
    )
    assert FakeAgentRunner.query_handler is not orig_query_handler
    assert (
        getattr(FakeAgentRunner.query_handler, "_datapaw_patched", False)
        is True
    )


def test_setup_runner_hooks_idempotent():
    """Idempotent: re-invoking must not stack patches."""
    fake_runner_module, FakeAgentRunner, _orig = _build_fake_runner_module()

    from plugin_datapaw.hooks import setup_runner_hooks

    setup_runner_hooks(_runner_module=fake_runner_module)
    first_factory = fake_runner_module.QwenPawAgent
    first_qh = FakeAgentRunner.query_handler

    setup_runner_hooks(_runner_module=fake_runner_module)  # second call

    assert fake_runner_module.QwenPawAgent is first_factory
    assert FakeAgentRunner.query_handler is first_qh


def test_datapaw_query_wrapper_schedules_trace_submit(monkeypatch):
    """DataPaw turns schedule one best-effort trace submit after completion."""
    from plugin_datapaw.constants import BUILTIN_DATAPAW_AGENT_ID
    from plugin_datapaw.hooks import _wrap_query_handler
    from plugin_datapaw.core import trace_submitter

    calls = []
    monkeypatch.setattr(
        trace_submitter,
        "schedule_trace_submit",
        lambda **kwargs: calls.append(kwargs),
    )

    async def orig_query_handler(self, msgs, request=None, **kwargs):
        yield "chunk", False

    async def run():
        wrapped = _wrap_query_handler(orig_query_handler)
        runner = SimpleNamespace(agent_id=BUILTIN_DATAPAW_AGENT_ID)
        request = SimpleNamespace(
            session_id="s1",
            user_id="default",
            channel="console",
            request_context={"datasource_id": "ds1"},
        )
        msgs = [SimpleNamespace(id="u1")]
        chunks = []
        async for item in wrapped(runner, msgs, request):
            chunks.append(item)
        return chunks

    assert asyncio.run(run()) == [("chunk", False)]
    assert len(calls) == 1
    assert calls[0]["session_id"] == "s1"
    assert calls[0]["user_id"] == "default"
    assert calls[0]["channel"] == "console"
    assert calls[0]["request_context"] == {"datasource_id": "ds1"}
    assert calls[0]["trigger_msg_id"] == "u1"
    assert "agent_name" not in calls[0]


def test_non_datapaw_query_wrapper_does_not_schedule_trace_submit(monkeypatch):
    """Non-DataPaw agents keep the original query path untouched."""
    from plugin_datapaw.hooks import _wrap_query_handler
    from plugin_datapaw.core import trace_submitter

    calls = []
    monkeypatch.setattr(
        trace_submitter,
        "schedule_trace_submit",
        lambda **kwargs: calls.append(kwargs),
    )

    async def orig_query_handler(self, msgs, request=None, **kwargs):
        yield "chunk", True

    async def run():
        wrapped = _wrap_query_handler(orig_query_handler)
        runner = SimpleNamespace(agent_id="default")
        request = SimpleNamespace(session_id="s1", user_id="default")
        chunks = []
        async for item in wrapped(runner, [SimpleNamespace(id="u1")], request):
            chunks.append(item)
        return chunks

    assert asyncio.run(run()) == [("chunk", True)]
    assert calls == []


def test_trace_submit_scheduling_error_does_not_break_datapaw_turn(
    monkeypatch,
):
    """Trace scheduling failures must not affect the chat response path."""
    from plugin_datapaw.constants import BUILTIN_DATAPAW_AGENT_ID
    import plugin_datapaw.hooks as hooks

    monkeypatch.setattr(
        hooks,
        "_schedule_trace_submit_for_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("trace failed"),
        ),
    )

    async def orig_query_handler(self, msgs, request=None, **kwargs):
        yield "chunk", True

    async def run():
        wrapped = hooks._wrap_query_handler(orig_query_handler)
        runner = SimpleNamespace(agent_id=BUILTIN_DATAPAW_AGENT_ID)
        request = SimpleNamespace(session_id="s1", user_id="default")
        chunks = []
        async for item in wrapped(runner, [SimpleNamespace(id="u1")], request):
            chunks.append(item)
        return chunks

    assert asyncio.run(run()) == [("chunk", True)]
