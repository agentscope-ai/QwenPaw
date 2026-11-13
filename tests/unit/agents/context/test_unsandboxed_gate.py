# -*- coding: utf-8 -*-
"""The unsandboxed-recall escape hatch is gated by deployment, not agent.json.

Running recall without a sandbox executes model-authored Python as the agent
user. ``scroll_unsandboxed_allowed`` must require BOTH the per-agent config
flag AND the deployment-layer ``QWENPAW_ALLOW_UNSANDBOXED_RECALL`` env var, so
an untrusted agent.json / API payload can never bypass the sandbox on its own.
"""

from types import SimpleNamespace

import pytest

from qwenpaw.agents.context import scroll_unsandboxed_allowed

_ENV = "QWENPAW_ALLOW_UNSANDBOXED_RECALL"


def _cfg(flag: bool) -> SimpleNamespace:
    return SimpleNamespace(allow_unsandboxed=flag)


def test_agent_flag_alone_is_not_enough(monkeypatch):
    # The attack: agent.json sets allow_unsandboxed=true with no env opt-in.
    monkeypatch.delenv(_ENV, raising=False)
    assert scroll_unsandboxed_allowed(_cfg(True)) is False


def test_env_alone_is_not_enough(monkeypatch):
    # Deployment allows it, but no agent requested it — stays sandboxed.
    monkeypatch.setenv(_ENV, "1")
    assert scroll_unsandboxed_allowed(_cfg(False)) is False


def test_both_required_grants(monkeypatch):
    monkeypatch.setenv(_ENV, "1")
    assert scroll_unsandboxed_allowed(_cfg(True)) is True


@pytest.mark.parametrize("val", ["true", "TRUE", "Yes", "on", " 1 "])
def test_truthy_env_values(monkeypatch, val):
    monkeypatch.setenv(_ENV, val)
    assert scroll_unsandboxed_allowed(_cfg(True)) is True


@pytest.mark.parametrize("val", ["", "0", "false", "no", "off", "nope"])
def test_non_truthy_env_values_deny(monkeypatch, val):
    monkeypatch.setenv(_ENV, val)
    assert scroll_unsandboxed_allowed(_cfg(True)) is False
