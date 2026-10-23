"""Independent, prepared C6 capture/project oracles; no SDK or process doubles.

Production imports are deliberately lazy: candidate execution waits for the
independent Source freeze. One HTTP/Driver chain remains in legacy_refs_suite.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

APP = "test-azure-application"
TENANT = "test-tenant"
TARGET = "azure_msteams#ABCDEFGHIJ:Ada#123456"
ROUTE = {
    "service_url": "https://connector.test",
    "conversation_id": "conversation-ABCDEFGHIJ",
    "azure_channel_id": "msteams",
    "bot_channel_id": "native-bot",
    "is_group": False,
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def prepare(tmp_path, *, profiles=False, local=False, agent_app=APP, refs=None):
    """Persist only actual old config/refs fields, never synthetic ownership."""
    root = tmp_path / "legacy"
    cwd = tmp_path / "host-cwd"
    cwd.mkdir(parents=True)
    workspace = root / "workspaces" / "default"
    workspace.mkdir(parents=True)
    config = {"enabled": True, "app_id": APP, "app_password": "sensitive-password-canary", "tenant_id": TENANT}
    raw = {"channels": {"azure_bot": config}}
    account_source = root / "config.json"
    if profiles:
        raw["agents"] = {"active_agent": "default", "profiles": {"default": {"id": "default", "workspace_dir": str(workspace)}}}
        account_source = write_json(workspace / "agent.json", {"id": "default", "channels": {"azure_bot": {**config, "app_id": agent_app}}})
    config_path = write_json(root / "config.json", raw)
    refs_path = write_json((workspace if local else root) / "azure_bot_refs.json", {TARGET: ROUTE} if refs is None else refs)
    return root, cwd, workspace, config_path, refs_path, account_source, config


def capture(case):
    from qwenpaw.plugins.azure_legacy import capture_azure_legacy
    root, cwd, _, config_path, *_ = case
    return capture_azure_legacy(config_path=config_path, legacy_state_dir=root, working_dir=cwd)


def manifest_path(case):
    return case[0] / "channel_state" / "azure_bot" / "legacy-capture.json"


def owner(workspace, app=APP):
    return {"workspace_dir": str(workspace.resolve()), "app_id": app, "tenant_id": TENANT}


def project(case, captured, *, workspace=None, app=APP, forged=None):
    from qwenpaw.plugins.official_execution_context import project_official_execution
    root, cwd, default, _, _, _, config = case
    selected = default if workspace is None else workspace
    values = {**config, "app_id": app, "workspace_dir": str(selected)}
    if forged is not None:
        values["legacy_reference_owner"] = forged
    result, environment = project_official_execution("azure_bot", values, working_dir=cwd, legacy_state_dir=root, environment={}, workspace_dir=selected, legacy_references=captured)
    assert environment == {}
    return result


def assert_authorization(value, captured, expected_owner, refs):
    assert set(value) == {"schema_version", "capture_id", "owner", "refs_sha256"}
    assert value == {"schema_version": 1, "capture_id": captured["capture_id"], "owner": expected_owner, "refs_sha256": digest(refs)}


@pytest.mark.parametrize("profiles,local", [(False, False), (True, True)])
def test_persisted_account_capture_preserves_full_refs_and_source_bytes(tmp_path, profiles, local):
    case = prepare(tmp_path, profiles=profiles, local=local)
    root, _, workspace, config_path, refs_path, account_source, _ = case
    watched = {p: p.read_bytes() for p in {config_path, refs_path, account_source}}
    captured = capture(case)
    assert set(captured) == {"schema_version", "capture_id", "entries", "unresolved"}
    assert captured["schema_version"] == 1
    assert len(captured["capture_id"]) == 32 and all(c in "0123456789abcdef" for c in captured["capture_id"])
    assert len(captured["entries"]) == 1 and captured["unresolved"] == []
    entry = captured["entries"][0]
    assert set(entry) == {"owner", "source", "config_source", "refs", "refs_sha256"}
    assert entry["owner"] == owner(workspace)
    assert entry["refs"] == {TARGET: ROUTE} and entry["refs_sha256"] == digest({TARGET: ROUTE})
    assert entry["source"] == {"path": str(refs_path.resolve()), "sha256": hashlib.sha256(watched[refs_path]).hexdigest()}
    assert entry["config_source"] == {"path": str(account_source.resolve()), "sha256": hashlib.sha256(watched[account_source]).hexdigest()}
    assert json.loads(manifest_path(case).read_bytes()) == captured
    assert "sensitive-password-canary" not in manifest_path(case).read_text()
    assert all(path.read_bytes() == data for path, data in watched.items())
    assert_authorization(project(case, captured)["legacy_reference_owner"], captured, owner(workspace), {TARGET: ROUTE})


def test_local_default_refs_take_precedence_over_global_refs(tmp_path):
    case = prepare(tmp_path, profiles=True, local=True)
    foreign = {"global-only": {**ROUTE, "conversation_id": "global-older"}}
    global_path = write_json(case[0] / "azure_bot_refs.json", foreign)
    before = global_path.read_bytes()
    captured = capture(case)
    refs = {key: route for entry in captured["entries"] for key, route in entry["refs"].items()}
    assert refs == {TARGET: ROUTE}
    assert global_path.read_bytes() == before


def test_raw_global_account_cannot_authorize_different_default_account(tmp_path):
    case = prepare(tmp_path, profiles=True, agent_app="account-B")
    captured = capture(case)
    assert captured["entries"] == []
    assert captured["unresolved"]
    for app in (APP, "account-B"):
        assert_authorization(project(case, captured, app=app)["legacy_reference_owner"], captured, None, {})


def test_same_physical_refs_cannot_be_claimed_by_two_workspace_owners(tmp_path):
    case = prepare(tmp_path, profiles=True, local=True)
    other = case[0] / "workspaces" / "other"
    write_json(other / "agent.json", {"id": "other", "channels": {"azure_bot": case[6]}})
    os.link(case[4], other / "azure_bot_refs.json")
    assert case[4].stat().st_ino == (other / "azure_bot_refs.json").stat().st_ino
    raw = json.loads(case[3].read_bytes())
    raw["agents"]["profiles"]["other"] = {"id": "other", "workspace_dir": str(other)}
    write_json(case[3], raw)
    captured = capture(case)
    assert captured["entries"] == [] and captured["unresolved"]
    for workspace in (case[2], other):
        assert_authorization(project(case, captured, workspace=workspace)["legacy_reference_owner"], captured, None, {})


def test_nondefault_persisted_profile_captures_own_local_account_only(tmp_path):
    case = prepare(tmp_path, profiles=True, local=True)
    other = case[0] / "workspaces" / "other"
    write_json(other / "agent.json", {"id": "other", "channels": {"azure_bot": {**case[6], "app_id": "other-app"}}})
    other_refs = {"other-target": {**ROUTE, "conversation_id": "other-conversation"}}
    write_json(other / "azure_bot_refs.json", other_refs)
    raw = json.loads(case[3].read_bytes())
    raw["agents"]["profiles"]["other"] = {"id": "other", "workspace_dir": str(other)}
    write_json(case[3], raw)
    captured = capture(case)
    assert len(captured["entries"]) == 2
    by_workspace = {entry["owner"]["workspace_dir"]: entry for entry in captured["entries"]}
    assert by_workspace[str(case[2].resolve())]["refs"] == {TARGET: ROUTE}
    assert by_workspace[str(other.resolve())]["owner"] == owner(other, "other-app")
    assert by_workspace[str(other.resolve())]["refs"] == other_refs
    assert_authorization(project(case, captured, workspace=other, app="other-app")["legacy_reference_owner"], captured, owner(other, "other-app"), other_refs)


def test_capture_is_once_only_despite_config_refs_changes_without_owned_state(tmp_path):
    from qwenpaw.plugins.azure_legacy import load_azure_legacy
    case = prepare(tmp_path)
    original_refs = case[4].read_bytes()
    captured = capture(case)
    frozen = manifest_path(case).read_bytes()
    assert case[4].read_bytes() == original_refs
    # Simulate uninstall's absence of per-account state, without deleting the
    # trusted capture. The first run has created no per-account state at all.
    assert not (case[2] / "channel_state").exists()
    changed_config = {"channels": {"azure_bot": {**case[6], "app_id": "new-account"}}}
    write_json(case[3], changed_config)
    write_json(case[4], {"new-target": {**ROUTE, "conversation_id": "new-conversation"}})
    changed_bytes = {path: path.read_bytes() for path in (case[3], case[4])}
    assert capture(case) == captured
    assert load_azure_legacy(legacy_state_dir=case[0]) == captured
    assert manifest_path(case).read_bytes() == frozen
    assert all(path.read_bytes() == data for path, data in changed_bytes.items())
    assert captured["entries"][0]["refs"] == {TARGET: ROUTE}


@pytest.mark.parametrize("change", ["same", "app", "workspace"])
def test_projection_overwrites_client_owner_and_foreign_account_gets_empty_authorization(tmp_path, change):
    case = prepare(tmp_path)
    captured = capture(case)
    target = case[2] if change != "workspace" else case[0] / "workspaces" / "other"
    app = "foreign-app" if change == "app" else APP
    forged = {"schema_version": 1, "capture_id": "0" * 32, "owner": owner(target, app), "refs_sha256": "0" * 64, "refs": {"attacker": ROUTE}}
    values = project(case, captured, workspace=target, app=app, forged=forged)
    expected_owner = owner(case[2]) if change == "same" else None
    assert_authorization(values["legacy_reference_owner"], captured, expected_owner, {TARGET: ROUTE} if change == "same" else {})
    assert forged["refs"] == {"attacker": ROUTE}


def test_large_frozen_refs_keep_runtime_bounded_and_restore_final_target(tmp_path):
    from azure_bot_native_support import state_module
    refs = {f"old-target-{index:04d}": {**ROUTE, "conversation_id": f"conversation-{index}-" + "x" * 2048} for index in range(600)}
    refs[TARGET] = {**ROUTE, "conversation_id": "final-target-retained"}
    case = prepare(tmp_path, refs=refs)
    assert len(case[4].read_bytes()) > 1024 * 1024
    captured = capture(case)
    values = project(case, captured)
    assert len(canonical(values)) < 4096
    assert_authorization(values["legacy_reference_owner"], captured, owner(case[2]), refs)
    store = state_module.AzureBotStateStore(values)
    try:
        store.begin()
        assert store.refs == refs
        assert store.resolve(TARGET, {}) == refs[TARGET]
        assert store.resolve("old-target-0000", {}) == refs["old-target-0000"]
    finally:
        store.close()
    assert json.loads(case[4].read_bytes()) == refs


def construct_official(case, monkeypatch):
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel
    from qwenpaw.__version__ import __version__
    import qwenpaw.constant as constants

    root = Path(__file__).resolve().parents[3]
    source = root / "plugins/channel/azure_bot"
    monkeypatch.setattr(constants, "WORKING_DIR", case[0])
    monkeypatch.chdir(case[1])
    description = describe_channel(source, PluginManifest.from_dict(json.loads((source / "plugin.json").read_bytes())))
    async def unused_process(_request):
        raise AssertionError("Unstarted factory must not invoke an Agent")
        yield
    return description.create_proxy(unused_process, case[6], python_executable=sys.executable, support_root=root / "src", instance_id="azure-capture-control", generation=1, qwenpaw_version=__version__, workspace_dir=case[2])


def tree_bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None for p in root.rglob("*")}


def test_missing_capture_factory_is_readonly_and_projects_explicit_no_authorization(tmp_path, monkeypatch):
    from qwenpaw.plugins.azure_legacy import load_azure_legacy
    case = prepare(tmp_path)
    before = tree_bytes(tmp_path)
    assert load_azure_legacy(legacy_state_dir=case[0]) is None
    proxy = construct_official(case, monkeypatch)
    assert proxy._launch_spec.config["legacy_reference_owner"] == {"schema_version": 1, "capture_id": "0" * 32, "owner": None, "refs_sha256": digest({})}
    assert tree_bytes(tmp_path) == before
    assert not manifest_path(case).exists()


@pytest.mark.parametrize("operation", ["capture", "load", "factory"])
def test_corrupt_capture_is_not_overwritten_and_azure_factory_fails_closed(tmp_path, monkeypatch, operation):
    from qwenpaw.plugins.azure_legacy import load_azure_legacy
    case = prepare(tmp_path)
    path = manifest_path(case)
    path.parent.mkdir(parents=True)
    invalid = b'{"schema_version":1,"capture_id":"tampered"}'
    path.write_bytes(invalid)
    old_bytes = {p: p.read_bytes() for p in (case[3], case[4])}
    with pytest.raises(ValueError, match="AZURE_LEGACY_CAPTURE_INVALID"):
        if operation == "capture":
            capture(case)
        elif operation == "load":
            load_azure_legacy(legacy_state_dir=case[0])
        else:
            construct_official(case, monkeypatch)
    assert path.read_bytes() == invalid
    assert all(path.read_bytes() == data for path, data in old_bytes.items())


def test_empty_local_file_does_not_fall_back_to_global(tmp_path):
    case = prepare(tmp_path, profiles=True, local=True, refs={})
    global_path = write_json(case[0] / "azure_bot_refs.json", {"global-only": ROUTE})
    original = global_path.read_bytes()
    captured = capture(case)
    assert all(entry["refs"] == {} for entry in captured["entries"])
    assert project(case, captured)["legacy_reference_owner"]["refs_sha256"] == digest({})
    assert global_path.read_bytes() == original


@pytest.mark.parametrize("key", ["azure_c6_third_party", "azure_bot"])
def test_nonofficial_factory_preserves_same_named_business_field_but_rejects_host_authority(tmp_path, key):
    from qwenpaw.plugins.channel_adapter import ChannelDescription
    from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
    from qwenpaw.__version__ import __version__

    case = prepare(tmp_path)
    captured = capture(case)
    root = Path(__file__).resolve().parents[3]
    code = tmp_path / "third-party"
    raw = json.loads((root / "plugins/channel/azure_bot/channel.json").read_bytes())
    raw["channel_key"] = key
    raw["config_schema"]["properties"]["legacy_reference_owner"] = {"type": "string", "default": ""}
    raw["config_fields"].append("legacy_reference_owner")
    path = write_json(code / "channel.json", raw)
    (code / "requirements.txt").write_text("")
    # Exercise the factory's own owner gate even with an Azure-shaped key.
    # No loader registration or SDK process is bypassed/claimed here.
    description = ChannelDescription("third-party-c6", "1.0.0", SharedChannelDescriptor.load(path), path, code, code / "requirements.txt", (), "third-party-revision", "Third party", "Constructor control")
    async def unused_process(_request):
        raise AssertionError("Constructor-only control must not run an Agent")
        yield
    kwargs = dict(python_executable=sys.executable, support_root=root / "src", instance_id="third-party-c6", generation=1, qwenpaw_version=__version__, workspace_dir=case[2])
    config = {**case[6], "legacy_reference_owner": "ordinary-plugin-business-value"}
    proxy = description.create_proxy(unused_process, config, **kwargs)
    assert proxy._launch_spec.config["legacy_reference_owner"] == "ordinary-plugin-business-value"
    assert "legacy_state_dir" not in proxy._launch_spec.config
    with pytest.raises(ValueError, match="AZURE_LEGACY_CONTEXT_CHANNEL_INVALID"):
        description.create_proxy(unused_process, config, legacy_references=captured, **kwargs)


@pytest.mark.parametrize("empty", [False, True])
def test_state_import_is_recorded_once_and_removed_target_does_not_reappear(tmp_path, empty):
    from azure_bot_native_support import state_module
    case = prepare(tmp_path, refs={} if empty else {TARGET: ROUTE})
    captured = capture(case)
    config = project(case, captured)
    store = state_module.AzureBotStateStore(config)
    try:
        store.begin()
        path = store.directory / "refs.json"
        saved = json.loads(path.read_bytes())
        assert saved["capture_id"] == captured["capture_id"]
        assert saved["refs"] == ({} if empty else {TARGET: ROUTE})
        if not empty:
            assert store.resolve(TARGET, {}) == ROUTE
            del store.refs[TARGET]
        store.save()
        removed_bytes = path.read_bytes()
    finally:
        store.close()
    resumed = state_module.AzureBotStateStore(config)
    try:
        resumed.begin()
        assert resumed.refs == {}
        with pytest.raises(ValueError, match="AZURE_ROUTE_UNAVAILABLE"):
            resumed.resolve(TARGET, {})
        assert path.read_bytes() == removed_bytes
    finally:
        resumed.close()
    assert captured["entries"][0]["refs"] == ({} if empty else {TARGET: ROUTE})


def test_real_core_policy_capture_failure_isolated_from_other_channel_migration(tmp_path, monkeypatch, caplog):
    from qwenpaw.config import utils
    from qwenpaw.plugins.official_channels import initialize_channel_policy
    import qwenpaw.constant as constants

    case = prepare(tmp_path)
    raw = json.loads(case[3].read_bytes())
    raw["channels"]["onebot"] = {"enabled": True}
    raw["channel_plugin_state"] = {"version": 1, "preset": "light", "legacy_pending": ["azure-bot"]}
    write_json(case[3], raw)
    invalid = b'{"schema_version":1,"private":"diagnostic-secret-must-not-leak"}'
    path = manifest_path(case)
    path.parent.mkdir(parents=True)
    path.write_bytes(invalid)
    monkeypatch.setattr(constants, "WORKING_DIR", case[0])
    monkeypatch.setattr(constants, "PLUGINS_DIR", case[0] / "plugins")
    monkeypatch.setattr(utils, "WORKING_DIR", case[0])
    monkeypatch.setattr(utils, "_config_cache", None)
    monkeypatch.setattr(utils, "_config_mtime", None)
    monkeypatch.delenv("QWENPAW_CHANNEL_PRESET", raising=False)
    initialize_channel_policy()
    state = utils.load_config().channel_plugin_state
    assert "onebot" in state.legacy_pending
    assert "azure-bot" not in state.legacy_pending
    assert "onebot" in state.legacy_captured
    assert "azure_bot" not in state.legacy_captured
    assert state.preset == "light" and state.version == 1
    assert path.read_bytes() == invalid
    assert "AZURE_LEGACY_CAPTURE_INVALID" in caplog.text
    assert "diagnostic-secret-must-not-leak" not in caplog.text
    assert "sensitive-password-canary" not in caplog.text
