# -*- coding: utf-8 -*-
"""Unit tests for the live-role NocoBase channel gate checker."""
from __future__ import annotations

from nocobase_auth.channel_gate import build_checker
from nocobase_auth.config import NocoBaseAuthConfig, RoleChannelMapping


def _checker(mappings, enabled=True):
    config = NocoBaseAuthConfig(enabled=enabled, role_channel_map=mappings)
    return build_checker(lambda: config, is_enabled=lambda: enabled)


def test_console_no_identity_denies_when_enabled():
    checker = _checker([])
    assert checker("console", "", {}) == "deny"


def test_console_known_user_default_allows():
    checker = _checker([])
    assert checker("console", "u@x.io", {"acl_roles": ["member"]}) == "allow"


def test_console_denied_role_blocks():
    checker = _checker(
        [RoleChannelMapping(role_name="banned", denied_channels=["console"])]
    )
    assert checker("console", "u@x.io", {"acl_roles": ["banned"]}) == "deny"


def test_console_allow_list_excludes_other_roles():
    checker = _checker(
        [RoleChannelMapping(role_name="admin", allowed_channels=["console"])]
    )
    # allow-list exists for console but caller lacks the role -> no explicit
    # opinion -> fail-closed channel still allows an authenticated user.
    assert checker("console", "u@x.io", {"acl_roles": ["member"]}) == "allow"


def test_console_explicit_allow_role():
    checker = _checker(
        [RoleChannelMapping(role_name="admin", allowed_channels=["console"])]
    )
    assert checker("console", "u@x.io", {"acl_roles": ["admin"]}) == "allow"


def test_disabled_plugin_never_blocks():
    checker = _checker([], enabled=False)
    assert checker("console", "", {}) is None


def test_non_failclosed_channel_no_opinion_falls_through():
    checker = _checker([])
    assert checker("feishu", "someone", {"acl_roles": []}) is None


def test_non_failclosed_channel_explicit_deny():
    checker = _checker(
        [RoleChannelMapping(role_name="x", denied_channels=["feishu"])]
    )
    assert checker("feishu", "someone", {"acl_roles": ["x"]}) == "deny"
