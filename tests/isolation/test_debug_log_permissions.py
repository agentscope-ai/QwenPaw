# -*- coding: utf-8 -*-
"""管理员日志接口的授权和响应脱敏契约。"""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.app.routers import console
from qwenpaw.identity.models import PlatformRole


ADMIN = ActorContext(
    user_id=uuid4(),
    actor_type=ActorType.USER,
    platform_role=PlatformRole.ADMIN,
    admin_mode=False,
    request_id="req-admin-debug",
)
MEMBER = replace(
    ADMIN,
    platform_role=PlatformRole.MEMBER,
    request_id="req-member-debug",
)


def _client(actor: ActorContext, monkeypatch, log_path) -> TestClient:
    monkeypatch.setattr(console, "LOG_FILE_PATH", log_path)
    monkeypatch.setattr(console, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        console,
        "load_envs",
        lambda: {"CUSTOM_INTERNAL_VALUE": "environment-secret-value"},
        raising=False,
    )

    app = FastAPI()

    @app.middleware("http")
    async def attach_actor(request: Request, call_next):
        request.state.actor = actor
        return await call_next(request)

    app.include_router(console.router, prefix="/api")
    return TestClient(app)


def test_member_cannot_read_global_backend_logs(monkeypatch, tmp_path) -> None:
    log_path = tmp_path / "qwenpaw.log"
    log_path.write_text("INFO harmless", encoding="utf-8")

    response = _client(MEMBER, monkeypatch, log_path).get(
        "/api/console/debug/backend-logs"
    )

    assert response.status_code == 403


def test_admin_log_response_redacts_secrets_and_absolute_paths(
    monkeypatch,
    tmp_path,
) -> None:
    log_path = tmp_path / "qwenpaw.log"
    sensitive_values = (
        "bearer-secret-value",
        "cookie-secret-value",
        "api-secret-value",
        "environment-secret-value",
        "sk-proj-abcdefghijklmnopqrstuvwxyz",
        "C:\\Users\\private-user\\QwenPaw\\secret.txt",
        "/home/private-user/qwenpaw/secret.txt",
    )
    log_path.write_text(
        "\n".join(
            (
                "INFO Authorization: Bearer bearer-secret-value",
                "INFO Cookie: session=cookie-secret-value; theme=dark",
                'INFO {"api_key":"api-secret-value"}',
                "INFO CUSTOM_INTERNAL_VALUE=environment-secret-value",
                "INFO token sk-proj-abcdefghijklmnopqrstuvwxyz",
                r"ERROR failed at C:\Users\private-user\QwenPaw\secret.txt",
                "ERROR failed at /home/private-user/qwenpaw/secret.txt",
            )
        ),
        encoding="utf-8",
    )

    response = _client(ADMIN, monkeypatch, log_path).get(
        "/api/console/debug/backend-logs?lines=100"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == "qwenpaw.log"
    assert "[REDACTED]" in payload["content"]
    assert "[REDACTED_PATH]" in payload["content"]
    for value in sensitive_values:
        assert value not in response.text
