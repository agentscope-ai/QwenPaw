# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""The plugin registers/unregisters identity+login hooks with core auth."""
from __future__ import annotations

import pytest

from nocobase_auth.config import NocoBaseAuthConfig, RoleChannelMapping

from qwenpaw.app import auth as auth_mod


@pytest.fixture(autouse=True)
def _clear():
    auth_mod._external_identity_resolvers.clear()
    auth_mod._external_login_authenticators.clear()
    yield
    auth_mod._external_identity_resolvers.clear()
    auth_mod._external_login_authenticators.clear()


async def _started_plugin(monkeypatch):
    from nocobase_auth.plugin import NocoBaseAuthPlugin
    from nocobase_auth import engine as eng_mod

    async def _noop_start(self):
        return None

    monkeypatch.setattr(eng_mod.NocoBaseEngine, "start", _noop_start)
    monkeypatch.setattr(
        NocoBaseAuthConfig,
        "seed_from_env",
        classmethod(lambda cls, path=None: False),
    )

    plugin = NocoBaseAuthPlugin()
    await plugin._on_startup()
    return plugin


async def test_startup_registers_and_uninstall_removes(monkeypatch) -> None:
    plugin = await _started_plugin(monkeypatch)
    assert auth_mod.has_external_identity_resolvers() is True
    assert len(auth_mod._external_login_authenticators) == 1

    await plugin._on_uninstall("nocobase-auth", delete_files=False)
    assert auth_mod.has_external_identity_resolvers() is False
    assert len(auth_mod._external_login_authenticators) == 0


async def test_login_denied_when_role_denies_console(monkeypatch) -> None:
    plugin = await _started_plugin(monkeypatch)
    engine = plugin._engine
    engine.config = NocoBaseAuthConfig(
        enabled=True,
        base_url="http://nb.local",
        role_channel_map=[
            RoleChannelMapping(
                role_name="blocked",
                denied_channels=["console"],
            ),
        ],
    )

    async def _creds(_u, _p):
        return ("blocked@example.com", "nb-token")

    async def _verify(_tok):
        return {
            "email": "blocked@example.com",
            "roles": [{"name": "blocked"}],
        }

    monkeypatch.setattr(engine, "authenticate_credentials", _creds)
    monkeypatch.setattr(engine, "verify_user_token", _verify)

    authenticator = auth_mod._external_login_authenticators[0]
    with pytest.raises(auth_mod.ExternalLoginDenied):
        await authenticator("blocked@example.com", "correct-pw")

    await plugin._on_uninstall("nocobase-auth", delete_files=False)


async def test_login_returns_identity_when_allowed(monkeypatch) -> None:
    plugin = await _started_plugin(monkeypatch)
    engine = plugin._engine
    engine.config = NocoBaseAuthConfig(
        enabled=True,
        base_url="http://nb.local",
        role_channel_map=[],
    )

    async def _creds(_u, _p):
        return ("member@example.com", "nb-token")

    async def _verify(_tok):
        return {"email": "member@example.com", "roles": [{"name": "member"}]}

    monkeypatch.setattr(engine, "authenticate_credentials", _creds)
    monkeypatch.setattr(engine, "verify_user_token", _verify)

    authenticator = auth_mod._external_login_authenticators[0]
    result = await authenticator("member@example.com", "correct-pw")
    assert result == auth_mod.ExternalLogin(
        identity="member@example.com",
        token="nb-token",
    )

    await plugin._on_uninstall("nocobase-auth", delete_files=False)


async def test_login_skips_acl_for_bad_credentials(monkeypatch) -> None:
    plugin = await _started_plugin(monkeypatch)
    engine = plugin._engine

    async def _invalid(_u, _p):
        return None

    async def _verify_never(_tok):
        raise AssertionError("verify must not run for invalid credentials")

    monkeypatch.setattr(engine, "authenticate_credentials", _invalid)
    monkeypatch.setattr(engine, "verify_user_token", _verify_never)

    authenticator = auth_mod._external_login_authenticators[0]
    assert await authenticator("nobody@example.com", "wrong") is None

    await plugin._on_uninstall("nocobase-auth", delete_files=False)
