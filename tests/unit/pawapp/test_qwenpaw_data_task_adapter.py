# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Data task adapter protocol, text replay, and failure-boundary tests."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from qwenpaw.pawapp.tasks import (
    ActionDescriptor,
    ExecutorRunRef,
    TaskOrigin,
    TaskScope,
    TaskStore,
    TaskStoreError,
)
from tests.pawapp_data_task_support import load_data_task_bridge

BRIDGE = load_data_task_bridge()
CAPS = {
    "protocol_version": 1,
    "durable_submissions": True,
    "event_replay": True,
}
REF = ExecutorRunRef(
    executor_id="data:test",
    session_id="ses_1",
    run_id="chat_1",
)


@pytest.fixture
async def submission(tmp_path):
    store = await TaskStore.open(tmp_path / "tasks.db")
    item = await store.create(
        TaskScope(
            principal_id="alice",
            workspace_id="w1",
            app_id="qwenpaw-data",
        ),
        BRIDGE.data_action_descriptor(),
        request_id="request-1",
        inputs={"text": "Analyze sales", "datasource_id": "sales"},
        origin=TaskOrigin(
            engagement="delegated",
            origin_ref="main:1",
            return_session_ref="main:1",
        ),
    )
    await store.begin_submission(item.handle.scope, item.handle.task_id)
    return await store.record_accepted(
        item.handle.scope,
        item.handle.task_id,
        REF,
    )


def receipt(submission, state="accepted"):
    return {
        "protocol_version": 1,
        "submission_id": submission.handle.submission_id,
        "state": state,
        "run": None
        if state == "not_found"
        else {
            "session_id": REF.session_id,
            "run_id": REF.run_id,
        },
    }


def frames(*items):
    return [
        {
            "sequence_number": seq,
            "session_id": REF.session_id,
            "chat_id": REF.run_id,
            **item,
        }
        for seq, item in enumerate(items)
    ]


def message(
    msg_id="m1",
    *,
    role="assistant",
    kind="message",
    content=None,
    seq=1,
):
    return {
        "object": "message",
        "id": msg_id,
        "sequence": seq,
        "type": kind,
        "role": role,
        "status": "in_progress",
        "content": [] if content is None else content,
    }


def text(value, *, msg_id="m1", delta=True):
    return {
        "object": "content",
        "msg_id": msg_id,
        "type": "text",
        "index": 0,
        "delta": delta,
        "text": value,
    }


def wire(items):
    return "".join(
        f'id: {item["sequence_number"]}\nevent: {item["object"]}\n'
        f"data: {json.dumps(item)}\n\n"
        for item in items
    )


