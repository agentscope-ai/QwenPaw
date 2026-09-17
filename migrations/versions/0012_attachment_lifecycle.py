# -*- coding: utf-8 -*-
"""Add explicit lifecycle metadata to chat attachments."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0012_attachment_lifecycle"
down_revision = "0011_attachment_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "attachments",
        sa.Column("lifecycle", sa.Text(), nullable=False, server_default="temporary"),
    )
    op.add_column("attachments", sa.Column("saved_path", sa.Text(), nullable=True))
    op.add_column(
        "attachments",
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attachments",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attachments",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_check_constraint(
        "ck_attachments_lifecycle",
        "attachments",
        "lifecycle IN ('temporary', 'saved', 'deleted')",
    )
    op.create_check_constraint(
        "ck_attachments_lifecycle_state",
        "attachments",
        "(lifecycle = 'temporary' AND saved_path IS NULL "
        "AND saved_at IS NULL AND deleted_at IS NULL) OR "
        "(lifecycle = 'saved' AND saved_path IS NOT NULL "
        "AND saved_at IS NOT NULL AND deleted_at IS NULL) OR "
        "(lifecycle = 'deleted' AND deleted_at IS NOT NULL AND "
        "((saved_path IS NULL AND saved_at IS NULL) OR "
        "(saved_path IS NOT NULL AND saved_at IS NOT NULL)))",
    )
    op.create_index(
        "ix_attachments_owner_agent_lifecycle_created",
        "attachments",
        ["owner_user_id", "agent_id", "lifecycle", "created_at"],
    )


def downgrade() -> None:
    has_non_temporary = op.get_bind().execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM attachments "
            "WHERE lifecycle <> 'temporary')"
        )
    ).scalar_one()
    if has_non_temporary:
        raise RuntimeError("attachment_lifecycle_prevents_downgrade")
    op.drop_index(
        "ix_attachments_owner_agent_lifecycle_created",
        table_name="attachments",
    )
    op.drop_constraint(
        "ck_attachments_lifecycle_state",
        "attachments",
        type_="check",
    )
    op.drop_constraint(
        "ck_attachments_lifecycle",
        "attachments",
        type_="check",
    )
    op.drop_column("attachments", "updated_at")
    op.drop_column("attachments", "deleted_at")
    op.drop_column("attachments", "saved_at")
    op.drop_column("attachments", "saved_path")
    op.drop_column("attachments", "lifecycle")
