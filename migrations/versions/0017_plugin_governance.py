"""Constrain plugin lifecycle and application grant subjects."""

import re

import sqlalchemy as sa
from alembic import op

revision = "0017_plugin_governance"
down_revision = "0016_shared_app_publications"
branch_labels = None
depends_on = None


def _schema() -> str:
    schema = op.get_bind().execute(sa.text("SELECT current_schema()")).scalar_one()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise RuntimeError("invalid_database_schema")
    return schema


def upgrade() -> None:
    schema = _schema()
    op.create_check_constraint(
        "ck_plugin_installations_status",
        "plugin_installations",
        "status IN ('installing','active','disabled','uninstalling','failed')",
    )
    op.create_check_constraint(
        "ck_app_grants_subject_type",
        "app_grants",
        "subject_type IN ('all_members','user')",
    )
    op.create_check_constraint(
        "ck_app_grants_subject_id",
        "app_grants",
        "((subject_type = 'all_members' AND subject_id IS NULL) OR "
        "(subject_type = 'user' AND subject_id IS NOT NULL))",
    )
    op.create_index(
        "ix_app_grants_user_enabled",
        "app_grants",
        ["subject_id", "enabled", "plugin_installation_id"],
    )
    role_exists = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='qwenpaw_runtime')"
            )
        )
        .scalar_one()
    )
    if role_exists:
        op.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{schema}".plugin_installations, '
            f'"{schema}".plugin_capabilities, "{schema}".app_grants, '
            f'"{schema}".agent_plugin_settings, "{schema}".app_user_data '
            "TO qwenpaw_runtime"
        )


def downgrade() -> None:
    op.drop_index("ix_app_grants_user_enabled", table_name="app_grants")
    op.drop_constraint("ck_app_grants_subject_id", "app_grants", type_="check")
    op.drop_constraint("ck_app_grants_subject_type", "app_grants", type_="check")
    op.drop_constraint(
        "ck_plugin_installations_status",
        "plugin_installations",
        type_="check",
    )
