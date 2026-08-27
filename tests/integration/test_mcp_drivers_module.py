# -*- coding: utf-8 -*-
"""Integration tests for MCP & Drivers module internals.

Covers src/qwenpaw/agents/acp/* and src/qwenpaw/drivers/* (module
level, 1,962 uncovered lines): acp service helpers, credentials
providers, driver types.
"""

from __future__ import annotations

import asyncio

import pytest


# ------------------------------------------------------------------ #
# acp service helpers
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_acp_resolve_process_command_found() -> None:
    """_resolve_process_command resolves an existing binary via PATH."""
    from qwenpaw.agents.acp.service import _resolve_process_command

    import os

    resolved = _resolve_process_command("python3", dict(os.environ))
    lowered = resolved.lower()
    assert (
        lowered.endswith("python3")
        or lowered.endswith("python3.exe")
        or "/" in resolved
        or "\\" in resolved
    )


@pytest.mark.integration
@pytest.mark.p1
def test_acp_resolve_process_command_missing() -> None:
    """_resolve_process_command falls back to the raw command."""
    from qwenpaw.agents.acp.service import _resolve_process_command

    resolved = _resolve_process_command(
        "integ-nonexistent-binary",
        {"PATH": "/nonexistent"},
    )
    assert resolved == "integ-nonexistent-binary"


@pytest.mark.integration
@pytest.mark.p1
def test_acp_kill_process_tree_noop() -> None:
    """_kill_process_tree tolerates a dead pid."""
    from qwenpaw.agents.acp.service import _kill_process_tree

    # pid 0 / negative are invalid; use a large unlikely pid
    _kill_process_tree(999999999)


# ------------------------------------------------------------------ #
# credentials providers
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_none_provider_resolves_empty() -> None:
    """NoneProvider resolves to an empty credential."""
    from qwenpaw.drivers.credentials.providers import NoneProvider

    provider = NoneProvider()
    cred = asyncio.run(provider.resolve())
    assert cred.kind == "none"
    assert cred.secrets == {}


@pytest.mark.integration
@pytest.mark.p1
def test_resolved_credential_values_merge() -> None:
    """ResolvedCredential.values merges public and secrets."""
    from qwenpaw.drivers.credentials.types import ResolvedCredential

    cred = ResolvedCredential(
        kind="token",
        public={"user": "u"},
        secrets={"token": "t"},
    )
    assert cred.values == {"user": "u", "token": "t"}


@pytest.mark.integration
@pytest.mark.p1
def test_is_transient_oauth_status() -> None:
    """_is_transient_oauth_status flags 429/503, not 401."""
    import httpx

    from qwenpaw.drivers.credentials.providers import (
        _is_transient_oauth_status,
    )

    def _err(code):
        request = httpx.Request("POST", "http://x")
        response = httpx.Response(code, request=request)
        return httpx.HTTPStatusError("e", request=request, response=response)

    assert _is_transient_oauth_status(_err(429)) is True
    assert _is_transient_oauth_status(_err(503)) is True
    assert _is_transient_oauth_status(_err(401)) is False


# ------------------------------------------------------------------ #
# driver types
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_driver_card_construct() -> None:
    """DriverCard builds with required fields and defaults."""
    from qwenpaw.drivers.contracts import DriverCard

    card = DriverCard(
        name="integ-driver",
        protocol="mcp",
        endpoint={"command": "echo"},
    )
    assert card.name == "integ-driver"
    assert card.enabled is True
    assert not card.credentials
