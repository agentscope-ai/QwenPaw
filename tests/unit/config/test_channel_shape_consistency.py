# -*- coding: utf-8 -*-
"""Consistency guards for legacy channel shape declarations.

``ChannelConfig`` retains legacy config shapes while official channels
move to plugins. Its fields must have built-in or official owners; new
plugin-only channels need not add legacy config fields. The union and
API layer must still cover every declared legacy shape.

These tests fail loudly when a declared legacy shape is missing from
one of those lists. That drift is what made ``GET`` on a single channel
answer with an unrelated channel's fields for ``onebot``, and what let
``PUT`` write an unvalidated dict to disk.
"""

# pylint: disable=protected-access
from __future__ import annotations

from typing import get_args

from qwenpaw.app.channels.registry import _BUILTIN_SPECS
from qwenpaw.app.routers.config import _channel_config_class
from qwenpaw.config.config import ChannelConfig, ChannelConfigUnion
from qwenpaw.plugins.official_channel_catalog import official_channel_owners


def _declared_config_classes() -> set[type]:
    """Config models declared as ``ChannelConfig`` fields."""
    return {field.annotation for field in ChannelConfig.model_fields.values()}


def test_builtin_specs_match_channel_config_fields() -> None:
    """Legacy fields have owners; every built-in keeps its config shape."""
    builtin = set(_BUILTIN_SPECS)
    official = set(official_channel_owners())
    legacy = set(ChannelConfig.model_fields)
    assert builtin.isdisjoint(official)
    assert builtin <= legacy
    assert legacy <= builtin | official


def test_channel_config_union_covers_every_builtin_channel() -> None:
    """``ChannelConfigUnion`` must list every built-in config model.

    The single-channel endpoints use it as ``response_model``.  When a
    model is missing, FastAPI cannot match the returned instance and
    falls back to coercing it into another member, silently dropping
    the channel's own fields.
    """
    assert _declared_config_classes() <= set(get_args(ChannelConfigUnion))


def test_channel_config_class_resolves_every_builtin_channel() -> None:
    """PUT validation must find a model for every built-in channel."""
    for name, field in ChannelConfig.model_fields.items():
        assert _channel_config_class(name) is field.annotation


def test_channel_config_class_returns_none_for_plugin_channel() -> None:
    """Plugin channels are not declared, so they stay untyped dicts."""
    assert _channel_config_class("some_plugin_channel") is None
