# -*- coding: utf-8 -*-
"""Unit tests for agent_context — context variable getters/setters."""
from __future__ import annotations

from qwenpaw.app import agent_context


def test_current_agent_id_round_trip():
    agent_context.set_current_agent_id("agent-42")
    assert agent_context.get_current_agent_id() == "agent-42"
    # Reset to avoid polluting other tests
    agent_context.set_current_agent_id("default")


def test_current_session_id():
    agent_context.set_current_session_id("sess-abc")
    assert agent_context.get_current_session_id() == "sess-abc"
    agent_context.set_current_session_id(None)


def test_current_user_id():
    agent_context.set_current_user_id("u1")
    assert agent_context.get_current_user_id() == "u1"
    agent_context.set_current_user_id(None)


def test_current_channel():
    agent_context.set_current_channel("discord")
    assert agent_context.get_current_channel() == "discord"
    agent_context.set_current_channel(None)


def test_root_session_id():
    agent_context.set_current_root_session_id("root-sess")
    assert agent_context.get_current_root_session_id() == "root-sess"
    agent_context.set_current_root_session_id(None)
