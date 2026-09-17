"""Persist Agent skill grants and immutable publication submissions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0015_skill_governance"
down_revision = "0014_artifact_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "skill_pool_agent_grants",
        sa.Column(
            "skill_id", UUID(), sa.ForeignKey("skill_pool_items.id"), primary_key=True
        ),
        sa.Column("agent_id", UUID(), sa.ForeignKey("agents.id"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("changed_by", UUID(), sa.ForeignKey("users.id"), nullable=False),
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
    )
    for column in [
        sa.Column("snapshot_key", sa.Text()),
        sa.Column("content_hash", sa.String(128)),
        sa.Column("skill_name", sa.String(256)),
        sa.Column("review_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "published_version_id", UUID(), sa.ForeignKey("skill_pool_versions.id")
        ),
    ]:
        op.add_column("skill_publish_requests", column)
    schema = op.get_bind().execute(sa.text("SELECT current_schema()")).scalar_one()
    import re

    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise RuntimeError("invalid_database_schema")
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='qwenpaw_runtime')"
            )
        )
        .scalar_one()
    ):
        op.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{schema}".skill_pool_agent_grants TO qwenpaw_runtime'
        )


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM skill_pool_agent_grants) OR EXISTS (SELECT 1 FROM skill_publish_requests WHERE snapshot_key IS NOT NULL)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("skill_governance_data_prevents_downgrade")
    for name in [
        "published_version_id",
        "review_version",
        "skill_name",
        "content_hash",
        "snapshot_key",
    ]:
        op.drop_column("skill_publish_requests", name)
    op.drop_table("skill_pool_agent_grants")
