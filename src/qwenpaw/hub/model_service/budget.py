# -*- coding: utf-8 -*-
"""Atomic monthly admission and conservative request settlement."""

from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from ..database import utc_now


class BudgetExceededError(ValueError):
    """The organization or member has insufficient unreserved tokens."""


class TokenBudgetService:
    """Use the request ledger as the single source of budget truth."""

    def __init__(self, store):
        self.store = store

    def period(self, db) -> str:
        """Freeze the monthly period using the deployment's IANA timezone."""
        zone = ZoneInfo(self.store.settings(db)["timezone"])
        return datetime.now(zone).strftime("%Y-%m")

    def limit(self, db, subject):
        """Distinguish absent overrides from explicit unlimited budgets."""
        row = db.execute(
            "SELECT token_limit FROM hub_token_budgets WHERE subject = ?",
            (subject,),
        ).fetchone()
        if row is not None:
            return row["token_limit"]
        return (
            None
            if subject == "organization"
            else self.store.settings(db)["member_token_limit"]
        )

    def usage(self, db, subject, period):
        """Compute balances from committed ledger rows in one snapshot."""
        clause = "" if subject == "organization" else " AND user_id = ?"
        args = (period,) if not clause else (period, subject)
        row = db.execute(
            f"SELECT COALESCE(SUM(charged), 0) AS charged, "
            f"COALESCE(SUM(actual), 0) AS actual, "
            f"COALESCE(SUM(CASE WHEN status IN ('reserved', 'dispatched') "
            f"THEN reserved ELSE 0 END), 0) AS reserved, "
            f"COALESCE(SUM(CASE WHEN status = 'conservative' "
            f"THEN charged ELSE 0 END), 0) AS conservative, "
            f"COUNT(*) AS requests FROM hub_model_requests "
            f"WHERE period = ?{clause}",
            args,
        ).fetchone()
        limit = self.limit(db, subject)
        result = dict(row)
        result.update(
            {
                "subject": subject,
                "period": period,
                "token_limit": limit,
                "remaining": None
                if limit is None
                else max(
                    0,
                    limit - row["charged"] - row["reserved"],
                ),
            },
        )
        return result

    def summary(self, user_id):
        """Read the two budgets that govern a member's next call."""
        with self.store.connect() as db:
            db.execute("BEGIN")
            period = self.period(db)
            return {
                "member": self.usage(db, user_id, period),
                "organization": self.usage(db, "organization", period),
                "timezone": self.store.settings(db)["timezone"],
            }

    def set_limit(self, subject, body):
        """Change a limit without rewriting usage or active reservations."""
        with self.store.connect() as db:
            if (
                subject != "organization"
                and not db.execute(
                    "SELECT 1 FROM hub_users WHERE user_id = ? "
                    "AND deleted_at IS NULL",
                    (subject,),
                ).fetchone()
            ):
                raise ValueError("Unknown budget member")
            if body.inherit:
                db.execute(
                    "DELETE FROM hub_token_budgets WHERE subject = ?",
                    (subject,),
                )
            else:
                db.execute(
                    "INSERT INTO hub_token_budgets VALUES (?, ?) "
                    "ON CONFLICT(subject) DO UPDATE SET "
                    "token_limit = excluded.token_limit",
                    (subject, body.token_limit),
                )

    def reserve(self, identity, model_id, catalog, output_limit):
        """Authorize and reserve both budgets in a short transaction."""
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM hub_users WHERE user_id = ? "
                "AND disabled = 0 AND deleted_at IS NULL",
                (identity["user_id"],),
            ).fetchone():
                raise PermissionError("Account is disabled")
            if (
                identity["runtime_id"] != "admin-test"
                and not db.execute(
                    "SELECT 1 FROM hub_model_runtime_tokens t JOIN runtimes r "
                    "ON r.runtime_id = t.runtime_id WHERE t.runtime_id = ? "
                    "AND t.digest = ? AND r.desired_state = 'running' "
                    "AND r.owner_user_id = ? AND r.deleted_at IS NULL",
                    (
                        identity["runtime_id"],
                        identity["digest"],
                        identity["user_id"],
                    ),
                ).fetchone()
            ):
                raise PermissionError("Runtime capability revoked")
            policy, model, connection = catalog.resolve(
                identity["user_id"],
                model_id,
                db,
                test=identity["runtime_id"] == "admin-test",
            )
            cap = model["output_token_limit"]
            if output_limit is not None:
                cap = min(cap, output_limit)
            reserved = model["input_token_limit"] + cap
            period = self.period(db)
            for subject in ("organization", identity["user_id"]):
                usage = self.usage(db, subject, period)
                if usage["token_limit"] is not None:
                    if not model["budget_verified"]:
                        raise ValueError("Model budget bounds are unverified")
                    if usage["remaining"] < reserved:
                        raise BudgetExceededError("hub_budget_exceeded")
            request_id = uuid.uuid4().hex
            db.execute(
                "INSERT INTO hub_model_requests "
                "(id, user_id, runtime_id, model_id, connection_id, "
                "revision, period, reserved, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reserved', ?)",
                (
                    request_id,
                    identity["user_id"],
                    identity["runtime_id"],
                    model_id,
                    model["connection_id"],
                    policy["revision"],
                    period,
                    reserved,
                    utc_now(),
                ),
            )
        return request_id, model, connection, cap

    def dispatch(self, request_id):
        """Persist dispatch before sending bytes upstream."""
        with self.store.connect() as db:
            db.execute(
                "UPDATE hub_model_requests SET status = 'dispatched' "
                "WHERE id = ? AND status = 'reserved'",
                (request_id,),
            )

    def settle(self, request_id, actual=None, error=None):
        """Charge uncertain dispatched requests fully and settle once."""
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM hub_model_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
            if not row or row["status"] not in {"reserved", "dispatched"}:
                return
            if row["status"] == "reserved":
                charged, status = 0, "released"
            elif actual is None:
                charged, status = row["reserved"], "conservative"
            else:
                charged, status = actual, "settled"
            db.execute(
                "UPDATE hub_model_requests SET charged = ?, actual = ?, "
                "status = ?, error = ?, completed_at = ? WHERE id = ?",
                (charged, actual, status, error, utc_now(), request_id),
            )
            if actual is not None and actual > row["reserved"]:
                db.execute(
                    "UPDATE hub_managed_models SET value_json = "
                    "json_set(value_json, '$.budget_verified', "
                    "json('false')), "
                    "revision = revision + 1 WHERE id = ?",
                    (row["model_id"],),
                )
                self.store.bump(db)

    def recover(self):
        """Close orphaned reservations before accepting calls after restart."""
        with self.store.connect() as db:
            db.execute(
                "UPDATE hub_model_requests SET "
                "charged = CASE WHEN status = 'dispatched' "
                "THEN reserved ELSE 0 END, "
                "status = CASE WHEN status = 'dispatched' "
                "THEN 'conservative' ELSE 'released' END, "
                "error = 'hub_restarted', completed_at = ? "
                "WHERE status IN ('reserved', 'dispatched')",
                (utc_now(),),
            )

    def report(self):
        """Return aggregate diagnostics without employee conversation text."""
        with self.store.connect() as db:
            period = self.period(db)
            users = [
                dict(row)
                for row in db.execute(
                    "SELECT user_id, username FROM hub_users "
                    "WHERE deleted_at IS NULL ORDER BY username",
                )
            ]
            return {
                "organization": self.usage(db, "organization", period),
                "members": [
                    {
                        **user,
                        **self.usage(
                            db,
                            user["user_id"],
                            period,
                        ),
                    }
                    for user in users
                ],
                "models": [
                    dict(row)
                    for row in db.execute(
                        "SELECT model_id, COUNT(*) AS requests, "
                        "SUM(charged) AS charged, SUM(actual) AS actual, "
                        "SUM(error IS NOT NULL) AS failures "
                        "FROM hub_model_requests WHERE period = ? "
                        "GROUP BY model_id",
                        (period,),
                    )
                ],
            }
