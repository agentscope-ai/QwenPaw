# -*- coding: utf-8 -*-
"""Tests for shared third-party Harness capability resolution."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.app.driver_config_service import DriverConfigService
from qwenpaw.drivers.constants import (
    CREDENTIAL_ALIAS_STATIC,
    CREDENTIAL_KIND_STATIC,
)
from qwenpaw.drivers.contracts import (
    CredentialRef,
    DriverCard,
    DriverPolicy,
    PolicyPrincipal,
    PolicyRule,
    PolicyTarget,
)
from qwenpaw.drivers.credentials.types import CredentialRecord
from qwenpaw.harnesses.capabilities import HarnessCapabilityResolver


def _write_skill(
    workspace_dir: Path,
    name: str,
    *,
    channels: list[str],
) -> None:
    skill_dir = workspace_dir / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} description\n---\n",
        encoding="utf-8",
    )
    manifest_path = workspace_dir / "skill.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {"skills": {}}
    )
    manifest["skills"][name] = {
        "enabled": True,
        "channels": channels,
    }
    manifest_path.write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_resolves_channel_scoped_skills(tmp_path: Path) -> None:
    _write_skill(tmp_path, "shared", channels=["all"])
    _write_skill(tmp_path, "console-only", channels=["console"])
    _write_skill(tmp_path, "dingtalk-only", channels=["dingtalk"])
    resolver = HarnessCapabilityResolver(tmp_path)

    capabilities = await resolver.resolve({"channel": "console"})

    assert [item.name for item in capabilities.skills] == [
        "console-only",
        "shared",
    ]
    assert capabilities.skills[0].description == ("console-only description")


@pytest.mark.asyncio
async def test_skill_fingerprint_tracks_all_projected_files(
    tmp_path: Path,
) -> None:
    _write_skill(tmp_path, "review", channels=["all"])
    skill_dir = tmp_path / "skills" / "review"
    resolver = HarnessCapabilityResolver(tmp_path)

    fingerprints = [(await resolver.resolve()).fingerprint]
    (skill_dir / "SKILL.md").write_text(
        "---\nname: review\ndescription: Updated\n---\n",
        encoding="utf-8",
    )
    fingerprints.append((await resolver.resolve()).fingerprint)
    references = skill_dir / "references"
    references.mkdir()
    (references / "guide.md").write_text("guide", encoding="utf-8")
    fingerprints.append((await resolver.resolve()).fingerprint)
    scripts = skill_dir / "scripts"
    scripts.mkdir()
    (scripts / "check.py").write_text("print('ok')\n", encoding="utf-8")
    fingerprints.append((await resolver.resolve()).fingerprint)

    assert len(set(fingerprints)) == 4


@pytest.mark.asyncio
async def test_resolves_mcp_secrets_without_fingerprinting_values(
    tmp_path: Path,
) -> None:
    workspace = SimpleNamespace(workspace_dir=tmp_path)
    driver_config = DriverConfigService(workspace)
    await driver_config.credential_store.put(
        CredentialRecord(
            ref="mcp/example",
            kind=CREDENTIAL_KIND_STATIC,
            secrets={"api_key": "super-secret-value"},
            meta={"updated_at": 42},
        ),
    )
    await driver_config.save_card(
        DriverCard(
            name="example",
            protocol="mcp",
            endpoint={
                "transport": "streamable_http",
                "url": "https://mcp.example.test",
                "headers": {
                    "Authorization": {
                        "source": "credential",
                        "credential": CREDENTIAL_ALIAS_STATIC,
                        "field": "api_key",
                        "format": "Bearer {value}",
                    },
                },
            },
            credentials={
                CREDENTIAL_ALIAS_STATIC: CredentialRef(
                    CREDENTIAL_KIND_STATIC,
                    "mcp/example",
                ),
            },
            config={
                "display_name": "Example MCP",
                "tools": ["read", "write"],
            },
            policy=DriverPolicy(
                default_effect="deny",
                rules=[
                    PolicyRule(
                        subject="*",
                        effect="allow",
                        target=PolicyTarget(kind="tool", name="read"),
                        principal=PolicyPrincipal(
                            source_type="channel",
                            source_value="console",
                            subject_type="all",
                            subject_value="*",
                        ),
                    ),
                ],
            ),
        ),
        reload_driver=False,
    )
    resolver = HarnessCapabilityResolver(tmp_path, workspace)

    capabilities = await resolver.resolve(
        {
            "channel": "console",
            "user_id": "person",
            "session_id": "chat",
        },
    )

    server = capabilities.mcp_servers[0]
    assert server.display_name == "Example MCP"
    assert server.revealed_headers() == {
        "Authorization": "Bearer super-secret-value",
    }
    assert server.tool_policies == {"read": "allow", "write": "deny"}
    assert server.credential_revision == "42"
    assert "super-secret-value" not in repr(server)
    assert "super-secret-value" not in capabilities.fingerprint

    await driver_config.credential_store.put(
        CredentialRecord(
            ref="mcp/example",
            kind=CREDENTIAL_KIND_STATIC,
            secrets={"api_key": "rotated-secret-value"},
            meta={"updated_at": 43},
        ),
    )
    rotated = await resolver.resolve(
        {
            "channel": "console",
            "user_id": "person",
            "session_id": "chat",
        },
    )

    assert rotated.fingerprint != capabilities.fingerprint
    assert "rotated-secret-value" not in repr(rotated)
    assert "rotated-secret-value" not in rotated.fingerprint


@pytest.mark.asyncio
async def test_skips_disabled_mcp_server(tmp_path: Path) -> None:
    workspace = SimpleNamespace(workspace_dir=tmp_path)
    driver_config = DriverConfigService(workspace)
    await driver_config.save_card(
        DriverCard(
            name="disabled",
            protocol="mcp",
            endpoint={
                "transport": "stdio",
                "command": "server",
            },
            enabled=False,
        ),
        reload_driver=False,
    )

    capabilities = await HarnessCapabilityResolver(
        tmp_path,
        workspace,
    ).resolve()

    assert capabilities.mcp_servers == []
