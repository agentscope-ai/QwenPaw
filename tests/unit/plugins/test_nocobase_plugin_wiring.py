# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""The plugin registers/unregisters an identity resolver with core auth."""
from __future__ import annotations

import pytest

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

    # Avoid real network sync: stub SyncEngine.start.
    from nocobase_auth import sync_engine as se

    async def _noop_start(self):
        return None

    monkeypatch.setattr(se.SyncEngine, "start", _noop_start)

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


async def test_login_authenticator_raises_denied_when_console_acl_denies(
    monkeypatch,
) -> None:
    plugin = await _started_plugin(monkeypatch)
    engine = plugin._sync_engine

    async def _valid_credentials(_username, _password):
        return ("blocked@example.com", "nb-token")

    monkeypatch.setattr(
        engine,
        "authenticate_credentials",
        _valid_credentials,
    )
    monkeypatch.setattr(
        engine.store,
        "is_channel_allowed",
        lambda _sender, _channel: False,
    )

    authenticator = auth_mod._external_login_authenticators[0]
    with pytest.raises(auth_mod.ExternalLoginDenied):
        await authenticator("blocked@example.com", "correct-pw")

    await plugin._on_uninstall("nocobase-auth", delete_files=False)


async def test_login_authenticator_returns_identity_when_acl_allows(
    monkeypatch,
) -> None:
    plugin = await _started_plugin(monkeypatch)
    engine = plugin._sync_engine

    async def _valid_credentials(_username, _password):
        return ("member@example.com", "nb-token")

    monkeypatch.setattr(
        engine,
        "authenticate_credentials",
        _valid_credentials,
    )
    monkeypatch.setattr(
        engine.store,
        "is_channel_allowed",
        lambda _sender, _channel: True,
    )

    authenticator = auth_mod._external_login_authenticators[0]
    result = await authenticator("member@example.com", "correct-pw")
    # The authenticator passes through the NocoBase-issued token so the
    # provider owns the token system end-to-end.
    assert result == auth_mod.ExternalLogin(
        identity="member@example.com",
        token="nb-token",
    )

    await plugin._on_uninstall("nocobase-auth", delete_files=False)


async def test_login_authenticator_skips_acl_for_bad_credentials(
    monkeypatch,
) -> None:
    plugin = await _started_plugin(monkeypatch)
    engine = plugin._sync_engine

    async def _invalid_credentials(_username, _password):
        return None

    def _never_called(_sender, _channel):
        raise AssertionError("ACL must not run for invalid credentials")

    monkeypatch.setattr(
        engine,
        "authenticate_credentials",
        _invalid_credentials,
    )
    monkeypatch.setattr(engine.store, "is_channel_allowed", _never_called)

    authenticator = auth_mod._external_login_authenticators[0]
    assert await authenticator("nobody@example.com", "wrong") is None

    await plugin._on_uninstall("nocobase-auth", delete_files=False)
