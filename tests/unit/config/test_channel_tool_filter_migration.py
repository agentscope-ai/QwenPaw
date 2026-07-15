# -*- coding: utf-8 -*-
"""Tests for legacy channel tool filter config migration."""

from __future__ import annotations

from qwenpaw.config.config import _migrate_tool_filter_fields


def test_migrate_true_filter_tool_messages_sets_split_filters():
    channels = {
        "dingtalk": {
            "enabled": True,
            "filter_tool_messages": True,
        },
    }

    assert _migrate_tool_filter_fields(channels)
    assert "filter_tool_messages" not in channels["dingtalk"]
    assert channels["dingtalk"]["filter_tool_calls"] is True
    assert channels["dingtalk"]["filter_tool_outputs"] is True


def test_migrate_false_filter_tool_messages_only_drops_legacy_field():
    channels = {
        "dingtalk": {
            "enabled": True,
            "filter_tool_messages": False,
        },
    }

    assert _migrate_tool_filter_fields(channels)
    assert channels["dingtalk"] == {"enabled": True}


def test_migrate_filter_tool_messages_preserves_existing_split_filters():
    channels = {
        "dingtalk": {
            "enabled": True,
            "filter_tool_messages": True,
            "filter_tool_calls": False,
        },
    }

    assert _migrate_tool_filter_fields(channels)
    assert "filter_tool_messages" not in channels["dingtalk"]
    assert channels["dingtalk"]["filter_tool_calls"] is False
    assert channels["dingtalk"]["filter_tool_outputs"] is True
