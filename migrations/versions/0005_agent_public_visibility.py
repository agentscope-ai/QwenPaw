# -*- coding: utf-8 -*-
"""Add the approved platform-public Agent visibility state."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_agent_public_visibility"
down_revision = "0004_identity_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_agents_visibility", "agents", type_="check")
    op.create_check_constraint(
        "ck_agents_visibility",
        "agents",
        "visibility IN ('private','shared','public_candidate','public')",
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE agents SET visibility = 'public_candidate' "
            "WHERE visibility = 'public'"
        )
    )
    op.drop_constraint("ck_agents_visibility", "agents", type_="check")
    op.create_check_constraint(
        "ck_agents_visibility",
        "agents",
        "visibility IN ('private','shared','public_candidate')",
    )
