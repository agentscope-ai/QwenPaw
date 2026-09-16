"""Lock shared-app publications and bind conversations to a version."""

import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0016_shared_app_publications"
down_revision = "0015_skill_governance"
branch_labels = None
depends_on = None


def _schema() -> str:
    schema = op.get_bind().execute(sa.text("SELECT current_schema()")).scalar_one()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise RuntimeError("invalid_database_schema")
    return schema


def upgrade():
    schema = _schema()
    op.create_check_constraint(
        "ck_shared_apps_status",
        "shared_apps",
        "status IN ('draft','active','retired')",
    )
    op.create_check_constraint(
        "ck_shared_apps_active_pointer",
        "shared_apps",
        "(status = 'active') = (current_publication_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_shared_app_publications_review_status",
        "shared_app_publications",
        "review_status IN ('pending','approved','rejected')",
    )
    op.create_check_constraint(
        "ck_shared_app_user_workspaces_status",
        "shared_app_user_workspaces",
        "status IN ('initializing','active','failed')",
    )
    op.add_column("shared_app_publications", sa.Column("review_note", sa.Text()))
    op.add_column(
        "shared_app_publications",
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
    )
    op.create_unique_constraint(
        "uq_shared_app_publications_id_app",
        "shared_app_publications",
        ["id", "shared_app_id"],
    )
    op.drop_constraint(
        "fk_shared_apps_current_publication", "shared_apps", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_shared_apps_current_publication",
        "shared_apps",
        "shared_app_publications",
        ["current_publication_id", "id"],
        ["id", "shared_app_id"],
    )
    op.add_column("conversations", sa.Column("shared_app_id", UUID()))
    op.add_column("conversations", sa.Column("publication_id", UUID()))
    op.create_foreign_key(
        "fk_conversations_shared_app",
        "conversations",
        "shared_apps",
        ["shared_app_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_conversations_publication_app",
        "conversations",
        "shared_app_publications",
        ["publication_id", "shared_app_id"],
        ["id", "shared_app_id"],
    )
    op.create_foreign_key(
        "fk_shared_app_user_workspaces_publication_app",
        "shared_app_user_workspaces",
        "shared_app_publications",
        ["publication_id", "shared_app_id"],
        ["id", "shared_app_id"],
    )
    op.create_check_constraint(
        "ck_conversations_shared_publication_pair",
        "conversations",
        "(shared_app_id IS NULL) = (publication_id IS NULL)",
    )
    op.create_index(
        "ix_conversations_owner_publication_updated",
        "conversations",
        ["owner_user_id", "publication_id", "updated_at"],
    )
    op.execute(
        f'''
        CREATE FUNCTION "{schema}".prevent_shared_app_publication_immutable_update()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.shared_app_id IS DISTINCT FROM OLD.shared_app_id
             OR NEW.version IS DISTINCT FROM OLD.version
             OR NEW.immutable_manifest IS DISTINCT FROM OLD.immutable_manifest
             OR NEW.baseline_workspace_key IS DISTINCT FROM OLD.baseline_workspace_key
             OR NEW.submitted_by IS DISTINCT FROM OLD.submitted_by THEN
            RAISE EXCEPTION 'shared_app_publication_immutable';
          END IF;
          RETURN NEW;
        END;
        $$
        '''
    )
    op.execute(
        f'''
        CREATE FUNCTION "{schema}".prevent_conversation_publication_rebind()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.publication_id IS NOT NULL AND
             (NEW.publication_id IS DISTINCT FROM OLD.publication_id OR
              NEW.shared_app_id IS DISTINCT FROM OLD.shared_app_id) THEN
            RAISE EXCEPTION 'conversation_publication_immutable';
          END IF;
          RETURN NEW;
        END;
        $$
        '''
    )
    op.execute(
        f'''
        CREATE TRIGGER trg_conversation_publication_immutable
        BEFORE UPDATE ON "{schema}".conversations
        FOR EACH ROW EXECUTE FUNCTION "{schema}".prevent_conversation_publication_rebind()
        '''
    )
    op.execute(
        f'''
        CREATE TRIGGER trg_shared_app_publication_immutable
        BEFORE UPDATE ON "{schema}".shared_app_publications
        FOR EACH ROW EXECUTE FUNCTION "{schema}".prevent_shared_app_publication_immutable_update()
        '''
    )
    role_exists = op.get_bind().execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='qwenpaw_runtime')")
    ).scalar_one()
    if role_exists:
        op.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{schema}".shared_apps, '
            f'"{schema}".shared_app_drafts, "{schema}".shared_app_publications, '
            f'"{schema}".shared_app_user_workspaces TO qwenpaw_runtime'
        )


def downgrade():
    schema = _schema()
    has_new_data = op.get_bind().execute(
        sa.text(
            f'SELECT EXISTS (SELECT 1 FROM "{schema}".conversations '
            "WHERE publication_id IS NOT NULL) OR EXISTS "
            f'(SELECT 1 FROM "{schema}".shared_app_publications '
            "WHERE review_note IS NOT NULL OR reviewed_at IS NOT NULL)"
        )
    ).scalar_one()
    if has_new_data:
        raise RuntimeError("shared_app_publication_data_prevents_downgrade")
    op.execute(
        f'DROP TRIGGER trg_shared_app_publication_immutable '
        f'ON "{schema}".shared_app_publications'
    )
    op.execute(
        f'DROP TRIGGER trg_conversation_publication_immutable '
        f'ON "{schema}".conversations'
    )
    op.execute(
        f'DROP FUNCTION "{schema}".prevent_conversation_publication_rebind()'
    )
    op.execute(
        f'DROP FUNCTION "{schema}".prevent_shared_app_publication_immutable_update()'
    )
    op.drop_index(
        "ix_conversations_owner_publication_updated",
        table_name="conversations",
    )
    op.drop_constraint(
        "ck_conversations_shared_publication_pair",
        "conversations",
        type_="check",
    )
    op.drop_constraint(
        "fk_conversations_publication_app", "conversations", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_shared_app_user_workspaces_publication_app",
        "shared_app_user_workspaces",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_conversations_shared_app", "conversations", type_="foreignkey"
    )
    op.drop_column("conversations", "publication_id")
    op.drop_column("conversations", "shared_app_id")
    op.drop_constraint(
        "fk_shared_apps_current_publication", "shared_apps", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_shared_apps_current_publication",
        "shared_apps",
        "shared_app_publications",
        ["current_publication_id"],
        ["id"],
    )
    op.drop_constraint(
        "uq_shared_app_publications_id_app",
        "shared_app_publications",
        type_="unique",
    )
    op.drop_column("shared_app_publications", "reviewed_at")
    op.drop_column("shared_app_publications", "review_note")
    op.drop_constraint(
        "ck_shared_app_user_workspaces_status",
        "shared_app_user_workspaces",
        type_="check",
    )
    op.drop_constraint(
        "ck_shared_app_publications_review_status",
        "shared_app_publications",
        type_="check",
    )
    op.drop_constraint("ck_shared_apps_status", "shared_apps", type_="check")
    op.drop_constraint(
        "ck_shared_apps_active_pointer", "shared_apps", type_="check"
    )
