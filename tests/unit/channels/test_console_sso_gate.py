# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,redefined-outer-name
"""Identity resolver + NocoBase channel gate, wired together."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# Make bundled plugins importable: plugins/bundle is not on sys.path for
# the channels test tree (only tests/unit/plugins/ conftest adds it).
_bundle_dir = str(Path(__file__).parents[3] / "plugins" / "bundle")
if _bundle_dir not in sys.path:
    sys.path.insert(0, _bundle_dir)

from nocobase_auth.channel_gate import build_checker  # noqa: E402
from nocobase_auth.identity_cache import TokenIdentityCache  # noqa: E402
from nocobase_auth.identity_resolver import (  # noqa: E402
    build_identity_resolver,
)
from nocobase_auth.permission_store import PermissionStore  # noqa: E402


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


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmp:
        s = PermissionStore(path=Path(tmp) / "perms.json")
        s.update_from_sync(
            users=[
                {
                    "id": "1",
                    "sender_id": "member@x.com",
                    "roles": ["member"],
                },
                {
                    "id": "2",
                    "sender_id": "boss@x.com",
                    "roles": ["admin"],
                },
            ],
            roles=[
                {"id": "1", "name": "member", "title": "Member"},
                {"id": "2", "name": "admin", "title": "Admin"},
            ],
            role_channel_map={
                "member": {"allowed": [], "denied": ["console"]},
                "admin": {"allowed": ["console"], "denied": []},
            },
        )
        yield s


async def _resolved_verdict(store, user):
    resolver = build_identity_resolver(
        _Engine(user),
        TokenIdentityCache(ttl_seconds=60, time_fn=lambda: 0.0),
    )
    sender_id = await resolver(_Req({"X-NocoBase-Token": "t"}))
    checker = build_checker(store, lambda: True)
    return checker("console", sender_id or "", {})


@pytest.mark.p0
async def test_member_denied(store) -> None:
    verdict = await _resolved_verdict(
        store,
        {"id": "1", "email": "member@x.com"},
    )
    assert verdict == "deny"


@pytest.mark.p0
async def test_admin_allowed(store) -> None:
    verdict = await _resolved_verdict(
        store,
        {"id": "2", "email": "boss@x.com"},
    )
    assert verdict == "allow"


@pytest.mark.p0
async def test_unknown_user_denied_fail_closed(store) -> None:
    verdict = await _resolved_verdict(
        store,
        {"id": "9", "email": "ghost@x.com"},
    )
    assert verdict == "deny"  # console fail-closed for unknown
