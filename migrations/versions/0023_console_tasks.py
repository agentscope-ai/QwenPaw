"""Durable dispatch metadata and user-isolated Console task contents."""
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0023_console_tasks"
down_revision = "0022_artifact_sample_answer"
branch_labels = None
depends_on = None


def upgrade():
    schema = op.get_bind().execute(sa.text("SELECT current_schema()")).scalar_one()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise RuntimeError("invalid_database_schema")
    op.create_table(
        "console_task_queue",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "owner_user_id", UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("state", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("claim", UUID()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("id", "owner_user_id"),
        sa.CheckConstraint("state IN ('pending','claimed','running','finished','interrupted')"),
    )
    op.create_index(
        "ix_console_task_dispatch", "console_task_queue", ["state", "lease_until", "created_at"]
    )
    op.create_index("ix_console_task_retention", "console_task_queue", ["finished_at"])
    op.create_table(
        "console_task_contents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("owner_user_id", UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["id", "owner_user_id"],
            ["console_task_queue.id", "console_task_queue.owner_user_id"],
            ondelete="CASCADE",
        ),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("parent_agent_id", sa.Text(), nullable=False),
        sa.Column("conversation_id", UUID(), nullable=False),
        sa.Column("parent_conversation_id", UUID(), nullable=False),
        sa.Column("run_id", UUID(), nullable=False),
        sa.Column("envelope", JSONB()),
        sa.Column("result", JSONB()),
    )
    op.execute("ALTER TABLE console_task_contents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE console_task_contents FORCE ROW LEVEL SECURITY")
    owned = f'owner_user_id = "{schema}".qwenpaw_current_user_id()'
    op.execute(
        f"CREATE POLICY console_task_owner ON console_task_contents USING ({owned}) WITH CHECK ({owned})"
    )
    role = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname='qwenpaw_runtime'"))
        .scalar()
    )
    if role:
        op.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON console_task_queue, console_task_contents TO qwenpaw_runtime"
        )


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS (SELECT 1 FROM console_task_queue)"))
        .scalar_one()
    ):
        raise RuntimeError("console_task_data_prevents_downgrade")
    op.drop_table("console_task_contents")
    op.drop_table("console_task_queue")
