# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,redefined-outer-name
"""Identity resolver + NocoBase channel gate, wired together (live roles)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make bundled plugins importable: plugins/bundle is not on sys.path for the
# channels test tree (only tests/unit/plugins/ conftest adds it).
_bundle_dir = str(Path(__file__).parents[3] / "plugins" / "bundle")
if _bundle_dir not in sys.path:
    sys.path.insert(0, _bundle_dir)

from nocobase_auth.channel_gate import build_checker  # noqa: E402
from nocobase_auth.config import (  # noqa: E402
    NocoBaseAuthConfig,
    RoleChannelMapping,
)
from nocobase_auth.identity_cache import TokenIdentityCache  # noqa: E402
from nocobase_auth.identity_resolver import (  # noqa: E402
    build_identity_resolver,
)


class _Cfg:
    enabled = True
    user_id_field = "email"


class _Engine:
    def __init__(self, user):
        self.config = _Cfg()
        self._user = user

    async def verify_user_token(self, _token):
        return self._user


class _Req:
    def __init__(self, headers):
        self.headers = headers


def _config():
    return NocoBaseAuthConfig(
        enabled=True,
        base_url="http://nb.local",
        role_channel_map=[
            RoleChannelMapping(
                role_name="member",
                denied_channels=["console"],
            ),
            RoleChannelMapping(
                role_name="admin",
                allowed_channels=["console"],
            ),
        ],
    )


async def _resolved_verdict(user):
    resolver = build_identity_resolver(
        _Engine(user),
        TokenIdentityCache(ttl_seconds=60, time_fn=lambda: 0.0),
    )
    identity = await resolver(_Req({"X-NocoBase-Token": "t"}))
    checker = build_checker(_config, lambda: True)
    sender_id = identity.sender_id if identity else ""
    roles = identity.roles if identity else []
    return checker("console", sender_id, {"acl_roles": roles})


@pytest.mark.p0
async def test_member_denied() -> None:
    verdict = await _resolved_verdict(
        {"id": "1", "email": "member@x.com", "roles": [{"name": "member"}]},
    )
    assert verdict == "deny"


@pytest.mark.p0
async def test_admin_allowed() -> None:
    verdict = await _resolved_verdict(
        {"id": "2", "email": "boss@x.com", "roles": [{"name": "admin"}]},
    )
    assert verdict == "allow"


@pytest.mark.p0
async def test_unauthenticated_denied_fail_closed() -> None:
    # An invalid/absent NocoBase token resolves to no identity -> the console
    # fail-closed gate denies it.
    verdict = await _resolved_verdict(None)
    assert verdict == "deny"
