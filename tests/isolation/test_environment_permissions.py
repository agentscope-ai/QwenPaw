# -*- coding: utf-8 -*-
"""部署环境变量接口的权限与密文响应契约。"""

from __future__ import annotations

import os
from dataclasses import replace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.app.routers import envs
from qwenpaw.identity.models import PlatformRole

ADMIN = ActorContext(
    user_id=uuid4(),
    actor_type=ActorType.USER,
    platform_role=PlatformRole.ADMIN,
    admin_mode=False,
    request_id="req-admin-envs",
)
MEMBER = replace(ADMIN, platform_role=PlatformRole.MEMBER, request_id="req-member-envs")


def _client(actor: ActorContext, monkeypatch, initial: dict[str, str]) -> tuple[TestClient, dict[str, str]]:
    persisted = dict(initial)

    def load() -> dict[str, str]:
        return dict(persisted)

    def save(updated: dict[str, str]) -> None:
        old = dict(persisted)
        persisted.clear()
        persisted.update(updated)
        for key, old_value in old.items():
            if key not in updated and os.environ.get(key) == old_value:
                os.environ.pop(key, None)
        os.environ.update(updated)

    monkeypatch.setattr(envs, "load_envs", load)
    monkeypatch.setattr(envs, "save_envs", save)

    app = FastAPI()
    app.include_router(envs.router, prefix="/api")
    app.dependency_overrides[envs.get_actor] = lambda: actor
    return TestClient(app), persisted


def test_member_cannot_list_or_change_deployment_envs(monkeypatch) -> None:
    client, persisted = _client(MEMBER, monkeypatch, {"EXISTING": "secret"})

    assert client.get("/api/envs").status_code == 403
    assert client.put(
        "/api/envs",
        json={"operations": [{"key": "EXISTING", "action": "delete"}]},
    ).status_code == 403
    assert persisted == {"EXISTING": "secret"}


def test_admin_list_never_returns_persisted_plaintext(monkeypatch) -> None:
    client, _persisted = _client(ADMIN, monkeypatch, {"API_TOKEN": "top-secret"})

    response = client.get("/api/envs")

    assert response.status_code == 200
    assert response.json() == [{"key": "API_TOKEN", "configured": True}]
    assert "top-secret" not in response.text
    assert "value" not in response.text.lower()


def test_explicit_keep_replace_delete_preserve_unmentioned_keys(monkeypatch) -> None:
    monkeypatch.setenv("KEEP_ME", "keep-secret")
    monkeypatch.setenv("REPLACE_ME", "old-secret")
    monkeypatch.setenv("DELETE_ME", "delete-secret")
    client, persisted = _client(
        ADMIN,
        monkeypatch,
        {
            "KEEP_ME": "keep-secret",
            "UNMENTIONED": "untouched-secret",
            "REPLACE_ME": "old-secret",
            "DELETE_ME": "delete-secret",
        },
    )

    response = client.put(
        "/api/envs",
        json={
            "operations": [
                {"key": "KEEP_ME", "action": "keep"},
                {"key": "REPLACE_ME", "action": "replace", "value": "new-secret"},
                {"key": "DELETE_ME", "action": "delete"},
            ],
        },
    )

    assert response.status_code == 200
    assert persisted == {
        "KEEP_ME": "keep-secret",
        "UNMENTIONED": "untouched-secret",
        "REPLACE_ME": "new-secret",
    }
    assert os.environ["KEEP_ME"] == "keep-secret"
    assert os.environ["REPLACE_ME"] == "new-secret"
    assert "DELETE_ME" not in os.environ
    assert "old-secret" not in response.text
    assert "new-secret" not in response.text
    assert all(set(item) == {"key", "configured"} for item in response.json())


def test_invalid_or_ambiguous_operations_are_rejected_without_writes(monkeypatch) -> None:
    client, persisted = _client(ADMIN, monkeypatch, {"EXISTING": "secret"})
    cases = [
        {"operations": [{"key": "EXISTING", "action": "replace"}]},
        {"operations": [{"key": "EXISTING", "action": "keep", "value": "leak"}]},
        {
            "operations": [
                {"key": "EXISTING", "action": "keep"},
                {"key": "EXISTING", "action": "delete"},
            ],
        },
        {"operations": [{"key": "BAD KEY", "action": "delete"}]},
    ]

    for body in cases:
        response = client.put("/api/envs", json=body)
        assert response.status_code in {400, 422}
        assert persisted == {"EXISTING": "secret"}

