# -*- coding: utf-8 -*-
import pytest

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
    def __init__(self):
        self.started = []
        self.next_id = 0

    def start_observation(self, **kwargs):
        self.started.append(kwargs)
        self.next_id += 1
        return FakeObservation(f"obs-{self.next_id}")


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
