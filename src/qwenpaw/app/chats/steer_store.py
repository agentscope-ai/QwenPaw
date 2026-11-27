# -*- coding: utf-8 -*-
"""Durable steer receipts in the conversation's existing event log."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from .context_revisions import read_revision_state


class SteerStoreMixin:
    """Keep receipt changes and transcript writes in one transaction."""

    def list_steers(
        self,
        *,
        session_id,
        turn_id=None,
        latest=False,
        include_messages=False,
        **_,
    ):
        with self._lock:
            if latest and turn_id is None:
                turn = self._conn.execute(
                    "SELECT turn_id FROM transcript_turns "
                    "WHERE session_id = ? ORDER BY turn_seq DESC LIMIT 1",
                    (session_id,),
                ).fetchone()
                if turn is None:
                    return []
                turn_id = turn[0]
            query = (
                "SELECT payload_json FROM event_log "
                "WHERE event_type = 'steer.receipt'"
            )
            params = ()
            if turn_id is not None:
                query += " AND turn_id = ?"
                params = (turn_id,)
            rows = self._conn.execute(query + " ORDER BY seq", params)
            receipts = {}
            for row in rows:
                receipt = json.loads(row[0])
                if receipt["session_id"] == session_id:
                    receipts[receipt["client_message_id"]] = receipt
            result = list(receipts.values())
            if include_messages:
                for receipt in result:
                    if receipt["status"] != "applied":
                        continue
                    message = self._conn.execute(
                        "SELECT payload_json FROM transcript_message_payloads "
                        "WHERE session_id = ? AND message_id = ? "
                        "AND superseded_at IS NULL",
                        (session_id, receipt["user_message_id"]),
                    ).fetchone()
                    if message:
                        receipt["message"] = json.loads(message[0])
            return result

    def history_steers(self, *, session_id, messages, **_):
        """Project receipts only into the message range owning their row."""
        turns = {}
        for message in messages:
            position = (message.metadata or {}).get(
                "qwenpaw_transcript_position",
                {},
            )
            if position.get("turn_id"):
                turns.setdefault(position["turn_id"], []).append(message)
        result = {}
        with self._lock:
            for turn_id, fragment in turns.items():
                last = self._conn.execute(
                    "SELECT MAX(ordinal) FROM transcript_messages "
                    "WHERE session_id = ? AND turn_id = ? "
                    "AND superseded_at IS NULL",
                    (session_id, turn_id),
                ).fetchone()[0]
                tail = False
                for message in fragment:
                    metadata = message.metadata or {}
                    position = metadata["qwenpaw_transcript_position"]
                    bounds = metadata.get("qwenpaw_history_fragment", {})
                    if position["ordinal"] == last and all(
                        bounds.get(f"{kind}_end", 0)
                        == bounds.get(f"{kind}_total", 0)
                        for kind in ("content", "text", "serialized")
                    ):
                        tail = True
                present = {message.id for message in fragment}
                result[turn_id] = [
                    receipt
                    for receipt in self.list_steers(
                        session_id=session_id,
                        turn_id=turn_id,
                    )
                    if (
                        receipt["status"] == "applied"
                        and receipt["user_message_id"] in present
                    )
                    or (receipt["status"] != "applied" and tail)
                ]
        return result

    def _save_steer(self, receipt):
        self._append_fact(
            event_type="steer.receipt",
            payload=receipt,
            idempotency_key=(
                f"steer:{receipt['client_message_id']}:"
                f"{receipt['revision']}"
            ),
            turn_id=receipt["turn_id"],
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )

    def accept_steer(
        self,
        *,
        session_id,
        turn_id,
        client_message_id,
        content,
        **_,
    ):
        with self._transaction():
            receipts = self.list_steers(session_id=session_id)
            for receipt in receipts:
                if receipt["client_message_id"] == client_message_id:
                    if (
                        receipt["content"] != content
                        or receipt["turn_id"] != turn_id
                    ):
                        raise ValueError("idempotency_conflict")
                    return receipt
            turn = self._conn.execute(
                "SELECT status FROM transcript_turns "
                "WHERE session_id = ? AND turn_id = ?",
                (session_id, turn_id),
            ).fetchone()
            if turn is None or turn[0] != "running":
                raise ValueError("no_active_turn")
            if not content or len(json.dumps(content).encode()) > 16 * 1024:
                raise ValueError("unsupported_content")
            current = [r for r in receipts if r["turn_id"] == turn_id]
            if (
                len(current) >= 32
                or sum(r["status"] == "accepted" for r in current) >= 10
                or sum(len(json.dumps(r["content"]).encode()) for r in current)
                + len(json.dumps(content).encode())
                > 128 * 1024
            ):
                raise ValueError("capacity_exceeded")
            receipt = {
                "session_id": session_id,
                "turn_id": turn_id,
                "client_message_id": client_message_id,
                "user_message_id": "msg_" + uuid4().hex,
                "content": content,
                "append_seq": len(current) + 1,
                "revision": 1,
                "status": "accepted",
            }
            self._save_steer(receipt)
            return receipt

    def apply_steers(
        self,
        *,
        session_id,
        turn_id,
        messages,
        step_index,
        **_,
    ):
        with self._transaction():
            receipts = {
                r["user_message_id"]: r
                for r in self.list_steers(
                    session_id=session_id,
                    turn_id=turn_id,
                )
            }
            for message, ordinal in messages:
                receipt = receipts.get(message.id)
                if receipt is None or receipt["status"] != "accepted":
                    raise ValueError("steer_not_pending")
                self.upsert_message(
                    session_id=session_id,
                    turn_id=turn_id,
                    message=message,
                    ordinal=ordinal,
                )
                self._save_steer(
                    {
                        **receipt,
                        "status": "applied",
                        "revision": 2,
                        "applied_step_index": step_index,
                        "ordinal": ordinal,
                    },
                )

    def fail_steers(self, *, session_id, turn_id=None, reason, **_):
        with self._transaction():
            for receipt in self.list_steers(
                session_id=session_id,
                turn_id=turn_id,
            ):
                if receipt["status"] == "accepted":
                    self._save_steer(
                        {
                            **receipt,
                            "status": "failed",
                            "revision": 2,
                            "reason": reason,
                        },
                    )

    def can_fork_turn(self, *, session_id, turn_id, **_):
        with self._read_connection() as connection:
            return steer_fork_boundary(connection, session_id, turn_id)


def steer_fork_boundary(connection, session_id, turn_id):
    """Validate a settled prefix against its committed context."""
    turn = connection.execute(
        "SELECT status FROM transcript_turns "
        "WHERE session_id = ? AND turn_id = ?",
        (session_id, turn_id),
    ).fetchone()
    revision = connection.execute(
        "SELECT revision_id FROM turn_context_revision "
        "WHERE session_id = ? AND turn_id = ?",
        (session_id, turn_id),
    ).fetchone()
    if (
        turn is None
        or turn[0] not in ("completed", "cancelled")
        or revision is None
    ):
        return False
    running_prefix = connection.execute(
        "SELECT 1 FROM transcript_turns WHERE session_id = ? "
        "AND status = 'running' AND turn_seq <= "
        "(SELECT turn_seq FROM transcript_turns "
        "WHERE session_id = ? AND turn_id = ?) LIMIT 1",
        (session_id, session_id, turn_id),
    ).fetchone()
    if running_prefix is not None:
        return False
    latest = {}
    for row in connection.execute(
        "SELECT payload_json FROM event_log "
        "WHERE event_type = 'steer.receipt' AND turn_id = ? ORDER BY seq",
        (turn_id,),
    ):
        receipt = json.loads(row[0])
        latest[receipt["client_message_id"]] = receipt
    if any(r["status"] == "accepted" for r in latest.values()):
        return False
    applied_ids = {
        row[0]
        for row in connection.execute(
            "SELECT message_id FROM transcript_messages "
            "WHERE session_id = ? AND turn_id = ? "
            "AND json_extract(envelope_json, '$.metadata.input_kind') "
            "= 'steer'",
            (session_id, turn_id),
        )
    }
    expected = {
        r["user_message_id"]
        for r in latest.values()
        if r["status"] == "applied"
    }
    if not expected.issubset(applied_ids):
        return False
    committed = connection.execute(
        "SELECT 1 FROM event_log WHERE event_type = 'runtime.committed' "
        "AND json_extract(payload_json, '$.revision_id') = ? LIMIT 1",
        (revision[0],),
    ).fetchone()
    if committed is None:
        return False
    state = read_revision_state(
        connection,
        session_id=session_id,
        revision_id=revision[0],
    )

    agent_state = state.get("agent", {}).get("state", {})
    if turn[0] == "cancelled":
        context = agent_state.get("context", [])
        client_id = turn_id.removeprefix("client:")
        if not any(
            message.get("role") == "user"
            and message.get("metadata", {}).get("qwenpaw_client_message_id")
            == client_id
            and message.get("metadata", {})
            .get("qwenpaw_turn_state", {})
            .get("status")
            == "canceled"
            for message in context
        ):
            return False
        pending_tools = set()
        for message in context:
            for block in message.get("content", []):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_call":
                    pending_tools.add(block.get("id"))
                elif block.get("type") == "tool_result":
                    pending_tools.discard(block.get("id"))
        if pending_tools:
            return False
    if not applied_ids:
        return True
    marker = agent_state.get("middle_context", {}).get(
        "qwenpaw_steer_boundary",
        {},
    )
    # A compressed-away steer requires recall proof beyond this release.
    # Hide that boundary rather than claiming a complete fork capability.
    context_ids = {
        msg.get("id")
        for msg in agent_state.get("context", [])
        if isinstance(msg, dict) and msg.get("role") == "user"
    }
    return (
        marker.get("turn_id") == turn_id
        and set(marker.get("message_ids", [])) == applied_ids
        and applied_ids.issubset(context_ids)
    )
