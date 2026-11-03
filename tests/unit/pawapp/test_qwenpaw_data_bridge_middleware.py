# -*- coding: utf-8 -*-
"""Bridge middleware tests: gating, takeover, clarification, cancel."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List

import pytest

from agentscope.event import TextBlockDeltaEvent
from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState

from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.hooks.session.session_hook import SessionSaveHook
from qwenpaw.runtime._state_utils import StateProxy
from qwenpaw.runtime.hooks import HookContext, HookRegistry
from qwenpaw.runtime.phases import Phase


def _user_msg(text: str) -> Msg:
    return Msg(name="user", role="user", content=[TextBlock(text=text)])


def _agent() -> SimpleNamespace:
    return SimpleNamespace(
        name="assistant",
        state=SimpleNamespace(context=[]),
    )


async def _forbidden_next(**_kwargs):
    raise AssertionError("next_handler must not run during takeover")
    yield  # pylint: disable=unreachable  # pragma: no cover


class FakeEngine:
    """Scripted engine client double."""

    def __init__(self, frames: List[Dict[str, Any]] | None = None) -> None:
        self.frames = frames or []
        self.calls: List[tuple] = []
        self.stream_kwargs: List[Dict[str, Any]] = []

    async def create_session(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(("create_session", kwargs))
        return {"id": "ses_1"}

    async def create_chat(
        self,
        session_id: str,
        text: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        self.calls.append(("create_chat", session_id, text, kwargs))
        return {"id": "chat_1"}

    async def answer_clarification(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("answer_clarification", args, kwargs))

    async def stop(self, session_id: str, chat_id: str) -> None:
        self.calls.append(("stop", session_id, chat_id))

    async def download_artifact(self, session_id: str, path: str) -> bytes:
        self.calls.append(("download_artifact", session_id, path))
        return b"IMG"

    async def stream_events(
        self,
        session_id: str,
        chat_id: str,
        *,
        after_sequence_number: int = -1,
    ) -> AsyncIterator[Dict[str, Any]]:
        self.stream_kwargs.append(
            {
                "session_id": session_id,
                "chat_id": chat_id,
                "after_sequence_number": after_sequence_number,
            },
        )
        for frame in self.frames:
            yield frame


def _store(bridge_session_store, tmp_path):
    return bridge_session_store.BridgeSessionStore(
        path=tmp_path / "bridge_sessions.json",
    )


def _mw(bridge_middleware, client, store, key="console:alice"):
    return bridge_middleware.DataBridgeMiddleware(
        client=client,
        store=store,
        session_key=key,
    )


async def _drain(gen) -> list:
    return [event async for event in gen]


_ANSWER_FRAMES = [
    {
        "object": "message",
        "id": "m1",
        "type": "message",
        "status": "in_progress",
        "sequence_number": 1,
    },
    {
        "object": "content",
        "type": "text",
        "msg_id": "m1",
        "delta": True,
        "text": "done",
        "sequence_number": 2,
    },
    {
        "object": "response",
        "id": "resp_1",
        "status": "completed",
        "sequence_number": 3,
    },
]


# ---------------------------------------------------------------- factory


def test_factory_gates_on_session_and_channel(
    bridge_middleware,
    bridge_session_store,
    tmp_path,
) -> None:
    store = _store(bridge_session_store, tmp_path)
    factory = bridge_middleware.make_bridge_middleware_factory(
        client=FakeEngine(),
        store=store,
    )

    def ctx(session_id: str, channel: str) -> SimpleNamespace:
        return SimpleNamespace(
            session_id=session_id,
            request=SimpleNamespace(channel=channel),
        )

    # inactive session → skipped
    assert factory(ctx("console:alice", "console"), None) is None
    store.update("console:alice", active=True)
    # app UI sessions and channel-less requests → skipped
    assert factory(ctx("pawapp:qwenpaw-data", "console"), None) is None
    assert factory(ctx("console:alice", ""), None) is None
    # active channel session → takeover
    assert factory(ctx("console:alice", "console"), None) is not None


# ---------------------------------------------------------------- takeover


@pytest.mark.asyncio
async def test_takeover_streams_engine_answer(
    bridge_middleware,
    bridge_session_store,
    tmp_path,
) -> None:
    store = _store(bridge_session_store, tmp_path)
    store.update("console:alice", active=True)
    client = FakeEngine(list(_ANSWER_FRAMES))
    middleware = _mw(bridge_middleware, client, store)
    agent = _agent()

    events = await _drain(
        middleware.on_reply(
            agent,
            {"inputs": _user_msg("分析3月GAAP")},
            _forbidden_next,
        ),
    )

    deltas = [e for e in events if isinstance(e, TextBlockDeltaEvent)]
    assert "".join(e.delta for e in deltas) == "done"
    # engine session created and persisted
    assert store.get("console:alice").engine_session_id == "ses_1"
    assert ("create_chat", "ses_1", "分析3月GAAP", {"datasource_id": None}) in (
        client.calls
    )
    # history recorded: user + assistant
    roles = [m.role for m in agent.state.context]
    assert roles == ["user", "assistant"]
    assert agent.state.context[-1].get_text_content() == "done"


@pytest.mark.asyncio
async def test_takeover_turn_survives_session_save_hook_and_reload(
    bridge_middleware,
    bridge_session_store,
    tmp_path,
) -> None:
    session_id = "console:alice"
    user_id = "alice"
    store = _store(bridge_session_store, tmp_path)
    store.update(session_id, active=True)
    agent = _agent()
    agent.state = AgentState(session_id=session_id)
    agent.state_dict = lambda: {
        "state": agent.state.model_dump(mode="json"),
    }

    await _drain(
        _mw(
            bridge_middleware,
            FakeEngine(list(_ANSWER_FRAMES)),
            store,
            key=session_id,
        ).on_reply(
            agent,
            {"inputs": _user_msg("分析3月GAAP")},
            _forbidden_next,
        ),
    )

    session_dir = tmp_path / "sessions"
    session = SafeJSONSession(save_dir=str(session_dir))
    hooks = HookRegistry()
    hooks.register(SessionSaveHook())
    ctx = HookContext(
        request=SimpleNamespace(
            user_id=user_id,
            channel="console",
            request_context={},
        ),
        session_id=session_id,
        agent_id="assistant",
        root_session_id=session_id,
        root_agent_id="assistant",
        workspace_dir=tmp_path,
        workspace=SimpleNamespace(session=session),
        app_services=None,
        agent=agent,
    )
    await hooks.run(Phase.POST_RESPONSE, ctx)

    restored = StateProxy()
    await SafeJSONSession(save_dir=str(session_dir)).load_session_state(
        session_id=session_id,
        user_id=user_id,
        channel="console",
        allow_not_exist=False,
        agent=restored,
    )
    restored_state = AgentState.model_validate(restored.data["state"])
    assert [
        (message.role, message.get_text_content())
        for message in restored_state.context
    ] == [
        ("user", "分析3月GAAP"),
        ("assistant", "done"),
    ]


@pytest.mark.asyncio
async def test_non_msg_inputs_fall_through(
    bridge_middleware,
    bridge_session_store,
    tmp_path,
) -> None:
    store = _store(bridge_session_store, tmp_path)
    middleware = _mw(bridge_middleware, FakeEngine(), store)
    sentinel = object()

    async def next_handler(**_kwargs):
        yield sentinel

    events = await _drain(
        middleware.on_reply(_agent(), {"inputs": None}, next_handler),
    )
    assert events == [sentinel]


@pytest.mark.asyncio
async def test_engine_down_yields_error_text(
    bridge_middleware,
    bridge_session_store,
    bridge,
    tmp_path,
) -> None:
    store = _store(bridge_session_store, tmp_path)
    store.update("console:alice", active=True)

    class DownEngine(FakeEngine):
        async def create_session(self, **kwargs: Any) -> Dict[str, Any]:
            raise bridge.EngineUnavailableError("not ready")

    middleware = _mw(bridge_middleware, DownEngine(), store)

    events = await _drain(
        middleware.on_reply(
            _agent(),
            {"inputs": _user_msg("hi")},
            _forbidden_next,
        ),
    )
    text = "".join(
        e.delta for e in events if isinstance(e, TextBlockDeltaEvent)
    )
    assert "不可用" in text
    assert "/data off" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["create_chat", "answer", "stream"])
async def test_stale_session_404_clears_persisted_state(
    bridge_middleware,
    bridge_session_store,
    bridge,
    tmp_path,
    failure_point: str,
) -> None:
    store = _store(bridge_session_store, tmp_path)
    pending = None
    if failure_point == "answer":
        pending = {
            "chat_id": "chat_old",
            "clarification_id": "call_old",
            "questions": [],
            "last_seq": 4,
        }
    store.update(
        "console:alice",
        active=True,
        engine_session_id="ses_stale",
        pending_clarification=pending,
    )

    class StaleEngine(FakeEngine):
        async def create_chat(self, *args: Any, **kwargs: Any):
            if failure_point == "create_chat":
                raise bridge.EngineResponseError(404, "secret missing detail")
            return await super().create_chat(*args, **kwargs)

        async def answer_clarification(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> None:
            if failure_point == "answer":
                raise bridge.EngineResponseError(404, "secret missing detail")
            await super().answer_clarification(*args, **kwargs)

        async def stream_events(
            self,
            session_id: str,
            chat_id: str,
            *,
            after_sequence_number: int = -1,
        ) -> AsyncIterator[Dict[str, Any]]:
            if failure_point == "stream":
                raise bridge.EngineResponseError(404, "secret missing detail")
            async for frame in super().stream_events(
                session_id,
                chat_id,
                after_sequence_number=after_sequence_number,
            ):
                yield frame

    events = await _drain(
        _mw(bridge_middleware, StaleEngine(), store).on_reply(
            _agent(),
            {"inputs": _user_msg("retry me")},
            _forbidden_next,
        ),
    )

    state = store.get("console:alice")
    assert state.engine_session_id == ""
    assert state.pending_clarification is None
    text = "".join(
        event.delta
        for event in events
        if isinstance(event, TextBlockDeltaEvent)
    )
    assert "已失效" in text
    assert "重新发送" in text
    assert "secret" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(400, "未能完成"), (500, "不可用")],
)
async def test_http_failures_use_fixed_safe_messages(
    bridge_middleware,
    bridge_session_store,
    bridge,
    tmp_path,
    status_code: int,
    expected: str,
) -> None:
    store = _store(bridge_session_store, tmp_path)
    store.update("console:alice", active=True)

    class ErrorEngine(FakeEngine):
        async def create_session(self, **kwargs: Any) -> Dict[str, Any]:
            raise bridge.EngineResponseError(
                status_code,
                "secret response body",
            )

    events = await _drain(
        _mw(bridge_middleware, ErrorEngine(), store).on_reply(
            _agent(),
            {"inputs": _user_msg("hi")},
            _forbidden_next,
        ),
    )
    text = "".join(
        event.delta
        for event in events
        if isinstance(event, TextBlockDeltaEvent)
    )
    assert expected in text
    assert "secret" not in text


# ------------------------------------------------------- clarification


@pytest.mark.asyncio
async def test_clarification_roundtrip(
    bridge_middleware,
    bridge_session_store,
    tmp_path,
) -> None:
    store = _store(bridge_session_store, tmp_path)
    store.update("console:alice", active=True)
    clarify_frames = [
        {
            "object": "message",
            "id": "p1",
            "type": "plugin_call",
            "status": "completed",
            "sequence_number": 5,
            "content": [
                {
                    "type": "data",
                    "data": {
                        "call_id": "call_9",
                        "name": "ask_user_question",
                        "arguments": (
                            '{"title": "T", "questions": [{'
                            '"question": "哪个季度?", '
                            '"multiSelect": false, '
                            '"options": [{"label": "Q1"}, '
                            '{"label": "Q2"}]}]}'
                        ),
                    },
                },
            ],
        },
    ]
    client = FakeEngine(clarify_frames)
    middleware = _mw(bridge_middleware, client, store)

    # Turn 1: engine asks for clarification.
    await _drain(
        middleware.on_reply(
            _agent(),
            {"inputs": _user_msg("分析GAAP")},
            _forbidden_next,
        ),
    )
    pending = store.get("console:alice").pending_clarification
    assert pending is not None
    assert pending["clarification_id"] == "call_9"
    assert pending["chat_id"] == "chat_1"
    assert pending["last_seq"] == 5

    # Turn 2: numeric reply answers and resumes the same chat stream.
    client.frames = list(_ANSWER_FRAMES)
    middleware2 = _mw(bridge_middleware, client, store)
    events = await _drain(
        middleware2.on_reply(
            _agent(),
            {"inputs": _user_msg("1")},
            _forbidden_next,
        ),
    )

    answer_call = next(
        c for c in client.calls if c[0] == "answer_clarification"
    )
    assert answer_call[1] == ("ses_1", "chat_1")
    assert answer_call[2]["clarification_id"] == "call_9"
    assert answer_call[2]["answers"] == [
        {
            "question": "哪个季度?",
            "selected_options": ["Q1"],
            "custom_text": None,
        },
    ]
    # resumed from the persisted sequence, same chat, no new chat created
    assert client.stream_kwargs[-1] == {
        "session_id": "ses_1",
        "chat_id": "chat_1",
        "after_sequence_number": 5,
    }
    assert store.get("console:alice").pending_clarification is None
    text = "".join(
        e.delta for e in events if isinstance(e, TextBlockDeltaEvent)
    )
    assert text == "done"


@pytest.mark.asyncio
async def test_clarification_free_text_becomes_custom_answer(
    bridge_middleware,
    bridge_session_store,
    tmp_path,
) -> None:
    store = _store(bridge_session_store, tmp_path)
    store.update(
        "console:alice",
        active=True,
        engine_session_id="ses_1",
        pending_clarification={
            "chat_id": "chat_1",
            "clarification_id": "call_9",
            "last_seq": 5,
            "questions": [
                {
                    "question": "哪个季度?",
                    "multi_select": False,
                    "options": [{"label": "Q1"}, {"label": "Q2"}],
                },
            ],
        },
    )
    client = FakeEngine(list(_ANSWER_FRAMES))
    middleware = _mw(bridge_middleware, client, store)

    await _drain(
        middleware.on_reply(
            _agent(),
            {"inputs": _user_msg("全年整体")},
            _forbidden_next,
        ),
    )
    answer_call = next(
        c for c in client.calls if c[0] == "answer_clarification"
    )
    assert answer_call[2]["answers"] == [
        {
            "question": "哪个季度?",
            "selected_options": [],
            "custom_text": "全年整体",
        },
    ]


@pytest.mark.asyncio
async def test_malformed_persisted_clarification_falls_back_to_custom_text(
    bridge_middleware,
    bridge_session_store,
    tmp_path,
) -> None:
    store = _store(bridge_session_store, tmp_path)
    store.update(
        "console:alice",
        active=True,
        engine_session_id="ses_1",
        pending_clarification={
            "chat_id": "chat_1",
            "clarification_id": "call_9",
            "last_seq": "not-a-number",
            "questions": [
                "not-a-question",
                {"question": 42, "options": "not-options"},
                {
                    "question": "Pick one",
                    "options": [{"description": "missing label"}],
                },
                {
                    "question": "Another",
                    "options": [{"label": 7}],
                },
            ],
        },
    )
    client = FakeEngine(list(_ANSWER_FRAMES))

    await _drain(
        _mw(bridge_middleware, client, store).on_reply(
            _agent(),
            {"inputs": _user_msg("1")},
            _forbidden_next,
        ),
    )

    answer_call = next(
        call for call in client.calls if call[0] == "answer_clarification"
    )
    assert answer_call[2]["answers"] == [
        {"question": "", "selected_options": [], "custom_text": "1"},
        {"question": "", "selected_options": [], "custom_text": "1"},
        {"question": "Pick one", "selected_options": [], "custom_text": "1"},
        {"question": "Another", "selected_options": [], "custom_text": "1"},
    ]
    assert client.stream_kwargs[-1]["after_sequence_number"] == -1


@pytest.mark.asyncio
async def test_answered_clarification_resumes_after_stream_failure(
    bridge_middleware,
    bridge_session_store,
    bridge,
    tmp_path,
) -> None:
    store = _store(bridge_session_store, tmp_path)
    store.update(
        "console:alice",
        active=True,
        engine_session_id="ses_1",
        pending_clarification={
            "chat_id": "chat_1",
            "clarification_id": "call_9",
            "last_seq": 5,
            "questions": [
                {
                    "question": "哪个季度?",
                    "multi_select": False,
                    "options": [{"label": "Q1"}, {"label": "Q2"}],
                },
            ],
        },
    )

    class FlakyStreamEngine(FakeEngine):
        def __init__(self) -> None:
            super().__init__(list(_ANSWER_FRAMES))
            self.stream_attempts = 0

        async def stream_events(
            self,
            session_id: str,
            chat_id: str,
            *,
            after_sequence_number: int = -1,
        ) -> AsyncIterator[Dict[str, Any]]:
            self.stream_attempts += 1
            if self.stream_attempts == 1:
                raise bridge.EngineUnavailableError("disconnected")
            async for frame in super().stream_events(
                session_id,
                chat_id,
                after_sequence_number=after_sequence_number,
            ):
                yield frame

    client = FlakyStreamEngine()
    middleware = _mw(bridge_middleware, client, store)

    await _drain(
        middleware.on_reply(
            _agent(),
            {"inputs": _user_msg("1")},
            _forbidden_next,
        ),
    )
    pending = store.get("console:alice").pending_clarification
    assert pending is not None and pending["answered"] is True

    await _drain(
        middleware.on_reply(
            _agent(),
            {"inputs": _user_msg("重试")},
            _forbidden_next,
        ),
    )

    assert [call[0] for call in client.calls].count(
        "answer_clarification",
    ) == 1
    assert not any(call[0] == "create_chat" for call in client.calls)
    assert store.get("console:alice").pending_clarification is None


# ---------------------------------------------------------------- datasource


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1", [0]),
        (" 1, 3 ", [0, 2]),
        ("1，2、3", [0, 1, 2]),
        ("1 2\t3", [0, 1, 2]),
        ("2,2", [1, 1]),
    ],
)
def test_parse_option_numbers_accepts_supported_separators(
    bridge_middleware,
    text: str,
    expected: list[int],
) -> None:
    assert bridge_middleware.parse_option_numbers(text, 3) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        ",1",
        "1,",
        "1,,2",
        "1，、2",
        "one",
        "1.2",
        "+1",
        "-1",
        "0",
        "4",
    ],
)
def test_parse_option_numbers_rejects_malformed_or_out_of_range_input(
    bridge_middleware,
    text: str,
) -> None:
    assert bridge_middleware.parse_option_numbers(text, 3) is None


def test_parse_option_numbers_handles_long_input_linearly(
    bridge_middleware,
) -> None:
    text = "1 " * 10_000 + "x"
    assert bridge_middleware.parse_option_numbers(text, 3) is None


@pytest.mark.asyncio
async def test_datasource_numeric_selection_binds_new_session(
    bridge_middleware,
    bridge_session_store,
    tmp_path,
) -> None:
    store = _store(bridge_session_store, tmp_path)
    store.update(
        "console:alice",
        active=True,
        engine_session_id="ses_old",
        pending_datasource_choice=[
            {"id": "ds_a", "name": "Demo PG"},
            {"id": "ds_b", "name": "DuckDB"},
        ],
    )
    client = FakeEngine()
    middleware = _mw(bridge_middleware, client, store)

    events = await _drain(
        middleware.on_reply(
            _agent(),
            {"inputs": _user_msg("2")},
            _forbidden_next,
        ),
    )

    state = store.get("console:alice")
    assert state.datasource_id == "ds_b"
    assert state.engine_session_id == "ses_1"  # fresh session
    assert state.pending_datasource_choice is None
    text = "".join(
        e.delta for e in events if isinstance(e, TextBlockDeltaEvent)
    )
    assert "DuckDB" in text
    session_call = next(c for c in client.calls if c[0] == "create_session")
    assert session_call[1]["datasource_id"] == "ds_b"


@pytest.mark.asyncio
async def test_datasource_non_numeric_reply_clears_offer_and_chats(
    bridge_middleware,
    bridge_session_store,
    tmp_path,
) -> None:
    store = _store(bridge_session_store, tmp_path)
    store.update(
        "console:alice",
        active=True,
        engine_session_id="ses_1",
        pending_datasource_choice=[{"id": "ds_a", "name": "Demo PG"}],
    )
    client = FakeEngine(list(_ANSWER_FRAMES))
    middleware = _mw(bridge_middleware, client, store)

    await _drain(
        middleware.on_reply(
            _agent(),
            {"inputs": _user_msg("分析3月")},
            _forbidden_next,
        ),
    )
    assert store.get("console:alice").pending_datasource_choice is None
    assert any(c[0] == "create_chat" for c in client.calls)


# ---------------------------------------------------------------- cancel


@pytest.mark.asyncio
async def test_cancel_stops_engine_chat(
    bridge_middleware,
    bridge_session_store,
    tmp_path,
) -> None:
    store = _store(bridge_session_store, tmp_path)
    store.update("console:alice", active=True, engine_session_id="ses_1")

    class HangingEngine(FakeEngine):
        async def stream_events(
            self,
            session_id: str,
            chat_id: str,
            *,
            after_sequence_number: int = -1,
        ) -> AsyncIterator[Dict[str, Any]]:
            yield {
                "object": "message",
                "id": "m1",
                "type": "message",
                "status": "in_progress",
                "sequence_number": 1,
            }
            raise asyncio.CancelledError()

    client = HangingEngine()
    middleware = _mw(bridge_middleware, client, store)

    with pytest.raises(asyncio.CancelledError):
        await _drain(
            middleware.on_reply(
                _agent(),
                {"inputs": _user_msg("long analysis")},
                _forbidden_next,
            ),
        )
    assert ("stop", "ses_1", "chat_1") in client.calls
