# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""GET /storage/profile reports the runtime footprint without touching it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

TOTAL_KEYS = {
    "taskWorkBytes",
    "taskWorkLegacyBytes",
    "taskWorkReclaimableBytes",
    "transactionsBytes",
    "transactionsLegacyBytes",
    "orphanBytes",
    "eventStreamBytes",
}


def test_profile_answers_even_with_no_projects(
    api_request,
    app,
    api_runtime_root,
):
    response = api_request(app, "GET", "/storage/profile")

    assert response.status_code == 200
    body = response.json()
    assert Path(body["dataRoot"]).is_dir()
    assert body["scratchReleaseEnabled"] is True
    assert body["projects"] == []
    assert set(body["totals"]) == TOTAL_KEYS
    assert all(value == 0 for value in body["totals"].values())


def test_orphan_scan_is_opt_in(api_request, app):
    response = api_request(
        app,
        "GET",
        "/storage/profile",
        params={"includeOrphans": "true"},
    )

    assert response.status_code == 200
    assert set(response.json()["totals"]) == TOTAL_KEYS


PROJECT_A = "project-" + "a" * 32
PROJECT_B = "project-" + "b" * 32
BASELINE = datetime(2026, 1, 10, tzinfo=timezone.utc)


def _seed_legacy_project(root: Path, project_id: str, *, count: int) -> Path:
    """A Project whose whole commit history predates its baseline.

    This is the imported-Project shape from the field: every transaction
    settled, none of it after the day the Project started being managed, so an
    unauthorized sweep frees nothing at all.
    """

    project = root / project_id
    transactions = project / "runtime" / "transactions"
    transactions.mkdir(parents=True)
    (project / "project.json").write_text("{}", encoding="utf-8")
    (project / "runtime" / ".storage-baseline.json").write_text(
        json.dumps({"version": 1, "since": BASELINE.isoformat()}),
        encoding="utf-8",
    )
    for index in range(count):
        directory = transactions / f"txn-{index:03d}"
        directory.mkdir()
        (directory / "journal.json").write_text(
            json.dumps({"state": "RUNTIME_FINALIZED"}),
            encoding="utf-8",
        )
        (directory / "final.json").write_bytes(b"x" * 64)
        moment = (BASELINE - timedelta(days=count - index)).timestamp()
        os.utime(directory, (moment, moment))
    return transactions


def test_reclaim_history_refuses_an_unconfirmed_press(
    api_request,
    app,
    api_runtime_root,
):
    transactions = _seed_legacy_project(api_runtime_root, PROJECT_A, count=60)

    missing = api_request(
        app,
        "POST",
        f"/storage/projects/{PROJECT_A}/reclaim-history",
        json={},
    )
    denied = api_request(
        app,
        "POST",
        f"/storage/projects/{PROJECT_A}/reclaim-history",
        json={"confirm": False},
    )

    assert missing.status_code == 400
    assert denied.status_code == 400
    assert missing.json()["code"] == "BAD_REQUEST"
    assert len(list(transactions.iterdir())) == 60


def test_reclaim_history_sweeps_only_the_requested_project(
    api_request,
    app,
    api_runtime_root,
):
    first = _seed_legacy_project(api_runtime_root, PROJECT_A, count=60)
    second = _seed_legacy_project(api_runtime_root, PROJECT_B, count=60)

    response = api_request(
        app,
        "POST",
        f"/storage/projects/{PROJECT_A}/reclaim-history",
        json={"confirm": True},
    )

    assert response.status_code == 200
    body = response.json()
    # The on-demand sweep is the boot sweep, so retention still holds: the
    # newest 50 receipts stay, only the surplus leaves.
    assert body["removedTransactions"] == 10
    assert body["transactionBytes"] > 0
    assert len(list(first.iterdir())) == 50
    assert len(list(second.iterdir())) == 60

    profile = api_request(app, "GET", "/storage/profile").json()
    rows = {item["projectId"]: item for item in profile["projects"]}
    assert rows[PROJECT_A]["historyKeptAt"] is None
    assert rows[PROJECT_B]["historyKeptAt"] is None


