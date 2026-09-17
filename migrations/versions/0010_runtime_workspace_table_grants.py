# -*- coding: utf-8 -*-
"""Grant the application role access to late workspace access tables."""

from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa

revision = "0010_runtime_workspace_grants"
down_revision = "0009_conversation_sharing_rls"
branch_labels = None
depends_on = None

_APPLICATION_ROLE = "qwenpaw_runtime"
_TABLES = ("agent_history_access", "agent_user_workspaces")
_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _target_schema() -> str:
    value = op.get_bind().execute(sa.text("SELECT current_schema()"))
    schema = value.scalar_one()
    if not isinstance(schema, str) or not _SAFE_SCHEMA.fullmatch(schema):
        raise RuntimeError("invalid_database_schema")
    return schema


def _role_exists() -> bool:
    result = op.get_bind().execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
        {"role": _APPLICATION_ROLE},
    )
    return bool(result.scalar_one())


def upgrade() -> None:
    if not _role_exists():
        return
    schema = _target_schema()
    tables = ", ".join(f'"{schema}"."{table}"' for table in _TABLES)
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {tables} '
        f'TO "{_APPLICATION_ROLE}"'
    )


def downgrade() -> None:
    if not _role_exists():
        return
    schema = _target_schema()
    tables = ", ".join(f'"{schema}"."{table}"' for table in _TABLES)
    op.execute(
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE {tables} '
        f'FROM "{_APPLICATION_ROLE}"'
    )
