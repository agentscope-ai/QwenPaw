# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position
from contextlib import contextmanager

import pytest

# flake8: noqa: E402,E501
pytest.importorskip(
    "langfuse",
    reason="langfuse SDK required for observability tests",
)

from qwenpaw.__version__ import __version__
from qwenpaw.observability import langfuse as lf


class FakeObservation:
    def __init__(self, observation_id: str):
        self.id = observation_id
        self.updates = []
        self.ended = False

    def update(self, **kwargs):
        self.updates.append(kwargs)
        return self

    def end(self):
        self.ended = True
        return self


class FakeClient:
    def __init__(self, *, trace_id=None, observation_id=None):
        self.started = []
        self.next_id = 0
        self._trace_id = trace_id
        self._observation_id = observation_id

    def start_observation(self, **kwargs):
        self.started.append(kwargs)
        self.next_id += 1
        return FakeObservation(f"obs-{self.next_id}")

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        self.started.append(kwargs)
        self.next_id += 1
        yield FakeObservation(f"obs-{self.next_id}")

    def get_current_observation_id(self):
        return self._observation_id or f"obs-{self.next_id}"

    def get_current_trace_id(self):
        return self._trace_id


@pytest.fixture(autouse=True)
def reset_context(monkeypatch):
    lf.clear_current_trace()
    monkeypatch.setattr(lf, "_langfuse_client", lambda: None)
    yield
    lf.clear_current_trace()


def test_model_kwargs_include_current_agent_trace_context():
    lf.set_current_trace(
        trace_id="trace-1",
        parent_observation_id="root-1",
        name="agent.react_loop",
        metadata={
            "session_id": "session-a",
            "agent_id": "default",
        },
    )

    kwargs = lf.current_generation_kwargs("qwen-max")

    assert kwargs == {
        "trace_id": "trace-1",
        "parent_observation_id": "root-1",
        "name": "llm.qwen-max",
        "metadata": {
            "session_id": "session-a",
            "agent_id": "default",
            "langfuse_observation_kind": "llm",
        },
    }


async def test_agent_trace_scope_creates_root_span_and_restores_context():
    client = FakeClient()

    async with lf.agent_trace_scope(
        trace_id="trace-1",
        name="agent.react_loop",
        metadata={"session_id": "session-a"},
        client_factory=lambda: client,
    ):
        kwargs = lf.current_generation_kwargs("qwen-max")

    assert len(client.started) == 1
    assert client.started[0]["as_type"] == "span"
    assert client.started[0]["name"] == "agent.react_loop"
    assert client.started[0]["trace_context"] == {"trace_id": "trace-1"}
    assert kwargs["parent_observation_id"] == "obs-1"
    assert not lf.current_generation_kwargs("qwen-max")


async def test_tool_span_records_input_output_and_error_status():
    client = FakeClient()
    lf.set_current_trace(
        trace_id="trace-1",
        parent_observation_id="root-1",
        name="agent.react_loop",
        metadata={"session_id": "session-a"},
    )

    with pytest.raises(RuntimeError):
        async with lf.tool_span(
            name="execute_shell_command",
            input={"command": "false"},
            client_factory=lambda: client,
        ) as span:
            assert span is not None
            raise RuntimeError("boom")

    assert len(client.started) == 1
    assert client.started[0]["as_type"] == "tool"
    assert client.started[0]["name"] == "tool.execute_shell_command"
    assert client.started[0]["trace_context"] == {
        "trace_id": "trace-1",
        "parent_span_id": "root-1",
    }
    observation = span
    assert observation.updates[-1]["level"] == "ERROR"
    assert observation.updates[-1]["status_message"] == "boom"
    assert observation.ended is True


async def test_agent_trace_scope_propagates_user_session_and_version(
    monkeypatch,
):
    """user_id/session_id/version from metadata reach propagate_attributes."""
    import langfuse as langfuse_mod

    captured = {}

    @contextmanager
    def fake_propagate(*, user_id, session_id, version):
        captured.update(
            user_id=user_id,
            session_id=session_id,
            version=version,
        )
        yield

    monkeypatch.setattr(langfuse_mod, "propagate_attributes", fake_propagate)

    client = FakeClient()
    async with lf.agent_trace_scope(
        trace_id="trace-1",
        name="agent.react_loop",
        metadata={"session_id": "session-a", "user_id": "user-42"},
        client_factory=lambda: client,
    ):
        pass

    assert captured == {
        "user_id": "user-42",
        "session_id": "session-a",
        "version": __version__,
    }


async def test_agent_trace_scope_uses_client_trace_id_when_available():
    """get_current_trace_id() overrides the caller-supplied trace_id."""
    client = FakeClient(trace_id="client-trace-99")

    async with lf.agent_trace_scope(
        trace_id="caller-trace",
        name="agent.react_loop",
        metadata={"session_id": "s1"},
        client_factory=lambda: client,
    ):
        ctx = lf.get_current_trace()

    assert ctx.trace_id == "client-trace-99"
    assert ctx.parent_observation_id == "obs-1"


async def test_agent_trace_scope_falls_back_to_caller_trace_id():
    """Caller trace_id is used when get_current_trace_id() is None."""
    client = FakeClient(trace_id=None)

    async with lf.agent_trace_scope(
        trace_id="caller-trace",
        name="agent.react_loop",
        metadata={"session_id": "s1"},
        client_factory=lambda: client,
    ):
        ctx = lf.get_current_trace()

    assert ctx.trace_id == "caller-trace"


async def test_agent_trace_scope_marks_span_error_and_reraises():
    """An exception inside the scope marks the span ERROR and re-raises."""
    client = FakeClient()

    with pytest.raises(RuntimeError, match="boom"):
        async with lf.agent_trace_scope(
            trace_id="trace-1",
            name="agent.react_loop",
            metadata={"session_id": "s1"},
            client_factory=lambda: client,
        ) as root_span:
            assert root_span is not None
            raise RuntimeError("boom")

    assert root_span.updates[-1] == {
        "level": "ERROR",
        "status_message": "boom",
        "output": {"status": "error"},
    }
    # span opened via start_as_current_observation is not .end()'d manually
    assert root_span.ended is False


async def test_agent_trace_scope_none_client_sets_trace_without_parent():
    """When the client is unavailable, trace is still set with no parent."""
    async with lf.agent_trace_scope(
        trace_id="trace-1",
        name="agent.react_loop",
        metadata={"session_id": "s1"},
        client_factory=lambda: None,
    ) as root_span:
        assert root_span is None
        ctx = lf.get_current_trace()
        assert ctx.trace_id == "trace-1"
        assert ctx.parent_observation_id is None

    # no previous trace -> cleared on exit
    assert lf.get_current_trace() is None
