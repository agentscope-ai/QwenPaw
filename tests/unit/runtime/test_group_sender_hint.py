# -*- coding: utf-8 -*-
"""Tests for GroupSenderHintContributor (group-chat sender prompt hint)."""

from types import SimpleNamespace

from qwenpaw.runtime.prompt_contributors import GroupSenderHintContributor


def _ctx(channel_meta):
    request = SimpleNamespace(channel_meta=channel_meta)
    return SimpleNamespace(request=request)


def test_hint_emitted_for_group_request() -> None:
    out = GroupSenderHintContributor().contribute_sync(
        _ctx({"is_group": True}),
    )
    assert out is not None
    assert '<msg sender=' in out


def test_hint_absent_for_non_group_request() -> None:
    assert (
        GroupSenderHintContributor().contribute_sync(
            _ctx({"is_group": False}),
        )
        is None
    )


def test_hint_absent_when_no_channel_meta() -> None:
    assert (
        GroupSenderHintContributor().contribute_sync(_ctx(None)) is None
    )


def test_hint_absent_when_no_request() -> None:
    assert (
        GroupSenderHintContributor().contribute_sync(SimpleNamespace())
        is None
    )
