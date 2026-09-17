# -*- coding: utf-8 -*-
"""Add short-lived access token state to user sessions."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_identity_sessions"
down_revision = "0003_governance_operations"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column(
        "user_sessions",
        sa.Column("access_token_hash", sa.Text()),
    )
    op.add_column(
        "user_sessions",
        sa.Column("access_expires_at", TS),
    )
    op.add_column(
        "user_sessions",
        sa.Column("last_seen_at", TS),
    )
    op.create_unique_constraint(
        "uq_user_sessions_access_hash",
        "user_sessions",
        ["access_token_hash"],
    )
    op.create_index(
        "ix_user_sessions_access_active",
        "user_sessions",
        ["access_token_hash", "access_expires_at", "revoked_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_sessions_access_active",
        table_name="user_sessions",
    )
    op.drop_constraint(
        "uq_user_sessions_access_hash",
        "user_sessions",
        type_="unique",
    )
    op.drop_column("user_sessions", "last_seen_at")
    op.drop_column("user_sessions", "access_expires_at")
    op.drop_column("user_sessions", "access_token_hash")