def test_reclaim_history_refuses_a_project_that_kept_its_history(
    api_request,
    app,
    api_runtime_root,
):
    """Opting out is answered with a refusal, not a silent zero.

    A button that reports success while deleting nothing teaches the person
    to press it again, so the kept case has to say so out loud.
    """

    from services.media_files.task_scratch import keep_project_history

    transactions = _seed_legacy_project(api_runtime_root, PROJECT_A, count=60)
    keep_project_history(
        api_runtime_root / PROJECT_A,
        now=datetime.now(timezone.utc),
    )

    response = api_request(
        app,
        "POST",
        f"/storage/projects/{PROJECT_A}/reclaim-history",
        json={"confirm": True},
    )

    assert response.status_code == 409
    assert len(list(transactions.iterdir())) == 60


def test_the_collapse_backups_are_counted_where_they_actually_sit(
    api_request,
    app,
    api_runtime_root,
):
    """The only storage this build adds sits outside every Project tree.

    A compressed pre-pass copy of a rewritten conversation is worth reporting:
    without it, the profile would claim a collapse freed bytes that the backup
    then quietly took back.
    """

    from services.media_files.task_scratch import ELISION_BACKUP_DIR_NAME

    backup = api_runtime_root / ELISION_BACKUP_DIR_NAME / "project-x"
    backup.mkdir(parents=True)
    handle = backup / "messages-20261102T120000.jsonl.gz"
    handle.write_bytes(b"\x1f\x8b" + b"z" * 100)

    body = api_request(app, "GET", "/storage/profile").json()

    assert body["elisionBackupBytes"] == 102


def test_requests_are_told_to_retry_while_recovery_runs():
    """A dead socket for minutes reads as a broken plugin, not a busy one.

    The first create() holds the registry lock for the whole recovery scan, so
    a request that arrives in that window must be answered, not queued.
    """

    from api.dependencies import project_file_services
    from domain.errors import RuntimePreparingError
    from services.project_files import facade

    facade.mark_runtime_preparing(True)
    try:
        with pytest.raises(RuntimePreparingError):
            project_file_services()
    finally:
        facade.mark_runtime_preparing(False)


