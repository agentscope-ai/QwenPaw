"""C6 password reauthentication must retain legitimately bound old state."""

import hashlib
import json

from nio import AsyncClient
import pytest

from matrix_native_support import BOT, hs, platform_factory, until

__all__ = ["hs", "platform_factory"]


@pytest.mark.asyncio
async def test_password_login_new_token_restores_unclaimed_legacy_state(
    hs, platform_factory, tmp_path, monkeypatch
):
    from qwenpaw.config.config import AgentProfileRef, Config
    from qwenpaw.config.utils import save_config

    legacy = tmp_path / "legacy"
    crypto = legacy / "matrix_crypto_store"
    crypto.mkdir(parents=True)
    workspace = tmp_path / "A"
    workspace.mkdir()
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path", lambda: legacy / "config.json"
    )
    config = Config()
    config.channels.matrix.homeserver = hs.url
    config.channels.matrix.user_id = BOT
    config.channels.matrix.password = "explicit-password"
    config.channels.matrix.access_token = ""
    config.agents.active_agent = "A"
    config.agents.profiles = {
        "A": AgentProfileRef(id="A", workspace_dir=str(workspace))
    }
    save_config(config)
    persisted = json.loads((legacy / "config.json").read_text())
    assert persisted["channels"]["matrix"]["homeserver"] == hs.url
    assert persisted["channels"]["matrix"]["access_token"] == ""
    assert persisted["agents"]["profiles"]["A"]["workspace_dir"] == str(
        workspace
    )
    old = {
        "matrix_auth_state.json": json.dumps(
            {
                "user_id": BOT,
                "device_id": "SERVER-DEVICE",
                "access_token": "old-cached-token-never-transmit",
            }
        ).encode(),
        "matrix_sync_token": b"legacy-batch",
        "matrix_crypto_store/"
        + BOT
        + "_SERVER-DEVICE.db": (b"opaque-real-crypto-sentinel-no-olm-claim"),
    }
    for name, data in old.items():
        (legacy / name).write_bytes(data)
    old["config.json"] = (legacy / "config.json").read_bytes()
    assert not (legacy / "matrix_plugin_owner.json").exists()
    from matrix_c6_capture_support import capture, factory_values

    capture(legacy)
    capture_bytes = (
        legacy / "channel_state/matrix/legacy-capture.json"
    ).read_bytes()
    assert b"old-cached-token-never-transmit" not in capture_bytes
    assert b"explicit-password" not in capture_bytes
    projected = factory_values(
        legacy,
        workspace,
        {
            **config.channels.matrix.model_dump(),
            "enabled": True,
            "device_id": "SERVER-DEVICE",
        },
        monkeypatch,
    )
    assert set(projected["legacy_state_owner"]) == {
        "schema_version",
        "capture_id",
        "owner",
        "auth_sha256",
    }
    assert projected["legacy_state_owner"]["owner"] is not None
    assert not (legacy / "matrix_plugin_owner.json").exists()
    platform = platform_factory(**projected)
    try:
        await platform.start()
        assert isinstance(platform._client, AsyncClient)
        assert platform._client.access_token == "password-result-token"
        assert platform.observed_states == ["connected"]
        assert platform._state.crypto_dir == crypto
        assert not (platform._state.directory / "crypto_store").exists()
        await until(lambda: len(hs.calls("/sync")) == 1)
        assert hs.calls("/sync")[0]["query"]["since"] == "legacy-batch"
    finally:
        after = {name: (legacy / name).read_bytes() for name in old}
        evidence = {
            "before_sha256": {
                name: hashlib.sha256(data).hexdigest()
                for name, data in old.items()
            },
            "after_sha256": {
                name: hashlib.sha256(data).hexdigest()
                for name, data in after.items()
            },
            "requests": hs.requests,
            "states": platform.observed_states,
            "legacy_owner_exists": (
                legacy / "matrix_plugin_owner.json"
            ).exists(),
        }
        (tmp_path / "c6-state-evidence.json").write_text(
            json.dumps(evidence, indent=2)
        )
        assert after == old
        assert len(hs.calls("/login")) == 1
        assert hs.calls("/login")[0]["body"]["password"] == (
            "explicit-password"
        )
        assert "old-cached-token-never-transmit" not in json.dumps(hs.requests)
