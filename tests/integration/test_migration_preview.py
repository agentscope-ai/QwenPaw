"""遗留数据迁移预览的只读、安全与权限契约。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.dependencies import get_actor
from qwenpaw.app.routers import migration as migration_router
from qwenpaw.identity.models import PlatformRole
from qwenpaw.migration.report import LegacyPostgresSnapshot
from qwenpaw.migration.scanner import scan_migration_preview


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _actor(role: PlatformRole) -> ActorContext:
    return ActorContext(
        user_id=UUID("11111111-1111-4111-8111-111111111111"),
        actor_type=ActorType.USER,
        platform_role=role,
        admin_mode=False,
        request_id="migration-preview-test",
    )


def _legacy_fixture(working_dir: Path, secret_dir: Path) -> None:
    _write_json(
        secret_dir / "auth.json",
        {
            "username": "legacy-admin",
            "password_hash": "do-not-return-password-hash",
            "jwt_secret": "ENC:gAAAA-secret-ciphertext",
        },
    )
    _write_json(
        working_dir / "config.json",
        {
            "agents": {
                "profiles": {
                    "alpha": {"name": "Alpha", "workspace": "workspaces/alpha"}
                }
            }
        },
    )
    workspace = working_dir / "workspaces" / "alpha"
    _write_json(
        workspace / "agent.json",
        {
            "id": "alpha",
            "mcp": {
                "clients": {
                    "docs": {
                        "command": "server",
                        "env": {"API_KEY": "plain-secret-must-not-leak"},
                    }
                }
            },
            "channels": {"matrix": {"password": ""}},
        },
    )
    _write_json(
        workspace / "chats.json",
        {
            "version": 1,
            "chats": [
                {"id": "chat-1", "session_id": "session-1"},
                {"id": "chat-2", "session_id": "session-2"},
            ],
        },
    )
    _write_json(
        workspace / "sessions" / "session-1.json",
        {
            "agent": {
                "state": {
                    "context": [
                        {"role": "user", "content": "hello"},
                        {"role": "assistant", "content": "hi"},
                    ]
                }
            }
        },
    )
    _write_json(
        workspace / "jobs.json",
        {"version": 1, "jobs": [{"id": "job-1"}]},
    )
    (workspace / "skills" / "review" / "SKILL.md").parent.mkdir(
        parents=True, exist_ok=True
    )
    (workspace / "skills" / "review" / "SKILL.md").write_text(
        "# Review", encoding="utf-8"
    )
    _write_json(
        working_dir / "inbox_events.json",
        [{"id": "event-1"}, {"id": "event-2"}],
    )
    _write_json(
        working_dir / "token_usage.json",
        {
            "2026-09-08": {
                "provider:model": {
                    "provider_id": "provider",
                    "model_name": "model",
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "call_count": 1,
                }
            }
        },
    )


def test_preview_scans_all_domains_without_writing_or_exposing_secrets(
    tmp_path: Path,
) -> None:
    """捕获漏扫领域、扫描写盘或把 Secret 值带入报告的回归。"""
    working_dir = tmp_path / "work"
    secret_dir = tmp_path / "secret"
    _legacy_fixture(working_dir, secret_dir)
    before = (_tree_hash(working_dir), _tree_hash(secret_dir))

    async def probe() -> LegacyPostgresSnapshot:
        return LegacyPostgresSnapshot(
            configured=True,
            table_count=2,
            row_count=5,
            schema_hash="sha256:legacy-pg",
        )

    report = asyncio.run(
        scan_migration_preview(
            working_dir=working_dir,
            secret_dir=secret_dir,
            legacy_postgres_probe=probe,
        )
    )

    assert [domain.key for domain in report.domains] == [
        "identity",
        "agents",
        "conversations",
        "messages",
        "skills",
        "mcp",
        "cron",
        "inbox",
        "tokens",
        "legacy_postgres",
    ]
    assert {domain.key: domain.count for domain in report.domains} == {
        "identity": 1,
        "agents": 1,
        "conversations": 2,
        "messages": 2,
        "skills": 1,
        "mcp": 1,
        "cron": 1,
        "inbox": 2,
        "tokens": 1,
        "legacy_postgres": 5,
    }
    assert report.read_only is True
    assert report.integrity.unchanged is True
    assert report.integrity.before_hash == report.integrity.after_hash
    assert before == (_tree_hash(working_dir), _tree_hash(secret_dir))
    assert all(domain.source_hash.startswith("sha256:") for domain in report.domains)
    assert all(domain.mapping for domain in report.domains)

    payload = report.model_dump_json()
    assert "do-not-return-password-hash" not in payload
    assert "gAAAA-secret-ciphertext" not in payload
    assert "plain-secret-must-not-leak" not in payload
    assert {ref.version for ref in report.secret_references} == {
        "fernet-v1",
        "plaintext",
    }
    assert all(
        ref.reference and not ref.value_exposed
        for ref in report.secret_references
    )
    assert all(
        "channels.matrix.password" not in ref.reference
        for ref in report.secret_references
    )


def test_preview_reports_invalid_json_as_rejected_item(tmp_path: Path) -> None:
    """捕获损坏数据被静默忽略、导致迁移数量看似正常的回归。"""
    working_dir = tmp_path / "work"
    secret_dir = tmp_path / "secret"
    working_dir.mkdir()
    secret_dir.mkdir()
    (secret_dir / "auth.json").write_text("{broken", encoding="utf-8")

    report = asyncio.run(
        scan_migration_preview(working_dir=working_dir, secret_dir=secret_dir)
    )

    identity = report.domains[0]
    assert identity.status == "rejected"
    assert identity.rejected[0].code == "invalid_json"
    assert identity.rejected[0].source == "secret/auth.json"
    assert identity.rejected[0].detail == "JSON 文件无法解析"


def test_agent_hash_includes_each_workspace_agent_config(tmp_path: Path) -> None:
    """捕获 Agent 哈希只覆盖根清单、漏掉实际 agent.json 的回归。"""
    working_dir = tmp_path / "work"
    secret_dir = tmp_path / "secret"
    _legacy_fixture(working_dir, secret_dir)

    first = asyncio.run(
        scan_migration_preview(working_dir=working_dir, secret_dir=secret_dir)
    )
    agent_path = working_dir / "workspaces" / "alpha" / "agent.json"
    agent_config = json.loads(agent_path.read_text(encoding="utf-8"))
    agent_config["name"] = "Updated Alpha"
    _write_json(agent_path, agent_config)
    second = asyncio.run(
        scan_migration_preview(working_dir=working_dir, secret_dir=secret_dir)
    )

    assert first.domains[1].source_hash != second.domains[1].source_hash


def test_preview_route_is_admin_only_and_returns_read_only_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """捕获普通用户越权读取迁移清单或接口缺失只读标记的回归。"""
    working_dir = tmp_path / "work"
    secret_dir = tmp_path / "secret"
    _legacy_fixture(working_dir, secret_dir)

    async def scan_fixture():
        return await scan_migration_preview(
            working_dir=working_dir,
            secret_dir=secret_dir,
        )

    monkeypatch.setattr(
        migration_router,
        "scan_configured_migration_preview",
        scan_fixture,
    )
    app = FastAPI()
    app.include_router(migration_router.router, prefix="/api")

    app.dependency_overrides[get_actor] = lambda: _actor(PlatformRole.MEMBER)
    with TestClient(app) as client:
        assert client.get("/api/migration/preview").status_code == 403

    app.dependency_overrides[get_actor] = lambda: _actor(PlatformRole.ADMIN)
    with TestClient(app) as client:
        response = client.get("/api/migration/preview")
    assert response.status_code == 200
    assert response.json()["read_only"] is True
    assert len(response.json()["domains"]) == 10
