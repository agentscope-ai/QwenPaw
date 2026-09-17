# -*- coding: utf-8 -*-
"""Register per-user private Agent workspaces and memory index state."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008_agent_user_workspaces"
down_revision = "0007_agent_history_access"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "agent_user_workspaces",
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("agent_id", UUID, nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("workspace_key", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("index_state", sa.String(length=32), nullable=False),
        sa.Column("index_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_accessed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scope IN ('public','private')",
            name="ck_agent_user_workspaces_scope",
        ),
        sa.CheckConstraint(
            "status IN ('active','access_revoked','cleanup_pending')",
            name="ck_agent_user_workspaces_status",
        ),
        sa.CheckConstraint(
            "index_state IN " "('ready','needs_reindex','reindexing','reindex_failed')",
            name="ck_agent_user_workspaces_index_state",
        ),
        sa.CheckConstraint(
            "index_version >= 0",
            name="ck_agent_user_workspaces_index_version",
        ),
        sa.CheckConstraint(
            "workspace_key NOT LIKE '/%' " "AND workspace_key NOT LIKE '%..%'",
            name="ck_agent_user_workspaces_relative_workspace_key",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_agent_user_workspaces_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_agent_user_workspaces_agent",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "user_id",
            "agent_id",
            "scope",
            name="pk_agent_user_workspaces",
        ),
    )
    op.create_index(
        "ix_agent_user_workspaces_agent_id",
        "agent_user_workspaces",
        ["agent_id"],
    )
    op.create_index(
        "ix_agent_user_workspaces_status",
        "agent_user_workspaces",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_user_workspaces_status",
        table_name="agent_user_workspaces",
    )
    op.drop_index(
        "ix_agent_user_workspaces_agent_id",
        table_name="agent_user_workspaces",
    )
    op.drop_table("agent_user_workspaces")
