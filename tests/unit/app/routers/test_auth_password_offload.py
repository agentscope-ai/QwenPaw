# -*- coding: utf-8 -*-
"""Expensive password hashing must not run on the ASGI event loop."""
from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from starlette.requests import Request

from qwenpaw.app.routers import auth


@pytest.mark.parametrize("operation", ["login", "register", "update"])
async def test_password_operations_run_outside_event_loop(
    monkeypatch,
    operation,
):
    loop_thread = threading.get_ident()
    worker_threads = []
    calls = []

    def password_operation(*args, **kwargs):
        worker_threads.append(threading.get_ident())
        calls.append((args, kwargs))
        return "issued-token"

    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "true")
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(
        auth,
        "has_registered_users",
        lambda: operation == "update",
    )
    monkeypatch.setattr(auth, "verify_token", lambda _: "alice")
    monkeypatch.setattr(auth, "resolve_client_ip", lambda _: "127.0.0.1")
    monkeypatch.setattr(
        auth,
        "rate_limiter",
        SimpleNamespace(
            is_user_locked=lambda _: False,
            is_ip_locked=lambda _: False,
            is_ip_rate_limited=lambda _: False,
            record_login_attempt=Mock(),
        ),
    )
    request = Request(
        {"type": "http", "headers": [(b"authorization", b"Bearer caller")]},
    )
    if operation == "login":
        monkeypatch.setattr(auth, "authenticate", password_operation)
        result = await auth.login(
            request,
            auth.LoginRequest(
                username="alice",
                password="password",
                expires_in=60,
            ),
        )
        assert calls == [(("alice", "password", 60), {})]
    elif operation == "register":
        monkeypatch.setattr(auth, "register_user", password_operation)
        result = await auth.register(
            auth.RegisterRequest(
                username="alice",
                password="password",
                expires_in=60,
            ),
        )
        assert calls == [(("alice", "password", 60), {})]
    else:
        monkeypatch.setattr(auth, "update_credentials", password_operation)
        result = await auth.update_profile(
            auth.UpdateProfileRequest(
                current_password="password",
                new_username="bob",
                expires_in=60,
            ),
            request,
        )
        assert calls == [
            (
                (),
                {
                    "current_password": "password",
                    "new_username": "bob",
                    "new_password": None,
                    "expiry_seconds": 60,
                },
            ),
        ]
    assert result.token == "issued-token"
    assert len(worker_threads) == 1
    assert worker_threads[0] != loop_thread
