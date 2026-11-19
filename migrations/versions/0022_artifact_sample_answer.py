"""Remember the user's answer for an immutable sample artifact."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0022_artifact_sample_answer"
down_revision = "0021_skill_public_admin_read"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user_agent_artifacts", sa.Column("sample_answer", JSONB()))


def downgrade():
    op.drop_column("user_agent_artifacts", "sample_answer")
