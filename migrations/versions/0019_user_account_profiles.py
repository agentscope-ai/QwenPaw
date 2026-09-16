"""Add enterprise profile fields to platform users."""

import sqlalchemy as sa
from alembic import op

revision = "0019_user_account_profiles"
down_revision = "0018_automation_authorization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(128), nullable=True))
    op.add_column("users", sa.Column("email", sa.String(254), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("department", sa.String(128), nullable=True))
    op.add_column("users", sa.Column("job_title", sa.String(128), nullable=True))
    op.add_column("users", sa.Column("remark", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "remark")
    op.drop_column("users", "job_title")
    op.drop_column("users", "department")
    op.drop_column("users", "phone")
    op.drop_column("users", "email")
    op.drop_column("users", "display_name")
