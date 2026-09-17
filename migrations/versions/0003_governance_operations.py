# -*- coding: utf-8 -*-
"""Create platform governance, publication and operations tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_governance_operations"
down_revision = "0002_agent_conversation"
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
        "credential_records",
        _id(),
        sa.Column("scope_type", sa.String(32), nullable=False),
        sa.Column("scope_id", UUID),
        sa.Column("secret_type", sa.String(64), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _created(),
        sa.Column("rotated_at", TS),
        sa.Column("revoked_at", TS),
        sa.CheckConstraint(
            "scope_type IN ('platform','agent','plugin','channel','driver')",
            name="ck_credential_records_scope_type",
        ),
    )
    op.create_index(
        "ix_credential_records_scope",
        "credential_records",
        ["scope_type", "scope_id", "status"],
    )

    op.create_table(
        "credential_bindings",
        _id(),
        sa.Column(
            "credential_id",
            UUID,
            sa.ForeignKey("credential_records.id"),
            nullable=False,
        ),
        sa.Column("consumer_type", sa.String(32), nullable=False),
        sa.Column("consumer_id", UUID, nullable=False),
        sa.Column("purpose", sa.String(128), nullable=False),
        sa.Column(
            "created_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _created(),
        sa.UniqueConstraint(
            "consumer_type",
            "consumer_id",
            "purpose",
            name="uq_credential_bindings_consumer_purpose",
        ),
    )
    op.create_foreign_key(
        "fk_model_providers_credential",
        "model_providers",
        "credential_records",
        ["credential_ref"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_agent_drivers_credential_binding",
        "agent_drivers",
        "credential_bindings",
        ["credential_binding_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_channel_bindings_credential",
        "channel_bindings",
        "credential_records",
        ["credential_ref"],
        ["id"],
    )

    op.create_table(
        "plugin_installations",
        _id(),
        sa.Column("plugin_id", sa.String(256), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("plugin_type", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "installed_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "installed_at", TS, nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("disabled_at", TS),
        sa.UniqueConstraint(
            "plugin_id", name="uq_plugin_installations_plugin_id"
        ),
    )

    op.create_table(
        "plugin_capabilities",
        sa.Column(
            "plugin_installation_id",
            UUID,
            sa.ForeignKey("plugin_installations.id"),
            nullable=False,
        ),
        sa.Column("capability_type", sa.String(64), nullable=False),
        sa.Column("capability_key", sa.String(256), nullable=False),
        sa.Column(
            "declared_config", JSON, nullable=False, server_default="{}"
        ),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.Column("reviewed_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", TS),
        sa.PrimaryKeyConstraint(
            "plugin_installation_id",
            "capability_type",
            "capability_key",
            name="pk_plugin_capabilities",
        ),
    )

    op.create_table(
        "app_grants",
        _id(),
        sa.Column(
            "plugin_installation_id",
            UUID,
            sa.ForeignKey("plugin_installations.id"),
            nullable=False,
        ),
        sa.Column("subject_type", sa.String(32), nullable=False),
        sa.Column("subject_id", UUID),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "granted_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _created(),
    )
    op.create_index(
        "uq_app_grants_subject",
        "app_grants",
        ["plugin_installation_id", "subject_type", "subject_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )

    op.create_table(
        "agent_plugin_settings",
        sa.Column(
            "agent_id", UUID, sa.ForeignKey("agents.id"), nullable=False
        ),
        sa.Column(
            "plugin_installation_id",
            UUID,
            sa.ForeignKey("plugin_installations.id"),
            nullable=False,
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("config", JSON, nullable=False, server_default="{}"),
        sa.Column(
            "credential_ref", UUID, sa.ForeignKey("credential_records.id")
        ),
        sa.Column(
            "updated_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _updated(),
        sa.PrimaryKeyConstraint(
            "agent_id",
            "plugin_installation_id",
            name="pk_agent_plugin_settings",
        ),
    )

    op.create_table(
        "app_user_data",
        sa.Column(
            "plugin_installation_id",
            UUID,
            sa.ForeignKey("plugin_installations.id"),
            nullable=False,
        ),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("agent_id", UUID, sa.ForeignKey("agents.id")),
        sa.Column("namespace", sa.String(128), nullable=False),
        sa.Column("key", sa.String(256), nullable=False),
        sa.Column("value", JSON, nullable=False),
        _updated(),
        sa.PrimaryKeyConstraint(
            "plugin_installation_id",
            "user_id",
            "namespace",
            "key",
            name="pk_app_user_data",
        ),
    )

    op.create_table(
        "automation_schedules",
        _id(),
        sa.Column(
            "agent_id", UUID, sa.ForeignKey("agents.id"), nullable=False
        ),
        sa.Column(
            "created_by_user_id",
            UUID,
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "automation_owner_user_id",
            UUID,
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("schedule", JSON, nullable=False),
        sa.Column("timezone", sa.String(128), nullable=False),
        sa.Column("task", JSON, nullable=False),
        sa.Column("dispatch", JSON, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "config_version", sa.Integer(), nullable=False, server_default="1"
        ),
        _created(),
        _updated(),
    )

    op.create_table(
        "automation_grants",
        _id(),
        sa.Column(
            "schedule_id",
            UUID,
            sa.ForeignKey("automation_schedules.id"),
            nullable=False,
        ),
        sa.Column(
            "authorized_by_user_id",
            UUID,
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("capability", sa.String(128), nullable=False),
        sa.Column("resource_scope", JSON, nullable=False),
        sa.Column("target_scope", JSON, nullable=False),
        sa.Column("expires_at", TS),
        sa.Column("revoked_at", TS),
    )

    op.create_table(
        "automation_executions",
        _id(),
        sa.Column(
            "schedule_id",
            UUID,
            sa.ForeignKey("automation_schedules.id"),
            nullable=False,
        ),
        sa.Column("run_id", UUID, sa.ForeignKey("runs.id")),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("trigger", sa.String(64), nullable=False),
        sa.Column("started_at", TS, nullable=False),
        sa.Column("finished_at", TS),
        sa.Column("delivery_status", sa.String(32)),
        sa.Column("error_summary", sa.Text()),
    )

    op.create_table(
        "notifications",
        _id(),
        sa.Column(
            "recipient_user_id",
            UUID,
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("agent_id", UUID, sa.ForeignKey("agents.id")),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_id", UUID),
        sa.Column("event_type", sa.String(96), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("payload_ref", sa.Text()),
        _created(),
    )
    op.create_index(
        "ix_notifications_recipient_created",
        "notifications",
        ["recipient_user_id", "created_at"],
    )

    op.create_table(
        "notification_receipts",
        sa.Column(
            "notification_id",
            UUID,
            sa.ForeignKey("notifications.id"),
            nullable=False,
        ),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("read_at", TS),
        sa.Column("deleted_at", TS),
        sa.PrimaryKeyConstraint(
            "notification_id", "user_id", name="pk_notification_receipts"
        ),
    )

    op.create_table(
        "approval_requests",
        _id(),
        sa.Column(
            "approval_user_id", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "agent_id", UUID, sa.ForeignKey("agents.id"), nullable=False
        ),
        sa.Column("conversation_id", UUID, sa.ForeignKey("conversations.id")),
        sa.Column("run_id", UUID, sa.ForeignKey("runs.id")),
        sa.Column("tool_call_id", UUID, sa.ForeignKey("tool_calls.id")),
        sa.Column("capability", sa.String(128), nullable=False),
        sa.Column(
            "redacted_arguments", JSON, nullable=False, server_default="{}"
        ),
        sa.Column("status", sa.String(32), nullable=False),
        _created(),
        sa.Column("decided_at", TS),
        sa.Column("expires_at", TS),
    )
    op.create_foreign_key(
        "fk_tool_calls_approval",
        "tool_calls",
        "approval_requests",
        ["approval_id"],
        ["id"],
    )

    op.create_table(
        "usage_records",
        _id(),
        sa.Column("occurred_at", TS, nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("agent_id", UUID, sa.ForeignKey("agents.id")),
        sa.Column("conversation_id", UUID, sa.ForeignKey("conversations.id")),
        sa.Column("run_id", UUID, sa.ForeignKey("runs.id")),
        sa.Column(
            "automation_schedule_id",
            UUID,
            sa.ForeignKey("automation_schedules.id"),
        ),
        sa.Column(
            "provider_id",
            UUID,
            sa.ForeignKey("model_providers.id"),
            nullable=False,
        ),
        sa.Column(
            "model_id", UUID, sa.ForeignKey("models.id"), nullable=False
        ),
        sa.Column(
            "prompt_tokens",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "completion_tokens",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "call_count", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.CheckConstraint(
            "prompt_tokens >= 0 AND completion_tokens >= 0 "
            "AND call_count >= 0",
            name="ck_usage_records_nonnegative",
        ),
    )
    op.create_index(
        "ix_usage_records_time_user_agent",
        "usage_records",
        ["occurred_at", "user_id", "agent_id"],
    )

    op.create_table(
        "shared_apps",
        _id(),
        sa.Column(
            "agent_id", UUID, sa.ForeignKey("agents.id"), nullable=False
        ),
        sa.Column(
            "owner_user_id", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_publication_id", UUID),
        _created(),
        _updated(),
        sa.UniqueConstraint("agent_id", name="uq_shared_apps_agent"),
    )

    op.create_table(
        "shared_app_drafts",
        _id(),
        sa.Column(
            "shared_app_id",
            UUID,
            sa.ForeignKey("shared_apps.id"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("manifest", JSON, nullable=False),
        sa.Column("workspace_key", sa.Text(), nullable=False),
        sa.Column(
            "created_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _updated(),
        sa.UniqueConstraint(
            "shared_app_id", "revision", name="uq_shared_app_drafts_revision"
        ),
    )

    op.create_table(
        "shared_app_publications",
        _id(),
        sa.Column(
            "shared_app_id",
            UUID,
            sa.ForeignKey("shared_apps.id"),
            nullable=False,
        ),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("immutable_manifest", JSON, nullable=False),
        sa.Column("baseline_workspace_key", sa.Text(), nullable=False),
        sa.Column(
            "submitted_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("reviewed_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.Column("published_at", TS),
        sa.Column("retired_at", TS),
        sa.UniqueConstraint(
            "shared_app_id",
            "version",
            name="uq_shared_app_publications_version",
        ),
    )
    op.create_foreign_key(
        "fk_shared_apps_current_publication",
        "shared_apps",
        "shared_app_publications",
        ["current_publication_id"],
        ["id"],
    )

    op.create_table(
        "shared_app_user_workspaces",
        sa.Column(
            "shared_app_id",
            UUID,
            sa.ForeignKey("shared_apps.id"),
            nullable=False,
        ),
        sa.Column(
            "publication_id",
            UUID,
            sa.ForeignKey("shared_app_publications.id"),
            nullable=False,
        ),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workspace_key", sa.Text(), nullable=False),
        sa.Column("quota", sa.BigInteger()),
        sa.Column("status", sa.String(32), nullable=False),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint(
            "shared_app_id",
            "publication_id",
            "user_id",
            name="pk_shared_app_user_workspaces",
        ),
    )

    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(256), primary_key=True),
        sa.Column("value", JSON, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _updated(),
    )

    op.create_table(
        "system_setting_revisions",
        _id(),
        sa.Column("key", sa.String(256), nullable=False),
        sa.Column("old_value", JSON),
        sa.Column("new_value", JSON, nullable=False),
        sa.Column(
            "changed_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("reason", sa.Text()),
        _created(),
    )

    op.create_table(
        "user_preferences",
        sa.Column(
            "user_id", UUID, sa.ForeignKey("users.id"), primary_key=True
        ),
        sa.Column(
            "language", sa.String(32), nullable=False, server_default="zh-CN"
        ),
        sa.Column(
            "timezone",
            sa.String(128),
            nullable=False,
            server_default="Asia/Shanghai",
        ),
        sa.Column("preferences", JSON, nullable=False, server_default="{}"),
        _updated(),
    )

    op.create_table(
        "security_policies",
        _id(),
        sa.Column("scope_type", sa.String(32), nullable=False),
        sa.Column("scope_id", UUID),
        sa.Column("policy_type", sa.String(64), nullable=False),
        sa.Column("config", JSON, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "enforced", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "updated_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _updated(),
        sa.UniqueConstraint(
            "scope_type",
            "scope_id",
            "policy_type",
            "version",
            name="uq_security_policies_scope_version",
        ),
    )

    op.create_table(
        "security_events",
        _id(),
        sa.Column("occurred_at", TS, nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("agent_id", UUID, sa.ForeignKey("agents.id")),
        sa.Column("run_id", UUID, sa.ForeignKey("runs.id")),
        sa.Column("event_type", sa.String(96), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("rule_id", sa.String(256)),
        sa.Column(
            "redacted_detail", JSON, nullable=False, server_default="{}"
        ),
    )
    op.create_index(
        "ix_security_events_occurred",
        "security_events",
        ["occurred_at", "severity"],
    )

    op.create_table(
        "backup_artifacts",
        _id(),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("backup_type", sa.String(32), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("manifest_hash", sa.String(128), nullable=False),
        sa.Column("signature", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        _created(),
        sa.UniqueConstraint(
            "storage_key", name="uq_backup_artifacts_storage_key"
        ),
    )

    op.create_table(
        "backup_operations",
        _id(),
        sa.Column(
            "artifact_id",
            UUID,
            sa.ForeignKey("backup_artifacts.id"),
            nullable=False,
        ),
        sa.Column("operation_type", sa.String(32), nullable=False),
        sa.Column(
            "requested_by", UUID, sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("scope_manifest", JSON, nullable=False),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.Column("error_summary", sa.Text()),
    )

    op.create_table(
        "audit_logs",
        _id(),
        sa.Column("actor_user_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("actor_identity_type", sa.String(32), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", UUID),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column(
            "redacted_detail", JSON, nullable=False, server_default="{}"
        ),
        _created(),
    )
    op.create_index(
        "ix_audit_logs_created_actor_resource",
        "audit_logs",
        ["created_at", "actor_user_id", "resource_type", "resource_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_shared_apps_current_publication",
        "shared_apps",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_tool_calls_approval", "tool_calls", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_channel_bindings_credential",
        "channel_bindings",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_agent_drivers_credential_binding",
        "agent_drivers",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_model_providers_credential",
        "model_providers",
        type_="foreignkey",
    )
    for table in (
        "audit_logs",
        "backup_operations",
        "backup_artifacts",
        "security_events",
        "security_policies",
        "user_preferences",
        "system_setting_revisions",
        "system_settings",
        "shared_app_user_workspaces",
        "shared_app_publications",
        "shared_app_drafts",
        "shared_apps",
        "usage_records",
        "approval_requests",
        "notification_receipts",
        "notifications",
        "automation_executions",
        "automation_grants",
        "automation_schedules",
        "app_user_data",
        "agent_plugin_settings",
        "app_grants",
        "plugin_capabilities",
        "plugin_installations",
        "credential_bindings",
        "credential_records",
    ):
        op.drop_table(table)
