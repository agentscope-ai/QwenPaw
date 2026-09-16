# -*- coding: utf-8 -*-
"""Create identity, model governance and Agent access tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_identity_access"
down_revision = None
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSON = postgresql.JSONB(astext_type=sa.Text())
TS = sa.DateTime(timezone=True)


def _id(name: str = "id") -> sa.Column:
    return sa.Column(name, UUID, primary_key=True)


def _created() -> sa.Column:
    return sa.Column(
        "created_at", TS, nullable=False, server_default=sa.text("now()")
    )


def _updated() -> sa.Column:
    return sa.Column(
        "updated_at", TS, nullable=False, server_default=sa.text("now()")
    )


def upgrade() -> None:
    op.create_table(
        "users",
        _id(),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("platform_role", sa.String(32), nullable=False),
        _created(),
        _updated(),
        sa.Column("last_login_at", TS),
        sa.CheckConstraint(
            "status IN ('active','disabled','locked','deleted')",
            name="ck_users_status",
        ),
        sa.CheckConstraint(
            "platform_role IN ('admin','member')",
            name="ck_users_platform_role",
        ),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("ix_users_status", "users", ["status"])

    op.create_table(
        "user_sessions",
        _id(),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("refresh_token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS),
        sa.Column("client_info", JSON, nullable=False, server_default="{}"),
        _created(),
        sa.UniqueConstraint(
            "refresh_token_hash", name="uq_user_sessions_refresh_hash"
        ),
    )
    op.create_index(
        "ix_user_sessions_user_active",
        "user_sessions",
        ["user_id", "expires_at", "revoked_at"],
    )

    op.create_table(
        "external_identities",
        _id(),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("external_subject_id", sa.String(512), nullable=False),
        sa.Column("binding_status", sa.String(32), nullable=False),
        sa.Column("metadata", JSON, nullable=False, server_default="{}"),
        _created(),
        sa.UniqueConstraint(
            "source",
            "external_subject_id",
            name="uq_external_identity_source_subject",
        ),
    )

    op.create_table(
        "model_providers",
        _id(),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "base_url_metadata", JSON, nullable=False, server_default="{}"
        ),
        sa.Column("credential_ref", UUID),
        sa.Column(
            "created_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _created(),
        _updated(),
        sa.UniqueConstraint("name", name="uq_model_providers_name"),
    )

    op.create_table(
        "models",
        _id(),
        sa.Column(
            "provider_id",
            UUID,
            sa.ForeignKey("model_providers.id"),
            nullable=False,
        ),
        sa.Column("model_key", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("capabilities", JSON, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("config", JSON, nullable=False, server_default="{}"),
        _created(),
        _updated(),
        sa.UniqueConstraint(
            "provider_id", "model_key", name="uq_models_provider_key"
        ),
    )

    op.create_table(
        "model_grants",
        _id(),
        sa.Column(
            "model_id", UUID, sa.ForeignKey("models.id"), nullable=False
        ),
        sa.Column("subject_type", sa.String(32), nullable=False),
        sa.Column("subject_id", UUID),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "created_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _created(),
        sa.CheckConstraint(
            "subject_type IN ('platform','user','agent')",
            name="ck_model_grants_subject_type",
        ),
    )
    op.create_index(
        "uq_model_grants_subject",
        "model_grants",
        ["model_id", "subject_type", "subject_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )

    op.create_table(
        "agents",
        _id(),
        sa.Column(
            "owner_user_id", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("visibility", sa.String(32), nullable=False),
        sa.Column("default_model_mode", sa.String(32), nullable=False),
        sa.Column("default_model_id", UUID, sa.ForeignKey("models.id")),
        sa.Column("draft_workspace_key", sa.Text(), nullable=False),
        sa.Column(
            "config_version", sa.Integer(), nullable=False, server_default="1"
        ),
        _created(),
        _updated(),
        sa.Column("deleted_at", TS),
        sa.CheckConstraint(
            "status IN ('draft','active','disabled','deleted')",
            name="ck_agents_status",
        ),
        sa.CheckConstraint(
            "visibility IN ('private','shared','public_candidate')",
            name="ck_agents_visibility",
        ),
    )
    op.create_index(
        "ix_agents_owner_status", "agents", ["owner_user_id", "status"]
    )

    op.create_table(
        "agent_members",
        sa.Column(
            "agent_id", UUID, sa.ForeignKey("agents.id"), nullable=False
        ),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column(
            "granted_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _created(),
        sa.Column("revoked_at", TS),
        sa.PrimaryKeyConstraint(
            "agent_id", "user_id", name="pk_agent_members"
        ),
        sa.CheckConstraint(
            "role IN ('collaborator','user')", name="ck_agent_members_role"
        ),
    )

    op.create_table(
        "agent_config_revisions",
        _id(),
        sa.Column(
            "agent_id", UUID, sa.ForeignKey("agents.id"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("structured_config", JSON, nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column(
            "changed_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _created(),
        sa.UniqueConstraint(
            "agent_id", "revision", name="uq_agent_config_revision"
        ),
        sa.UniqueConstraint(
            "agent_id", "content_hash", name="uq_agent_config_content_hash"
        ),
    )


def downgrade() -> None:
    for table in (
        "agent_config_revisions",
        "agent_members",
        "agents",
        "model_grants",
        "models",
        "model_providers",
        "external_identities",
        "user_sessions",
        "users",
    ):
        op.drop_table(table)
