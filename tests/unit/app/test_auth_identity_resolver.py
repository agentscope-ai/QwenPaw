# -*- coding: utf-8 -*-
"""Unit tests for the external identity resolver registry in auth.py."""
from __future__ import annotations

import pytest

from qwenpaw.app.auth import (
    _external_identity_resolvers,
    _resolve_external_identity,
    has_external_identity_resolvers,
    register_external_identity_resolver,
    unregister_external_identity_resolver,
)


@pytest.fixture(autouse=True)
def _clear_resolvers():
    _external_identity_resolvers.clear()
    yield
    _external_identity_resolvers.clear()


def test_register_and_has():
    assert has_external_identity_resolvers() is False

    async def r(_request):
        return None

    register_external_identity_resolver(r)
    assert has_external_identity_resolvers() is True
    unregister_external_identity_resolver(r)
    assert has_external_identity_resolvers() is False


def test_register_is_idempotent():
    async def r(_request):
        return None

    register_external_identity_resolver(r)
    register_external_identity_resolver(r)
    assert len(_external_identity_resolvers) == 1


async def test_resolve_returns_first_non_none():
    async def r_none(_request):
        return None

    async def r_alice(_request):
        return "alice@example.com"

    register_external_identity_resolver(r_none)
    register_external_identity_resolver(r_alice)
    assert await _resolve_external_identity(object()) == "alice@example.com"


async def test_resolve_swallows_exceptions_and_continues():
    async def r_boom(_request):
        raise RuntimeError("boom")

    async def r_ok(_request):
        return "bob@example.com"

    register_external_identity_resolver(r_boom)
    register_external_identity_resolver(r_ok)
    assert await _resolve_external_identity(object()) == "bob@example.com"


async def test_resolve_all_none():
    async def r(_request):
        return None

    register_external_identity_resolver(r)
    assert await _resolve_external_identity(object()) is None
