# -*- coding: utf-8 -*-
"""Create conversation, runtime event, Skill, MCP and channel tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_agent_conversation"
down_revision = "0001_identity_access"
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
        "conversations",
        _id(),
        sa.Column(
            "agent_id", UUID, sa.ForeignKey("agents.id"), nullable=False
        ),
        sa.Column(
            "owner_user_id", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("model_override_id", UUID, sa.ForeignKey("models.id")),
        _created(),
        _updated(),
        sa.Column("deleted_at", TS),
        sa.CheckConstraint(
            "status IN ('active','archived','deleted')",
            name="ck_conversations_status",
        ),
    )
    op.create_index(
        "ix_conversations_owner_agent_updated",
        "conversations",
        ["owner_user_id", "agent_id", "updated_at"],
    )

    op.create_table(
        "conversation_members",
        sa.Column(
            "conversation_id",
            UUID,
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column(
            "granted_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _created(),
        sa.PrimaryKeyConstraint(
            "conversation_id", "user_id", name="pk_conversation_members"
        ),
    )

    op.create_table(
        "runs",
        _id(),
        sa.Column(
            "conversation_id",
            UUID,
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column(
            "initiated_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "started_at", TS, nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("finished_at", TS),
        sa.Column("error_summary", sa.Text()),
        sa.CheckConstraint(
            "status IN ('queued','running','waiting_input','waiting_approval',"
            "'completed','failed','cancelled')",
            name="ck_runs_status",
        ),
    )
    op.create_index(
        "ix_runs_conversation_started",
        "runs",
        ["conversation_id", "started_at"],
    )

    op.create_table(
        "messages",
        _id(),
        sa.Column(
            "conversation_id",
            UUID,
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column("run_id", UUID, sa.ForeignKey("runs.id")),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("message_type", sa.String(64), nullable=False),
        sa.Column("content", JSON, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id")),
        _created(),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_messages_conversation_sequence",
        ),
    )

    op.create_table(
        "run_events",
        _id(),
        sa.Column("run_id", UUID, sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(96), nullable=False),
        sa.Column("payload", JSON, nullable=False),
        sa.Column("tool_call_id", UUID),
        _created(),
        sa.UniqueConstraint(
            "run_id", "sequence", name="uq_run_events_sequence"
        ),
    )

    op.create_table(
        "tool_calls",
        _id(),
        sa.Column("run_id", UUID, sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("call_id", sa.String(256), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("tool_name", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "redacted_arguments", JSON, nullable=False, server_default="{}"
        ),
        sa.Column("approval_id", UUID),
        sa.Column("output_ref", sa.Text()),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.UniqueConstraint(
            "run_id", "call_id", name="uq_tool_calls_run_call"
        ),
    )
    op.create_foreign_key(
        "fk_run_events_tool_call",
        "run_events",
        "tool_calls",
        ["tool_call_id"],
        ["id"],
    )

    op.create_table(
        "attachments",
        _id(),
        sa.Column(
            "conversation_id",
            UUID,
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column("message_id", UUID, sa.ForeignKey("messages.id")),
        sa.Column(
            "owner_user_id", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(256), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        _created(),
        sa.CheckConstraint("size >= 0", name="ck_attachments_size"),
        sa.UniqueConstraint("storage_key", name="uq_attachments_storage_key"),
    )

    op.create_table(
        "user_agent_preferences",
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "agent_id", UUID, sa.ForeignKey("agents.id"), nullable=False
        ),
        sa.Column(
            "last_conversation_id", UUID, sa.ForeignKey("conversations.id")
        ),
        sa.Column("draft_input", sa.Text()),
        _updated(),
        sa.PrimaryKeyConstraint(
            "user_id", "agent_id", name="pk_user_agent_preferences"
        ),
    )

    op.create_table(
        "skill_pool_items",
        _id(),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_version_id", UUID),
        sa.Column(
            "created_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _created(),
        _updated(),
        sa.UniqueConstraint("name", name="uq_skill_pool_items_name"),
    )

    op.create_table(
        "skill_pool_versions",
        _id(),
        sa.Column(
            "skill_id",
            UUID,
            sa.ForeignKey("skill_pool_items.id"),
            nullable=False,
        ),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("content_key", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("metadata", JSON, nullable=False, server_default="{}"),
        sa.Column(
            "published_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _created(),
        sa.UniqueConstraint(
            "skill_id", "version", name="uq_skill_pool_versions_version"
        ),
    )
    op.create_foreign_key(
        "fk_skill_pool_current_version",
        "skill_pool_items",
        "skill_pool_versions",
        ["current_version_id"],
        ["id"],
    )

    op.create_table(
        "agent_skills",
        _id(),
        sa.Column(
            "agent_id", UUID, sa.ForeignKey("agents.id"), nullable=False
        ),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("content_key", sa.Text(), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "source_pool_version_id",
            UUID,
            sa.ForeignKey("skill_pool_versions.id"),
        ),
        sa.Column(
            "detached", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("config", JSON, nullable=False, server_default="{}"),
        _updated(),
        sa.UniqueConstraint("agent_id", "name", name="uq_agent_skills_name"),
    )

    op.create_table(
        "skill_publish_requests",
        _id(),
        sa.Column(
            "agent_skill_id",
            UUID,
            sa.ForeignKey("agent_skills.id"),
            nullable=False,
        ),
        sa.Column(
            "submitted_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reviewed_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("review_note", sa.Text()),
        _created(),
        sa.Column("reviewed_at", TS),
    )

    op.create_table(
        "agent_drivers",
        _id(),
        sa.Column(
            "agent_id", UUID, sa.ForeignKey("agents.id"), nullable=False
        ),
        sa.Column("protocol", sa.String(32), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_revision_id", UUID),
        sa.Column("credential_binding_id", UUID),
        sa.Column(
            "created_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _created(),
        sa.UniqueConstraint("agent_id", "name", name="uq_agent_drivers_name"),
    )

    op.create_table(
        "driver_revisions",
        _id(),
        sa.Column(
            "driver_id",
            UUID,
            sa.ForeignKey("agent_drivers.id"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("config", JSON, nullable=False),
        sa.Column("tool_allowlist", JSON, nullable=False, server_default="[]"),
        sa.Column("policy", JSON, nullable=False, server_default="{}"),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column(
            "created_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _created(),
        sa.UniqueConstraint(
            "driver_id", "revision", name="uq_driver_revisions_revision"
        ),
    )
    op.create_foreign_key(
        "fk_agent_drivers_current_revision",
        "agent_drivers",
        "driver_revisions",
        ["current_revision_id"],
        ["id"],
    )

    op.create_table(
        "mcp_oauth_sessions",
        _id(),
        sa.Column(
            "driver_id",
            UUID,
            sa.ForeignKey("agent_drivers.id"),
            nullable=False,
        ),
        sa.Column(
            "initiated_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("state_hash", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("completed_at", TS),
        sa.UniqueConstraint("state_hash", name="uq_mcp_oauth_state_hash"),
    )

    op.create_table(
        "channel_bindings",
        _id(),
        sa.Column(
            "agent_id", UUID, sa.ForeignKey("agents.id"), nullable=False
        ),
        sa.Column("channel_type", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("config", JSON, nullable=False, server_default="{}"),
        sa.Column("credential_ref", UUID),
        sa.Column(
            "created_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "updated_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _created(),
        _updated(),
        sa.UniqueConstraint(
            "agent_id", "channel_type", name="uq_channel_bindings_agent_type"
        ),
    )

    op.create_table(
        "channel_external_identities",
        _id(),
        sa.Column(
            "channel_binding_id",
            UUID,
            sa.ForeignKey("channel_bindings.id"),
            nullable=False,
        ),
        sa.Column("external_subject_id", sa.String(512), nullable=False),
        sa.Column("platform_user_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("binding_status", sa.String(32), nullable=False),
        sa.Column("metadata", JSON, nullable=False, server_default="{}"),
        _created(),
        sa.UniqueConstraint(
            "channel_binding_id",
            "external_subject_id",
            name="uq_channel_external_identity",
        ),
    )

    op.create_table(
        "channel_access_rules",
        _id(),
        sa.Column(
            "channel_binding_id",
            UUID,
            sa.ForeignKey("channel_bindings.id"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("subject_pattern", sa.Text(), nullable=False),
        sa.Column("effect", sa.String(16), nullable=False),
        sa.Column(
            "created_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _updated(),
        sa.CheckConstraint(
            "effect IN ('allow','deny')", name="ck_channel_access_rules_effect"
        ),
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_agent_drivers_current_revision",
        "agent_drivers",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_skill_pool_current_version",
        "skill_pool_items",
        type_="foreignkey",
    )
    for table in (
        "channel_access_rules",
        "channel_external_identities",
        "channel_bindings",
        "mcp_oauth_sessions",
        "driver_revisions",
        "agent_drivers",
        "skill_publish_requests",
        "agent_skills",
        "skill_pool_versions",
        "skill_pool_items",
        "user_agent_preferences",
        "attachments",
        "run_events",
        "tool_calls",
        "messages",
        "runs",
        "conversation_members",
        "conversations",
    ):
        op.drop_table(table)