def client(
    submission,
    *,
    events=(),
    query=None,
    capabilities=None,
    requests=None,
):
    def handler(request):
        if requests is not None:
            requests.append(request)
        if request.url.path == "/api/v1/capabilities/submissions":
            return httpx.Response(
                200,
                json=CAPS if capabilities is None else capabilities,
            )
        if request.url.path.endswith("/events"):
            return httpx.Response(
                200,
                text=wire(events),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(
            200,
            json=receipt(submission) if query is None else query,
        )

    return BRIDGE.DataTaskAdapter(
        lambda: ("http://engine.test", "test-token"),
        executor_id=REF.executor_id,
        transport=httpx.MockTransport(handler),
    )


async def collect(adapter, submission):
    try:
        return [event async for event in adapter.attach(submission)]
    finally:
        await adapter.aclose()


def test_registered_contract_matches_design_fixture():
    path = (
        Path(__file__).resolve().parents[3]
        / "docs/design/pawapp-vnext-data-action.example.json"
    )
    assert (
        BRIDGE.data_action_descriptor()
        == ActionDescriptor.model_validate_json(path.read_text())
    )


async def test_submit_uses_durable_endpoint_and_scope_stamp(submission):
    requests = []
    adapter = client(submission, requests=requests)
    try:
        assert await adapter.submit(submission) == REF
    finally:
        await adapter.aclose()
    assert [req.url.path for req in requests] == [
        "/api/v1/capabilities/submissions",
        "/api/v1/submissions",
    ]
    assert json.loads(requests[-1].content) == {
        "protocol_version": 1,
        "agent_id": "default",
        "submission_id": submission.handle.submission_id,
        **submission.inputs,
    }
    assert all(
        req.headers["authorization"] == "Bearer test-token" for req in requests
    )
    assert all(
        req.headers["x-user-id"]
        == adapter.identity_namespace(submission.handle.scope)
        for req in requests
    )


@pytest.mark.parametrize("field", ["principal_id", "workspace_id", "app_id"])
def test_each_scope_component_changes_namespace(submission, field):
    scope = submission.handle.scope
    assert BRIDGE.DataTaskAdapter.identity_namespace(
        scope,
    ) != BRIDGE.DataTaskAdapter.identity_namespace(
        scope.model_copy(update={field: "other"}),
    )


@pytest.mark.parametrize(
    "caps",
    [
        {},
        {**CAPS, "protocol_version": 2},
        {**CAPS, "protocol_version": True},
        {**CAPS, "durable_submissions": False},
        {**CAPS, "event_replay": False},
    ],
)
async def test_unsupported_engine_is_blocked_before_post(submission, caps):
    requests = []
    adapter = client(submission, capabilities=caps, requests=requests)
    try:
        with pytest.raises(
            TaskStoreError,
            match="unsupported_engine_protocol",
        ):
            await adapter.submit(submission)
    finally:
        await adapter.aclose()
    assert [req.method for req in requests] == ["GET"]


@pytest.mark.parametrize("status", [301, 401, 404, 500, 501])
async def test_http_failure_is_unknown_without_leaking_body(
    submission,
    status,
):
    def handler(request):
        if request.url.path.endswith("capabilities/submissions"):
            return httpx.Response(200, json=CAPS)
        return httpx.Response(status, text="secret-response-token")

    adapter = BRIDGE.DataTaskAdapter(
        lambda: ("http://engine.test", "test-token"),
        executor_id=REF.executor_id,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert (await adapter.query(submission)).state == "unknown"
        with pytest.raises(TaskStoreError) as exc:
            await adapter.submit(submission)
        assert "secret" not in str(exc.value)
    finally:
        await adapter.aclose()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"state": "not_found"},
        {
            "protocol_version": 1,
            "submission_id": "wrong",
            "state": "not_found",
        },
    ],
)
async def test_malformed_lookup_is_unknown(submission, payload):
    adapter = client(submission, query=payload)
    try:
        assert (await adapter.query(submission)).state == "unknown"
    finally:
        await adapter.aclose()


async def test_only_authoritative_lookup_permits_retry(submission):
    adapter = client(submission, query=receipt(submission, "not_found"))
    try:
        assert (await adapter.query(submission)).state == "not_found"
    finally:
        await adapter.aclose()


async def test_text_snapshots_replace_deltas_and_exclude_private_prose(
    submission,
):
    items = frames(
        {"object": "response", "status": "created"},
        message("reasoning", kind="reasoning"),
        text("private thought", msg_id="reasoning"),
        message("tool", role="tool", kind="plugin_call", seq=2),
        text("tool secret", msg_id="tool"),
        message(seq=3),
        text("Rev"),
        text("enue"),
        text("Revenue", delta=False),
        message(
            content=[{"type": "text", "text": "Revenue corrected"}],
            seq=3,
        ),
        message("m2", seq=4),
        text("is 42", msg_id="m2"),
        {"object": "response", "status": "completed"},
    )
    events = await collect(client(submission, events=items), submission)
    assert events[-1].status == "succeeded"
    assert events[-1].text_result == "Revenue corrected\n\nis 42"
    assert "private thought" not in str(
        [event.model_dump() for event in events],
    )
    assert "tool secret" not in str([event.model_dump() for event in events])


async def test_resume_rebuilds_projection_and_only_emits_after_cursor(
    submission,
):
    items = frames(
        message(),
        text("Rev"),
        text("enue"),
        {"object": "response", "status": "completed"},
    )
    resumed = submission.model_copy(
        update={
            "handle": submission.handle.model_copy(
                update={
                    "replay_cursor": "1",
                    "executor_sequence": 1,
                    "text_result": "Rev",
                },
            ),
        },
    )
    events = await collect(client(resumed, events=items), resumed)
    assert [event.sequence for event in events] == [2, 3]
    assert events[-1].text_result == "Revenue"


