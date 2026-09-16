"""Add per-user Agent artifact lifecycle metadata."""
from __future__ import annotations

import re
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0014_artifact_lifecycle"
down_revision = "0013_user_personal_library"
branch_labels = None
depends_on = None

_APPLICATION_ROLE = "qwenpaw_runtime"
_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_TABLE = "user_agent_artifacts"


def _target_schema() -> str:
    value = op.get_bind().execute(sa.text("SELECT current_schema()")).scalar_one()
    if not isinstance(value, str) or not _SAFE_SCHEMA.fullmatch(value):
        raise RuntimeError("invalid_database_schema")
    return value


def _role_exists() -> bool:
    return bool(op.get_bind().execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
        {"role": _APPLICATION_ROLE},
    ).scalar_one())


def upgrade() -> None:
    schema = _target_schema()
    op.create_table(_TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="SET NULL")),
        sa.Column("relative_path", sa.Text(), nullable=False), sa.Column("original_name", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False), sa.Column("size", sa.BigInteger(), nullable=False), sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("source_tool", sa.Text(), nullable=False), sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('active','deleted')", name="ck_user_agent_artifacts_status"),
        sa.UniqueConstraint("owner_user_id", "agent_id", "relative_path", name="uq_user_agent_artifacts_path"),
    )
    op.create_index("ix_user_agent_artifacts_owner_agent_status", _TABLE, ["owner_user_id", "agent_id", "status", "created_at"])
    op.execute(f'ALTER TABLE "{_TABLE}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{_TABLE}" FORCE ROW LEVEL SECURITY')
    current_user = f'"{schema}".qwenpaw_current_user_id()'
    for action, clause in (("SELECT", "USING"), ("DELETE", "USING")):
        op.execute(f"CREATE POLICY user_agent_artifacts_{action.lower()} ON \"{_TABLE}\" FOR {action} {clause} (owner_user_id = {current_user})")
    op.execute(f"CREATE POLICY user_agent_artifacts_insert ON \"{_TABLE}\" FOR INSERT WITH CHECK (owner_user_id = {current_user})")
    op.execute(f"CREATE POLICY user_agent_artifacts_update ON \"{_TABLE}\" FOR UPDATE USING (owner_user_id = {current_user}) WITH CHECK (owner_user_id = {current_user})")
    if _role_exists():
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "{schema}"."{_TABLE}" TO "{_APPLICATION_ROLE}"')


def downgrade() -> None:
    if op.get_bind().execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {_TABLE})")).scalar_one():
        raise RuntimeError("artifact_lifecycle_data_prevents_downgrade")
    schema = _target_schema()
    if _role_exists():
        op.execute(f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE "{schema}"."{_TABLE}" FROM "{_APPLICATION_ROLE}"')
    op.drop_table(_TABLE)
