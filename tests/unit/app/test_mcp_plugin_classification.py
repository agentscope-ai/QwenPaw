# -*- coding: utf-8 -*-
"""Upgrade evidence must preserve custom data without starting MCP runtime."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import builtins
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from qwenpaw.app.mcp_plugin_migration import (
    MCPUsageSnapshot,
    MCPWorkspaceSnapshot,
    classify_mcp_usage,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures" / "mcp_plugin_upgrade"
SRC = ROOT.parent / "src"
SECRET = "synthetic-secret-do-not-disclose"


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch, tmp_path):
    for name in (
        "QWENPAW_WORKING_DIR",
        "QWENPAW_SECRET_DIR",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
    ):
        folder = tmp_path / name.lower()
        folder.mkdir()
        monkeypatch.setenv(name, str(folder))
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.setenv("QWENPAW_TELEMETRY_DISABLED", "1")
    monkeypatch.setenv(
        "PYTHON_KEYRING_BACKEND",
        "keyring.backends.null.Keyring",
    )
    for name in tuple(os.environ):
        if name.endswith(("_API_KEY", "_TOKEN", "_SECRET")):
            monkeypatch.delenv(name)


def load_default(version):
    return json.loads((FIXTURES / f"default-v{version}.json").read_text())


def workspace(data=None, *, workspace_id="main", errors=()):
    data = data or {}
    return MCPWorkspaceSnapshot(
        workspace_id=workspace_id,
        config=data.get("config", {}),
        cards=tuple(data.get("cards", ())),
        errors=errors,
    )


def classify(data=None, **kwargs):
    return classify_mcp_usage(
        MCPUsageSnapshot(workspaces=(workspace(data),), **kwargs),
    )


@pytest.mark.parametrize("version", (0, 1, 2))
def test_pristine_and_migrated_defaults_are_unused(version):
    default = load_default(version)
    cases = [
        None,
        {"config": {"mcp": {}}},
        default,
        {"config": {"mcp": {"clients": {}, "migration_version": version}}},
    ]
    if default["cards"]:
        cases.append({"cards": default["cards"]})
    for data in cases:
        decision = classify(data)
        assert decision.status == "unused"
        assert decision.workspace_statuses == {"main": "unused"}


def test_empty_inventory_is_unused():
    assert (
        classify_mcp_usage(MCPUsageSnapshot(workspaces=())).status == "unused"
    )


def test_normalized_legacy_default_aliases_are_unused():
    data = load_default(0)
    client = data["config"]["mcp"]["clients"]["anysearch"]
    client["isActive"] = client.pop("enabled")
    client["baseUrl"] = client.pop("url")
    client["type"] = "http"
    del client["transport"]
    assert classify(data).status == "unused"


@pytest.mark.parametrize("source", ("legacy", "card"))
def test_custom_disabled_sources_are_preserved(source):
    data = load_default(2)
    if source == "legacy":
        data["cards"] = []
        data["config"]["mcp"]["clients"]["anysearch"][
            "url"
        ] = "https://private.example/mcp"
    else:
        data["config"] = {}
        data["cards"][0]["endpoint"]["url"] = "https://private.example/mcp"
    original = deepcopy(data)
    decision = classify(data)
    assert decision.status == "configured"
    assert decision.workspace_statuses == {"main": "configured"}
    assert data == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("enabled", True),
        ("url", "https://custom.example/mcp"),
        ("name", "My Search"),
        ("description", "Personal search"),
        ("headers", {"Authorization": "Bearer " + SECRET}),
        ("env", {"REGION": "local"}),
        ("tools", ["search"]),
        ("http_timeout", 45),
        ("oauth", {"client_id": "my-app", "access_token": SECRET}),
    ],
)
def test_default_name_does_not_hide_custom_legacy_fields(field, value):
    data = load_default(0)
    data["config"]["mcp"]["clients"]["anysearch"][field] = value
    assert classify(data).status == "configured"


@pytest.mark.parametrize(
    "field,value",
    [
        ("enabled", True),
        (
            "endpoint",
            {"transport": "stdio", "command": "local-mcp", "args": []},
        ),
        ("config", {"display_name": "anysearch_mcp", "tools": ["search"]}),
        (
            "credentials",
            {
                "oauth": {
                    "kind": "oauth_auth_code",
                    "ref": "mcp/anysearch/oauth",
                },
            },
        ),
        ("credentials", {"custom": {"kind": "static", "ref": "mcp/personal"}}),
        ("policy", {"default_effect": "allow", "rules": []}),
    ],
)
def test_default_card_name_does_not_hide_custom_fields(field, value):
    data = {"cards": load_default(2)["cards"]}
    if field == "credentials":
        data["cards"][0][field].update(value)
    else:
        data["cards"][0][field] = value
    assert classify(data).status == "configured"


def test_opaque_historical_default_credential_requires_review():
    data = {"cards": load_default(1)["cards"]}
    card = data["cards"][0]
    card["credentials"] = {
        "static": {"kind": "static", "ref": "mcp/anysearch"},
    }
    card["endpoint"]["headers"]["Authorization"] = {
        "source": "credential",
        "credential": "static",
        "field": "authorization",
    }
    original = deepcopy(data)
    result = classify(data)
    assert result.status == "needs_review"
    assert result.workspace_statuses == {"main": "needs_review"}
    assert data == original


@pytest.mark.parametrize(
    "settings,uninstalled",
    [
        ({"enabled": False}, False),
        ({"enabled": True}, True),
        (None, True),
    ],
)
def test_explicit_off_wins(settings, uninstalled):
    data = load_default(0)
    data["config"]["mcp"]["clients"]["anysearch"]["enabled"] = True
    snapshots = (
        workspace(data),
        workspace(errors=("broken json",), workspace_id="broken"),
    )
    original = deepcopy(settings)
    result = classify_mcp_usage(
        MCPUsageSnapshot(
            workspaces=snapshots,
            plugin_settings=settings,
            plugin_uninstalled=uninstalled,
        ),
    )
    assert result.status == "explicit_off"
    assert set(result.workspace_statuses) == {"main", "broken"}
    assert settings == original


def test_missing_settings_is_not_explicit_opt_in():
    assert classify(plugin_settings={}).status == "unused"


def test_inventory_includes_inactive_workspaces():
    disabled = {
        "config": {
            "enabled": False,
            "mcp": {
                "clients": {
                    "local": {
                        "name": "local",
                        "enabled": False,
                        "transport": "stdio",
                        "command": "local-mcp",
                        "args": [],
                    },
                },
            },
        },
    }
    result = classify_mcp_usage(
        MCPUsageSnapshot(
            workspaces=(
                workspace(load_default(0)),
                workspace(disabled, workspace_id="never-started"),
                workspace(errors=("unreadable card",), workspace_id="broken"),
            ),
        ),
    )
    assert result.status == "configured"
    assert result.workspace_statuses == {
        "main": "unused",
        "never-started": "configured",
        "broken": "needs_review",
    }


@pytest.mark.parametrize(
    "data",
    [
        {"config": {"mcp": "corrupt"}},
        {"config": {"mcp": {"clients": []}}},
        {"config": {"mcp": {"clients": {"x": "corrupt"}}}},
        {"config": {"mcp": {"clients": {"x": {"transport": "future"}}}}},
        {"config": {"mcp": {"clients": {"x": {"name": "x", "command": ""}}}}},
        {"config": {"mcp": {"unknown_legacy_servers": ["x"]}}},
        {"config": {"mcp": {"migration_version": 999, "clients": {}}}},
        {
            "cards": [
                {"name": "broken", "protocol": "mcp", "endpoint": "corrupt"},
            ],
        },
    ],
)
def test_invalid_snapshot_requires_review(data):
    decision = classify(data)
    assert decision.status == "needs_review"
    assert decision.workspace_statuses == {"main": "needs_review"}
    assert decision.reasons


def test_file_error_is_not_hidden_by_unused_default():
    decision = classify_mcp_usage(
        MCPUsageSnapshot(
            workspaces=(
                workspace(load_default(2), errors=("invalid YAML " + SECRET,)),
            ),
        ),
    )
    assert decision.status == "needs_review"
    assert decision.workspace_statuses == {"main": "needs_review"}
    assert SECRET not in repr(decision)


def test_duplicate_card_names_require_review():
    cards = load_default(2)["cards"]
    custom = deepcopy(cards[0])
    custom["endpoint"]["url"] = "https://custom.example/mcp"
    result = classify({"cards": [cards[0], custom]})
    assert result.status == "needs_review"
    assert result.workspace_statuses == {"main": "needs_review"}


def test_reasons_are_fixed_codes_without_secret_or_user_text():
    data = load_default(0)
    data["config"]["mcp"]["clients"][SECRET] = {
        "name": SECRET,
        "enabled": False,
        "transport": "stdio",
        "command": "local-mcp",
        "env": {"TOKEN": SECRET},
    }
    result = classify(data)
    assert result.status == "configured"
    assert result.reasons
    assert SECRET not in repr(result)
    assert all(
        re.fullmatch(r"[a-z][a-z0-9_.:-]*", code) for code in result.reasons
    )


def test_classification_never_reads_or_writes_files_or_mutates_snapshot(
    monkeypatch,
    tmp_path,
):
    data = load_default(2)
    data["cards"][0]["config"]["tools"] = ["search"]
    original = deepcopy(data)
    settings = {"enabled": True, "config": {"marker": SECRET}}
    settings_before = deepcopy(settings)
    snapshot = MCPUsageSnapshot(
        workspaces=(workspace(data),),
        plugin_settings=settings,
    )
    config_file = tmp_path / "agent.json"
    config_file.write_text(json.dumps(data))
    before = config_file.read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Classification must perform no file or credential I/O",
        )

    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", forbidden)
        guard.setattr(os, "open", forbidden)
        for name in (
            "open",
            "read_text",
            "read_bytes",
            "write_text",
            "write_bytes",
            "unlink",
            "mkdir",
            "exists",
            "is_file",
            "iterdir",
            "glob",
        ):
            guard.setattr(Path, name, forbidden)
        result = classify_mcp_usage(snapshot)
    assert result.status == "configured"
    assert data == original
    assert settings == settings_before
    assert config_file.read_bytes() == before
    with pytest.raises(FrozenInstanceError):
        snapshot.workspaces = ()


def test_snapshot_retains_independent_input_data():
    data = load_default(2)
    saved_workspace = workspace(data)
    data["config"]["mcp"]["clients"]["anysearch"]["enabled"] = True
    data["cards"][0]["endpoint"]["url"] = "https://custom.example/mcp"
    result = classify_mcp_usage(
        MCPUsageSnapshot(workspaces=(saved_workspace,)),
    )
    assert result.status == "unused"


def test_classification_does_not_import_transport_or_load_credentials(
    tmp_path,
):
    script = """
