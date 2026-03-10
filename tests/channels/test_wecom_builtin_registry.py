# -*- coding: utf-8 -*-

from copaw.app.channels.registry import get_channel_registry


def test_wecom_builtin_registered():
    registry = get_channel_registry()
    assert "wecom" in registry
