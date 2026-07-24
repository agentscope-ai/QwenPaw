# -*- coding: utf-8 -*-
"""acl_roles injection into the console native payload."""
from __future__ import annotations

from qwenpaw.app.routers.console import _extract_session_and_payload


def test_acl_roles_injected_into_meta():
    payload = _extract_session_and_payload(
        {"user_id": "x", "session_id": "s", "input": []},
        acl_sender_id="u@x.io",
        acl_roles=["admin", "member"],
    )
    assert payload["acl_sender_id"] == "u@x.io"
    assert payload["meta"]["acl_sender_id"] == "u@x.io"
    assert payload["meta"]["acl_roles"] == ["admin", "member"]


def test_no_roles_absent_from_meta():
    payload = _extract_session_and_payload(
        {"user_id": "x", "session_id": "s", "input": []},
        acl_sender_id="u@x.io",
    )
    assert payload["meta"].get("acl_roles", []) == []


def test_roles_without_sender_still_injected():
    payload = _extract_session_and_payload(
        {"user_id": "x", "session_id": "s", "input": []},
        acl_roles=["admin"],
    )
    assert payload["meta"]["acl_roles"] == ["admin"]