import importlib.abc
from pathlib import Path
import sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = (
            "mcp", "qwenpaw.drivers.handlers", "qwenpaw.drivers.manager",
            "qwenpaw.drivers.credentials", "qwenpaw.app.mcp_manager",
            "qwenpaw.drivers.adapters.mcp_legacy_config",
        )
        if any(
            fullname == prefix or fullname.startswith(prefix + ".")
            for prefix in blocked
        ):
            raise AssertionError(
                "Runtime import during classification: " + fullname
            )
sys.meta_path.insert(0, Guard())
import qwenpaw.app.mcp_plugin_migration as migration
assert Path(migration.__file__).resolve().is_relative_to(
    Path(sys.argv[1]).resolve()
)
snapshot = migration.MCPUsageSnapshot(
    workspaces=(migration.MCPWorkspaceSnapshot(workspace_id="clean"),)
)
assert migration.classify_mcp_usage(snapshot).status == "unused"
"""
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.endswith(("_API_KEY", "_TOKEN", "_SECRET"))
    }
    env.update(PYTHONPATH=str(SRC), PYTHONDONTWRITEBYTECODE="1")
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script, str(SRC)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize(
    "policy",
    [
        {"default_effect": "deny", "rules": {}},
        {"default_effect": "permit", "rules": []},
        {
            "default_effect": "deny",
            "rules": [
                {
                    "subject": "*",
                    "effect": "permit",
                    "target": {"kind": "tool", "name": "*"},
                },
            ],
        },
    ],
    ids=("rules-not-list", "invalid-default-effect", "invalid-rule-effect"),
)
def test_malformed_card_policy_requires_review(policy):
    data = {"cards": load_default(2)["cards"]}
    data["cards"][0]["policy"] = policy
    original = deepcopy(data)
    result = classify(data)
    assert result.status == "needs_review"
    assert result.workspace_statuses == {"main": "needs_review"}
    assert result.reasons
    assert data == original


def test_unsupported_card_transport_requires_review():
    data = {"cards": load_default(2)["cards"]}
    data["cards"][0]["endpoint"]["transport"] = "unsupported-transport"
    result = classify(data)
    assert result.status == "needs_review"
    assert result.workspace_statuses == {"main": "needs_review"}


def test_endpoint_missing_credential_alias_requires_review():
    data = {"cards": load_default(2)["cards"]}
    data["cards"][0]["endpoint"]["headers"]["Authorization"][
        "credential"
    ] = "missing_alias"
    original = deepcopy(data)
    result = classify(data)
    assert result.status == "needs_review"
    assert result.workspace_statuses == {"main": "needs_review"}
    assert data == original


def test_declared_unused_credential_alias_remains_configured():
    data = {"cards": load_default(2)["cards"]}
    data["cards"][0]["credentials"]["reserved"] = {
        "kind": "static",
        "ref": "env:RESERVED_API_KEY",
    }
    original = deepcopy(data)
    result = classify(data)
    assert result.status == "configured"
    assert result.workspace_statuses == {"main": "configured"}
    assert data == original


@pytest.mark.parametrize(
    "inventory",
    ("non-mcp-only", "same-name-with-mcp", "duplicate-non-mcp"),
)
def test_non_mcp_cards_are_ignored_by_mcp_classification(inventory):
    default = load_default(2)["cards"][0]
    external = {
        "name": "anysearch",
        "protocol": "http",
        "endpoint": {"url": "https://service.example/api", "method": "GET"},
        "config": {},
        "credentials": {},
        "enabled": True,
        "policy": {"default_effect": "deny", "rules": []},
    }
    cards = [external]
    if inventory == "same-name-with-mcp":
        cards.append(default)
    elif inventory == "duplicate-non-mcp":
        duplicate = deepcopy(external)
        duplicate["endpoint"]["url"] = "https://another.example/api"
        cards.append(duplicate)
    data = {"cards": cards}
    original = deepcopy(data)
    result = classify(data)
    assert result.status == "unused"
    assert result.workspace_statuses == {"main": "unused"}
    assert data == original


def test_valid_endpoint_extension_is_preserved_as_configuration():
    data = {"cards": load_default(2)["cards"]}
    data["cards"][0]["endpoint"]["vendor_extension"] = {"cache_enabled": True}
    original = deepcopy(data)
    result = classify(data)
    assert result.status == "configured"
    assert result.workspace_statuses == {"main": "configured"}
    assert data == original


@pytest.mark.parametrize("section", ("headers", "env"))
def test_legacy_structured_bindings_remain_configured(section):
    data = {"cards": load_default(2)["cards"]}
    card = data["cards"][0]
    card["credentials"] = {}
    binding = {"public": {"X-Mode": "legacy"}, "secret_refs": {}}
    if section == "headers":
        card["endpoint"]["headers"] = binding
    else:
        card["endpoint"] = {
            "transport": "stdio",
            "command": "local-mcp",
            "args": [],
            "env": binding,
        }
    original = deepcopy(data)
    result = classify(data)
    assert result.status == "configured"
    assert result.workspace_statuses == {"main": "configured"}
    assert data == original


def test_unsupported_policy_target_kind_requires_review():
    data = {"cards": load_default(2)["cards"]}
    rule = data["cards"][0]["policy"]["rules"][0]
    rule["target"]["kind"] = "unsupported-policy-kind"
    original = deepcopy(data)
    result = classify(data)
    assert result.status == "needs_review"
    assert result.workspace_statuses == {"main": "needs_review"}
    assert data == original


@pytest.mark.parametrize("subject_value", ("", "   "))
def test_user_principal_requires_nonempty_subject_value(subject_value):
    data = {"cards": load_default(2)["cards"]}
    principal = data["cards"][0]["policy"]["rules"][0]["principal"]
    principal["subject_type"] = "user"
    principal["subject_value"] = subject_value
    original = deepcopy(data)
    result = classify(data)
    assert result.status == "needs_review"
    assert result.workspace_statuses == {"main": "needs_review"}
    assert data == original


@pytest.mark.parametrize(
    "case",
    ("literal-value-none", "credential-format-none"),
)
def test_nullable_existing_value_source_fields_remain_configured(case):
    data = {"cards": load_default(2)["cards"]}
    headers = data["cards"][0]["endpoint"]["headers"]
    if case == "literal-value-none":
        headers["X-Optional"] = {"source": "literal", "value": None}
    else:
        headers["Authorization"]["format"] = None
    original = deepcopy(data)
    result = classify(data)
    assert result.status == "configured"
    assert result.workspace_statuses == {"main": "configured"}
    assert data == original