def test_manual_reclaim_writes_its_confirmation_receipt(
    api_request,
    app,
    api_runtime_root,
    monkeypatch,
):
    """The most recent explicit confirmation is available to storage diagnostics."""

    from services.media_files.task_scratch import (
        RECLAIM_CONFIRMATION_FILE_NAME,
    )

    monkeypatch.setenv("CREATOR_STORAGE_AUTO_RECLAIM_MAX_BYTES", "100")
    transactions = _seed_legacy_project(api_runtime_root, PROJECT_A, count=60)

    response = api_request(
        app,
        "POST",
        f"/storage/projects/{PROJECT_A}/reclaim-history",
        json={"confirm": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["confirmedAt"]
    assert body["removedTransactions"] == 10
    marker = (
        api_runtime_root
        / PROJECT_A
        / "runtime"
        / RECLAIM_CONFIRMATION_FILE_NAME
    )
    assert marker.is_file()
    assert len(list(transactions.iterdir())) == 50


def test_the_profile_carries_the_cap_and_the_pending_bytes(
    api_request,
    app,
    api_runtime_root,
    monkeypatch,
):
    """The console decides 'over the cap' from the report, not a constant.

    A threshold hardcoded in the UI drifts the moment the environment moves
    it, so the report travels with the number the sweeps actually honour.
    """

    monkeypatch.setenv("CREATOR_STORAGE_AUTO_RECLAIM_MAX_BYTES", "100")
    _seed_legacy_project(api_runtime_root, PROJECT_A, count=60)

    body = api_request(app, "GET", "/storage/profile").json()

    assert body["autoReclaimMaxBytes"] == 100
    row = next(
        item for item in body["projects"] if item["projectId"] == PROJECT_A
    )
    assert row["pendingReclaimBytes"] > 100
    assert row["reclaimConfirmedAt"] is None


def test_the_event_stream_size_is_reported_never_rewritten(
    api_request,
    app,
    api_runtime_root,
):
    """The durable event stream is surfaced, never collapsed in place.

    Its seqs are the SSE resume cursor, so rewriting it would desync every
    connected client; reporting the size is what lets an operator decide to
    rebuild by export instead of guessing why reconnects got slow.
    """
    created = api_request(
        app,
        "POST",
        "/projects",
        json={
            "clientRequestId": "event-stream-report",
            "name": "事件流",
            "scenario": "general",
            "aspectRatio": "16:9",
            "resolution": "720P",
        },
    )
    project_id = created.json()["projectId"]
    sessions = (
        api_runtime_root / project_id / "runtime" / "sessions" / "session-1"
    )
    sessions.mkdir(parents=True)
    (sessions / "events.jsonl").write_bytes(b"x" * 4096)

    body = api_request(app, "GET", "/storage/profile").json()
    row = next(
        item for item in body["projects"] if item["projectId"] == project_id
    )
    assert row["eventStreamBytes"] == 4096
    assert body["eventStreamReportMaxBytes"] == 64 * 1024 * 1024


def test_the_profile_scan_is_cached_per_reader(
    api_request,
    app,
    monkeypatch,
) -> None:
    """One walk of a 40 GB tree must not repeat for every reader.

    The home page asks for the profile on load and again on every return from
    a Project. Measured on the field's data root a single scan cost 1.4 s
    idle and up to 41 s while the process was busy -- which is how "open a
    Project, go back" turned into a 20+ second wait.
    """

    from api import storage_profile_routes

    calls: list[bool] = []
    real_scan = storage_profile_routes.project_storage_profile

    def spy_scan(services, *, include_orphans=False):
        calls.append(bool(include_orphans))
        return real_scan(services, include_orphans=include_orphans)

    monkeypatch.setattr(
        storage_profile_routes,
        "project_storage_profile",
        spy_scan,
    )
    storage_profile_routes.invalidate_storage_profile_cache()

    api_request(app, "GET", "/storage/profile")
    api_request(app, "GET", "/storage/profile")
    assert calls == [False]  # the second reader reused the scan

    monkeypatch.setenv("CREATOR_STORAGE_PROFILE_TTL_SECONDS", "0")
    api_request(app, "GET", "/storage/profile")
    api_request(app, "GET", "/storage/profile")
    assert calls == [False, False, False]  # TTL 0 scans per request again


def test_invalidation_is_scoped_to_one_data_root() -> None:
    """A reclaim must clear its own root and leave another's scan alone.

    Serving a stale scan after a reclaim would bring back the "released but the
    button is still there" defect, while clearing every root would make two
    data roots fight over one cache.
    """

    from api import storage_profile_routes

    storage_profile_routes._profile_cache.clear()
    storage_profile_routes._profile_cache[("/root-a", False)] = (0.0, {})
    storage_profile_routes._profile_cache[("/root-b", False)] = (0.0, {})

    storage_profile_routes.invalidate_storage_profile_cache("/root-a")
    assert list(storage_profile_routes._profile_cache) == [("/root-b", False)]

    storage_profile_routes.invalidate_storage_profile_cache()
    assert not storage_profile_routes._profile_cache


def test_reclaim_confirmation_does_not_authorize_future_history(
    api_request, app, api_runtime_root
):
    from services.project_files.transaction_gc import (
        collect_project_transactions,
    )

    root = api_runtime_root / PROJECT_A
    transactions = _seed_legacy_project(api_runtime_root, PROJECT_A, count=60)
    assert collect_project_transactions(root) == (0, 0)
    assert len(list(transactions.iterdir())) == 60
    reply = api_request(
        app,
        "POST",
        f"/storage/projects/{PROJECT_A}/reclaim-history",
        json={"confirm": True},
    )
    assert reply.status_code == 200
    new = transactions / "txn-new"
    new.mkdir()
    (new / "journal.json").write_text('{"state":"ABORTED"}')
    assert collect_project_transactions(root) == (0, 0)
    assert len(list(transactions.iterdir())) == 51
    profile = api_request(app, "GET", "/storage/profile").json()
    assert (
        next(
            row for row in profile["projects"] if row["projectId"] == PROJECT_A
        )["pendingReclaimBytes"]
        > 0
    )


def test_manual_reclaim_preserves_unverifiable_reservations(
    api_request, app, api_runtime_root
):
    transactions = _seed_legacy_project(api_runtime_root, PROJECT_A, count=60)
    records = transactions.parent / "commands" / "idempotency"
    records.mkdir(parents=True)
    (records / "unknown.json").write_bytes(b"{")
    reply = api_request(
        app,
        "POST",
        f"/storage/projects/{PROJECT_A}/reclaim-history",
        json={"confirm": True},
    )
    assert reply.status_code == 200
    assert reply.json()["removedTransactions"] == 0
    assert len(list(transactions.iterdir())) == 60
