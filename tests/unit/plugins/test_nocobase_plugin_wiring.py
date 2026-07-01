# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""The plugin registers/unregisters an identity resolver with core auth."""
from __future__ import annotations

import pytest

from qwenpaw.app import auth as auth_mod


@pytest.fixture(autouse=True)
def _clear():
    auth_mod._external_identity_resolvers.clear()
    yield
    auth_mod._external_identity_resolvers.clear()


async def test_startup_registers_and_uninstall_removes(monkeypatch) -> None:
    from nocobase_auth.plugin import NocoBaseAuthPlugin

    # Avoid real network sync: stub SyncEngine.start.
    from nocobase_auth import sync_engine as se

    async def _noop_start(self):
        return None

    monkeypatch.setattr(se.SyncEngine, "start", _noop_start)

    plugin = NocoBaseAuthPlugin()
    await plugin._on_startup()
    assert auth_mod.has_external_identity_resolvers() is True

    await plugin._on_uninstall("nocobase-auth", delete_files=False)
    assert auth_mod.has_external_identity_resolvers() is False
