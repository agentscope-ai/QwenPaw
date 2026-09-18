# -*- coding: utf-8 -*-
"""Behavioural tests for the Hub gateway usage analytics roll-up.

``qwenpaw.hub.model_service.analytics.usage_details`` is the only place
that decides how the gateway ledger is aggregated for the member usage
dashboard: which requests fall inside the requested window, which local
day each one is bucketed into, and what the charging semantics are for
each request status.  It is a module-level function over a real
``GovernanceStore``, so it is driven against a throwaway database rather
than a double.

Every assertion below was read off a probe run, not inferred.  Two
product behaviours are asserted as they are, with the discrepancy
spelled out in a comment, because a test that encoded what the code
"should" do would hide them:

* the range guard accepts a same-day window and rejects a 366-day one,
  while its message says "1 to 365 days";
* ``conservative`` sums the ``charged`` column, not ``reserved``.
"""
# pylint: disable=redefined-outer-name,unused-argument
# pylint: disable=use-implicit-booleaness-not-comparison
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfoNotFoundError

import pytest

from qwenpaw.hub.model_service import analytics as an
from qwenpaw.hub.model_service.storage import GovernanceStore

ROW_KEYS = {
    "actual",
    "charged",
    "conservative",
    "date",
    "failures",
    "model_id",
    "model_name",
    "requests",
    "reserved",
    "user_id",
    "username",
}


@pytest.fixture(name="store")
def store_fixture(tmp_path: Path) -> GovernanceStore:
    return GovernanceStore(tmp_path / "control.db")


def _set_timezone(store: GovernanceStore, zone: str) -> None:
    with store.connect() as db:
        db.execute("BEGIN")
        row = db.execute(
            "SELECT value_json FROM hub_governance_settings "
            "WHERE singleton = 1",
        ).fetchone()
        settings: dict[str, Any] = json.loads(str(row["value_json"]))
        settings["timezone"] = zone
        db.execute(
            "UPDATE hub_governance_settings SET value_json = ?",
            (json.dumps(settings),),
        )


def _add_model(store: GovernanceStore, model_id: str, name: Any = None):
    with store.connect() as db:
        db.execute("BEGIN")
        db.execute(
            "INSERT INTO hub_model_connections(id, value_json) "
            "VALUES (?, ?)",
            (model_id, json.dumps({"provider_id": "dashscope"})),
        )
        value: dict[str, Any] = {}
        if name is not None:
            value["name"] = name
        db.execute(
            "INSERT INTO hub_managed_models(id, connection_id, value_json) "
            "VALUES (?, ?, ?)",
            (model_id, model_id, json.dumps(value)),
        )


def _add_user(store: GovernanceStore, user_id: str, username: str) -> None:
    with store.connect() as db:
        db.execute("BEGIN")
        db.execute(
            "INSERT INTO hub_users(user_id, username, password_hash, "
            "password_salt, role, profile_json, preferences_json, "
            "metadata_json, created_at, updated_at) "
            "VALUES (?, ?, 'h', 's', 'user', '{}', '{}', '{}', 'x', 'x')",
            (user_id, username),
        )


