# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qwenpaw.portability.models import SourcePlugin
from qwenpaw.portability.providers.external_state import (
    discover_codex_plugins,
    discover_codex_plugin_mcp,
    discover_qoder_mcp,
    discover_qoder_plugin_mcp,
    discover_qoder_plugins,
)


def test_codex_plugin_uses_marketplace_source_not_installed_cache(
    tmp_path: Path,
):
    codex_home = tmp_path / ".codex"
    marketplace = tmp_path / "marketplace"
    plugin = marketplace / "plugins/demo"
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text(
        json.dumps({"id": "demo", "name": "Demo", "version": "1.0.0"}),
        encoding="utf-8",
    )
    manifest_dir = marketplace / ".codex-plugin"
    manifest_dir.mkdir()
    (manifest_dir / "marketplace.json").write_text(
        json.dumps(
            {"plugins": [{"name": "demo", "source": "../plugins/demo"}]},
        ),
        encoding="utf-8",
    )
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        '[plugins."demo@local"]\nenabled = true\n'
        '[marketplaces.local]\nsource_type = "directory"\n'
        f'source = "{marketplace}"\n',
        encoding="utf-8",
    )
    cache = codex_home / "plugins/cache/local/demo/cache-id/.codex-plugin"
    cache.mkdir(parents=True)
    (cache / "plugin.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "version": "9.9.9",
                "interface": {"displayName": "Demo Plugin"},
            },
        ),
        encoding="utf-8",
    )

    marketplaces, plugins = discover_codex_plugins(codex_home)

    assert marketplaces[0].source == str(marketplace.resolve())
    assert plugins[0].name == "Demo Plugin"
    assert plugins[0].version == "9.9.9"
    assert plugins[0].install_source == str(plugin.resolve())
    assert "cache" not in plugins[0].install_source


def test_codex_content_plugin_cache_is_staging_input_not_install_source(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / ".codex"
    plugin = codex_home / "plugins/cache/openai-curated-remote/expo/1.0.2"
    manifest = plugin / ".codex-plugin/plugin.json"
    skill = plugin / "skills/building-native-ui/SKILL.md"
    manifest.parent.mkdir(parents=True)
    skill.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "name": "expo",
                "version": "1.0.2",
                "skills": "./skills/",
                "interface": {"displayName": "Expo"},
            },
        ),
        encoding="utf-8",
    )
    skill.write_text("# Expo", encoding="utf-8")
    (plugin.parent / ".codex-remote-plugin-install.json").write_text(
        '{"schema_version":1}',
        encoding="utf-8",
    )

    _marketplaces, plugins = discover_codex_plugins(codex_home)

    assert len(plugins) == 1
    assert plugins[0].name == "Expo"
    assert plugins[0].install_source == ""
    assert plugins[0].metadata["install_path"] == str(plugin.resolve())
    assert plugins[0].metadata["adapter"] == "codex_content_bundle_v1"


@pytest.mark.parametrize("manifest_dir", [".codex-plugin", ".claude-plugin"])
def test_codex_content_plugin_discovers_owned_mcp(
    tmp_path: Path,
    manifest_dir: str,
) -> None:
    root = tmp_path / "cloudflare"
    manifest = root / manifest_dir / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "name": "cloudflare",
                "mcpServers": "./.mcp.json",
            },
        ),
        encoding="utf-8",
    )
    (root / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "cloudflare-api": {
                        "type": "http",
                        "url": "https://mcp.cloudflare.com/mcp",
                    },
                    "local": {
                        "command": "node",
                        "args": ["./mcp/server.mjs"],
                        "cwd": ".",
                        "env_vars": ["CODEX_HOME"],
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    plugin = SourcePlugin(
        source_id="cloudflare@openai-curated-remote",
        name="Cloudflare",
        marketplace="openai-curated-remote",
        metadata={"install_path": str(root)},
    )

    servers, warnings, discovered = discover_codex_plugin_mcp([plugin])

    assert not warnings
    assert discovered == 2
    assert [server.name for server in servers] == ["cloudflare-api", "local"]
    assert servers[0].url == "https://mcp.cloudflare.com/mcp"
    assert servers[0].metadata["source_plugin"] == plugin.source_id
    assert servers[1].cwd == ""
    assert servers[1].env == {"CODEX_HOME": "${CODEX_HOME}"}
    assert servers[1].metadata["source_plugin_relative_cwd"] == "."


def test_qoder_plugin_cache_is_metadata_only(tmp_path: Path):
    home = tmp_path / ".qoder"
    plugins_root = home / "plugins"
    cache = plugins_root / "cache/qoder-bundler/demo"
    cache.mkdir(parents=True)
    (cache / "plugin.json").write_text(
        json.dumps({"id": "demo", "name": "Demo", "version": "1.0.0"}),
        encoding="utf-8",
    )
    (plugins_root / "installed_plugins_v2.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "demo@qoder-bundler": [
                        {"enabled": True, "version": "1.0.0"},
                    ],
                },
            },
        ),
        encoding="utf-8",
    )

    marketplaces, plugins = discover_qoder_plugins(home)

    assert marketplaces[0].source_type == "builtin"
    assert plugins[0].install_source == ""


