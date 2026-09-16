# -*- coding: utf-8 -*-
"""Persist historical read-only Agent access after a conversation exists."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_agent_history_access"
down_revision = "0006_user_channel_bindings"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "agent_history_access",
        sa.Column("agent_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column(
            "first_chat_created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_chat_created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_agent_history_access_agent",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_agent_history_access_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "agent_id",
            "user_id",
            name="pk_agent_history_access",
        ),
    )
    op.create_index(
        "ix_agent_history_access_user_id",
        "agent_history_access",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_history_access_user_id",
        table_name="agent_history_access",
    )
    op.drop_table("agent_history_access")
