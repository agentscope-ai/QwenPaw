# -*- coding: utf-8 -*-
"""Tests for ACL-safe batch grouping in ChannelManager.

A shared-session group chat routes every member to one queue key, so a
drained batch can hold messages from different senders. Merging across
senders would keep only the first sender's ``acl_sender_id`` while
concatenating everyone's content, letting one member's message be judged
by another member's access-control decision.
"""

from types import SimpleNamespace

from qwenpaw.app.channels.manager import (
    _acl_identity_of,
    _split_batch_by_acl_identity,
)


def _native(acl_sender_id: str, text: str) -> dict:
    return {
        "channel_id": "onebot",
        "sender_id": "group-1",
        "acl_sender_id": acl_sender_id,
        "content_parts": [{"type": "text", "text": text}],
        "meta": {"is_group": True, "group_id": "group-1"},
    }


class TestAclIdentityOf:
    def test_prefers_acl_sender_id_over_sender_id(self) -> None:
        payload = {"acl_sender_id": "real-user", "sender_id": "group-1"}
        assert _acl_identity_of(payload) == "real-user"

    def test_falls_back_to_sender_id_when_acl_absent(self) -> None:
        assert _acl_identity_of({"sender_id": "group-1"}) == "group-1"

    def test_reads_request_objects_via_attributes(self) -> None:
        request = SimpleNamespace(acl_sender_id="", user_id="user-9")
        assert _acl_identity_of(request) == "user-9"

    def test_missing_identity_is_empty_string(self) -> None:
        assert _acl_identity_of({}) == ""


class TestSplitBatchByAclIdentity:
    def test_single_sender_batch_stays_one_group(self) -> None:
        batch = [_native("user-a", "one"), _native("user-a", "two")]

        groups = _split_batch_by_acl_identity(batch)

        assert len(groups) == 1
        assert groups[0] == batch

    def test_different_senders_are_never_merged(self) -> None:
        allowed = _native("user-allowed", "hello")
        blocked = _native("user-blocked", "run rm -rf /")

        groups = _split_batch_by_acl_identity([allowed, blocked])

        assert len(groups) == 2
        assert groups[0] == [allowed]
        assert groups[1] == [blocked]

    def test_preserves_arrival_order_and_regroups_runs(self) -> None:
        batch = [
            _native("user-a", "a1"),
            _native("user-a", "a2"),
            _native("user-b", "b1"),
            _native("user-a", "a3"),
        ]

        groups = _split_batch_by_acl_identity(batch)

        assert [[p["acl_sender_id"] for p in g] for g in groups] == [
            ["user-a", "user-a"],
            ["user-b"],
            ["user-a"],
        ]

    def test_no_payload_is_dropped_or_duplicated(self) -> None:
        batch = [
            _native("user-a", "a1"),
            _native("user-b", "b1"),
            _native("user-c", "c1"),
            _native("user-b", "b2"),
        ]

        groups = _split_batch_by_acl_identity(batch)

        flattened = [payload for group in groups for payload in group]
        assert flattened == batch

    def test_empty_batch_yields_no_groups(self) -> None:
        assert not _split_batch_by_acl_identity([])

    def test_single_payload_yields_one_group(self) -> None:
        payload = _native("user-a", "only")
        assert _split_batch_by_acl_identity([payload]) == [[payload]]
