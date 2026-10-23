# -*- coding: utf-8 -*-
"""DingTalk feedback receipts through the real lifecycle and SQLite archive."""

import hashlib
import json
from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/channel/dingtalk"))

# The isolated child loads this repository's plugin before importing it.
from dingtalk.driver import DingTalkDriver  # noqa: E402
from qwenpaw.channel_protocol.errors import RpcError  # noqa: E402
from qwenpaw.channel_protocol.models import (  # noqa: E402
    IdentityParams,
    ResponseFinishParams,
    ResponseOutcome,
    SendParams,
)
from qwenpaw.channel_protocol.response_receipts import (  # noqa: E402
    ResponseReceiptStore,
    receipt_key,
)
from qwenpaw.channel_protocol.shared_worker import DriverContext  # noqa: E402

STATE_KEY = "dingtalk.shared.responses"


class HostPeer:
    """Only the host RPC boundary is simulated; archive validation is real."""

    def __init__(self, root):
        self.path = root / "host-state.json"
        self.receipts = ResponseReceiptStore(root / "receipts.sqlite3")
        self.events = []
        self.fail_archive = False

    def register_method(self, *args):
        pass

    async def notify(self, *args):
        pass

    def rows(self):
        return json.loads(self.path.read_text()).get(STATE_KEY, [])

    async def call(self, name, params):
        if name == "event.batch":
            self.events.extend(params["events"])
            return {
                "batch_id": params["batch_id"],
                "accepted_event_ids": [
                    e["event_id"] for e in params["events"]
                ],
                "duplicate_event_ids": [],
                "rejected_events": [],
            }
        key = params["key"]
        if name.startswith("host.state."):
            state = (
                json.loads(self.path.read_text()) if self.path.exists() else {}
            )
            if name.endswith(".put"):
                state[key] = params["value"]
                self.path.write_text(json.dumps(state))
            return {"value": state.get(key)}
        if name == "host.receipt.get":
            return {"value": self.receipts.get(key)}
        if name == "host.receipt.put":
            if self.fail_archive:
                raise OSError("archive unavailable")
            self.receipts.put(key, params["value"])
            return {"value": params["value"]}
        raise AssertionError(name)


class Platform:
    at_sender_on_reply = False

    def __init__(self, peer):
        self.peer = peer
        self.effects = []
        self.feedback_journals = []

    async def _send_emotion(
        self, message_id, conversation_id, label, **kwargs
    ):
        self.feedback_journals.append(self.peer.rows())
        self.effects.append(("emotion", message_id, label, kwargs["recall"]))
        raise PermissionError("emotion API permission denied")

    def _ai_card_enabled(self):
        return False

    def _parts_to_single_text(self, parts):
        return "\n".join(p.text for p in parts if p.type == "text")

    async def send_parts(self, target, parts, meta, **kwargs):
        self.effects.append(("text", self._parts_to_single_text(parts)))

    def _route_from_handle(self, handle):
        return {}

    async def _load_session_webhook_entry(self, key):
        return {}


def bound(root, generation=1):
    peer = HostPeer(root)
    driver = DingTalkDriver()
    identity = IdentityParams("dingtalk", "feedback-test", generation)
    driver.bind(DriverContext(peer, identity))
    driver._platform = Platform(peer)
    driver._connected = True
    return driver, peer, identity


async def prepare_and_send(driver, peer, identity, index=0):
    await driver._message(
        {
            "sender_id": "human",
            "acl_sender_id": "actor",
            "message_id": f"message-{index}",
            "content_parts": [{"type": "text", "text": "hello"}],
            "meta": {
                "message_id": f"message-{index}",
                "conversation_id": "conversation",
                "is_group": True,
            },
        }
    )
    handle = peer.events[-1]["response_handle"]
    prepared = await driver._prepare(
        {
            **identity.to_mapping(),
            "response_handle": handle,
            "delivery_id": hashlib.sha256(
                (handle + ":prepare").encode()
            ).hexdigest(),
        },
        None,
    )
    assert prepared["state"] == "acknowledged"
    result = await driver._send(
        SendParams.from_mapping(
            {
                **identity.to_mapping(),
                "to_handle": handle,
                "delivery_id": f"text-{index}",
                "operation": "message.create",
                "content_parts": [
                    {"type": "text", "text": "normal text reply"}
                ],
            }
        ),
        None,
    )
    assert result["state"] == "acknowledged"
    return handle


async def finish(driver, identity, handle):
    return await driver._finish(
        ResponseFinishParams(
            **identity.to_mapping(),
            response_handle=handle,
            outcome=ResponseOutcome.COMPLETED,
        ),
        None,
    )


