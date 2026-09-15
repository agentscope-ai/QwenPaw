# -*- coding: utf-8 -*-
"""Single-use invitations redeemed atomically with account creation."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from .database import utc_now


def secret_digest(value: str) -> str:
    """Hash a high-entropy capability without storing its plaintext."""
    return hashlib.sha256(value.encode()).hexdigest()


class InvitationService:
    """Issue finite invitation batches and serialize their redemption."""

    def __init__(self, store, auth):
        self.store = store
        self.auth = auth

    def create(self, actor_id: str, body) -> dict:
        """Return newly generated codes exactly once."""
        batch_id = uuid.uuid4().hex
        now = utc_now()
        expires = (
            datetime.now(timezone.utc)
            + timedelta(
                days=body.valid_days,
            )
        ).isoformat()
        codes = []
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM hub_invite_batches WHERE request_id = ?",
                (body.request_id,),
            ).fetchone():
                raise ValueError("Batch already created; codes cannot replay")
            for model_id in body.model_ids:
                if not db.execute(
                    "SELECT 1 FROM hub_managed_models WHERE id = ?",
                    (model_id,),
                ).fetchone():
                    raise ValueError("Unknown model grant")
            db.execute(
                "INSERT INTO hub_invite_batches VALUES (?, ?, ?, ?, ?)",
                (batch_id, actor_id, body.request_id, body.note, now),
            )
            for _ in range(body.count):
                code = secrets.token_urlsafe(32)
                invite_id = uuid.uuid4().hex
                db.execute(
                    "INSERT INTO hub_invites "
                    "(id, batch_id, digest, expires_at, policy_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        invite_id,
                        batch_id,
                        secret_digest(code),
                        expires,
                        json.dumps(
                            {
                                "model_ids": body.model_ids,
                                "token_limit": body.token_limit,
                                "inherit_budget": body.inherit_budget,
                            },
                        ),
                    ),
                )
                codes.append({"id": invite_id, "code": code})
        return {"id": batch_id, "expires_at": expires, "codes": codes}

    def list_batches(self) -> list[dict]:
        """Return batch progress without invitation material."""
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT b.*, COUNT(i.id) AS total, "
                "SUM(i.redeemed_by IS NOT NULL) AS redeemed, "
                "SUM(i.revoked_at IS NOT NULL) AS revoked, "
                "MIN(i.expires_at) AS expires_at "
                "FROM hub_invite_batches b JOIN hub_invites i "
                "ON b.id = i.batch_id GROUP BY b.id "
                "ORDER BY b.created_at DESC LIMIT 200",
            ).fetchall()
        return [dict(row) for row in rows]

    def revoke(self, batch_id: str) -> None:
        """Revoke only unused invitations, leaving accounts intact."""
        with self.store.connect() as db:
            db.execute(
                "UPDATE hub_invites SET revoked_at = ? "
                "WHERE batch_id = ? AND redeemed_by IS NULL",
                (utc_now(), batch_id),
            )

    def redeem(self, code: str, username: str, password: str):
        """Consume a code and create its ordinary member in one transaction."""
        try:
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT * FROM hub_invites WHERE digest = ? "
                    "AND revoked_at IS NULL AND redeemed_by IS NULL "
                    "AND expires_at > ?",
                    (secret_digest(code), utc_now()),
                ).fetchone()
                if self.auth.registration_mode(db) != "invite" or row is None:
                    raise PermissionError("Invalid or unavailable invitation")
                user_id = self.auth.insert_user(db, username, password)
                policy = json.loads(row["policy_json"])
                for model_id in policy["model_ids"]:
                    model_row = db.execute(
                        "SELECT value_json FROM hub_managed_models "
                        "WHERE id = ?",
                        (model_id,),
                    ).fetchone()
                    if model_row is None:
                        continue
                    model = json.loads(model_row[0])
                    if model["enabled"] and not model["all_members"]:
                        model["user_ids"].append(user_id)
                        db.execute(
                            "UPDATE hub_managed_models SET value_json = ?, "
                            "revision = revision + 1 WHERE id = ?",
                            (json.dumps(model), model_id),
                        )
                        self.store.bump(db)
                if not policy["inherit_budget"]:
                    db.execute(
                        "INSERT INTO hub_token_budgets VALUES (?, ?)",
                        (user_id, policy["token_limit"]),
                    )
                db.execute(
                    "UPDATE hub_invites SET redeemed_by = ?, "
                    "redeemed_at = ? WHERE id = ?",
                    (user_id, utc_now(), row["id"]),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Username already exists") from exc
        user = self.auth.get_user(user_id)
        return user, self.auth.create_token(user)
