"""Ordinary Chat late-result races: no second executor or user admission."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock

from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.app.chats.background_results import (
    ChatBackgroundResults,
    consume_result_ticket,
)
from qwenpaw.app.task_tracker import RunInput, TaskTracker
from qwenpaw.runtime.reply_cycle import InternalResultInput, ReplyCycleContext
from qwenpaw.schemas import TextContent


def result_message():
    return Msg(
        name="background", role="assistant", content=[TextBlock(text="42")]
    )


class Harness:
    def __init__(self):
        self.tracker = TaskTracker()
        self.results = ChatBackgroundResults(self.tracker, "chat")
        self.tracker.background_results["chat"] = self.results
        self.payload = {
            "content_parts": [TextContent(text="calculate")],
            "meta": {"request_context": {"_background_results": self.results}},
        }
        self.results.payload = self.payload
        self.results.stream_fn = self.stream
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.closing, self.save_release = asyncio.Event(), asyncio.Event()
        self.consume_entered, self.consume_release = (
            asyncio.Event(),
            asyncio.Event(),
        )
        self.consume_release.set()
        self.save_release.set()
        self.writers = self.max_writers = 0
        self.seen = []
        self.inputs = []
        self.saved = "saved"

    async def start(self):
        await self.tracker.submit_or_start(
            "chat",
            self.payload,
            self.stream,
            RunInput((TextContent(text="calculate"),), "original"),
        )
        await self.entered.wait()
        rc = self.payload["meta"]["request_context"]["_reply_cycle_context"]
        self.route = self.results.bind_call(
            rc.snapshot, SimpleNamespace(id="call", name="calculate")
        )
        self.work = self.route.register()
        return self.work

    async def stream(self, payload):
        self.writers += 1
        self.max_writers = max(self.max_writers, self.writers)
        rc = payload["meta"]["request_context"]
        cycle, mailbox = rc["_reply_cycle_context"], rc["_run_input_mailbox"]
        pending = [rc["_internal_result"]] if "_internal_result" in rc else []
        try:
            if not pending:
                self.inputs.extend(payload["content_parts"])
                self.entered.set()
                await self.release.wait()
                cycle.finish_reply("completed")
            while True:
                for item in pending:
                    assert isinstance(item, InternalResultInput)
                    if self.results.is_cancelled(item.work_id):
                        continue
                    cycle.activate(item.input_ids)
                    self.results.observed(item.work_id, cycle.run_id)
                    self.consume_entered.set()
                    await self.consume_release.wait()
                    self.seen.append(item.work_id)
                    self.results.replied(item.work_id, cycle.run_id)
                    cycle.finish_reply("completed")
                    yield (
                        'data: {"object":"response","status":"completed"}\n\n'
                    )
                pending = mailbox.drain_after_reply()
                if not pending:
                    mailbox.close()
                    break
            self.closing.set()
            await self.save_release.wait()
            rc["_session_save_result"].status = self.saved
        finally:
            self.writers -= 1

    async def flush(self):
        if self.work.submit_task is not None:
            await asyncio.wait_for(self.work.submit_task, 2)
        assert await self.tracker.wait_all_done(timeout=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["active", "closing", "idle"])
async def test_result_returns_once_through_single_writer(phase):
    h = Harness()
    work = await h.start()
    h.route.finish_receipt()
    if phase == "closing":
        h.save_release.clear()
    if phase != "active":
        h.release.set()
        await h.closing.wait()
    if phase == "idle":
        assert await h.tracker.wait_all_done(timeout=2)
    work.complete("completed", result_message())
    await asyncio.sleep(0)
    if phase == "closing":
        assert not h.seen
        h.save_release.set()
    h.release.set()
    await h.flush()
    work.complete("completed", result_message())
    h.results.retry_pending()
    await asyncio.sleep(0)
    assert h.seen == [work.work_id]
    assert len(h.inputs) == 1
    assert h.max_writers == 1
    assert work.delivery == "delivered"
    assert not h.results.pending("original")


@pytest.mark.asyncio
async def test_result_before_receipt_is_held():
    h = Harness()
    work = await h.start()
    work.complete("completed", result_message())
    await asyncio.sleep(0)
    assert work.submit_task is None
    h.route.finish_receipt()
    h.release.set()
    await h.flush()
    assert h.seen == [work.work_id]


@pytest.mark.asyncio
async def test_cancel_consuming_input_covers_all_its_calls():
    h = Harness()
    work = await h.start()
    sibling = h.route.register()
    h.route.finish_receipt()
    h.consume_release.clear()
    work.complete("completed", result_message())
    await work.submit_task
    h.release.set()
    await h.consume_entered.wait()
    await h.tracker.request_stop("chat")
    sibling.complete("completed", result_message())
    h.results.retry_pending()
    assert work.delivery == sibling.delivery == "cancelled"
    assert not h.seen


@pytest.mark.asyncio
async def test_unsaved_parent_receipt_does_not_start_a_new_agent():
    h = Harness()
    work = await h.start()
    h.saved = "failed"
    h.route.finish_receipt()
    h.release.set()
    assert await h.tracker.wait_all_done(timeout=2)
    work.complete("completed", result_message())
    await h.flush()
    assert work.delivery == "failed"
    assert "receipt" in work.error
    assert h.results.pending("original")
    assert not h.seen


@pytest.mark.asyncio
async def test_dispatch_ticket_is_destination_bound_one_use_and_ready_gated():
    h = Harness()
    await h.start()
    token = await asyncio.to_thread(h.route.issue_ticket, "child")
    with pytest.raises(ValueError):
        consume_result_ticket(token, "other")
    child = consume_result_ticket(token, "child")
    with pytest.raises(ValueError):
        consume_result_ticket(token, "child")
    child.complete("completed", result_message())
    assert child.submit_task is None
    h.route.finish_receipt()
    h.release.set()
    await child.submit_task
    assert await h.tracker.wait_all_done(timeout=2)
    assert child.delivery == "delivered"
    # Other work is still outstanding; a replied parent is not task success.
    assert h.results.pending("original")


@pytest.mark.asyncio
async def test_agent_observation_and_feedback_markers_are_idempotent():
    h = Harness()
    work = await h.start()
    work.complete("completed", result_message())
    agent = object.__new__(QwenPawAgent)
    agent.name = "Parent"
    agent._request_context = {"_background_results": h.results}
    agent._reply_cycle_context = ReplyCycleContext("continuation", "original")
    agent._context_manager = None
    agent._observed_result_ids = set()
    agent._feedback_result_ids = set()
    agent._active_result_ids = set()
    agent.observe = AsyncMock()
    item = h.results.make_input(work)
    assert await agent.observe_background_result(item)
    assert await agent.observe_background_result(item)
    agent.observe.assert_awaited_once()
    message = agent.observe.call_args.args[0]
    assert message.role == "assistant"
    assert message.metadata["internal_result_id"] == work.work_id
    agent._feedback_result_ids.add(work.work_id)
    assert not await agent.observe_background_result(item)
    assert work.delivery == "replied"
    await h.tracker.request_stop("chat")


@pytest.mark.asyncio
async def test_explicit_result_query_joins_push_feedback_identity():
    h = Harness()
    work = await h.start()
    work.task_id = "child-task"
    query_route = h.results.bind_call(
        h.route.snapshot, SimpleNamespace(id="query", name="check_agent_task")
    )
    query_route.record_polled_result("child-task")
    assert query_route.reported_results == {work.work_id}
    agent = object.__new__(QwenPawAgent)
    agent._request_context = {"_background_results": h.results}
    agent._reply_cycle_context = ReplyCycleContext("reply", "query-input")
    agent._activate_reply_cycle = agent._reply_cycle_context.activate
    agent._observed_result_ids = set()
    agent._feedback_result_ids = set()
    agent._active_result_ids = set()
    agent.accept_background_tool_result(work.work_id)
    assert agent._active_result_ids == {work.work_id}
    assert agent._observed_result_ids == {work.work_id}
    assert work.delivery == "observed"
    assert (
        "original" in agent._reply_cycle_context.snapshot.responds_to_input_ids
    )
    # Once that reply completes, the already queued push cannot answer twice.
    agent._feedback_result_ids.update(agent._active_result_ids)
    work.complete("completed", result_message())
    assert not await agent.observe_background_result(
        h.results.make_input(work)
    )
    await h.tracker.request_stop("chat")


@pytest.mark.asyncio
async def test_close_revokes_unconsumed_tickets_and_cancels_producer():
    h = Harness()
    await h.start()
    token = await asyncio.to_thread(h.route.issue_ticket, "child")
    work = consume_result_ticket(token, "child", consume=False)
    cancelled = asyncio.Event()
    work.cancel = cancelled.set
    await h.results.close()
    assert cancelled.is_set()
    with pytest.raises(ValueError):
        consume_result_ticket(token, "child")
    await h.tracker.request_stop("chat")


@pytest.mark.asyncio
async def test_delete_revokes_result_owner_before_late_completion():
    from qwenpaw.app.chats.api import _close_background_results

    h = Harness()
    work = await h.start()
    await _close_background_results(
        SimpleNamespace(task_tracker=h.tracker), ["chat"]
    )
    work.complete("completed", result_message())
    assert h.results.closed
    assert work.delivery == "cancelled"
    assert "chat" not in h.tracker.background_results
    assert not h.seen


@pytest.mark.asyncio
async def test_idle_result_uses_current_workspace_after_hot_reload():
    h = Harness()
    work = await h.start()
    h.route.finish_receipt()
    h.release.set()
    assert await h.tracker.wait_all_done(timeout=2)
    current = SimpleNamespace(
        task_tracker=h.tracker,
        channel_manager=SimpleNamespace(
            get_channel=AsyncMock(
                return_value=SimpleNamespace(stream_one=h.stream)
            )
        ),
    )
    h.results.workspace = SimpleNamespace(
        agent_id="default",
        _manager=SimpleNamespace(get_agent=AsyncMock(return_value=current)),
    )
    work.complete("completed", result_message())
    await h.flush()
    assert work.delivery == "delivered"
    assert h.results.workspace is current


@pytest.mark.asyncio
async def test_owned_offload_returns_through_chat_not_legacy_hint_queue():
    import httpx
    from fastapi import FastAPI
    from agentscope.tool import ToolResponse
    from qwenpaw.tool_calls import ToolCoordinator

    h = Harness()
    await h.start()
    coordinator = ToolCoordinator(
        default_timeout_secs=0.001, offload_on_deadline=True
    )
    release = asyncio.Event()
    call = SimpleNamespace(id="offload", name="slow", input={})

    async def handler(tool_call):
        await release.wait()
        yield ToolResponse(id=tool_call.id, content=[TextBlock(text="42")])

    events = [
        event
        async for event in coordinator.execute(
            tool_call=call,
            next_handler=handler,
            session_id="session",
            agent_id="default",
            root_session_id="root",
            result_route=h.route,
        )
    ]
    assert events[-1].metadata["offloaded"]
    from qwenpaw.app.routers.tool_calls import _entry_to_info, ListResponse

    entry = coordinator.get(call.id)
    assert entry.ctx.result_route is h.route
    assert entry.ctx.background_work is not None
    entry.ctx.extra["label"] = "public label"
    info = _entry_to_info(entry, coordinator)
    assert info.extra == {"label": "public label"}
    assert "result_route" not in info.model_dump_json()
    assert '"total":1' in ListResponse(items=[info], total=1).model_dump_json()
    # Exercise FastAPI's actual list/detail response serialization with live
    # route/work objects, not just an empty real-server listing.
    from qwenpaw.app.routers.tool_calls import router

    app = FastAPI()
    app.state.app_services = SimpleNamespace(tool_coordinator=coordinator)
    app.include_router(router, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        listing = await client.get("/api/tool-calls/session")
        assert listing.status_code == 200
        assert listing.json()["total"] == 1
        detail = await client.get("/api/tool-calls/session/offload")
        assert detail.status_code == 200
        assert detail.json()["extra"] == {"label": "public label"}
        assert "result_route" not in detail.text
    offloaded = h.route.works[-1]
    h.route.finish_receipt()
    h.release.set()
    assert await h.tracker.wait_all_done(timeout=2)
    release.set()
    for _ in range(200):
        if offloaded.delivery == "delivered":
            break
        await asyncio.sleep(0.01)
    assert offloaded.delivery == "delivered"
    assert "42" in offloaded.message.get_text_content()
    assert await coordinator.pop_pending_hints("session") == []
    assert h.seen == [offloaded.work_id]
    await h.results.close()


@pytest.mark.asyncio
async def test_native_internal_input_has_no_forged_user_message(tmp_path):
    from qwenpaw.app.channels.console.channel import ConsoleChannel

    async def process(request):
        assert request.input == []
        assert isinstance(
            request.request_context["_internal_result"], InternalResultInput
        )
        if False:
            yield

    channel = ConsoleChannel(
        process=process, enabled=True, bot_prefix="", media_dir=str(tmp_path)
    )
    channel._apply_no_text_debounce = lambda *_: pytest.fail("Not user input")
    payload = {
        "sender_id": "test",
        "meta": {
            "session_id": "session",
            "request_context": {
                "_internal_result": InternalResultInput(
                    "work", ("original",), result_message()
                )
            },
        },
    }
    assert channel.build_agent_request_from_native(payload).input == []
    assert [event async for event in channel.stream_one(payload)] == []
