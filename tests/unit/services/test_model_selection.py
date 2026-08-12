# -*- coding: utf-8 -*-
"""Tests for canonical request-to-global model resolution."""

from types import SimpleNamespace

from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.services.model_selection import (
    parse_model_slot,
    resolve_effective_model_slot,
    session_model_slot,
)


def _slot(name: str) -> ModelSlotConfig:
    return ModelSlotConfig(provider_id="provider", model=name)


def test_parse_model_slot_accepts_slot_like_objects() -> None:
    value = SimpleNamespace(provider_id="provider", model="compatible")

    assert parse_model_slot(value) == _slot("compatible")


def test_model_resolution_follows_canonical_priority() -> None:
    chat_meta = {
        "runtime_context": {
            "model_slot_override": _slot("session").model_dump(),
        },
    }
    slot, source = resolve_effective_model_slot(
        request_override=_slot("request"),
        chat_meta=chat_meta,
        agent_model=_slot("agent"),
        global_model=_slot("global"),
    )
    assert slot == _slot("request")
    assert source == "request"


def test_model_resolution_falls_back_through_session_agent_and_global() -> (
    None
):
    chat_meta = {
        "runtime_context": {
            "model_slot_override": _slot("session").model_dump(),
        },
    }
    assert resolve_effective_model_slot(
        chat_meta=chat_meta,
        agent_model=_slot("agent"),
        global_model=_slot("global"),
    ) == (_slot("session"), "session")
    assert resolve_effective_model_slot(
        agent_model=_slot("agent"),
        global_model=_slot("global"),
    ) == (_slot("agent"), "agent")
    assert resolve_effective_model_slot(
        global_model=_slot("global"),
    ) == (_slot("global"), "global")


def test_session_model_slot_ignores_unrelated_or_invalid_metadata() -> None:
    assert (
        session_model_slot({"runtime_context": {"project_dir": "/tmp"}})
        is None
    )
    assert (
        session_model_slot(
            {"runtime_context": {"model_slot_override": {"model": "missing"}}},
        )
        is None
    )
