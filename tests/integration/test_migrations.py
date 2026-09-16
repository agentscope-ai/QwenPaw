# -*- coding: utf-8 -*-
"""Alembic schema contract and disposable PostgreSQL migration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_REVISIONS = (
    "0001_identity_access",
    "0002_agent_conversation",
    "0003_governance_operations",
    "0004_identity_sessions",
    "0005_agent_public_visibility",
    "0006_user_channel_bindings",
    "0007_agent_history_access",
    "0008_agent_user_workspaces",
    "0009_conversation_sharing_rls",
    "0010_runtime_workspace_grants",
    "0011_attachment_scope",
    "0012_attachment_lifecycle",
    "0013_user_personal_library",
    "0014_artifact_lifecycle",
    "0015_skill_governance",
    "0016_shared_app_publications",
    "0017_plugin_governance",
    "0018_automation_authorization",
    "0019_user_account_profiles",
    "0020_agent_personal_library",
)
EXPECTED_TABLES = frozenset(
    {
        "agent_config_revisions",
        "agent_drivers",
        "agent_members",
        "agent_history_access",
        "agent_plugin_settings",
        "agent_skills",
        "agent_user_workspaces",
        "agents",
        "app_grants",
        "app_user_data",
        "approval_requests",
        "attachments",
        "audit_logs",
        "automation_executions",
        "automation_grants",
        "automation_schedules",
        "backup_artifacts",
        "backup_operations",
        "channel_access_rules",
        "channel_bindings",
        "channel_external_identities",
        "conversation_members",
        "conversations",
        "credential_bindings",
        "credential_records",
        "driver_revisions",
        "external_identities",
        "mcp_oauth_sessions",
        "messages",
        "model_grants",
        "model_providers",
        "models",
        "notification_receipts",
        "notifications",
        "plugin_capabilities",
        "plugin_installations",
        "run_events",
        "runs",
        "security_events",
        "security_policies",
        "shared_app_drafts",
        "shared_app_publications",
        "shared_app_user_workspaces",
        "shared_apps",
        "skill_pool_items",
        "skill_pool_agent_grants",
        "skill_pool_versions",
        "skill_publish_requests",
        "system_setting_revisions",
        "system_settings",
        "tool_calls",
        "usage_records",
        "user_agent_preferences",
        "user_library_documents",
        "user_agent_artifacts",
        "user_preferences",
        "user_sessions",
        "users",
    }
)


def _alembic_config(postgres_test_schema=None) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    if postgres_test_schema is not None:
        config.set_main_option(
            "sqlalchemy.url",
            postgres_test_schema.async_url(),
        )
        config.attributes["target_schema"] = postgres_test_schema.name
    return config


def _schema_tables(admin, schema: str) -> set[str]:
    rows = admin.execute(
        "SELECT tablename FROM pg_tables "
        f"WHERE schemaname = '{schema}' ORDER BY tablename",
    )
    return {row for row in rows.splitlines() if row}


def _column_is_nullable(admin, schema: str, table: str, column: str) -> bool:
    return (
        admin.execute(
            "SELECT is_nullable FROM information_schema.columns "
            f"WHERE table_schema = '{schema}' AND table_name = '{table}' "
            f"AND column_name = '{column}'",
        )
        == "YES"
    )


def _table_columns(admin, schema: str, table: str) -> set[str]:
    rows = admin.execute(
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_schema = '{schema}' AND table_name = '{table}' "
        "ORDER BY column_name",
    )
    return {row for row in rows.splitlines() if row}


def _check_constraint(admin, schema: str, name: str) -> str:
    return admin.execute(
        "SELECT pg_get_constraintdef(c.oid) "
        "FROM pg_constraint c "
        "JOIN pg_namespace n ON n.oid = c.connamespace "
        f"WHERE n.nspname = '{schema}' AND c.conname = '{name}'",
    )


def _column_definitions(admin, schema: str, table: str) -> dict[str, tuple[str, ...]]:
    rows = admin.execute(
        "SELECT column_name,udt_name,is_nullable,"
        "coalesce(character_maximum_length::text,''),coalesce(column_default,'') "
        "FROM information_schema.columns "
        f"WHERE table_schema='{schema}' AND table_name='{table}' ORDER BY column_name"
    )
    return {
        parts[0]: tuple(parts[1:])
        for row in rows.splitlines()
        if (parts := row.split("|"))
    }


def _foreign_keys(admin, schema: str, table: str) -> set[str]:
    rows = admin.execute(
        "SELECT a.attname,r.relname,b.attname "
        "FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid "
        "JOIN pg_namespace n ON n.oid=t.relnamespace "
        "JOIN pg_class r ON r.oid=c.confrelid "
        "JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=c.conkey[1] "
        "JOIN pg_attribute b ON b.attrelid=r.oid AND b.attnum=c.confkey[1] "
        f"WHERE n.nspname='{schema}' AND t.relname='{table}' AND c.contype='f'"
    )
    return set(rows.splitlines())


def _rls_enabled(admin, schema: str, table: str) -> tuple[str, str]:
    row = admin.execute(
        "SELECT relrowsecurity::text || '|' || relforcerowsecurity::text "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        f"WHERE n.nspname = '{schema}' AND c.relname = '{table}'",
    )
    enabled, forced = row.split("|", 1)
    return enabled, forced


def _role_exists(admin, role: str) -> bool:
    return (
        admin.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_roles "
            f"WHERE rolname = '{role}')",
        )
        == "t"
    )


def _table_privileges(
    admin,
    schema: str,
    table: str,
    role: str,
) -> set[str]:
    rows = admin.execute(
        "SELECT privilege_type FROM information_schema.role_table_grants "
        f"WHERE table_schema = '{schema}' AND table_name = '{table}' "
        f"AND grantee = '{role}' ORDER BY privilege_type",
    )
    return {row for row in rows.splitlines() if row}


def test_revision_chain_is_linear_and_named_by_domain() -> None:
    """The complete reviewed revision sequence has one linear head."""
    script = ScriptDirectory.from_config(_alembic_config())
    revisions = tuple(reversed(tuple(script.walk_revisions())))

    assert tuple(revision.revision for revision in revisions) == (EXPECTED_REVISIONS)
    assert tuple(revision.down_revision for revision in revisions) == (
        None,
        *EXPECTED_REVISIONS[:-1],
    )
    assert script.get_current_head() == EXPECTED_REVISIONS[-1]


@pytest.mark.integration
def test_empty_schema_upgrade_repeat_and_downgrade(
    postgres_test_schema,
) -> None:
    """The complete schema must be reversible and repeatable in isolation."""
    from postgres import DockerPostgresAdmin

    admin = DockerPostgresAdmin(postgres_test_schema.config)
    config = _alembic_config(postgres_test_schema)

    command.upgrade(config, "head")
    assert _schema_tables(admin, postgres_test_schema.name) == (
        EXPECTED_TABLES | {"alembic_version"}
    )
    schema = postgres_test_schema.name
    user_columns = _column_definitions(admin, schema, "users")
    assert {
        name: user_columns[name]
        for name in (
            "display_name",
            "email",
            "phone",
            "department",
            "job_title",
            "remark",
        )
    } == {
        "display_name": ("varchar", "YES", "128", ""),
        "email": ("varchar", "YES", "254", ""),
        "phone": ("varchar", "YES", "32", ""),
        "department": ("varchar", "YES", "128", ""),
        "job_title": ("varchar", "YES", "128", ""),
        "remark": ("varchar", "YES", "500", ""),
    }
    library_columns = _column_definitions(admin, schema, "user_library_documents")
    assert library_columns["agent_id"] == ("uuid", "NO", "", "")
    assert _column_definitions(admin, schema, "skill_pool_agent_grants") == {
        "skill_id": ("uuid", "NO", "", ""),
        "agent_id": ("uuid", "NO", "", ""),
        "enabled": ("bool", "NO", "", "false"),
        "changed_by": ("uuid", "NO", "", ""),
        "created_at": ("timestamptz", "NO", "", "now()"),
        "updated_at": ("timestamptz", "NO", "", "now()"),
    }
    assert (
        _check_constraint(admin, schema, "skill_pool_agent_grants_pkey")
        == "PRIMARY KEY (skill_id, agent_id)"
    )
    assert _foreign_keys(admin, schema, "skill_pool_agent_grants") == {
        "skill_id|skill_pool_items|id",
        "agent_id|agents|id",
        "changed_by|users|id",
    }
    assert _table_columns(admin, schema, "skill_publish_requests") == {
        "id",
        "agent_skill_id",
        "submitted_by",
        "status",
        "reviewed_by",
        "review_note",
        "created_at",
        "reviewed_at",
        "snapshot_key",
        "content_hash",
        "skill_name",
        "review_version",
        "published_version_id",
    }
    request_columns = _column_definitions(admin, schema, "skill_publish_requests")
    expected_new_columns = {
        "snapshot_key": ("text", "YES", "", ""),
        "content_hash": ("varchar", "YES", "128", ""),
        "skill_name": ("varchar", "YES", "256", ""),
        "review_version": ("int4", "NO", "", "0"),
        "published_version_id": ("uuid", "YES", "", ""),
    }
    assert {
        name: request_columns[name] for name in expected_new_columns
    } == expected_new_columns
    assert _foreign_keys(admin, schema, "skill_publish_requests") == {
        "agent_skill_id|agent_skills|id",
        "submitted_by|users|id",
        "reviewed_by|users|id",
        "published_version_id|skill_pool_versions|id",
    }
    assert _column_is_nullable(
        admin,
        postgres_test_schema.name,
        "model_grants",
        "subject_id",
    )
    assert _column_is_nullable(
        admin,
        postgres_test_schema.name,
        "app_grants",
        "subject_id",
    )
    assert {
        "access_token_hash",
        "access_expires_at",
        "last_seen_at",
    }.issubset(
        _table_columns(
            admin,
            postgres_test_schema.name,
            "user_sessions",
        )
    )
    assert "'public'" in _check_constraint(
        admin,
        postgres_test_schema.name,
        "ck_agents_visibility",
    )
    assert _table_columns(admin, schema, "shared_app_publications").issuperset(
        {"review_note", "reviewed_at"}
    )
    assert _table_columns(admin, schema, "conversations").issuperset(
        {"shared_app_id", "publication_id"}
    )
    assert "publication_id IS NULL" in _check_constraint(
        admin, schema, "ck_conversations_shared_publication_pair"
    )
    assert "'active'" in _check_constraint(
        admin, schema, "ck_shared_apps_status"
    )
    assert "'approved'" in _check_constraint(
        admin, schema, "ck_shared_app_publications_review_status"
    )
    assert "'initializing'" in _check_constraint(
        admin, schema, "ck_shared_app_user_workspaces_status"
    )
    assert "'uninstalling'" in _check_constraint(
        admin, schema, "ck_plugin_installations_status"
    )
    assert "'all_members'" in _check_constraint(
        admin, schema, "ck_app_grants_subject_type"
    )
    assert "subject_id IS NULL" in _check_constraint(
        admin, schema, "ck_app_grants_subject_id"
    )
    assert not _column_is_nullable(
        admin,
        postgres_test_schema.name,
        "channel_bindings",
        "owner_user_id",
    )
    channel_binding_owner_constraint = _check_constraint(
        admin,
        postgres_test_schema.name,
        "uq_channel_bindings_agent_owner_type",
    )
    assert "agent_id" in channel_binding_owner_constraint
    assert "owner_user_id" in channel_binding_owner_constraint
    assert "channel_type" in channel_binding_owner_constraint
    assert {
        "agent_id",
        "user_id",
        "first_chat_created_at",
        "last_chat_created_at",
    } == _table_columns(
        admin,
        postgres_test_schema.name,
        "agent_history_access",
    )
    assert "viewer" in _check_constraint(
        admin,
        postgres_test_schema.name,
        "ck_conversation_members_role",
    )
    assert {
        "agent_id",
        "original_name",
        "lifecycle",
        "saved_path",
        "saved_at",
        "deleted_at",
        "updated_at",
    }.issubset(
        _table_columns(
            admin,
            postgres_test_schema.name,
            "attachments",
        )
    )
    assert _column_is_nullable(
        admin,
        postgres_test_schema.name,
        "attachments",
        "conversation_id",
    )
    for table in (
        "conversations",
        "conversation_members",
        "runs",
        "messages",
        "run_events",
        "tool_calls",
        "attachments",
        "approval_requests",
    ):
        assert _rls_enabled(
            admin,
            postgres_test_schema.name,
            table,
        ) == ("true", "true")
    if _role_exists(admin, "qwenpaw_runtime"):
        expected_privileges = {"SELECT", "INSERT", "UPDATE", "DELETE"}
        for table in (
            "agent_history_access",
            "agent_user_workspaces",
            "skill_pool_agent_grants",
            "shared_apps",
            "shared_app_drafts",
            "shared_app_publications",
            "shared_app_user_workspaces",
        ):
            assert _table_privileges(
                admin,
                postgres_test_schema.name,
                table,
                "qwenpaw_runtime",
            ) == expected_privileges
    command.upgrade(config, "head")
    assert (
        admin.execute(
            f'SELECT version_num FROM "{postgres_test_schema.name}".alembic_version',
        )
        == EXPECTED_REVISIONS[-1]
    )

    command.downgrade(config, "base")
    assert _schema_tables(admin, postgres_test_schema.name) == {"alembic_version"}
    assert (
        admin.execute(
            f'SELECT count(*) FROM "{postgres_test_schema.name}".alembic_version',
        )
        == "0"
    )


@pytest.mark.integration
def test_attachment_scope_migration_backfills_existing_rows(
    postgres_test_schema,
) -> None:
    """0011 must preserve old attachments and derive their Agent/name metadata."""
    from postgres import DockerPostgresAdmin

    admin = DockerPostgresAdmin(postgres_test_schema.config)
    config = _alembic_config(postgres_test_schema)
    schema = postgres_test_schema.name
    user_id = "11111111-1111-4111-8111-111111111111"
    agent_id = "22222222-2222-4222-8222-222222222222"
    conversation_id = "33333333-3333-4333-8333-333333333333"
    attachment_id = "44444444-4444-4444-8444-444444444444"

    command.upgrade(config, "0010_runtime_workspace_grants")
    admin.execute(
        f'SET search_path TO "{schema}"; '
        "INSERT INTO users "
        "(id, username, password_hash, status, platform_role) VALUES "
        f"('{user_id}', 'attachment-migration-user', 'hash', 'active', 'member'); "
        "INSERT INTO agents "
        "(id, owner_user_id, name, status, visibility, default_model_mode, "
        "draft_workspace_key) VALUES "
        f"('{agent_id}', '{user_id}', 'Attachment migration Agent', 'active', "
        "'private', 'inherit', 'agents/attachment-migration'); "
        "INSERT INTO conversations "
        "(id, agent_id, owner_user_id, title, status) VALUES "
        f"('{conversation_id}', '{agent_id}', '{user_id}', "
        "'Attachment migration conversation', 'active'); "
        "INSERT INTO attachments "
        "(id, conversation_id, owner_user_id, storage_key, media_type, size, "
        "content_hash) VALUES "
        f"('{attachment_id}', '{conversation_id}', '{user_id}', "
        "'C:\\\\legacy\\\\report.txt', 'text/plain', 6, 'sha256:legacy')",
    )

    command.upgrade(config, "head")

    assert (
        admin.execute(
            f"SELECT agent_id::text || '|' || original_name || '|' || lifecycle "
            f"FROM \"{schema}\"."
            f"attachments WHERE id = '{attachment_id}'",
        )
        == f"{agent_id}|report.txt|temporary"
    )


@pytest.mark.integration
def test_nonempty_unversioned_schema_is_rejected_without_changes(
    postgres_test_schema,
) -> None:
    """An old or unrelated schema must never be adopted implicitly."""
    from postgres import DockerPostgresAdmin

    admin = DockerPostgresAdmin(postgres_test_schema.config)
    admin.execute(
        f'CREATE TABLE "{postgres_test_schema.name}".legacy_sentinel '
        "(id integer PRIMARY KEY, value text NOT NULL); "
        f'INSERT INTO "{postgres_test_schema.name}".legacy_sentinel '
        "VALUES (1, 'unchanged')",
    )

    with pytest.raises(RuntimeError, match="nonempty_unversioned_schema"):
        command.upgrade(_alembic_config(postgres_test_schema), "head")

    assert _schema_tables(admin, postgres_test_schema.name) == {"legacy_sentinel"}
    assert (
        admin.execute(
            "SELECT value FROM "
            f'"{postgres_test_schema.name}".legacy_sentinel WHERE id = 1',
        )
        == "unchanged"
    )