@pytest.mark.asyncio
async def test_failed_feedback_and_successful_text_archive_and_release_route(
    tmp_path,
):
    driver, peer, identity = bound(tmp_path)
    handle = await prepare_and_send(driver, peer, identity)
    assert ("text", "normal text reply") in driver._platform.effects
    await finish(driver, identity, handle)
    archived = peer.receipts.get(receipt_key(STATE_KEY, handle))
    assert archived["cleanup_state"] == "complete"
    assert archived["route_refs"] == []
    assert {r["resource_id"] for r in archived["resource_refs"]} == {
        handle + ":🤔Thinking",
        handle + ":recall",
        handle + ":🥳Done",
    }
    for ref in archived["resource_refs"]:
        assert ref["attributes"]["state"] == "unknown"
        assert ref["attributes"]["reason_code"] == "PLATFORM_RESULT_UNKNOWN"
        assert len(ref["attributes"]["fingerprint"]) == 64
    assert [
        effect[2:]
        for effect in driver._platform.effects
        if effect[0] == "emotion"
    ] == [
        ("🤔Thinking", False),
        ("🤔Thinking", True),
        ("🥳Done", False),
    ]
    for journal, suffix in zip(
        driver._platform.feedback_journals,
        ("🤔Thinking", "recall", "🥳Done"),
        strict=True,
    ):
        intent = next(
            ref
            for ref in journal[0]["resource_refs"]
            if ref["resource_id"] == handle + ":" + suffix
        )
        assert re.fullmatch(
            "[0-9a-f]{64}", intent["attributes"]["fingerprint"]
        )
        assert intent["attributes"]["state"] == "unknown"
    assert peer.rows() == []
    assert driver._routes.snapshots() == ()


def legacy_row(*, pending=False):
    """The exact old internal feedback journal, independent of new helpers."""
    handle = "dingtalk:reply:legacy-feedback"
    attempts = [
        {
            "kind": "dingtalk.attempt",
            "resource_id": handle + ":" + suffix,
            "attributes": {
                "operation": "reaction",
                "state": "unknown",
                "reason_code": "PLATFORM_RESULT_UNKNOWN",
            },
        }
        for suffix in ("🤔Thinking", "recall", "🥳Done", "☹️Error")
    ]
    return {
        "response_handle": handle,
        "kind": "terminal",
        "version": 9,
        "route_refs": (
            [
                {
                    "kind": "dingtalk.route",
                    "resource_id": handle,
                    "attributes": {
                        "to_handle": "",
                        "bot_prefix": "",
                        "session_ctx": json.dumps(
                            {
                                "message_id": "old-message",
                                "conversation_id": "conversation",
                            }
                        ),
                    },
                }
            ]
            if pending
            else []
        ),
        "resource_refs": attempts
        + (
            [
                {
                    "kind": "dingtalk.delivery",
                    "resource_id": "old-prepare",
                    "attributes": {"prepare": "true", "prepared": "true"},
                }
            ]
            if pending
            else []
        ),
        "outcome": "completed",
        "cleanup_state": "pending" if pending else "complete",
        "closed_at_ms": 1,
        "cleanup_completed_at_ms": None if pending else 2,
        "expires_at_ms": None if pending else 9999999999999,
    }


def seed(peer, row):
    peer.path.write_text(json.dumps({STATE_KEY: [row]}))


def archived_feedback(peer, handle):
    row = peer.receipts.get(receipt_key(STATE_KEY, handle))
    assert row["cleanup_state"] == "complete"
    assert row["route_refs"] == []
    for ref in row["resource_refs"]:
        attrs = ref["attributes"]
        assert attrs["state"] == "unknown"
        assert attrs["reason_code"] == "PLATFORM_RESULT_UNKNOWN"
        assert re.fullmatch("[0-9a-f]{64}", attrs["fingerprint"])
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pending", [True, False], ids=["pending", "complete-no-route"]
)
async def test_legacy_feedback_survives_migration_and_repeated_restart_without_replay(
    tmp_path, pending
):
    driver, peer, identity = bound(tmp_path)
    row = legacy_row(pending=pending)
    handle = row["response_handle"]
    seed(peer, row)
    await driver._restore_responses()
    if pending:
        assert driver._routes.snapshot(handle).cleanup_state.value == "pending"
        await finish(driver, identity, handle)
    archived = archived_feedback(peer, handle)
    assert {ref["resource_id"] for ref in archived["resource_refs"]} == {
        ref["resource_id"]
        for ref in row["resource_refs"]
        if ref["kind"] == "dingtalk.attempt"
    }
    assert driver._platform.effects == []
    assert peer.rows() == []
    for generation in (2, 3):
        restarted, restored, identity = bound(tmp_path, generation)
        await restarted._restore_responses()
        await finish(restarted, identity, handle)
        assert restarted._routes.snapshots() == ()
        assert restored.rows() == []
        assert (
            restored.receipts.get(receipt_key(STATE_KEY, handle)) == archived
        )
        assert restarted._platform.effects == []


@pytest.mark.asyncio
async def test_over_128_sequential_feedback_failures_release_live_capacity(
    tmp_path,
):
    driver, peer, identity = bound(tmp_path)
    for index in range(130):
        handle = await prepare_and_send(driver, peer, identity, index)
        await finish(driver, identity, handle)
        assert driver._routes.snapshot(handle) is None
        assert peer.rows() == []
    assert len(peer.receipts.list(limit=1000)) == 130
    restarted, restored, identity = bound(tmp_path, 2)
    await restarted._restore_responses()
    assert restarted._routes.snapshots() == ()
    handle = await prepare_and_send(restarted, restored, identity, 130)
    await finish(restarted, identity, handle)
    assert len(restored.receipts.list(limit=1000)) == 131


