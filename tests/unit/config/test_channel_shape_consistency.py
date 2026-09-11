# -*- coding: utf-8 -*-
"""Consistency guards for built-in channel shape declarations.

A built-in channel is declared in more than one place, and those places
must stay in sync.  ``ChannelConfig`` is the source of truth for the
config shape (this is what doctor already walks), while the registry
and the API layer keep their own lists.

These tests fail loudly when a newly added channel is missing from one
of those lists.  That drift is what made ``GET`` on a single channel
answer with an unrelated channel's fields for ``onebot``, and what let
``PUT`` write an unvalidated dict to disk.
"""

# pylint: disable=protected-access
from __future__ import annotations

from typing import get_args

from qwenpaw.app.channels.registry import _BUILTIN_SPECS
from qwenpaw.app.routers.config import _channel_config_class
from qwenpaw.config.config import ChannelConfig, ChannelConfigUnion


def _declared_config_classes() -> set[type]:
    """Config models declared as ``ChannelConfig`` fields."""
    return {field.annotation for field in ChannelConfig.model_fields.values()}


def test_builtin_specs_match_channel_config_fields() -> None:
    """Every built-in channel implementation has a config field."""
    assert set(_BUILTIN_SPECS) == set(ChannelConfig.model_fields)


def test_channel_config_union_covers_every_builtin_channel() -> None:
    """``ChannelConfigUnion`` must list every built-in config model.

    The single-channel endpoints use it as ``response_model``.  When a
    model is missing, FastAPI cannot match the returned instance and
    falls back to coercing it into another member, silently dropping
    the channel's own fields.
    """
    assert set(get_args(ChannelConfigUnion)) == _declared_config_classes()


def test_channel_config_class_resolves_every_builtin_channel() -> None:
    """PUT validation must find a model for every built-in channel."""
    for name, field in ChannelConfig.model_fields.items():
        assert _channel_config_class(name) is field.annotation


def test_channel_config_class_returns_none_for_plugin_channel() -> None:
    """Plugin channels are not declared, so they stay untyped dicts."""
    assert _channel_config_class("some_plugin_channel") is None
