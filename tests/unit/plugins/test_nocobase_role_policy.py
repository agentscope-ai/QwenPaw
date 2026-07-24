# -*- coding: utf-8 -*-
"""Unit tests for role→channel policy evaluation."""
from __future__ import annotations

from nocobase_auth.config import RoleChannelMapping
from nocobase_auth.role_policy import evaluate_role_channel


def _map():
    return [
        RoleChannelMapping(role_name="admin", allowed_channels=["console"]),
        RoleChannelMapping(role_name="banned", denied_channels=["console"]),
    ]


def test_empty_map_returns_none():
    assert evaluate_role_channel(["admin"], "console", []) is None


def test_allowed_role_returns_true():
    assert evaluate_role_channel(["admin"], "console", _map()) is True


def test_denied_role_returns_false():
    assert evaluate_role_channel(["banned"], "console", _map()) is False


def test_deny_precedes_allow():
    assert (
        evaluate_role_channel(["admin", "banned"], "console", _map()) is False
    )


def test_unmentioned_channel_returns_none():
    assert evaluate_role_channel(["admin"], "feishu", _map()) is None


def test_empty_roles_returns_none():
    assert evaluate_role_channel([], "console", _map()) is None
