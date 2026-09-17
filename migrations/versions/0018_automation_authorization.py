"""Constrain automation ownership, authorization and execution state."""

from alembic import op

revision = "0018_automation_authorization"
down_revision = "0017_plugin_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_automation_schedules_type",
        "automation_schedules",
        "type IN ('cron','once')",
    )
    op.create_check_constraint(
        "ck_automation_schedules_status",
        "automation_schedules",
        "status IN ('pending_authorization','active','paused',"
        "'authorization_revoked','failed')",
    )
    op.create_check_constraint(
        "ck_automation_schedules_config_version",
        "automation_schedules",
        "config_version >= 1",
    )
    op.create_check_constraint(
        "ck_automation_executions_status",
        "automation_executions",
        "status IN ('success','error','running','skipped','cancelled')",
    )
    op.create_index(
        "ix_automation_schedules_agent_owner_status",
        "automation_schedules",
        ["agent_id", "automation_owner_user_id", "status"],
    )
    op.create_index(
        "ix_automation_grants_schedule_active",
        "automation_grants",
        ["schedule_id", "revoked_at", "expires_at"],
    )
    op.create_index(
        "ix_automation_executions_schedule_started",
        "automation_executions",
        ["schedule_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_automation_executions_schedule_started",
        table_name="automation_executions",
    )
    op.drop_index(
        "ix_automation_grants_schedule_active",
        table_name="automation_grants",
    )
    op.drop_index(
        "ix_automation_schedules_agent_owner_status",
        table_name="automation_schedules",
    )
    op.drop_constraint(
        "ck_automation_executions_status",
        "automation_executions",
        type_="check",
    )
    op.drop_constraint(
        "ck_automation_schedules_config_version",
        "automation_schedules",
        type_="check",
    )
    op.drop_constraint(
        "ck_automation_schedules_status",
        "automation_schedules",
        type_="check",
    )
    op.drop_constraint(
        "ck_automation_schedules_type",
        "automation_schedules",
        type_="check",
    )
