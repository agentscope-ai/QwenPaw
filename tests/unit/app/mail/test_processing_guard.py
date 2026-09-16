# -*- coding: utf-8 -*-
"""Durable batch consent and shared failure-budget regression tests."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from qwenpaw.app.mail.processing_guard import MailProcessingGuard


def _guard(tmp_path: Path, fingerprint: str = "mailbox"):
    return MailProcessingGuard(tmp_path / "guard.json", fingerprint)


def _pause_batch(guard, source="monitor", first=1):
    uids = list(range(first, first + 51))
    assert not guard.check_batch(source, uids, 7)
    return guard.get_pause(), uids


@pytest.mark.parametrize("count", [0, 1, 50, 51, 1033])
def test_batch_boundary_and_public_pause(tmp_path, count):
    guard = _guard(tmp_path)
    assert guard.check_batch("monitor", list(range(1, count + 1)), 7) == (
        count <= 50
    )
    pause = guard.get_pause()
    if count <= 50:
        assert pause is None
    else:
        assert pause["reason"] == "batch"
        assert pause["count"] == count
        assert set(pause) == {"pause_id", "reason", "count", "notified"}
        assert _guard(tmp_path).get_pause() == pause


def test_confirmation_survives_restart_and_covers_only_shown_uids(tmp_path):
    guard = _guard(tmp_path)
    pause, uids = _pause_batch(guard)
    assert guard.resume(pause["pause_id"])
    guard = _guard(tmp_path)
    assert guard.check_batch("monitor", uids, 7)
    assert guard.check_batch("monitor", uids[20:], 7)
    # Distinct later UIDs were not included in the user's confirmation.
    assert not guard.check_batch(
        "monitor",
        uids[20:] + list(range(101, 152)),
        7,
    )
    next_pause = guard.get_pause()
    assert next_pause["count"] == 51
    assert next_pause["pause_id"] != pause["pause_id"]
    assert not guard.resume(pause["pause_id"])
    assert guard.resume(next_pause["pause_id"])
    assert guard.check_batch("monitor", uids[20:] + list(range(101, 152)), 7)


@pytest.mark.parametrize(
    ("source", "uidvalidity"),
    [("approved", 7), ("monitor", 8), ("monitor", None)],
)
def test_batch_authorization_is_namespace_scoped(
    tmp_path,
    source,
    uidvalidity,
):
    guard = _guard(tmp_path)
    pause, uids = _pause_batch(guard)
    assert guard.resume(pause["pause_id"])
    assert not guard.check_batch(source, uids, uidvalidity)
    assert guard.get_pause()["count"] == 51


def test_new_mailbox_does_not_inherit_consent_or_pause_token(tmp_path):
    original = _guard(tmp_path)
    pause, uids = _pause_batch(original)
    replacement = _guard(tmp_path, "new-mailbox")
    assert replacement.get_pause() is None
    assert not replacement.resume(pause["pause_id"])
    assert not replacement.check_batch("monitor", uids, 7)
    assert replacement.get_pause()["pause_id"] != pause["pause_id"]


def test_failures_persist_success_resets_and_resume_requires_token(tmp_path):
    guard = _guard(tmp_path)
    guard.record_result(False)
    guard.record_result(False)
    guard = _guard(tmp_path)
    assert guard.get_pause() is None
    guard.record_result(True)
    guard.record_result(False)
    guard.record_result(False)
    assert guard.get_pause() is None
    guard.record_result(False)
    pause = guard.get_pause()
    assert pause["reason"] == "failures"
    assert pause["count"] == 3
    assert not guard.check_batch("approved", [1], 7)
    assert _guard(tmp_path).get_pause() == pause
    assert not guard.resume("stale")
    assert guard.resume(pause["pause_id"])
    assert not guard.resume(pause["pause_id"])
    guard.record_result(False)
    assert guard.get_pause() is None
    # Resuming a failure pause grants no batch permission.
    assert not guard.check_batch("approved", list(range(1, 52)), 7)


def test_notification_ack_cannot_ack_new_pause(tmp_path):
    guard = _guard(tmp_path)
    pause, _ = _pause_batch(guard)
    guard.mark_notified("stale")
    assert not guard.get_pause()["notified"]
    guard.mark_notified(pause["pause_id"])
    assert _guard(tmp_path).get_pause()["notified"]
    assert guard.resume(pause["pause_id"])
    for _ in range(3):
        guard.record_result(False)
    guard.mark_notified(pause["pause_id"])
    assert not guard.get_pause()["notified"]


@pytest.mark.parametrize("operation", ["batch", "failure", "resume", "notify"])
def test_write_failure_never_unlocks_processing(tmp_path, operation):
    guard = _guard(tmp_path)
    pause = None
    if operation in {"resume", "notify"}:
        pause, _ = _pause_batch(guard)
    with patch(
        "qwenpaw.app.mail.processing_guard.write_json_atomic",
        side_effect=OSError("disk full"),
    ), pytest.raises(OSError, match="disk full"):
        if operation == "batch":
            guard.check_batch("monitor", list(range(1, 52)), 7)
        elif operation == "failure":
            guard.record_result(False)
        elif operation == "resume":
            guard.resume(pause["pause_id"])
        else:
            guard.mark_notified(pause["pause_id"])
    assert not guard.check_batch("monitor", [1], 7)
    if pause is None:
        assert guard.get_pause()["reason"] == "state_error"
    else:
        assert guard.get_pause() == pause
        assert _guard(tmp_path).get_pause() == pause


@pytest.mark.parametrize(
    "raw",
    [
        "{truncated",
        "[]",
        "{}",
        '{"mailbox_fingerprint":"mailbox"}',
        '{"mailbox_fingerprint":"mailbox","failures":"bad",'
        '"approved":{},"pause":null}',
        '{"mailbox_fingerprint":"mailbox","failures":0,"approved":{},'
        '"pause":{"reason":"invalid","count":0}}',
    ],
)
def test_corrupt_state_requires_explicit_recovery(tmp_path, raw):
    path = tmp_path / "guard.json"
    path.write_text(raw, encoding="utf-8")
    guard = _guard(tmp_path)
    assert not guard.check_batch("monitor", [1], 7)
    pause = guard.get_pause()
    assert pause["reason"] == "state_error"
    assert guard.resume(pause["pause_id"])
    assert _guard(tmp_path).check_batch("monitor", [1], 7)


def test_concurrent_failure_transactions_do_not_lose_updates(tmp_path):
    guard = _guard(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(guard.record_result, [False] * 20))
    state = json.loads((tmp_path / "guard.json").read_text("utf-8"))
    assert state["failures"] == 20
    assert guard.get_pause()["reason"] == "failures"
    assert _guard(tmp_path).get_pause() == guard.get_pause()


def test_concurrent_resume_only_grants_batch_once(tmp_path):
    guard = _guard(tmp_path)
    pause, uids = _pause_batch(guard)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(guard.resume, [pause["pause_id"]] * 8))
    assert results.count(True) == 1
    assert _guard(tmp_path).check_batch("monitor", uids, 7)


def test_failure_resume_keeps_previous_batch_consent_not_new_arrivals(
    tmp_path,
):
    guard = _guard(tmp_path)
    pause, uids = _pause_batch(guard)
    assert guard.resume(pause["pause_id"])
    for _ in range(3):
        guard.record_result(False)
    assert guard.resume(guard.get_pause()["pause_id"])
    assert guard.check_batch("monitor", uids, 7)
    assert not guard.check_batch("monitor", uids + list(range(101, 152)), 7)
    assert guard.get_pause()["count"] == 51


def test_batch_confirmation_does_not_reset_consecutive_failures(tmp_path):
    guard = _guard(tmp_path)
    guard.record_result(False)
    guard.record_result(False)
    pause, _ = _pause_batch(guard)
    assert guard.resume(pause["pause_id"])
    guard.record_result(False)
    pause = guard.get_pause()
    assert pause["reason"] == "failures"
    assert pause["count"] == 3
