# -*- coding: utf-8 -*-

from copaw.app.routers.console import _MAX_AUTH_DEBUG_VALUE_LENGTH, _sanitize_auth_debug_event


def test_sanitize_auth_debug_event_drops_sensitive_and_unknown_fields() -> None:
    payload = {
        "event": "login",
        "stage": "failed",
        "phone": "******1234",
        "password": "secret",
        "smsCode": "123456",
        "token": "abc",
        "unknown": "ignored",
    }

    sanitized = _sanitize_auth_debug_event(payload)

    assert sanitized == {
        "event": "login",
        "stage": "failed",
        "phone": "******1234",
    }


def test_sanitize_auth_debug_event_truncates_long_values() -> None:
    payload = {
        "event": "register",
        "stage": "failed",
        "error": "x" * (_MAX_AUTH_DEBUG_VALUE_LENGTH + 10),
    }

    sanitized = _sanitize_auth_debug_event(payload)

    assert len(sanitized["error"]) == _MAX_AUTH_DEBUG_VALUE_LENGTH
    assert sanitized["event"] == "register"
    assert sanitized["stage"] == "failed"

