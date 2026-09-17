# -*- coding: utf-8 -*-
"""Tests for Console subagent chat registration metadata."""

from qwenpaw.app.routers.console import _chat_registration_fields


def test_subagent_registration_fields_are_first_class():
    payload = {
        "meta": {
            "request_context": {
                "_spawn_subagent": True,
                "parent_session_id": "parent",
                "root_session_id": "root",
            },
        },
    }

    assert _chat_registration_fields(payload) == {
        "source": "subagent",
        "parent_session_id": "parent",
        "root_session_id": "root",
    }


def test_regular_chat_does_not_accept_subagent_relationship_fields():
    payload = {
        "meta": {
            "request_context": {
                "parent_session_id": "parent",
                "root_session_id": "root",
            },
        },
    }

    assert not _chat_registration_fields(payload)