@pytest.mark.parametrize(
    "change",
    ["gap", "wrong_run", "changed_prefix", "missing_prefix"],
)
async def test_replay_inconsistency_cannot_complete(submission, change):
    items = frames(
        message(),
        text("old"),
        {"object": "response", "status": "completed"},
    )
    if change == "gap":
        items[1]["sequence_number"] = 8
    elif change == "wrong_run":
        items[1]["chat_id"] = "chat_other"
    else:
        submission = submission.model_copy(
            update={
                "handle": submission.handle.model_copy(
                    update={
                        "replay_cursor": "1",
                        "executor_sequence": 1,
                        "text_result": "original",
                    },
                ),
            },
        )
        if change == "missing_prefix":
            items = []
    with pytest.raises(TaskStoreError, match="engine_replay_"):
        await collect(client(submission, events=items), submission)


@pytest.mark.parametrize(
    "status,reason,expected",
    [
        ("failed", None, "failed"),
        ("cancelled", None, "cancelled"),
        ("cancelled", "executor_restarted", "interrupted"),
    ],
)
async def test_terminal_mapping_preserves_partial_result(
    submission,
    status,
    reason,
    expected,
):
    items = frames(
        message(),
        text("partial"),
        {
            "object": "response",
            "status": status,
            "error": {
                "code": "VALIDATION",
                "message": "provider secret",
                "details": {"reason": reason},
            },
        },
    )
    events = await collect(client(submission, events=items), submission)
    assert events[-1].status == expected
    assert events[-1].text_result == "partial"
    assert "provider secret" not in str(events[-1].model_dump())


async def test_eof_does_not_produce_success(submission):
    items = frames(message(), text("partial"))
    events = await collect(client(submission, events=items), submission)
    assert all(event.status != "succeeded" for event in events)


async def test_replaced_run_is_rejected_before_replay(submission):
    payload = receipt(submission)
    payload["run"]["run_id"] = "chat_replacement"
    requests = []
    adapter = client(submission, query=payload, requests=requests)
    with pytest.raises(TaskStoreError, match="run_conflict"):
        await collect(adapter, submission)
    assert not any(
        request.url.path.endswith("/events") for request in requests
    )


async def test_old_engine_does_not_fall_back_to_chat_post(submission):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(404)

    adapter = BRIDGE.DataTaskAdapter(
        lambda: ("http://engine.test", "token"),
        executor_id=REF.executor_id,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(
            TaskStoreError,
            match="unsupported_engine_protocol",
        ):
            await adapter.submit(submission)
    finally:
        await adapter.aclose()
    assert len(requests) == 1
    assert requests[0].url.path == "/api/v1/capabilities/submissions"


async def test_scope_change_cannot_attach_another_scopes_run(submission):
    other = submission.model_copy(
        update={
            "handle": submission.handle.model_copy(
                update={
                    "scope": submission.handle.scope.model_copy(
                        update={"workspace_id": "other"},
                    ),
                },
            ),
        },
    )
    requests = []
    adapter = client(
        other,
        query=receipt(other, "not_found"),
        requests=requests,
    )
    with pytest.raises(TaskStoreError, match="run_conflict"):
        await collect(adapter, other)
    assert all(
        request.headers["x-user-id"]
        == adapter.identity_namespace(other.handle.scope)
        for request in requests
    )


@pytest.mark.parametrize(
    "body",
    [
        "id: 0\ndata: {broken}\n\n",
        "id: 0\ndata: []\n\n",
        'id: 0\ndata: {"sequence_number": 1}\n\n',
        'id: 0\ndata: {"sequence_number": 0,"object":"response",'
        '"status":"completed"}\n',
    ],
)
async def test_malformed_or_truncated_stream_is_not_success(submission, body):
    def handler(request):
        if request.url.path.endswith("capabilities/submissions"):
            return httpx.Response(200, json=CAPS)
        if request.url.path.endswith("/events"):
            return httpx.Response(
                200,
                text=body,
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(200, json=receipt(submission))

    adapter = BRIDGE.DataTaskAdapter(
        lambda: ("http://engine.test", "test-token"),
        executor_id=REF.executor_id,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(TaskStoreError):
        await collect(adapter, submission)
