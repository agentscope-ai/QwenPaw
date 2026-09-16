# -*- coding: utf-8 -*-
"""Bind chat attachments to an owner, agent, conversation, and message."""

from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0011_attachment_scope"
down_revision = "0010_runtime_workspace_grants"
branch_labels = None
depends_on = None

_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _target_schema() -> str:
    value = op.get_bind().execute(sa.text("SELECT current_schema()")).scalar_one()
    if not isinstance(value, str) or not _SAFE_SCHEMA.fullmatch(value):
        raise RuntimeError("invalid_database_schema")
    return value


def _drop_attachment_policies() -> None:
    op.execute('DROP POLICY IF EXISTS "attachments_select" ON "attachments"')
    op.execute('DROP POLICY IF EXISTS "attachments_write" ON "attachments"')
    op.execute('DROP POLICY IF EXISTS "attachments_insert" ON "attachments"')
    op.execute('DROP POLICY IF EXISTS "attachments_update" ON "attachments"')
    op.execute('DROP POLICY IF EXISTS "attachments_delete" ON "attachments"')


def upgrade() -> None:
    schema = _target_schema()
    _drop_attachment_policies()
    op.add_column("attachments", sa.Column("agent_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_attachments_agent_id",
        "attachments",
        "agents",
        ["agent_id"],
        ["id"],
    )
    op.add_column(
        "attachments",
        sa.Column("original_name", sa.Text(), nullable=True),
    )
    op.execute(
        "UPDATE attachments a SET agent_id = c.agent_id "
        "FROM conversations c WHERE c.id = a.conversation_id"
    )
    op.execute(
        r"UPDATE attachments SET original_name = COALESCE("
        r"NULLIF(regexp_replace(storage_key, '^.*[/\\]', ''), ''), "
        r"'attachment')"
    )
    op.alter_column("attachments", "agent_id", nullable=False)
    op.alter_column("attachments", "original_name", nullable=False)
    op.alter_column("attachments", "conversation_id", nullable=True)
    op.create_index(
        "ix_attachments_owner_agent_created",
        "attachments",
        ["owner_user_id", "agent_id", "created_at"],
    )

    current_user = f'"{schema}".qwenpaw_current_user_id()'
    op.execute(
        "CREATE POLICY attachments_select ON attachments FOR SELECT "
        f"USING (owner_user_id = {current_user})"
    )
    op.execute(
        "CREATE POLICY attachments_insert ON attachments FOR INSERT "
        f"WITH CHECK (owner_user_id = {current_user})"
    )
    op.execute(
        "CREATE POLICY attachments_update ON attachments FOR UPDATE "
        f"USING (owner_user_id = {current_user}) "
        f"WITH CHECK (owner_user_id = {current_user})"
    )
    op.execute(
        "CREATE POLICY attachments_delete ON attachments FOR DELETE "
        f"USING (owner_user_id = {current_user})"
    )


def downgrade() -> None:
    pending = op.get_bind().execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM attachments WHERE conversation_id IS NULL)")
    ).scalar_one()
    if pending:
        raise RuntimeError("pending_attachments_prevent_downgrade")
    schema = _target_schema()
    _drop_attachment_policies()
    op.execute(
        "CREATE POLICY attachments_select ON attachments FOR SELECT "
        f'USING ("{schema}".qwenpaw_can_read_conversation(conversation_id))'
    )
    op.execute(
        "CREATE POLICY attachments_write ON attachments FOR ALL "
        f'USING ("{schema}".qwenpaw_can_write_conversation(conversation_id)) '
        f'WITH CHECK ("{schema}".qwenpaw_can_write_conversation(conversation_id))'
    )
    op.drop_index("ix_attachments_owner_agent_created", table_name="attachments")
    op.alter_column("attachments", "conversation_id", nullable=False)
    op.drop_column("attachments", "original_name")
    op.drop_constraint(
        "fk_attachments_agent_id",
        "attachments",
        type_="foreignkey",
    )
    op.drop_column("attachments", "agent_id")
