# -*- coding: utf-8 -*-
"""Tests for LangfuseToolSpanMiddleware output recording.

These tests use fakes only and do NOT require the ``langfuse`` SDK, so
the file is deliberately not gated by ``pytest.importorskip``: CI does
not install the SDK, and gating would silently skip the regression
guards for tool output recording.

Covers:
- Output recorded exactly once on normal drain
- Output survives a consumer that stops at the ToolResponse
  (ToolCoordinatorMiddleware._drain behaviour)
- Output recorded from the terminal chunk on ERROR/INTERRUPTED paths
- Intermediate streaming chunks are ignored
- Output recorded when the tool raises, with the original exception
  preserved
- A raising ``observation.update()`` never breaks the tool call
- Oversized output is truncated
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, AsyncIterator

import pytest

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk, ToolResponse

from qwenpaw.agents.middlewares import LangfuseToolSpanMiddleware
from qwenpaw.observability import langfuse as lf

# ---------------------------------------------------------------------------
# Shared fakes (copied from test_langfuse_integration.py so this file
# stays independent of the SDK-gated module)
# ---------------------------------------------------------------------------


class FakeObservation:
    def __init__(self, observation_id: str):
        self.id = observation_id
        self.updates: list[dict] = []
        self.ended = False
        # Track call order: update must happen before end, otherwise the
        # real SDK may drop the output.
        self.calls: list[str] = []

    def update(self, **kwargs):
        self.updates.append(kwargs)
        self.calls.append("update")
        return self

    def end(self):
        self.ended = True
        self.calls.append("end")
        return self


class BrokenUpdateObservation(FakeObservation):
    """Observation whose update() always raises (simulates SDK failure)."""

    def update(self, **kwargs):
        self.calls.append("update")
        raise RuntimeError("langfuse update failed")


class FakeClient:
    def __init__(self, *, trace_id=None, observation_id=None):
        self.started: list[dict] = []
        self.observations: list[FakeObservation] = []
        self.next_id = 0
        self._trace_id = trace_id
        self._observation_id = observation_id
        # Observation factory; tests may swap it to inject failures.
        self.observation_factory = FakeObservation

    def start_observation(self, **kwargs):
        self.started.append(kwargs)
        self.next_id += 1
        obs = self.observation_factory(f"obs-{self.next_id}")
        self.observations.append(obs)
        return obs

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        self.started.append(kwargs)
        self.next_id += 1
        obs = self.observation_factory(f"obs-{self.next_id}")
        self.observations.append(obs)
        yield obs

    def get_current_observation_id(self):
        return self._observation_id or f"obs-{self.next_id}"

    def get_current_trace_id(self):
        return self._trace_id

    def break_observations(self) -> None:
        """Make every observation created from now on raise on update."""
        self.observation_factory = BrokenUpdateObservation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_langfuse_context(monkeypatch):
    """Ensure clean Langfuse state for each test."""
    lf.clear_current_trace()
    monkeypatch.setattr(lf, "_langfuse_client", lambda: None)
    yield
    lf.clear_current_trace()


@pytest.fixture
def client(monkeypatch) -> FakeClient:
    """Active Langfuse trace backed by a FakeClient."""
    c = FakeClient()
    monkeypatch.setattr(lf, "is_langfuse_enabled", lambda: True)
    monkeypatch.setattr(lf, "_langfuse_client", lambda: c)
    lf.set_current_trace(
        trace_id="trace-1",
        parent_observation_id="root-obs",
        name="agent.react_loop",
        metadata={"session_id": "s1"},
    )
    return c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_call() -> SimpleNamespace:
    return SimpleNamespace(name="t", input={}, id="tc-1")


def _text_response(text: str) -> ToolResponse:
    return ToolResponse(
        content=[TextBlock(type="text", text=text)],
        id="tc-1",
    )


def _chunk(text: str, state=ToolResultState.SUCCESS) -> ToolChunk:
    return ToolChunk(
        content=[TextBlock(type="text", text=text)],
        id="tc-1",
        state=state,
    )


def _terminal(state) -> bool:
    return state in (ToolResultState.ERROR, ToolResultState.INTERRUPTED)


async def _run_like_drain(
    events: AsyncIterator[Any],
    stop_at_response: bool = True,
) -> list[Any]:
    """Consume the middleware like ``ToolCoordinatorMiddleware._drain``.

    Stops at the first ToolResponse (or terminal chunk) and closes the
    generator afterwards, mimicking the coordinator abandoning it.
    """
    collected: list[Any] = []
    gen = events
    async for event in gen:
        collected.append(event)
        if (stop_at_response and isinstance(event, ToolResponse)) or (
            isinstance(event, ToolChunk) and _terminal(event.state)
        ):
            break
    await gen.aclose()
    return collected


def _output_updates(obs: FakeObservation) -> list[dict]:
    return [u for u in obs.updates if "output" in u]


def _recorded_texts(obs: FakeObservation) -> list[str]:
    return [
        text
        for u in _output_updates(obs)
        for text in u["output"].get("content", [])
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLangfuseToolSpanMiddleware:
    """LangfuseToolSpanMiddleware output-recording tests."""

    async def test_passthrough_when_no_active_trace(self, monkeypatch):
        """Middleware passes events through when no trace is active."""
        monkeypatch.setattr(lf, "is_langfuse_enabled", lambda: True)

        events_in = ["chunk1", "chunk2", "done"]

        async def fake_next_handler():
            for e in events_in:
                yield e

        mw = LangfuseToolSpanMiddleware()
        collected = await _run_like_drain(
            mw.on_acting(
                SimpleNamespace(),
                {"tool_call": _tool_call()},
                fake_next_handler,
            ),
            stop_at_response=False,
        )

        assert collected == events_in

    async def test_creates_tool_span_when_trace_active(self, client):
        """Middleware wraps tool execution in a Langfuse tool span."""
        tool_response = _text_response("result data")

        async def fake_next_handler():
            yield tool_response

        mw = LangfuseToolSpanMiddleware()
        input_kwargs = {
            "tool_call": SimpleNamespace(
                name="execute_shell",
                input={"command": "ls"},
                id="tc-1",
            ),
        }
        collected = await _run_like_drain(
            mw.on_acting(
                SimpleNamespace(),
                input_kwargs,
                fake_next_handler,
            ),
        )

        assert collected == [tool_response]
        assert collected[0] is tool_response
        assert len(client.started) == 1
        assert client.started[0]["name"] == "tool.execute_shell"
        assert client.started[0]["as_type"] == "tool"

    async def test_records_output_on_normal_drain(self, client):
        """Output is recorded exactly once when the consumer fully drains."""

        async def fake_next_handler():
            yield _text_response("result data")

        mw = LangfuseToolSpanMiddleware()
        await _run_like_drain(
            mw.on_acting(
                SimpleNamespace(),
                {"tool_call": _tool_call()},
                fake_next_handler,
            ),
        )

        obs = client.observations[0]
        assert _output_updates(obs) == [
            {
                "output": {"content": ["result data"]},
            },
        ]
        # update must happen before end, otherwise the real SDK may
        # drop the output
        assert obs.calls == ["update", "end"]

    async def test_records_output_when_consumer_stops_at_tool_response(
        self,
        client,
    ):
        """Regression: output survives a consumer that stops early.

        ``ToolCoordinatorMiddleware._drain`` returns as soon as it receives
        the final ``ToolResponse``, so the middleware generator is never
        resumed after its ``yield``. The output must therefore be written
        before the yield (or in the ``finally`` on close), not after the
        ``async for`` loop — otherwise the observation is exported with
        input but no output.
        """

        async def fake_next_handler():
            yield _text_response("result data")

        mw = LangfuseToolSpanMiddleware()
        await _run_like_drain(
            mw.on_acting(
                SimpleNamespace(),
                {"tool_call": _tool_call()},
                fake_next_handler,
            ),
        )

        obs = client.observations[0]
        assert _output_updates(obs) == [
            {
                "output": {"content": ["result data"]},
            },
        ]
        assert obs.calls == ["update", "end"]

    @pytest.mark.parametrize(
        "state",
        [ToolResultState.ERROR, ToolResultState.INTERRUPTED],
    )
    async def test_records_output_on_terminal_chunk(self, client, state):
        """Regression: output is recorded from the terminal chunk.

        ``_drain`` returns as soon as it sees an ERROR/INTERRUPTED
        ToolChunk, so no ToolResponse ever flows through the middleware
        and ``final_response`` stays None. The terminal chunk itself
        must be recorded, otherwise the observation exports with input
        but no output (the original bug: ``updates: [], ended: True``).
        """

        async def fake_next_handler():
            yield _chunk("boom: file not found", state)

        mw = LangfuseToolSpanMiddleware()
        await _run_like_drain(
            mw.on_acting(
                SimpleNamespace(),
                {"tool_call": _tool_call()},
                fake_next_handler,
            ),
        )

        obs = client.observations[0]
        assert _output_updates(obs) == [
            {
                "output": {
                    "content": ["boom: file not found"],
                },
            },
        ]
        assert obs.calls == ["update", "end"]

    async def test_intermediate_chunks_are_ignored(self, client):
        """Only the terminal chunk is recorded; streaming chunks are not.

        The middleware keeps an O(1) reference to the terminal chunk, so
        a long streaming session must not inflate the observation with
        intermediate partial output, and exactly one output update must
        be written.
        """

        async def fake_next_handler():
            for i in range(50):
                yield _chunk(f"part {i}")
            yield _chunk("boom", ToolResultState.ERROR)

        mw = LangfuseToolSpanMiddleware()
        await _run_like_drain(
            mw.on_acting(
                SimpleNamespace(),
                {"tool_call": _tool_call()},
                fake_next_handler,
            ),
        )

        obs = client.observations[0]
        assert _output_updates(obs) == [{"output": {"content": ["boom"]}}]
        assert obs.calls == ["update", "end"]

    async def test_records_output_on_tool_exception(self, client):
        """A raising tool gets its error recorded and the exception passes.

        A raising tool never yields an ERROR chunk: the exception unwinds
        through the middleware and the coordinator synthesizes the
        ToolResponse at its own layer. The middleware must record the
        error and re-raise the ORIGINAL exception untouched.
        """

        async def fake_next_handler():
            raise RuntimeError("disk on fire")
            # The unreachable yield makes this an async generator so the
            # middleware can iterate it; pylint/coverage flags are expected.
            yield  # pylint: disable=unreachable

        mw = LangfuseToolSpanMiddleware()
        gen = mw.on_acting(
            SimpleNamespace(),
            {"tool_call": _tool_call()},
            fake_next_handler,
        )
        with pytest.raises(RuntimeError, match="disk on fire"):
            async for _ in gen:
                pass

        obs = client.observations[0]
        # Our record carries the tool error text (the second update with
        # level=ERROR comes from tool_span itself on exception paths)
        assert any("disk on fire" in t for t in _recorded_texts(obs))
        assert obs.calls[0] == "update"
        assert obs.ended is True

    async def test_update_failure_does_not_break_tool_call(self, client):
        """A raising observation.update() must not alter the tool result.

        Langfuse is optional observability: any SDK failure must be
        swallowed (debug log only), and the ToolResponse must flow to
        the consumer exactly as produced.
        """
        client.break_observations()

        tool_response = _text_response("result data")

        async def fake_next_handler():
            yield tool_response

        mw = LangfuseToolSpanMiddleware()
        collected = await _run_like_drain(
            mw.on_acting(
                SimpleNamespace(),
                {"tool_call": _tool_call()},
                fake_next_handler,
            ),
        )

        assert collected == [tool_response]
        assert collected[0] is tool_response
        obs = client.observations[0]
        assert isinstance(obs, BrokenUpdateObservation)
        assert obs.calls == ["update", "end"]

    async def test_update_failure_on_error_chunk_does_not_break(
        self,
        client,
    ):
        """SDK failure on the ERROR path must not alter the error chunk."""
        client.break_observations()

        error_chunk = _chunk("boom", ToolResultState.ERROR)

        async def fake_next_handler():
            yield error_chunk

        mw = LangfuseToolSpanMiddleware()
        collected = await _run_like_drain(
            mw.on_acting(
                SimpleNamespace(),
                {"tool_call": _tool_call()},
                fake_next_handler,
            ),
        )

        assert collected == [error_chunk]

    async def test_output_truncated_over_8kb(self, client):
        """Oversized output is truncated with an explicit marker."""
        from qwenpaw.agents.middlewares import _MAX_RECORDED_TEXT_CHARS

        big_text = "x" * (_MAX_RECORDED_TEXT_CHARS + 1000)

        async def fake_next_handler():
            yield _text_response(big_text)

        mw = LangfuseToolSpanMiddleware()
        await _run_like_drain(
            mw.on_acting(
                SimpleNamespace(),
                {"tool_call": _tool_call()},
                fake_next_handler,
            ),
        )

        obs = client.observations[0]
        recorded = _recorded_texts(obs)[0]
        assert "[truncated 1000 chars]" in recorded
        assert len(recorded) < _MAX_RECORDED_TEXT_CHARS + 100
