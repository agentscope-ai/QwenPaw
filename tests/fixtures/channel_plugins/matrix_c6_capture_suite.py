"""Prepared capture and ownership controls; execute only after Source freeze."""

import json

import pytest

from matrix_c6_capture_support import (
    BOT,
    DEVICE,
    OLD_TOKEN,
    capture,
    factory_values,
    raw_case,
    snapshot,
    write_json,
)
from matrix_native_support import hs, platform_factory

__all__ = ["hs", "platform_factory"]


def manifest(root):
    return root / "channel_state/matrix/legacy-capture.json"


def assert_bounded_authority(values):
    authority = values["legacy_state_owner"]
    assert set(authority) == {
        "schema_version",
        "capture_id",
        "owner",
        "auth_sha256",
    }
    assert OLD_TOKEN not in json.dumps(authority)
    assert "explicit-password" not in json.dumps(authority)
    return authority


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["server", "user", "device", "crypto"])
async def test_valid_capture_rejects_actual_foreign_owner_without_old_token(
    hs, platform_factory, tmp_path, monkeypatch, change
):
    saved_server = (
        "https://old-server.invalid" if change == "server" else hs.url
    )
    root, workspace, config = raw_case(tmp_path, saved_server)
    captured = capture(root)
    valid = factory_values(root, workspace, config, monkeypatch)
    assert assert_bounded_authority(valid)["owner"] is not None
    assert captured["capture_id"] == valid["legacy_state_owner"]["capture_id"]
    if change == "user":
        hs.user = "@other:example.com"
    elif change == "device":
        hs.device = "OTHER-DEVICE"
    elif change == "crypto":
        crypto = root / "matrix_crypto_store"
        (crypto / f"{BOT}_{DEVICE}.db").rename(crypto / "foreign-device.db")
    old_bytes = snapshot(root)
    values = factory_values(
        root, workspace, {**config, "homeserver": hs.url}, monkeypatch
    )
    platform = platform_factory(**values)
    with pytest.raises(RuntimeError):
        await platform.start()
    assert platform.observed_states == ["failed"]
    assert len(hs.calls("/login")) == 1
    assert not hs.calls("/sync")
    assert OLD_TOKEN not in json.dumps(hs.requests)
    for name, data in old_bytes.items():
        assert (root / name).read_bytes() == data
    assert not (root / "matrix_plugin_owner.json").exists()


def test_same_account_two_workspaces_cannot_first_claim_global_state(
    tmp_path, monkeypatch
):
    root, workspace, config = raw_case(
        tmp_path, "https://saved.invalid", ambiguous=True
    )
    old_bytes = snapshot(root)
    captured = capture(root)
    assert captured["capture_id"]
    for selected in (workspace, tmp_path / "B"):
        values = factory_values(root, selected, config, monkeypatch)
        assert assert_bounded_authority(values)["owner"] is None
    for name, data in old_bytes.items():
        assert (root / name).read_bytes() == data
    assert not (root / "matrix_plugin_owner.json").exists()


def test_first_capture_is_secret_free_and_never_reinterprets_changed_files(
    tmp_path, monkeypatch
):
    from qwenpaw.plugins.matrix_legacy import load_matrix_legacy

    root, workspace, config = raw_case(tmp_path, "https://saved.invalid")
    captured = capture(root)
    frozen = manifest(root).read_bytes()
    assert OLD_TOKEN.encode() not in frozen
    assert b"explicit-password" not in frozen
    assert (
        assert_bounded_authority(
            factory_values(root, workspace, config, monkeypatch)
        )["owner"]
        is not None
    )
    raw = json.loads((root / "config.json").read_text())
    raw["channels"]["matrix"]["homeserver"] = "https://changed.invalid"
    write_json(root / "config.json", raw)
    write_json(
        root / "matrix_auth_state.json",
        {
            "user_id": "@changed:example.com",
            "device_id": "NEW",
            "access_token": "changed-secret",
        },
    )
    changed = snapshot(root)
    assert capture(root) == captured
    assert load_matrix_legacy(legacy_state_dir=root) == captured
    assert manifest(root).read_bytes() == frozen
    assert snapshot(root) == changed


def test_factory_without_capture_is_readonly_and_overwrites_forged_authority(
    tmp_path, monkeypatch
):
    from qwenpaw.plugins.matrix_legacy import load_matrix_legacy

    root, workspace, config = raw_case(tmp_path, "https://saved.invalid")
    before = snapshot(root)
    forged = {"owner": {"workspace_dir": str(workspace)}, "token": OLD_TOKEN}
    assert load_matrix_legacy(legacy_state_dir=root) is None
    values = factory_values(
        root, workspace, {**config, "legacy_state_owner": forged}, monkeypatch
    )
    assert assert_bounded_authority(values)["owner"] is None
    assert snapshot(root) == before
    assert not manifest(root).exists()
    capture(root)
    values = factory_values(
        root, workspace, {**config, "legacy_state_owner": forged}, monkeypatch
    )
    assert assert_bounded_authority(values)["owner"] is not None
    assert values["legacy_state_owner"] != forged
    assert forged["token"] == OLD_TOKEN


def test_corrupt_capture_isolates_matrix_from_other_core_channel_migration(
    tmp_path, monkeypatch, caplog
):
    from qwenpaw.config import utils
    from qwenpaw.plugins.official_channels import initialize_channel_policy
    import qwenpaw.constant as constants

    root, _, _ = raw_case(tmp_path, "https://saved.invalid")
    raw = json.loads((root / "config.json").read_text())
    raw["channels"]["onebot"] = {"enabled": True}
    raw["channel_plugin_state"] = {
        "version": 1,
        "preset": "light",
        "legacy_pending": ["matrix"],
    }
    write_json(root / "config.json", raw)
    invalid = b'{"schema_version":1,"secret":"capture-secret-canary"}'
    path = manifest(root)
    path.parent.mkdir(parents=True)
    path.write_bytes(invalid)
    monkeypatch.setattr(constants, "WORKING_DIR", root)
    monkeypatch.setattr(constants, "PLUGINS_DIR", root / "plugins")
    monkeypatch.setattr(utils, "WORKING_DIR", root)
    monkeypatch.setattr(utils, "_config_cache", None)
    monkeypatch.setattr(utils, "_config_mtime", None)
    monkeypatch.delenv("QWENPAW_CHANNEL_PRESET", raising=False)
    initialize_channel_policy()
    state = utils.load_config().channel_plugin_state
    assert "matrix" not in state.legacy_pending
    assert "matrix" not in state.legacy_captured
    assert "onebot" in state.legacy_pending
    assert "onebot" in state.legacy_captured
    assert path.read_bytes() == invalid
    assert "MATRIX_LEGACY_CAPTURE_INVALID" in caplog.text
    assert "capture-secret-canary" not in caplog.text
    assert "explicit-password" not in caplog.text
