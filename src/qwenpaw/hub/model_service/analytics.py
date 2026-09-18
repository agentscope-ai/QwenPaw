# -*- coding: utf-8 -*-
"""Date-scoped model and member analytics from the gateway ledger."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def usage_details(store, start_date: date, end_date: date):
    """Aggregate metadata only, preserving the ledger's charging semantics."""
    if not 0 <= (end_date - start_date).days < 365:
        raise ValueError("Usage range must contain 1 to 365 days")
    with store.connect() as db:
        db.execute("BEGIN")
        zone = ZoneInfo(store.settings(db)["timezone"])
        start = datetime.combine(start_date, time.min, zone)
        end = datetime.combine(end_date + timedelta(days=1), time.min, zone)
        records = db.execute(
            "SELECT r.created_at, r.user_id, r.model_id, r.charged, "
            "r.actual, r.reserved, r.status, r.error, u.username, "
            "json_extract(m.value_json, '$.name') AS model_name "
            "FROM hub_model_requests r "
            "LEFT JOIN hub_users u ON u.user_id = r.user_id "
            "LEFT JOIN hub_managed_models m ON m.id = r.model_id "
            "WHERE r.created_at >= ? AND r.created_at < ? "
            "ORDER BY r.created_at",
            (
                start.astimezone(timezone.utc).isoformat(),
                end.astimezone(timezone.utc).isoformat(),
            ),
        )
        groups = {}
        for row in records:
            day = datetime.fromisoformat(row["created_at"])
            label = day.astimezone(zone).date().isoformat()
            key = (label, row["user_id"], row["model_id"])
            group = groups.setdefault(
                key,
                {
                    "date": label,
                    "user_id": row["user_id"],
                    "username": row["username"] or row["user_id"],
                    "model_id": row["model_id"],
                    "model_name": row["model_name"] or row["model_id"],
                    "requests": 0,
                    "charged": 0,
                    "actual": 0,
                    "reserved": 0,
                    "conservative": 0,
                    "failures": 0,
                },
            )
            group["requests"] += 1
            group["charged"] += row["charged"]
            group["actual"] += row["actual"] or 0
            group["failures"] += int(row["error"] is not None)
            if row["status"] in {"reserved", "dispatched"}:
                group["reserved"] += row["reserved"]
            if row["status"] == "conservative":
                group["conservative"] += row["charged"]
        return {"timezone": str(zone), "rows": list(groups.values())}
