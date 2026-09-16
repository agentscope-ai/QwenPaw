"""将个人资料库改为用户与 Agent 双重隔离。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0020_agent_personal_library"
down_revision = "0019_user_account_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_library_documents", sa.Column("agent_id", UUID(as_uuid=True), nullable=True))
    op.execute(
        """
        UPDATE user_library_documents d
        SET agent_id = (
            SELECT g.agent_id
            FROM user_library_agent_grants g
            WHERE g.owner_user_id = d.owner_user_id AND g.status = 'active'
            ORDER BY g.created_at, g.agent_id
            LIMIT 1
        )
        """
    )
    orphan_count = op.get_bind().execute(
        sa.text("SELECT count(*) FROM user_library_documents WHERE agent_id IS NULL")
    ).scalar_one()
    if orphan_count:
        raise RuntimeError("personal_library_documents_without_active_agent")
    op.execute(
        """
        INSERT INTO user_library_documents (
            id, owner_user_id, agent_id, relative_path, name, media_type,
            size, sha256, created_at, updated_at
        )
        SELECT CAST(md5(d.id::text || g.agent_id::text) AS uuid),
               d.owner_user_id, g.agent_id, d.relative_path, d.name,
               d.media_type, d.size, d.sha256, d.created_at, d.updated_at
        FROM user_library_documents d
        JOIN user_library_agent_grants g ON g.owner_user_id = d.owner_user_id
        WHERE g.status = 'active' AND g.agent_id <> d.agent_id
        """
    )
    op.drop_index("ix_user_library_documents_owner_updated", table_name="user_library_documents")
    op.drop_constraint("uq_user_library_documents_owner_path", "user_library_documents", type_="unique")
    op.create_foreign_key(
        "fk_user_library_documents_agent",
        "user_library_documents",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("user_library_documents", "agent_id", nullable=False)
    op.create_unique_constraint(
        "uq_user_library_documents_owner_agent_path",
        "user_library_documents",
        ["owner_user_id", "agent_id", "relative_path"],
    )
    op.create_index(
        "ix_user_library_documents_owner_agent_updated",
        "user_library_documents",
        ["owner_user_id", "agent_id", sa.text("updated_at DESC")],
    )
    op.drop_table("user_library_agent_grants")


def downgrade() -> None:
    has_data = op.get_bind().execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM user_library_documents)")
    ).scalar_one()
    if has_data:
        raise RuntimeError("agent_scoped_personal_library_data_prevents_downgrade")
    op.create_table(
        "user_library_agent_grants",
        sa.Column("owner_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_user_library_agent_grants_status"),
        sa.UniqueConstraint("owner_user_id", "agent_id", name="uq_user_library_agent_grants_owner_agent"),
    )
    op.create_index("ix_user_library_agent_grants_owner_status", "user_library_agent_grants", ["owner_user_id", "status"])
    op.drop_index("ix_user_library_documents_owner_agent_updated", table_name="user_library_documents")
    op.drop_constraint("uq_user_library_documents_owner_agent_path", "user_library_documents", type_="unique")
    op.drop_constraint("fk_user_library_documents_agent", "user_library_documents", type_="foreignkey")
    op.drop_column("user_library_documents", "agent_id")
    op.create_unique_constraint("uq_user_library_documents_owner_path", "user_library_documents", ["owner_user_id", "relative_path"])
    op.create_index("ix_user_library_documents_owner_updated", "user_library_documents", ["owner_user_id", sa.text("updated_at DESC")])
