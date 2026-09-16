# -*- coding: utf-8 -*-
"""Make channel bindings private to the user who owns the binding."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_user_channel_bindings"
down_revision = "0005_agent_public_visibility"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "channel_bindings",
        sa.Column("owner_user_id", UUID, nullable=True),
    )
    op.execute(
        "UPDATE channel_bindings "
        "SET owner_user_id = created_by "
        "WHERE owner_user_id IS NULL"
    )
    op.alter_column(
        "channel_bindings",
        "owner_user_id",
        existing_type=UUID,
        nullable=False,
    )
    op.create_foreign_key(
        "fk_channel_bindings_owner_user",
        "channel_bindings",
        "users",
        ["owner_user_id"],
        ["id"],
    )
    op.drop_constraint(
        "uq_channel_bindings_agent_type",
        "channel_bindings",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_channel_bindings_agent_owner_type",
        "channel_bindings",
        ["agent_id", "owner_user_id", "channel_type"],
    )
    op.create_index(
        "ix_channel_bindings_owner_user_id",
        "channel_bindings",
        ["owner_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_channel_bindings_owner_user_id",
        table_name="channel_bindings",
    )
    op.drop_constraint(
        "uq_channel_bindings_agent_owner_type",
        "channel_bindings",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_channel_bindings_agent_type",
        "channel_bindings",
        ["agent_id", "channel_type"],
    )
    op.drop_constraint(
        "fk_channel_bindings_owner_user",
        "channel_bindings",
        type_="foreignkey",
    )
    op.drop_column("channel_bindings", "owner_user_id")
