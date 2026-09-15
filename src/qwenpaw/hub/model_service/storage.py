# -*- coding: utf-8 -*-
"""Transactional storage shared by Hub governance services."""

from __future__ import annotations

import json
from pathlib import Path

from ..database import connect_hub_database, initialize_hub_database


SCHEMA = """
CREATE TABLE IF NOT EXISTS hub_governance_settings (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    value_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS hub_model_connections (
    id TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS hub_managed_models (
    id TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL REFERENCES hub_model_connections(id),
    value_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS hub_model_runtime_tokens (
    runtime_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES hub_users(user_id),
    digest TEXT NOT NULL UNIQUE,
    observed_revision INTEGER NOT NULL DEFAULT 0,
    observed_at TEXT
);
CREATE TABLE IF NOT EXISTS hub_invite_batches (
    id TEXT PRIMARY KEY,
    actor_id TEXT NOT NULL,
    request_id TEXT NOT NULL UNIQUE,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hub_invites (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES hub_invite_batches(id),
    digest TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    redeemed_by TEXT REFERENCES hub_users(user_id),
    redeemed_at TEXT,
    policy_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hub_token_budgets (
    subject TEXT PRIMARY KEY,
    token_limit INTEGER CHECK(token_limit IS NULL OR token_limit >= 0)
);
CREATE TABLE IF NOT EXISTS hub_model_requests (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    runtime_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    connection_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    period TEXT NOT NULL,
    reserved INTEGER NOT NULL,
    charged INTEGER NOT NULL DEFAULT 0,
    actual INTEGER,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_model_requests_period_user
ON hub_model_requests(period, user_id, status);
CREATE INDEX IF NOT EXISTS idx_model_requests_model
ON hub_model_requests(model_id, created_at);
CREATE INDEX IF NOT EXISTS idx_invites_batch ON hub_invites(batch_id);
"""

DEFAULTS = {
    "enabled": False,
    "invitation_enabled": False,
    "default_model_id": None,
    "member_token_limit": None,
    "timezone": "UTC",
}


class GovernanceStore:
    """Own the single-instance governance schema and configuration."""

    def __init__(self, database_path: Path):
        self.database_path = database_path
        initialize_hub_database(database_path)
        with self.connect() as db:
            db.executescript(SCHEMA)
            db.execute(
                "INSERT OR IGNORE INTO hub_governance_settings "
                "VALUES (1, ?, 1)",
                (json.dumps(DEFAULTS),),
            )

    def connect(self):
        """Open a short-lived connection with common Hub settings."""
        return connect_hub_database(self.database_path)

    def settings(self, db=None) -> dict:
        """Read one revisioned policy snapshot."""
        if db is None:
            with self.connect() as connection:
                return self.settings(connection)
        row = db.execute(
            "SELECT * FROM hub_governance_settings WHERE singleton = 1",
        ).fetchone()
        return {
            **json.loads(row["value_json"]),
            "revision": row["revision"],
        }

    def bump(self, db) -> None:
        """Advance the catalog revision within the caller transaction."""
        db.execute(
            "UPDATE hub_governance_settings SET revision = revision + 1",
        )
