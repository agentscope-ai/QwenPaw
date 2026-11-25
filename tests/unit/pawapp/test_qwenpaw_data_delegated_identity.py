# -*- coding: utf-8 -*-
"""Exercise delegated identities against the installed Data runtime."""
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("qwenpaw_data_auth")


def provisioner():
    path = (
        Path(__file__).resolve().parents[3]
        / "plugins/apps/qwenpaw-data/backend/delegated_identity.py"
    )
    spec = importlib.util.spec_from_file_location("data_identity", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.provision


def test_managed_identity_is_idempotent_and_workspace_isolated(tmp_path):
    provision = provisioner()
    alice, bob = "pawapp_" + "a" * 64, "pawapp_" + "b" * 64
    first = provision(tmp_path, alice)
    assert first == provision(tmp_path, alice)
    second = provision(tmp_path, bob)
    assert first["workspace_id"] != second["workspace_id"]
    assert first["workspace_ids"] == [alice]
    assert second["workspace_ids"] == [bob]
    assert first["role"] == "ws_admin"


def test_revocation_is_not_repaired_on_the_next_request(tmp_path):
    from sqlalchemy import delete
    from qwenpaw_data_auth.authentication import AuthenticationError
    from qwenpaw_data_auth.database import get_db, role_bindings

    provision = provisioner()
    identity = "pawapp_" + "c" * 64
    provision(tmp_path, identity)
    with get_db(str(tmp_path / "control_plane.db")) as db:
        db.execute(
            delete(role_bindings).where(role_bindings.c.user_id == identity),
        )
        db.commit()
    with pytest.raises(AuthenticationError, match="not authorized"):
        provision(tmp_path, identity)
    # A repeated call must still fail, never recreate the grant.
    with pytest.raises(AuthenticationError, match="not authorized"):
        provision(tmp_path, identity)


def test_untrusted_scope_cannot_create_an_identity(tmp_path):
    with pytest.raises(ValueError, match="Invalid PawApp identity"):
        provisioner()(tmp_path, "administrator")


def test_installed_host_resolves_delegation_and_enforces_session_ownership(
    tmp_path,
    monkeypatch,
):
    import asyncio
    from fastapi.testclient import TestClient
    from qwenpaw_data.host.core.api.app import create_app
    from qwenpaw_data.host.core.settings import clear_settings
    from qwenpaw_data.host.core.db.engine import reset_engine
    from sqlalchemy import delete
    from qwenpaw_data_auth.database import get_db, role_bindings

    provision = provisioner()
    alice, bob = "pawapp_" + "a" * 64, "pawapp_" + "b" * 64
    provision(tmp_path, alice)
    provision(tmp_path, bob)
    monkeypatch.setenv("QWENPAW_DATA_HOME", str(tmp_path))
    monkeypatch.setenv(
        "QWENPAW_DATA_DB_URL",
        str(tmp_path / "control_plane.db"),
    )
    monkeypatch.setenv("QWENPAW_DATA_AUTH_MODE", "local")
    monkeypatch.setenv("QWENPAW_DATA_WORKSPACE_BACKEND", "local")
    monkeypatch.setenv("QWENPAW_DATA_SERVICE_SECRET", "server-delegation-only")
    monkeypatch.setenv(
        "QWENPAW_DATA_AUTH_SECRET",
        "test-signing-only-" + "x" * 48,
    )
    clear_settings()
    asyncio.run(reset_engine())

    def headers(identity):
        return {
            "X-QwenPaw-Data-Service-Secret": "server-delegation-only",
            "X-User-Id": identity,
            "X-QwenPaw-Data-Workspace-Id": identity,
        }

    try:
        with TestClient(
            create_app(),
            base_url="http://localhost",
            client=("127.0.0.1", 50000),
        ) as client:
            me = client.get("/api/v1/console/identity", headers=headers(alice))
            assert me.status_code == 200, me.text
            assert me.json()["active_workspace_id"] == alice
            assert me.json()["role"] == "ws_admin"
            created = client.post(
                "/api/v1/sessions",
                headers=headers(alice),
                json={"title": "Alice"},
            )
            assert created.status_code == 200, created.text
            sid = created.json()["session"]["id"]
            assert client.get(
                f"/api/v1/sessions/{sid}",
                headers=headers(bob),
            ).status_code in (403, 404)
            assert client.get(
                "/api/v1/console/identity",
                headers={"X-User-Id": alice},
            ).status_code in (401, 403)
            with get_db(str(tmp_path / "control_plane.db")) as db:
                db.execute(
                    delete(role_bindings).where(
                        role_bindings.c.user_id == alice,
                    ),
                )
                db.commit()
            assert (
                client.get(
                    "/api/v1/console/identity",
                    headers=headers(alice),
                ).status_code
                == 403
            )
    finally:
        asyncio.run(reset_engine())
        clear_settings()


def test_fresh_managed_context_issues_workspace_tokens(tmp_path, monkeypatch):
    import asyncio

    from fastapi.testclient import TestClient
    from context_manager.settings import (
        clear_settings as clear_context_settings,
    )
    from qwenpaw_data.host.core.db.engine import reset_engine
    from qwenpaw_data.host.core.settings import (
        clear_settings as clear_host_settings,
    )
    from qwenpaw_data_auth.database import get_db, role_bindings
    from sqlalchemy import delete

    backend = (
        Path(__file__).resolve().parents[3]
        / "plugins/apps/qwenpaw-data/backend"
    )
    monkeypatch.syspath_prepend(str(backend))
    monkeypatch.chdir(tmp_path)
    database = tmp_path / "control_plane.db"
    monkeypatch.setenv("QWENPAW_DATA_HOME", str(tmp_path))
    monkeypatch.setenv(
        "QWENPAW_DATA_DB_URL",
        f"sqlite+aiosqlite:///{database.as_posix()}",
    )
    monkeypatch.setenv("QWENPAW_DATA_AUTH_MODE", "multi-user")
    monkeypatch.setenv(
        "QWENPAW_DATA_SERVICE_SECRET",
        "service-secret-for-test",
    )
    monkeypatch.setenv(
        "QWENPAW_DATA_AUTH_SECRET",
        "test-signing-secret-" + "x" * 40,
    )
    monkeypatch.setenv("NEO4J_PASSWORD", "test-only")
    from managed_context import create_app

    identity = "pawapp_" + "d" * 64
    scope = {
        "tenant_id": "pawapp",
        "user_id": identity,
        "workspace_id": identity,
    }
    auth = {"X-QwenPaw-Data-Service-Secret": "service-secret-for-test"}
    endpoint = "/api/auth/temporary-access"
    clear_host_settings()
    try:
        with TestClient(create_app(), base_url="http://localhost") as client:
            assert (
                client.post(endpoint, json=scope, headers=auth).status_code
                == 404
            )
            provisioner()(tmp_path, identity)
            assert client.post(endpoint, json=scope).status_code == 403
            issued = client.post(endpoint, json=scope, headers=auth)
            assert issued.status_code == 200, issued.text
            bearer = {
                "Authorization": f"Bearer {issued.json()['access_token']}",
            }
            assert (
                client.get("/api/datasource-types", headers=bearer).status_code
                == 200
            )
            with get_db(str(database)) as db:
                db.execute(
                    delete(role_bindings).where(
                        role_bindings.c.user_id == identity,
                    ),
                )
                db.commit()
            assert (
                client.post(endpoint, json=scope, headers=auth).status_code
                == 403
            )
    finally:
        asyncio.run(reset_engine())
        clear_host_settings()
        clear_context_settings()
