# -*- coding: utf-8 -*-
"""Add read-only conversation sharing constraints and row isolation."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import re

revision = "0009_conversation_sharing_rls"
down_revision = "0008_agent_user_workspaces"
branch_labels = None
depends_on = None

_DIRECT_TABLES = (
    "conversations",
    "conversation_members",
    "runs",
    "messages",
    "attachments",
    "approval_requests",
)
_RUN_TABLES = ("run_events", "tool_calls")
_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _target_schema() -> str:
    value = op.get_bind().execute(sa.text("SELECT current_schema()")).scalar_one()
    if not isinstance(value, str) or not _SAFE_SCHEMA.fullmatch(value):
        raise RuntimeError("invalid_database_schema")
    return value


def _create_helpers(schema: str) -> None:
    conversations = f'"{schema}"."conversations"'
    users = f'"{schema}"."users"'
    agents = f'"{schema}"."agents"'
    members = f'"{schema}"."conversation_members"'
    agent_members = f'"{schema}"."agent_members"'
    runs = f'"{schema}"."runs"'
    op.execute(
        f"""
        CREATE FUNCTION "{schema}".qwenpaw_current_user_id() RETURNS uuid
        LANGUAGE plpgsql STABLE AS $$
        DECLARE
            raw_user_id text;
        BEGIN
            raw_user_id := current_setting('qwenpaw.user_id', true);
            IF raw_user_id IS NULL OR raw_user_id = '' THEN
                RETURN NULL;
            END IF;
            RETURN raw_user_id::uuid;
        EXCEPTION WHEN invalid_text_representation THEN
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION "{schema}".qwenpaw_can_read_conversation(target_id uuid)
        RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $qwenpaw$
            SELECT EXISTS (
                SELECT 1
                FROM {conversations} c
                JOIN {users} u ON u.id = "{schema}".qwenpaw_current_user_id()
                    AND u.status = 'active'
                JOIN {agents} a ON a.id = c.agent_id
                    AND a.status <> 'deleted'
                LEFT JOIN {members} cm
                    ON cm.conversation_id = c.id
                    AND cm.user_id = u.id
                    AND cm.role = 'viewer'
                LEFT JOIN {agent_members} am
                    ON am.agent_id = a.id
                    AND am.user_id = u.id
                    AND am.revoked_at IS NULL
                WHERE c.id = target_id
                    AND c.status <> 'deleted'
                    AND (
                        c.owner_user_id = u.id
                        OR (
                            cm.user_id IS NOT NULL
                            AND (
                                a.owner_user_id = u.id
                                OR a.visibility = 'public'
                                OR am.user_id IS NOT NULL
                            )
                        )
                    )
            )
        $qwenpaw$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION "{schema}".qwenpaw_can_write_conversation(target_id uuid)
        RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $qwenpaw$
            SELECT EXISTS (
                SELECT 1
                FROM {conversations} c
                JOIN {users} u ON u.id = "{schema}".qwenpaw_current_user_id()
                    AND u.status = 'active'
                WHERE c.id = target_id
                    AND c.status <> 'deleted'
                    AND c.owner_user_id = u.id
            )
        $qwenpaw$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION "{schema}".qwenpaw_can_read_run(target_id uuid)
        RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $qwenpaw$
            SELECT EXISTS (
                SELECT 1 FROM {runs} r
                WHERE r.id = target_id
                    AND "{schema}".qwenpaw_can_read_conversation(r.conversation_id)
            )
        $qwenpaw$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION "{schema}".qwenpaw_can_write_run(target_id uuid)
        RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $qwenpaw$
            SELECT EXISTS (
                SELECT 1 FROM {runs} r
                WHERE r.id = target_id
                    AND "{schema}".qwenpaw_can_write_conversation(r.conversation_id)
            )
        $qwenpaw$
        """
    )


def _enable_rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')


def upgrade() -> None:
    schema = _target_schema()
    op.create_check_constraint(
        "ck_conversation_members_role",
        "conversation_members",
        "role = 'viewer'",
    )
    op.create_index(
        "ix_conversation_members_user_conversation",
        "conversation_members",
        ["user_id", "conversation_id"],
    )
    _create_helpers(schema)

    for table in (*_DIRECT_TABLES, *_RUN_TABLES):
        _enable_rls(table)

    op.execute(
        f'CREATE POLICY conversations_select ON "conversations" FOR SELECT '
        f'USING ("{schema}".qwenpaw_can_read_conversation(id))'
    )
    op.execute(
        "CREATE POLICY conversations_insert ON conversations FOR INSERT "
        f'WITH CHECK (owner_user_id = "{schema}".qwenpaw_current_user_id())'
    )
    op.execute(
        "CREATE POLICY conversations_update ON conversations FOR UPDATE "
        f'USING ("{schema}".qwenpaw_can_write_conversation(id)) '
        f'WITH CHECK (owner_user_id = "{schema}".qwenpaw_current_user_id())'
    )
    op.execute(
        "CREATE POLICY conversations_delete ON conversations FOR DELETE "
        f'USING ("{schema}".qwenpaw_can_write_conversation(id))'
    )

    op.execute(
        "CREATE POLICY conversation_members_select ON conversation_members "
        f'FOR SELECT USING ("{schema}".qwenpaw_can_write_conversation(conversation_id) '
        f'OR user_id = "{schema}".qwenpaw_current_user_id())'
    )
    op.execute(
        "CREATE POLICY conversation_members_insert ON conversation_members "
        f'FOR INSERT WITH CHECK (role = \'viewer\' AND '
        f'"{schema}".qwenpaw_can_write_conversation(conversation_id) AND '
        f'user_id <> "{schema}".qwenpaw_current_user_id())'
    )
    op.execute(
        "CREATE POLICY conversation_members_delete ON conversation_members "
        f'FOR DELETE USING ("{schema}".qwenpaw_can_write_conversation(conversation_id))'
    )

    for table in ("runs", "messages", "attachments"):
        op.execute(
            f'CREATE POLICY {table}_select ON "{table}" FOR SELECT '
            f'USING ("{schema}".qwenpaw_can_read_conversation(conversation_id))'
        )
        op.execute(
            f'CREATE POLICY {table}_write ON "{table}" FOR ALL '
            f'USING ("{schema}".qwenpaw_can_write_conversation(conversation_id)) '
            f'WITH CHECK ("{schema}".qwenpaw_can_write_conversation(conversation_id))'
        )

    op.execute(
        "CREATE POLICY approval_requests_select ON approval_requests FOR SELECT "
        "USING ((conversation_id IS NOT NULL AND "
        f'"{schema}".qwenpaw_can_read_conversation(conversation_id)) OR '
        "(conversation_id IS NULL AND "
        f'approval_user_id = "{schema}".qwenpaw_current_user_id()))'
    )
    op.execute(
        "CREATE POLICY approval_requests_write ON approval_requests FOR ALL "
        "USING ((conversation_id IS NOT NULL AND "
        f'"{schema}".qwenpaw_can_write_conversation(conversation_id)) OR '
        "(conversation_id IS NULL AND "
        f'approval_user_id = "{schema}".qwenpaw_current_user_id())) '
        "WITH CHECK ((conversation_id IS NOT NULL AND "
        "qwenpaw_can_write_conversation(conversation_id)) OR "
        "(conversation_id IS NULL AND "
        "approval_user_id = qwenpaw_current_user_id()))"
    )

    for table in _RUN_TABLES:
        op.execute(
            f'CREATE POLICY {table}_select ON "{table}" FOR SELECT '
            f'USING ("{schema}".qwenpaw_can_read_run(run_id))'
        )
        op.execute(
            f'CREATE POLICY {table}_write ON "{table}" FOR ALL '
            f'USING ("{schema}".qwenpaw_can_write_run(run_id)) '
            f'WITH CHECK ("{schema}".qwenpaw_can_write_run(run_id))'
        )


def downgrade() -> None:
    policy_names = {
        "conversations": (
            "conversations_select",
            "conversations_insert",
            "conversations_update",
            "conversations_delete",
        ),
        "conversation_members": (
            "conversation_members_select",
            "conversation_members_insert",
            "conversation_members_delete",
        ),
        "runs": ("runs_select", "runs_write"),
        "messages": ("messages_select", "messages_write"),
        "attachments": ("attachments_select", "attachments_write"),
        "approval_requests": (
            "approval_requests_select",
            "approval_requests_write",
        ),
        "run_events": ("run_events_select", "run_events_write"),
        "tool_calls": ("tool_calls_select", "tool_calls_write"),
    }
    for table, names in policy_names.items():
        for name in names:
            op.execute(f'DROP POLICY IF EXISTS "{name}" ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')

    schema = _target_schema()
    for signature in (
        "qwenpaw_can_write_run(uuid)",
        "qwenpaw_can_read_run(uuid)",
        "qwenpaw_can_write_conversation(uuid)",
        "qwenpaw_can_read_conversation(uuid)",
        "qwenpaw_current_user_id()",
    ):
        op.execute(f'DROP FUNCTION IF EXISTS "{schema}".{signature}')
    op.drop_index(
        "ix_conversation_members_user_conversation",
        table_name="conversation_members",
    )
    op.drop_constraint(
        "ck_conversation_members_role",
        "conversation_members",
        type_="check",
    )