def _add_request(store: GovernanceStore, **fields: Any) -> None:
    row: dict[str, Any] = {
        "id": None,
        "user_id": "u1",
        "model_id": "m1",
        "reserved": 0,
        "charged": 0,
        "actual": None,
        "status": "completed",
        "error": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    row.update(fields)
    request_id = row["id"] or f'r-{row["created_at"]}'
    with store.connect() as db:
        db.execute("BEGIN")
        db.execute(
            "INSERT INTO hub_model_requests(id, user_id, runtime_id, "
            "model_id, connection_id, revision, period, reserved, "
            "charged, actual, status, error, created_at, completed_at) "
            "VALUES (?, ?, 'rt', ?, ?, 1, 'p', ?, ?, ?, ?, ?, ?, NULL)",
            (
                request_id,
                row["user_id"],
                row["model_id"],
                row["model_id"],
                row["reserved"],
                row["charged"],
                row["actual"],
                row["status"],
                row["error"],
                row["created_at"],
            ),
        )


def _by_key(rows: list[dict]) -> dict[str, dict]:
    return {str(row["date"]): row for row in rows}


class TestUsageRangeGuard:
    def test_a_reversed_window_is_rejected(
        self,
        store: GovernanceStore,
    ) -> None:
        with pytest.raises(ValueError) as excinfo:
            an.usage_details(store, date(2026, 1, 2), date(2026, 1, 1))
        assert excinfo.value.args[0] == (
            "Usage range must contain 1 to 365 days"
        )

    def test_a_same_day_window_is_accepted_despite_the_message(
        self,
        store: GovernanceStore,
    ) -> None:
        # The message promises "1 to 365 days" but the guard is
        # ``0 <= (end - start).days < 365``.  Observed behaviour: a
        # zero-day delta is accepted, not rejected.
        out = an.usage_details(store, date(2026, 1, 1), date(2026, 1, 1))
        assert out["rows"] == []

    def test_a_365_day_span_is_rejected(
        self,
        store: GovernanceStore,
    ) -> None:
        # 2025-01-01..2026-01-01 is a 365-day delta, which is the first
        # value the guard rejects even though the message advertises 365.
        with pytest.raises(ValueError):
            an.usage_details(store, date(2025, 1, 1), date(2026, 1, 1))

    def test_a_364_day_span_is_the_widest_accepted(
        self,
        store: GovernanceStore,
    ) -> None:
        out = an.usage_details(store, date(2025, 1, 1), date(2025, 12, 31))
        assert out["rows"] == []

    @pytest.mark.parametrize("delta", [-1, -2, -400])
    def test_end_before_start_is_always_rejected(
        self,
        store: GovernanceStore,
        delta: int,
    ) -> None:
        start = date(2026, 3, 10)
        with pytest.raises(ValueError):
            an.usage_details(store, start, start + timedelta(days=delta))


class TestEmptyLedger:
    def test_no_requests_returns_an_empty_row_list(
        self,
        store: GovernanceStore,
    ) -> None:
        out = an.usage_details(store, date(2026, 1, 1), date(2026, 1, 5))
        # Equality with [] rather than a falsy check: the contract is a
        # list, and None or {} would both pass ``not out["rows"]``.
        assert out["rows"] == []

    def test_the_result_carries_exactly_two_keys(
        self,
        store: GovernanceStore,
    ) -> None:
        out = an.usage_details(store, date(2026, 1, 1), date(2026, 1, 5))
        assert sorted(out.keys()) == ["rows", "timezone"]

    def test_the_default_timezone_is_reported(
        self,
        store: GovernanceStore,
    ) -> None:
        out = an.usage_details(store, date(2026, 1, 1), date(2026, 1, 5))
        assert out["timezone"] == "UTC"

    def test_an_unknown_timezone_is_not_silently_defaulted(
        self,
        store: GovernanceStore,
    ) -> None:
        _set_timezone(store, "Mars/Olympus")
        with pytest.raises(ZoneInfoNotFoundError):
            an.usage_details(store, date(2026, 1, 1), date(2026, 1, 5))


class TestGrouping:
    def test_two_requests_on_one_day_share_one_row(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_model(store, "m1", "Qwen Max")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id="a1",
            created_at="2026-01-01T01:00:00+00:00",
            charged=10,
            actual=7,
        )
        _add_request(
            store,
            id="a2",
            created_at="2026-01-01T05:00:00+00:00",
            charged=20,
        )

        rows = an.usage_details(store, date(2026, 1, 1), date(2026, 1, 1))[
            "rows"
        ]

        assert len(rows) == 1
        row = rows[0]
        assert row["requests"] == 2
        assert row["charged"] == 30
        assert row["actual"] == 7
        assert row["date"] == "2026-01-01"
        assert row["username"] == "alice"
        assert row["model_name"] == "Qwen Max"

    def test_each_row_carries_the_full_shape(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_model(store, "m1", "Qwen Max")
        _add_user(store, "u1", "alice")
        _add_request(store, id="s1", created_at="2026-01-01T01:00:00+00:00")

        row = an.usage_details(store, date(2026, 1, 1), date(2026, 1, 1))[
            "rows"
        ][0]

        assert set(row.keys()) == ROW_KEYS

    def test_different_models_do_not_merge(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_model(store, "m1", "M1")
        _add_model(store, "m2", "M2")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id="g1",
            model_id="m1",
            created_at="2026-07-01T01:00:00+00:00",
            charged=1,
        )
        _add_request(
            store,
            id="g2",
            model_id="m2",
            created_at="2026-07-01T02:00:00+00:00",
            charged=2,
        )

        rows = an.usage_details(store, date(2026, 7, 1), date(2026, 7, 1))[
            "rows"
        ]

        assert [
            (r["model_id"], r["model_name"], r["charged"]) for r in rows
        ] == [
            ("m1", "M1", 1),
            ("m2", "M2", 2),
        ]

    def test_different_members_do_not_merge(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_model(store, "m2", "M2")
        _add_user(store, "u1", "alice")
        _add_user(store, "u2", "bob")
        _add_request(
            store,
            id="h1",
            user_id="u1",
            model_id="m2",
            created_at="2026-07-01T01:00:00+00:00",
            charged=2,
        )
        _add_request(
            store,
            id="h2",
            user_id="u2",
            model_id="m2",
            created_at="2026-07-01T03:00:00+00:00",
            charged=9,
        )

        rows = an.usage_details(store, date(2026, 7, 1), date(2026, 7, 1))[
            "rows"
        ]

        assert [(r["user_id"], r["username"], r["charged"]) for r in rows] == [
            ("u1", "alice", 2),
            ("u2", "bob", 9),
        ]

    def test_rows_follow_ledger_order_not_insertion_order(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_model(store, "m1", "M1")
        _add_user(store, "u1", "alice")
        # Inserted newest-first on purpose.
        _add_request(
            store,
            id="o2",
            created_at="2026-07-02T00:00:00+00:00",
            charged=9,
        )
        _add_request(
            store,
            id="o1",
            created_at="2026-07-01T00:00:00+00:00",
            charged=1,
        )

        rows = an.usage_details(store, date(2026, 7, 1), date(2026, 7, 3))[
            "rows"
        ]

        assert [r["date"] for r in rows] == ["2026-07-01", "2026-07-02"]


class TestDisplayFallbacks:
    def test_a_missing_member_row_falls_back_to_the_user_id(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_request(
            store,
            id="b1",
            user_id="ghost",
            model_id="nope",
            created_at="2026-02-01T00:00:00+00:00",
            charged=1,
        )

        row = an.usage_details(store, date(2026, 2, 1), date(2026, 2, 1))[
            "rows"
        ][0]

        assert row["username"] == "ghost"
        assert row["model_name"] == "nope"

    def test_a_model_without_a_display_name_falls_back_to_its_id(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_model(store, "m1", name=None)
        _add_user(store, "u1", "alice")
        _add_request(store, id="n1", created_at="2026-02-01T00:00:00+00:00")

        row = an.usage_details(store, date(2026, 2, 1), date(2026, 2, 1))[
            "rows"
        ][0]

        assert row["model_name"] == "m1"


class TestChargingSemantics:
    def test_a_null_actual_contributes_zero(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_model(store, "m1", "M")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id="h1",
            actual=None,
            charged=1,
            created_at="2026-08-01T00:00:00+00:00",
        )
        _add_request(
            store,
            id="h2",
            actual=5,
            charged=1,
            created_at="2026-08-01T01:00:00+00:00",
        )

        row = an.usage_details(store, date(2026, 8, 1), date(2026, 8, 1))[
            "rows"
        ][0]

        assert row["actual"] == 5
        assert row["charged"] == 2

    @pytest.mark.parametrize(
        "status,expected_reserved",
        [("reserved", 100), ("dispatched", 100)],
    )
    def test_only_inflight_statuses_count_reserved(
        self,
        store: GovernanceStore,
        status: str,
        expected_reserved: int,
    ) -> None:
        _add_model(store, "m1", "M")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id=f"rf-{status}",
            status=status,
            reserved=100,
            created_at="2026-03-01T00:00:00+00:00",
        )

        row = an.usage_details(store, date(2026, 3, 1), date(2026, 3, 1))[
            "rows"
        ][0]

        assert row["reserved"] == expected_reserved

    @pytest.mark.parametrize("status", ["completed", "failed", "conservative"])
    def test_settled_statuses_do_not_count_reserved(
        self,
        store: GovernanceStore,
        status: str,
    ) -> None:
        _add_model(store, "m1", "M")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id=f"rs-{status}",
            status=status,
            reserved=300,
            created_at="2026-03-01T00:00:00+00:00",
        )

        row = an.usage_details(store, date(2026, 3, 1), date(2026, 3, 1))[
            "rows"
        ][0]

        assert row["reserved"] == 0

    def test_conservative_sums_the_charged_column(
        self,
        store: GovernanceStore,
    ) -> None:
        # reserved is 200 here; if the code summed reserved instead of
        # charged this would read 200 rather than 30.
        _add_model(store, "m1", "M")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id="c3",
            status="conservative",
            reserved=200,
            charged=30,
            created_at="2026-03-01T02:00:00+00:00",
        )

        row = an.usage_details(store, date(2026, 3, 1), date(2026, 3, 1))[
            "rows"
        ][0]

        assert row["conservative"] == 30
        assert row["reserved"] == 0

    def test_other_statuses_leave_conservative_at_zero(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_model(store, "m1", "M")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id="cz",
            status="completed",
            charged=8,
            created_at="2026-03-01T03:00:00+00:00",
        )

        row = an.usage_details(store, date(2026, 3, 1), date(2026, 3, 1))[
            "rows"
        ][0]

        assert row["conservative"] == 0
        assert row["charged"] == 8

    def test_the_four_statuses_combine_in_one_row(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_model(store, "m1", "Qwen Max")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id="c1",
            status="reserved",
            reserved=100,
            created_at="2026-03-01T00:00:00+00:00",
        )
        _add_request(
            store,
            id="c2",
            status="dispatched",
            reserved=50,
            charged=5,
            created_at="2026-03-01T01:00:00+00:00",
        )
        _add_request(
            store,
            id="c3b",
            status="conservative",
            reserved=200,
            charged=30,
            created_at="2026-03-01T02:00:00+00:00",
        )
        _add_request(
            store,
            id="c4",
            status="completed",
            reserved=300,
            charged=8,
            actual=8,
            created_at="2026-03-01T03:00:00+00:00",
        )

        row = an.usage_details(store, date(2026, 3, 1), date(2026, 3, 1))[
            "rows"
        ][0]

        assert row["requests"] == 4
        assert row["charged"] == 43
        assert row["actual"] == 8
        assert row["reserved"] == 150
        assert row["conservative"] == 30
        assert row["failures"] == 0


class TestFailureCounting:
    def test_an_error_message_counts_as_a_failure(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_model(store, "m1", "M")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id="d1",
            error="boom",
            status="failed",
            created_at="2026-04-01T00:00:00+00:00",
        )
        _add_request(
            store,
            id="d2",
            charged=3,
            created_at="2026-04-01T01:00:00+00:00",
        )

        row = an.usage_details(store, date(2026, 4, 1), date(2026, 4, 1))[
            "rows"
        ][0]

        assert row["failures"] == 1
        assert row["requests"] == 2

    def test_a_failed_status_without_an_error_is_not_a_failure(
        self,
        store: GovernanceStore,
    ) -> None:
        # Failures are keyed off the error column, not off the status.
        _add_model(store, "m1", "M")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id="d3",
            error=None,
            status="failed",
            created_at="2026-04-01T00:00:00+00:00",
        )

        row = an.usage_details(store, date(2026, 4, 1), date(2026, 4, 1))[
            "rows"
        ][0]

        assert row["failures"] == 0
        assert row["requests"] == 1


class TestWindowEdges:
    def test_the_start_of_the_first_day_is_inside(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_model(store, "m1", "M")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id="f0",
            created_at="2026-06-01T00:00:00+00:00",
            charged=1,
        )

        rows = an.usage_details(store, date(2026, 6, 1), date(2026, 6, 1))[
            "rows"
        ]

        assert [r["charged"] for r in rows] == [1]

    def test_the_last_instant_of_the_last_day_is_inside(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_model(store, "m1", "M")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id="f2",
            created_at="2026-06-01T23:59:59+00:00",
            charged=2,
        )

        rows = an.usage_details(store, date(2026, 6, 1), date(2026, 6, 1))[
            "rows"
        ]

        assert [r["charged"] for r in rows] == [2]

    def test_the_midnight_after_the_last_day_is_outside(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_model(store, "m1", "M")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id="f3",
            created_at="2026-06-02T00:00:00+00:00",
            charged=4,
        )

        rows = an.usage_details(store, date(2026, 6, 1), date(2026, 6, 1))[
            "rows"
        ]

        assert rows == []

    def test_widening_the_window_admits_the_next_day(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_model(store, "m1", "M")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id="f4",
            created_at="2026-06-02T00:00:00+00:00",
            charged=4,
        )

        buckets = _by_key(
            an.usage_details(store, date(2026, 6, 1), date(2026, 6, 2))[
                "rows"
            ],
        )

        assert buckets["2026-06-02"]["charged"] == 4


class TestTimezoneBucketing:
    def test_a_utc_ledger_keeps_the_utc_day(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_model(store, "m1", "M")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id="e1",
            created_at="2026-05-01T20:00:00+00:00",
            charged=4,
        )

        out = an.usage_details(store, date(2026, 5, 1), date(2026, 5, 2))

        assert out["timezone"] == "UTC"
        assert [r["date"] for r in out["rows"]] == ["2026-05-01"]

    def test_an_east_of_utc_zone_moves_the_row_to_the_next_day(
        self,
        store: GovernanceStore,
    ) -> None:
        _set_timezone(store, "Asia/Shanghai")
        _add_model(store, "m1", "M")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id="e2",
            created_at="2026-05-01T20:00:00+00:00",
            charged=4,
        )

        out = an.usage_details(store, date(2026, 5, 1), date(2026, 5, 2))

        assert out["timezone"] == "Asia/Shanghai"
        assert [r["date"] for r in out["rows"]] == ["2026-05-02"]

    def test_a_west_of_utc_zone_keeps_the_same_day(
        self,
        store: GovernanceStore,
    ) -> None:
        _set_timezone(store, "America/New_York")
        _add_model(store, "m1", "M")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id="e3",
            created_at="2026-05-01T20:00:00+00:00",
            charged=4,
        )

        out = an.usage_details(store, date(2026, 5, 1), date(2026, 5, 2))

        assert out["timezone"] == "America/New_York"
        assert [r["date"] for r in out["rows"]] == ["2026-05-01"]

    def test_rows_can_split_across_days_in_one_query(
        self,
        store: GovernanceStore,
    ) -> None:
        # 15:30Z is 23:30 in Shanghai (same day); 16:30Z is 00:30 the
        # next day there, so one window yields two buckets.
        _set_timezone(store, "Asia/Shanghai")
        _add_model(store, "m1", "M")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id="k1",
            created_at="2026-05-01T15:30:00+00:00",
            charged=3,
        )
        _add_request(
            store,
            id="k2",
            created_at="2026-05-01T16:30:00+00:00",
            charged=4,
        )

        buckets = _by_key(
            an.usage_details(store, date(2026, 5, 1), date(2026, 5, 2))[
                "rows"
            ],
        )

        assert sorted(buckets) == ["2026-05-01", "2026-05-02"]
        assert buckets["2026-05-01"]["charged"] == 3
        assert buckets["2026-05-02"]["charged"] == 4

    def test_the_reported_zone_matches_the_configured_one(
        self,
        store: GovernanceStore,
    ) -> None:
        _set_timezone(store, "Europe/Berlin")

        out = an.usage_details(store, date(2026, 5, 1), date(2026, 5, 2))

        assert out["timezone"] == str(store.settings()["timezone"])


