"""Keep owned conversation reads independent of Agent soft deletion."""

import re

from alembic import op
import sqlalchemy as sa

revision = "0024_owner_history_durability"
down_revision = "0023_console_tasks"
branch_labels = None
depends_on = None


def _replace_read_helper(*, preserve_owned: bool) -> None:
    schema = op.get_bind().execute(sa.text("SELECT current_schema()")).scalar_one()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise RuntimeError("invalid_database_schema")
    # Viewer membership, active-user checks and deleted-chat checks stay intact.
    agent_gate = "" if preserve_owned else "AND a.status <> 'deleted'"
    viewer_gate = "a.status = 'active'" if preserve_owned else "a.status <> 'deleted'"
    op.execute(f"""
        CREATE OR REPLACE FUNCTION "{schema}".qwenpaw_can_read_conversation(target_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $qwenpaw$
            SELECT EXISTS (
                SELECT 1
                FROM "{schema}".conversations c
                JOIN "{schema}".users u
                    ON u.id = "{schema}".qwenpaw_current_user_id()
                    AND u.status = 'active'
                JOIN "{schema}".agents a ON a.id = c.agent_id
                LEFT JOIN "{schema}".conversation_members cm
                    ON cm.conversation_id = c.id AND cm.user_id = u.id
                    AND cm.role = 'viewer'
                LEFT JOIN "{schema}".agent_members am
                    ON am.agent_id = a.id AND am.user_id = u.id
                    AND am.revoked_at IS NULL
                WHERE c.id = target_id AND c.status <> 'deleted'
                    {agent_gate}
                    AND (
                        c.owner_user_id = u.id
                        OR (
                            {viewer_gate}
                            AND cm.user_id IS NOT NULL
                            AND (
                                a.owner_user_id = u.id
                                OR a.visibility = 'public'
                                OR am.user_id IS NOT NULL
                            )
                        )
                    )
            )
        $qwenpaw$
    """)


def _replace_write_helper(*, require_live_access: bool) -> None:
    schema = op.get_bind().execute(sa.text("SELECT current_schema()")).scalar_one()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise RuntimeError("invalid_database_schema")
    live_gate = (
        f"""
        AND EXISTS (
            SELECT 1 FROM "{schema}".agents a
            WHERE a.id = c.agent_id AND a.status = 'active'
                AND (
                    a.owner_user_id = u.id OR a.visibility = 'public'
                    OR EXISTS (
                        SELECT 1 FROM "{schema}".agent_members am
                        WHERE am.agent_id = a.id AND am.user_id = u.id
                            AND am.revoked_at IS NULL
                    )
                )
        )
    """
        if require_live_access
        else ""
    )
    op.execute(f"""
        CREATE OR REPLACE FUNCTION "{schema}".qwenpaw_can_write_conversation(target_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $qwenpaw$
            SELECT EXISTS (
                SELECT 1 FROM "{schema}".conversations c
                JOIN "{schema}".users u
                    ON u.id = "{schema}".qwenpaw_current_user_id()
                    AND u.status = 'active'
                WHERE c.id = target_id AND c.status <> 'deleted'
                    AND c.owner_user_id = u.id
                    {live_gate}
            )
        $qwenpaw$
    """)


def upgrade() -> None:
    _replace_read_helper(preserve_owned=True)
    _replace_write_helper(require_live_access=True)


def downgrade() -> None:
    _replace_read_helper(preserve_owned=False)
    _replace_write_helper(require_live_access=False)