@pytest.mark.asyncio
async def test_archive_write_failure_keeps_live_evidence_until_durable_retry(
    tmp_path,
):
    driver, peer, identity = bound(tmp_path)
    handle = await prepare_and_send(driver, peer, identity)
    peer.fail_archive = True
    with pytest.raises(RpcError) as caught:
        await finish(driver, identity, handle)
    assert caught.value.data["reason_code"] == "RESPONSE_FINISH_FAILED"
    assert isinstance(caught.value.__cause__, OSError)
    assert driver._routes.snapshot(handle) is not None
    assert len(peer.rows()) == 1
    assert peer.rows()[0]["response_handle"] == handle
    assert peer.receipts.get(receipt_key(STATE_KEY, handle)) is None
    effects = list(driver._platform.effects)
    peer.fail_archive = False
    await finish(driver, identity, handle)
    archived_feedback(peer, handle)
    assert driver._routes.snapshot(handle) is None
    assert peer.rows() == []
    assert driver._platform.effects == effects


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        {"fingerprint": ""},
        {"fingerprint": "invalid"},
        {"fingerprint": "A" * 64},
        {"operation": "message.create"},
        {"reason_code": "OTHER_REASON"},
        {"reason_code": None},
        {"sequence": "0"},
        {"resource_id": "unrelated:🤔Thinking"},
        {"resource_id": "dingtalk:reply:legacy-feedback:Thinking"},
        {"resource_id": "dingtalk:reply:legacy-feedback:🤔Thinking-extra"},
    ],
    ids=[
        "empty-fingerprint",
        "bad-fingerprint",
        "uppercase-fingerprint",
        "other-operation",
        "other-reason",
        "missing-reason",
        "extra-attribute",
        "other-handle",
        "wrong-label",
        "suffix-extension",
    ],
)
async def test_malformed_or_unrelated_legacy_attempts_are_not_repaired(
    tmp_path, mutation
):
    driver, peer, _ = bound(tmp_path)
    row = legacy_row()
    ref = row["resource_refs"][0]
    row["resource_refs"] = [ref]
    for key, value in mutation.items():
        if key == "resource_id":
            ref[key] = value
        elif value is None:
            ref["attributes"].pop(key)
        else:
            ref["attributes"][key] = value
    seed(peer, row)
    with pytest.raises(ValueError, match="RESPONSE_RECEIPT_INVALID"):
        await driver._restore_responses()
    assert peer.rows() == [row]
    assert peer.receipts.list() == []
    assert driver._platform.effects == []


@pytest.mark.asyncio
async def test_valid_existing_fingerprint_is_preserved(tmp_path):
    driver, peer, _ = bound(tmp_path)
    row = legacy_row()
    row["resource_refs"][0]["attributes"]["fingerprint"] = "a" * 64
    seed(peer, row)
    await driver._restore_responses()
    archived = archived_feedback(peer, row["response_handle"])
    preserved = next(
        ref
        for ref in archived["resource_refs"]
        if ref["resource_id"].endswith(":🤔Thinking")
    )
    assert preserved["attributes"]["fingerprint"] == "a" * 64


@pytest.mark.asyncio
async def test_feedback_fingerprint_is_stable_across_generation_and_distinct_per_effect(
    tmp_path,
):
    fingerprints = []
    for generation in (1, 2):
        root = tmp_path / str(generation)
        root.mkdir()
        driver, _, _ = bound(root, generation)
        handle = "dingtalk:reply:legacy-feedback"
        meta = {"message_id": "message", "conversation_id": "conversation"}
        await driver._persist_route(handle, {"session_ctx": json.dumps(meta)})
        snapshot = driver._routes.snapshot(handle)
        for label, recall in (
            ("🤔Thinking", False),
            ("🤔Thinking", True),
            ("🥳Done", False),
            ("☹️Error", False),
        ):
            snapshot = await driver._feedback(
                snapshot, meta, label, recall=recall
            )
        values = {
            ref.resource_id: dict(ref.attributes)["fingerprint"]
            for ref in snapshot.resource_refs
        }
        assert len(set(values.values())) == 4
        assert all(
            re.fullmatch("[0-9a-f]{64}", value) for value in values.values()
        )
        fingerprints.append(values)
    assert fingerprints[0] == fingerprints[1]
    root = tmp_path / "legacy"
    root.mkdir()
    driver, peer, _ = bound(root, 3)
    seed(peer, legacy_row())
    await driver._restore_responses()
    migrated = archived_feedback(peer, handle)
    assert {
        ref["resource_id"]: ref["attributes"]["fingerprint"]
        for ref in migrated["resource_refs"]
    } == fingerprints[0]
