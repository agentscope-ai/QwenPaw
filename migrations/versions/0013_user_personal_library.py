# -*- coding: utf-8 -*-
"""Add isolated metadata for user personal libraries.

File bodies remain in the filesystem.  PostgreSQL stores only ownership,
integrity metadata and the per-Agent read grant state.
"""

from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0013_user_personal_library"
down_revision = "0012_attachment_lifecycle"
branch_labels = None
depends_on = None

_APPLICATION_ROLE = "qwenpaw_runtime"
_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_DOCUMENTS_TABLE = "user_library_documents"
_GRANTS_TABLE = "user_library_agent_grants"


def _target_schema() -> str:
    value = op.get_bind().execute(sa.text("SELECT current_schema()")).scalar_one()
    if not isinstance(value, str) or not _SAFE_SCHEMA.fullmatch(value):
        raise RuntimeError("invalid_database_schema")
    return value


def _role_exists() -> bool:
    result = op.get_bind().execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
        {"role": _APPLICATION_ROLE},
    )
    return bool(result.scalar_one())


def _grant_application_role(schema: str) -> None:
    if not _role_exists():
        return
    tables = ", ".join(
        f'"{schema}"."{table}"' for table in (_DOCUMENTS_TABLE, _GRANTS_TABLE)
    )
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {tables} '
        f'TO "{_APPLICATION_ROLE}"'
    )


def _revoke_application_role(schema: str) -> None:
    if not _role_exists():
        return
    tables = ", ".join(
        f'"{schema}"."{table}"' for table in (_DOCUMENTS_TABLE, _GRANTS_TABLE)
    )
    op.execute(
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE {tables} '
        f'FROM "{_APPLICATION_ROLE}"'
    )


def _enable_owner_rls(schema: str, table: str) -> None:
    current_user = f'"{schema}".qwenpaw_current_user_id()'
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY {table}_select ON "{table}" FOR SELECT '
        f'USING (owner_user_id = {current_user})'
    )
    op.execute(
        f'CREATE POLICY {table}_insert ON "{table}" FOR INSERT '
        f'WITH CHECK (owner_user_id = {current_user})'
    )
    op.execute(
        f'CREATE POLICY {table}_update ON "{table}" FOR UPDATE '
        f'USING (owner_user_id = {current_user}) '
        f'WITH CHECK (owner_user_id = {current_user})'
    )
    op.execute(
        f'CREATE POLICY {table}_delete ON "{table}" FOR DELETE '
        f'USING (owner_user_id = {current_user})'
    )


def upgrade() -> None:
    schema = _target_schema()
    op.create_table(
        _DOCUMENTS_TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("size >= 0", name="ck_user_library_documents_size"),
        sa.UniqueConstraint(
            "owner_user_id",
            "relative_path",
            name="uq_user_library_documents_owner_path",
        ),
    )
    op.create_index(
        "ix_user_library_documents_owner_updated",
        _DOCUMENTS_TABLE,
        ["owner_user_id", sa.text("updated_at DESC")],
    )
    op.create_table(
        _GRANTS_TABLE,
        sa.Column(
            "owner_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_user_library_agent_grants_status",
        ),
        sa.UniqueConstraint(
            "owner_user_id",
            "agent_id",
            name="uq_user_library_agent_grants_owner_agent",
        ),
    )
    op.create_index(
        "ix_user_library_agent_grants_owner_status",
        _GRANTS_TABLE,
        ["owner_user_id", "status"],
    )
    _enable_owner_rls(schema, _DOCUMENTS_TABLE)
    _enable_owner_rls(schema, _GRANTS_TABLE)
    _grant_application_role(schema)


def downgrade() -> None:
    has_data = op.get_bind().execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM user_library_documents) "
            "OR EXISTS (SELECT 1 FROM user_library_agent_grants)"
        )
    ).scalar_one()
    if has_data:
        raise RuntimeError("personal_library_data_prevents_downgrade")
    schema = _target_schema()
    _revoke_application_role(schema)
    op.drop_table(_GRANTS_TABLE)
    op.drop_table(_DOCUMENTS_TABLE)
