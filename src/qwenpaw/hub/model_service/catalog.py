# -*- coding: utf-8 -*-
"""Revisioned model aliases, grants, and control-only credentials."""

from __future__ import annotations

import json
import logging
import secrets
import uuid

from ...providers.openai_provider import token_limit_kwargs
from ..database import utc_now
from ..invitations import secret_digest
from .provider_setup import model_provider

_SYSTEM = "__qwenpaw_hub_system__"
_SCOPE = "organization-models"
logger = logging.getLogger(__name__)


class ModelCatalog:
    """Resolve all organization configuration on the trusted server."""

    def __init__(self, store, vault):
        self.store = store
        self.vault = vault

    def rows(self, table: str, db=None) -> list[dict]:
        """Read one of the two internal catalog tables."""
        if table not in {"hub_model_connections", "hub_managed_models"}:
            raise ValueError("Unknown catalog table")
        if db is None:
            with self.store.connect() as connection:
                return self.rows(table, connection)
        return [
            {
                **json.loads(row["value_json"]),
                "id": row["id"],
                "revision": row["revision"],
            }
            for row in db.execute(f"SELECT * FROM {table}").fetchall()
        ]

    def require_revision(self, db, table, resource_id, revision):
        """Reject stale editors, including concurrent invitation grants."""
        current = next(
            (row for row in self.rows(table, db) if row["id"] == resource_id),
            None,
        )
        if current is None or current["revision"] != revision:
            raise ValueError("Configuration changed; refresh before saving")

    def save_connection(self, body, connection_id=None) -> dict:
        """Store a secret by immutable reference before publishing metadata."""
        updating = connection_id is not None
        connection_id = connection_id or uuid.uuid4().hex
        value = body.model_dump(exclude={"api_key", "revision"})
        with self.store.connect() as db:
            previous = next(
                (
                    r
                    for r in self.rows(
                        "hub_model_connections",
                        db,
                    )
                    if r["id"] == connection_id
                ),
                None,
            )
        if body.api_key:
            secret_name = f"MODEL_{uuid.uuid4().hex.upper()}"
            self.vault.put(
                tenant_id=_SYSTEM,
                scope=_SCOPE,
                name=secret_name,
                value=body.api_key,
                trusted=True,
            )
        elif previous:
            secret_name = previous["secret_ref"]
        else:
            raise ValueError("An API key is required for a new connection")
        value["secret_ref"] = secret_name
        try:
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if updating:
                    self.require_revision(
                        db,
                        "hub_model_connections",
                        connection_id,
                        body.revision,
                    )
                db.execute(
                    "INSERT INTO hub_model_connections(id, value_json) "
                    "VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET "
                    "value_json = excluded.value_json, "
                    "revision = hub_model_connections.revision + 1",
                    (connection_id, json.dumps(value)),
                )
                self._validate_default(
                    db,
                    self.store.settings(db)["default_model_id"],
                )
                self.store.bump(db)
        except BaseException:
            if body.api_key:
                try:
                    self.vault.delete(
                        tenant_id=_SYSTEM,
                        scope=_SCOPE,
                        name=secret_name,
                    )
                except Exception:
                    logger.error(
                        "Could not remove unused model secret",
                    )
            raise
        # Replaced secrets stay valid for already-admitted request snapshots.
        return {"id": connection_id}

    def connections(self) -> list[dict]:
        """Expose metadata, never a secret reference or plaintext key."""
        return [
            {
                **{k: v for k, v in row.items() if k != "secret_ref"},
                "has_key": True,
            }
            for row in self.rows("hub_model_connections")
        ]

    def save_model(self, body, model_id=None) -> dict:
        """Atomically publish an alias and its member grants."""
        updating = model_id is not None
        model_id = model_id or uuid.uuid4().hex
        value = body.model_dump(exclude={"revision"})
        if "output_limit_field" not in body.model_fields_set:
            value["output_limit_field"] = next(
                iter(token_limit_kwargs(body.upstream_model, 1)),
            )
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if updating:
                self.require_revision(
                    db,
                    "hub_managed_models",
                    model_id,
                    body.revision,
                )
            if not db.execute(
                "SELECT 1 FROM hub_model_connections WHERE id = ?",
                (body.connection_id,),
            ).fetchone():
                raise ValueError("Connection does not exist")
            for user_id in body.user_ids:
                if not db.execute(
                    "SELECT 1 FROM hub_users WHERE user_id = ? "
                    "AND deleted_at IS NULL",
                    (user_id,),
                ).fetchone():
                    raise ValueError("Unknown member")
            db.execute(
                "INSERT INTO hub_managed_models "
                "(id, connection_id, value_json) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "connection_id = excluded.connection_id, "
                "value_json = excluded.value_json, "
                "revision = hub_managed_models.revision + 1",
                (model_id, body.connection_id, json.dumps(value)),
            )
            self._validate_default(
                db,
                self.store.settings(db)["default_model_id"],
            )
            self.store.bump(db)
        return {"id": model_id}

    def save_policy(self, body) -> dict:
        """Reject stale writes and invalid organization defaults."""
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = self.store.settings(db)
            if old["revision"] != body.revision:
                raise ValueError("Policy changed; refresh before saving")
            if (
                old["timezone"] != body.timezone
                and db.execute(
                    "SELECT 1 FROM hub_model_requests LIMIT 1",
                ).fetchone()
            ):
                raise ValueError("Budget timezone is fixed after first use")
            self._validate_default(db, body.default_model_id)
            db.execute(
                "UPDATE hub_governance_settings SET value_json = ?, "
                "revision = revision + 1 WHERE singleton = 1",
                (json.dumps(body.model_dump(exclude={"revision"})),),
            )
        return self.store.settings()

    def _validate_default(self, db, model_id):
        """Validate the default within every catalog write transaction."""
        if model_id is None:
            return
        model = next(
            (
                m
                for m in self.rows("hub_managed_models", db)
                if m["id"] == model_id
            ),
            None,
        )
        if model and model["enabled"] and model["all_members"]:
            self._require_connection(
                model,
                self.rows("hub_model_connections", db),
            )
            return
        raise ValueError("Choose an enabled all-member default")

    @staticmethod
    def _require_connection(model, connections):
        """Explain connection availability to administrators only."""
        connection = next(
            (c for c in connections if c["id"] == model["connection_id"]),
            None,
        )
        if connection is None:
            raise ValueError("Connection does not exist")
        if not connection["enabled"]:
            raise ValueError("Model provider connection is disabled")

    @staticmethod
    def _available(model, connection, user_id, *, test=False):
        """Apply one authorization rule to both discovery and inference."""
        return bool(
            connection
            and connection["enabled"]
            and (
                test
                or (
                    model["enabled"]
                    and (model["all_members"] or user_id in model["user_ids"])
                )
            ),
        )

    def resolve(self, user_id, model_id, db=None, *, test=False):
        """Resolve the current policy, alias, and upstream snapshot."""
        if db is None:
            with self.store.connect() as connection:
                connection.execute("BEGIN")
                return self.resolve(user_id, model_id, connection, test=test)
        policy = self.store.settings(db)
        connections = {
            c["id"]: c for c in self.rows("hub_model_connections", db)
        }
        for model in self.rows("hub_managed_models", db):
            connection = connections.get(model["connection_id"])
            if model["id"] == model_id and test:
                self._require_connection(model, connections.values())
            if model["id"] == model_id and self._available(
                model,
                connection,
                user_id,
                test=test,
            ):
                return policy, model, connection
        raise PermissionError("Model is unavailable or not authorized")

    def member_catalog(self, user_id: str) -> dict:
        """Build an explicit allowlisted directory, without upstream fields."""
        with self.store.connect() as db:
            db.execute("BEGIN")
            policy = self.store.settings(db)
            connections = {
                c["id"]: c for c in self.rows("hub_model_connections", db)
            }
            items = []
            for model in self.rows("hub_managed_models", db):
                if not self._available(
                    model,
                    connections.get(model["connection_id"]),
                    user_id,
                ):
                    continue
                items.append(
                    {
                        "supports_agent_thinking": model_provider(
                            model,
                            connections[model["connection_id"]],
                        ).supports_agent_thinking(model["upstream_model"]),
                        **{
                            k: model[k]
                            for k in (
                                "id",
                                "name",
                                "description",
                                "supports_image",
                                "input_token_limit",
                                "output_token_limit",
                            )
                        },
                    },
                )
        return {
            "revision": policy["revision"],
            "models": items,
            "default_model_id": (
                policy["default_model_id"]
                or (items[0]["id"] if items else None)
            ),
        }

    def issue_token(self, record) -> str:
        """Rotate a runtime's model-only capability at each start."""
        token = secrets.token_urlsafe(32)
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO hub_model_runtime_tokens "
                "(runtime_id, user_id, digest) VALUES (?, ?, ?) "
                "ON CONFLICT(runtime_id) DO UPDATE SET "
                "digest = excluded.digest, user_id = excluded.user_id",
                (
                    record.runtime_id,
                    record.owner_user_id,
                    secret_digest(token),
                ),
            )
        return token

    def authenticate(self, token: str) -> dict:
        """Resolve identity from a capability and current account state."""
        with self.store.connect() as db:
            row = db.execute(
                "SELECT t.* FROM hub_model_runtime_tokens t "
                "JOIN hub_users u ON u.user_id = t.user_id "
                "JOIN runtimes r ON r.runtime_id = t.runtime_id "
                "WHERE t.digest = ? AND u.disabled = 0 "
                "AND u.deleted_at IS NULL AND r.deleted_at IS NULL "
                "AND r.owner_user_id = t.user_id "
                "AND r.desired_state = 'running'",
                (secret_digest(token),),
            ).fetchone()
        if row is None:
            raise PermissionError("Invalid model runtime credential")
        return dict(row)

    def observe(self, runtime_id: str, revision: int):
        """Record directory acknowledgement separately from successful use."""
        with self.store.connect() as db:
            db.execute(
                "UPDATE hub_model_runtime_tokens SET "
                "observed_revision = ?, observed_at = ? WHERE runtime_id = ?",
                (revision, utc_now(), runtime_id),
            )

    def key(self, connection: dict) -> str:
        """Resolve an immutable control-only secret reference."""
        return self.vault.get(
            tenant_id=_SYSTEM,
            scope=_SCOPE,
            name=connection["secret_ref"],
        )
