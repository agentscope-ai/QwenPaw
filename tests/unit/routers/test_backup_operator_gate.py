# -*- coding: utf-8 -*-
"""Unit tests for backup route operator access checks."""
from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.routers import backup as backup_router
from qwenpaw.config import Config


def _build_client(host: str) -> AsyncClient:
    app = FastAPI()
    app.include_router(backup_router.router, prefix="/api")
    transport = ASGITransport(app=app, client=(host, 12345))
    return AsyncClient(transport=transport, base_url="http://test")


def _patch_backup_deps(monkeypatch, *, auth_enabled=False, has_users=False):
    config = Config()
    monkeypatch.setattr(
        backup_router,
        "is_auth_enabled",
        lambda: auth_enabled,
    )
    monkeypatch.setattr(
        backup_router,
        "has_registered_users",
        lambda: has_users,
    )
    monkeypatch.setattr(backup_router, "load_config", lambda: config)
    monkeypatch.setattr(backup_router, "list_backups", _fake_list_backups)
    return config


async def _fake_list_backups():
    return []


async def test_backup_routes_reject_remote_callers_when_auth_is_disabled(
    monkeypatch,
):
    _patch_backup_deps(monkeypatch, auth_enabled=False, has_users=False)

    async with _build_client("198.51.100.7") as client:
        resp = await client.get("/api/backups")

    assert resp.status_code == 403
    assert "require authentication" in resp.json()["detail"]


async def test_backup_routes_allow_localhost_when_auth_is_disabled(
    monkeypatch,
):
    _patch_backup_deps(monkeypatch, auth_enabled=False, has_users=False)

    async with _build_client("127.0.0.1") as client:
        resp = await client.get("/api/backups")

    assert resp.status_code == 200
    assert resp.json() == []


async def test_backup_routes_allow_configured_trusted_host_without_auth(
    monkeypatch,
):
    config = _patch_backup_deps(
        monkeypatch,
        auth_enabled=False,
        has_users=False,
    )
    config.security.allow_no_auth_hosts = ["10.0.0.5"]

    async with _build_client("10.0.0.5") as client:
        resp = await client.get("/api/backups")

    assert resp.status_code == 200
    assert resp.json() == []


async def test_backup_routes_defer_to_auth_middleware_when_auth_is_enabled(
    monkeypatch,
):
    _patch_backup_deps(monkeypatch, auth_enabled=True, has_users=True)

    async with _build_client("198.51.100.7") as client:
        resp = await client.get("/api/backups")

    assert resp.status_code == 200
    assert resp.json() == []