def test_qoder_mcp_is_translated_without_copying_credentials(
    tmp_path: Path,
):
    home = tmp_path / ".qoder"
    home.mkdir()
    (home / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "local": {
                        "command": "npx",
                        "args": ["server"],
                        "env": {"API_TOKEN": "secret-value"},
                    },
                    "remote": {
                        "type": "sse",
                        "url": "https://example.test/sse",
                        "headers": {"Authorization": "Bearer secret"},
                    },
                },
            },
        ),
        encoding="utf-8",
    )

    servers, warnings, discovered = discover_qoder_mcp(home)

    assert not warnings
    assert discovered == 2
    assert servers[0].env == {"API_TOKEN": "${API_TOKEN}"}
    assert servers[0].auth_status == "reauthorize"
    assert servers[1].transport == "sse"
    assert servers[1].headers == {"Authorization": "${AUTHORIZATION}"}
    assert "secret" not in "".join(item.model_dump_json() for item in servers)


def test_qoder_plugin_mcp_uses_the_normal_mcp_pipeline(tmp_path: Path):
    home = tmp_path / ".qoder"
    plugins_root = home / "plugins"
    gitlab = plugins_root / "cache/community/gitlab/1.0.0"
    mongodb = plugins_root / "cache/community/mongodb/1.0.0"
    gitlab.mkdir(parents=True)
    mongodb.mkdir(parents=True)
    (gitlab / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "GitLab": {
                        "type": "http",
                        "url": "https://gitlab.example/mcp",
                        "headers": {"Authorization": "secret"},
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    (mongodb / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "mongodb": {
                        "command": "npx",
                        "args": ["-y", "mongodb-mcp-server@1"],
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    plugins = [
        SourcePlugin(
            source_id="gitlab@community",
            name="gitlab",
            marketplace="community",
            metadata={"install_path": str(gitlab)},
        ),
        SourcePlugin(
            source_id="mongodb@community",
            name="mongodb",
            marketplace="community",
            metadata={"install_path": str(mongodb)},
        ),
    ]

    servers, warnings, discovered = discover_qoder_plugin_mcp(plugins)

    assert not warnings
    assert discovered == 2
    assert [server.name for server in servers] == ["GitLab", "mongodb"]
    assert servers[0].source_id == ("qoder:plugin-mcp:gitlab@community:GitLab")
    assert servers[0].headers == {"Authorization": "${AUTHORIZATION}"}
    assert servers[0].metadata["source_plugin"] == "gitlab@community"
    assert servers[1].command == "npx"


def test_qoder_custom_plugin_with_native_extensions_is_not_adapted(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".qoder"
    plugins_root = home / "plugins"
    source = plugins_root / "custom/native-plugin"
    skill = source / "skills/demo"
    manifest_dir = source / ".qoder-plugin"
    skill.mkdir(parents=True)
    manifest_dir.mkdir()
    (skill / "SKILL.md").write_text("# Demo", encoding="utf-8")
    (manifest_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "native-plugin",
                "version": "1.0.0",
                "skills": "./skills/",
                "hooks": "./hooks/hooks.json",
            },
        ),
        encoding="utf-8",
    )
    (plugins_root / "installed_plugins_v2.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "native-plugin@local-custom": [
                        {
                            "enabled": True,
                            "source": "custom",
                            "installPath": str(source),
                        },
                    ],
                },
            },
        ),
        encoding="utf-8",
    )

    _marketplaces, plugins = discover_qoder_plugins(home)

    assert plugins[0].install_source == ""
    assert "adapter" not in plugins[0].metadata