class TestTransactionHygiene:
    def test_the_connection_is_left_usable_after_the_read(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_model(store, "m1", "M")
        _add_user(store, "u1", "alice")
        _add_request(store, id="t1", created_at="2026-09-01T00:00:00+00:00")

        an.usage_details(store, date(2026, 9, 1), date(2026, 9, 1))

        with store.connect() as db:
            db.execute("BEGIN")
            count = db.execute(
                "SELECT COUNT(*) AS n FROM hub_model_requests",
            ).fetchone()
        assert int(count["n"]) == 1

    def test_the_ledger_is_not_modified_by_reporting(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_model(store, "m1", "M")
        _add_user(store, "u1", "alice")
        _add_request(
            store,
            id="t2",
            created_at="2026-09-01T00:00:00+00:00",
            charged=6,
        )

        first = an.usage_details(store, date(2026, 9, 1), date(2026, 9, 1))
        second = an.usage_details(store, date(2026, 9, 1), date(2026, 9, 1))

        assert first == second
        assert first["rows"][0]["charged"] == 6

    def test_the_returned_rows_are_plain_dicts(
        self,
        store: GovernanceStore,
    ) -> None:
        _add_model(store, "m1", "M")
        _add_user(store, "u1", "alice")
        _add_request(store, id="t3", created_at="2026-09-01T00:00:00+00:00")

        row = an.usage_details(store, date(2026, 9, 1), date(2026, 9, 1))[
            "rows"
        ][0]

        # sqlite3.Row would also answer row["charged"]; the contract is a
        # JSON-serialisable dict because routes.py returns it directly.
        assert not isinstance(row, sqlite3.Row)
        assert json.loads(json.dumps(row)) == row
