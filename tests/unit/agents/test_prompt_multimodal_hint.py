# -*- coding: utf-8 -*-
"""Tests for the per-agent TTL cache behind ``build_multimodal_hint``."""

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Iterator

import pytest

from qwenpaw.agents import prompt as prompt_module
from qwenpaw.agents.prompt import build_multimodal_hint
from qwenpaw.app.agent_context import set_current_agent_id

# A text-only model: the only configuration that renders a non-empty hint.
_TEXT_ONLY_MODEL = SimpleNamespace(
    supports_image=False,
    supports_video=False,
    supports_multimodal=False,
)


@contextmanager
def _agent_context(agent_id: str) -> Iterator[None]:
    set_current_agent_id(agent_id)
    try:
        yield
    finally:
        set_current_agent_id("")


@pytest.fixture(autouse=True)
def _clean_cache():
    prompt_module._MULTIMODAL_HINT_CACHE.clear()
    yield
    prompt_module._MULTIMODAL_HINT_CACHE.clear()


def _install_resolver(monkeypatch, results):
    """Serve ``results`` one per call and count resolutions."""
    calls = {"n": 0}

    def fake_resolve():
        calls["n"] += 1
        return results[min(calls["n"] - 1, len(results) - 1)]

    monkeypatch.setattr(prompt_module, "_get_active_model_info", fake_resolve)
    return calls


def test_hint_resolved_once_per_agent_within_ttl(monkeypatch):
    calls = _install_resolver(
        monkeypatch, [(_TEXT_ONLY_MODEL, "text-only-model")]
    )

    with _agent_context("agent-a"):
        first = build_multimodal_hint()
        second = build_multimodal_hint()

    assert first == second
    assert first != ""
    assert calls["n"] == 1


def test_hint_is_not_shared_across_agents(monkeypatch):
    # Two agents, different active models: one text-only (non-empty hint),
    # one multimodal (empty hint). A shared slot would hand one agent the
    # other agent's hint.
    calls = _install_resolver(
        monkeypatch,
        [(_TEXT_ONLY_MODEL, "text-only"), (SimpleNamespace(
            supports_image=True, supports_video=False, supports_multimodal=None
        ), "vision-model")],
    )

    with _agent_context("agent-a"):
        hint_a = build_multimodal_hint()
    with _agent_context("agent-b"):
        hint_b = build_multimodal_hint()

    assert hint_a != ""  # text-only: advisory hint present
    assert hint_b == ""  # vision model: no hint
    assert calls["n"] == 2


def test_unresolved_model_is_not_cached(monkeypatch):
    # First resolution fails (model not yet configured), then succeeds.
    # The empty result must not be pinned for the TTL window.
    calls = _install_resolver(
        monkeypatch,
        [(None, None), (_TEXT_ONLY_MODEL, "text-only-model")],
    )

    with _agent_context("agent-a"):
        assert build_multimodal_hint() == ""
        assert build_multimodal_hint() != ""

    assert calls["n"] == 2
