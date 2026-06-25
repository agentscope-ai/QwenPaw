# -*- coding: utf-8 -*-
"""Tests for data-source store, masking, and REST routes."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugin_datapaw.constants import (
    DATAPAW_CM_BASE_URL_ENV,
    DEFAULT_DATAPAW_CM_BASE_URL,
)
from plugin_datapaw.core.data_sources import cm_notifier
from plugin_datapaw.core.data_sources.cm_notifier import (
    _data_source_payload,
    notify_cm,
)
from plugin_datapaw.core.data_sources.masking import mask_value, restore_config_values
from plugin_datapaw.core.data_sources.models import (
    DataSourceCreateRequest,
    DataSourceUpdateRequest,
    validate_config_for_type,
)
from plugin_datapaw.core.data_sources.connection_testers import (
    _build_odps_sqlalchemy_url,
    test_connection as probe_connection,
)
from plugin_datapaw.core.data_sources.store import (
    DataSourceConflictError,
    DataSourceNotFoundError,
    DataSourceStore,
)

PLUGIN_DIR = Path(__file__).resolve().parent.parent


def _load_router_module():
    """Load the router module without importing ``core.routers.__init__``."""
    name = "plugin_datapaw.core.routers.data_sources"
    if name in sys.modules:
        return sys.modules[name]
    path = PLUGIN_DIR / "core" / "routers" / "data_sources.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MYSQL_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "secret12345",
    "db": "demo",
}


@pytest.fixture
def store(tmp_path: Path) -> DataSourceStore:
    return DataSourceStore(path=tmp_path / "data_sources.json")


def test_mask_and_restore_secret() -> None:
    masked = mask_value("secret12345")
    assert masked != "secret12345"
    restored = restore_config_values(
        {"password": masked},
        {"password": "secret12345"},
    )
    assert restored["password"] == "secret12345"


def test_store_crud_roundtrip(store: DataSourceStore) -> None:
    created = store.create(
        DataSourceCreateRequest(
            type="mysql",
            name="用户库",
            config=dict(MYSQL_CONFIG),
        ),
    )
    assert created.name == "用户库"
    assert created.config["password"] != MYSQL_CONFIG["password"]

    listed = store.list_all()
    assert len(listed) == 1
    assert listed[0].id == created.id

    fetched = store.get(created.id)
    assert fetched.config["password"] != MYSQL_CONFIG["password"]

    updated = store.update(
        created.id,
        DataSourceUpdateRequest(name="用户库-新"),
    )
    assert updated.name == "用户库-新"

    store.delete(created.id)
    with pytest.raises(DataSourceNotFoundError):
        store.get(created.id)


def test_store_encrypts_secrets_on_disk(store: DataSourceStore) -> None:
    created = store.create(
        DataSourceCreateRequest(
            type="mysql",
            name="enc-test",
            config=dict(MYSQL_CONFIG),
        ),
    )
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["items"][0]["config"]["password"].startswith("ENC:")
    assert store.get(created.id, masked=False).config["password"] == MYSQL_CONFIG["password"]


def test_store_rejects_duplicate_name(store: DataSourceStore) -> None:
    payload = DataSourceCreateRequest(
        type="mysql",
        name="dup",
        config=dict(MYSQL_CONFIG),
    )
    store.create(payload)
    with pytest.raises(DataSourceConflictError):
        store.create(payload)


def test_store_update_preserves_masked_password(store: DataSourceStore) -> None:
    created = store.create(
        DataSourceCreateRequest(
            type="mysql",
            name="pw-test",
            config=dict(MYSQL_CONFIG),
        ),
    )
    masked_pw = created.config["password"]
    updated = store.update(
        created.id,
        DataSourceUpdateRequest(config={"host": "10.0.0.1", "password": masked_pw}),
    )
    raw = store.get(created.id, masked=False)
    assert raw.config["password"] == MYSQL_CONFIG["password"]
    assert updated.config["host"] == "10.0.0.1"


def test_validate_config_missing_field() -> None:
    with pytest.raises(ValueError, match="hostRequired"):
        validate_config_for_type("mysql", {"port": 3306})


def test_validate_odps_allows_missing_access_keys() -> None:
    validate_config_for_type(
        "odps",
        {
            "endpoint": "https://service.odps.aliyun.com/api",
            "project_name": "demo_project",
            "app_name": "datapaw",
        },
    )


def test_build_odps_sqlalchemy_url_with_credentials() -> None:
    url = _build_odps_sqlalchemy_url(
        {
            "endpoint": "https://service.odps.aliyun.com/api",
            "project_name": "demo_project",
            "access_id": "ak id",
            "access_key": "sk/key",
            "app_name": "datapaw",
        },
    )
    assert url.startswith("odps://ak+id:sk%2Fkey@demo_project/")
    assert "endpoint=https%3A%2F%2Fservice.odps.aliyun.com%2Fapi" in url
    assert "app_name=datapaw" in url


def test_build_odps_sqlalchemy_url_without_credentials() -> None:
    url = _build_odps_sqlalchemy_url(
        {
            "endpoint": "https://service.odps.aliyun.com/api",
            "project_name": "demo_project",
            "app_name": "datapaw",
        },
    )
    assert url.startswith("odps://demo_project/")
    assert "@" not in url


TRUSTED_ODPS_CONFIG = {"app_name": "semantic-layer"}

TRUSTED_POSTGRESQL_CONFIG = {"db": "tongyi_busi"}


def test_trusted_odps_connection_bypasses_live_probe() -> None:
    success, message = probe_connection("odps", TRUSTED_ODPS_CONFIG)
    assert success is True
    assert message == "connectionOk"


def test_trusted_postgresql_connection_bypasses_live_probe() -> None:
    success, message = probe_connection("postgresql", TRUSTED_POSTGRESQL_CONFIG)
    assert success is True
    assert message == "connectionOk"


@pytest.fixture
def api_client(store: DataSourceStore, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    router_mod = _load_router_module()
    monkeypatch.setattr(router_mod, "_store", store)
    monkeypatch.setattr(
        router_mod,
        "test_connection",
        lambda ds_type, config: (True, "connectionOk"),
    )

    app = FastAPI()
    app.include_router(
        router_mod.router,
        prefix="/datapaw/data-sources",
    )
    return TestClient(app)

def test_router_create_list_delete(api_client: TestClient) -> None:
    create_resp = api_client.post(
        "/datapaw/data-sources",
        json={
            "type": "mysql",
            "name": "api-db",
            "config": MYSQL_CONFIG,
        },
    )
    assert create_resp.status_code == 200
    body = create_resp.json()
    assert body["name"] == "api-db"
    assert "createdAt" in body
    record_id = body["id"]

    list_resp = api_client.get("/datapaw/data-sources")
    assert list_resp.status_code == 200
    assert len(list_resp.json()["items"]) == 1

    get_resp = api_client.get(f"/datapaw/data-sources/{record_id}")
    assert get_resp.status_code == 200

    update_resp = api_client.put(
        f"/datapaw/data-sources/{record_id}",
        json={"name": "api-db-renamed"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "api-db-renamed"

    delete_resp = api_client.delete(f"/datapaw/data-sources/{record_id}")
    assert delete_resp.status_code == 204


def test_router_test_connection(api_client: TestClient) -> None:
    resp = api_client.post(
        "/datapaw/data-sources/test",
        json={"type": "mysql", "config": MYSQL_CONFIG},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["message"] == "connectionOk"
    assert "latencyMs" in body


def test_router_missing_fields_returns_400(api_client: TestClient) -> None:
    resp = api_client.post(
        "/datapaw/data-sources",
        json={"type": "mysql", "name": "bad", "config": {"host": "127.0.0.1"}},
    )
    assert resp.status_code == 400


class _FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


class _RecordingAsyncClient:
    """Captures the single POST a notify_cm call makes."""

    captured: list[dict] = []
    status_code = 200
    raise_on_post = False

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    async def __aenter__(self) -> "_RecordingAsyncClient":
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    async def post(self, url, json=None, headers=None):  # noqa: A002
        type(self).captured.append({"url": url, "json": json, "headers": headers})
        if type(self).raise_on_post:
            raise RuntimeError("network down")
        return _FakeResponse(type(self).status_code)


@pytest.fixture
def recording_client(monkeypatch: pytest.MonkeyPatch):
    _RecordingAsyncClient.captured = []
    _RecordingAsyncClient.status_code = 200
    _RecordingAsyncClient.raise_on_post = False
    monkeypatch.setattr(cm_notifier.httpx, "AsyncClient", _RecordingAsyncClient)
    return _RecordingAsyncClient


def _make_unmasked_record(store: DataSourceStore):
    created = store.create(
        DataSourceCreateRequest(type="mysql", name="cm-src", config=dict(MYSQL_CONFIG)),
    )
    return store.get(created.id, masked=False)


def test_cm_payload_created_is_unmasked(store: DataSourceStore) -> None:
    record = _make_unmasked_record(store)
    payload = _data_source_payload("created", record)
    assert payload["action"] == "created"
    assert payload["dataSource"]["config"]["password"] == MYSQL_CONFIG["password"]
    assert "createdAt" in payload["dataSource"]


def test_cm_payload_deleted_only_id_and_type(store: DataSourceStore) -> None:
    record = _make_unmasked_record(store)
    payload = _data_source_payload("deleted", record)
    assert payload["dataSource"] == {"id": record.id, "type": "mysql"}


def test_notify_cm_uses_default_when_unset(
    store: DataSourceStore,
    monkeypatch: pytest.MonkeyPatch,
    recording_client,
) -> None:
    monkeypatch.delenv(DATAPAW_CM_BASE_URL_ENV, raising=False)
    record = _make_unmasked_record(store)
    asyncio.run(notify_cm("created", record))

    assert len(recording_client.captured) == 1
    sent = recording_client.captured[0]
    assert sent["url"] == f"{DEFAULT_DATAPAW_CM_BASE_URL}/api/datasources/sync"
    assert sent["json"]["dataSource"]["config"]["password"] == MYSQL_CONFIG["password"]


def test_notify_cm_uses_default_when_blank(
    store: DataSourceStore,
    monkeypatch: pytest.MonkeyPatch,
    recording_client,
) -> None:
    monkeypatch.setenv(DATAPAW_CM_BASE_URL_ENV, "   ")
    record = _make_unmasked_record(store)
    asyncio.run(notify_cm("updated", record))

    assert len(recording_client.captured) == 1
    assert (
        recording_client.captured[0]["url"]
        == f"{DEFAULT_DATAPAW_CM_BASE_URL}/api/datasources/sync"
    )


def test_notify_cm_posts_unmasked_payload(
    store: DataSourceStore,
    monkeypatch: pytest.MonkeyPatch,
    recording_client,
) -> None:
    monkeypatch.setenv(DATAPAW_CM_BASE_URL_ENV, "http://cm.local/")
    record = _make_unmasked_record(store)
    asyncio.run(notify_cm("created", record))

    assert len(recording_client.captured) == 1
    sent = recording_client.captured[0]
    assert sent["url"] == "http://cm.local/api/datasources/sync"
    assert sent["json"]["dataSource"]["config"]["password"] == MYSQL_CONFIG["password"]
    assert sent["headers"]["X-Request-Id"]


def test_notify_cm_swallows_errors(
    store: DataSourceStore,
    monkeypatch: pytest.MonkeyPatch,
    recording_client,
) -> None:
    monkeypatch.setenv(DATAPAW_CM_BASE_URL_ENV, "http://cm.local")
    recording_client.raise_on_post = True
    record = _make_unmasked_record(store)
    asyncio.run(notify_cm("updated", record))


def test_router_create_notifies_unmasked(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router_mod = _load_router_module()
    calls: list[tuple] = []
    monkeypatch.setattr(
        router_mod,
        "notify_cm",
        lambda action, record: calls.append((action, record)),
    )

    resp = api_client.post(
        "/datapaw/data-sources",
        json={"type": "mysql", "name": "notify-db", "config": MYSQL_CONFIG},
    )
    assert resp.status_code == 200
    assert resp.json()["config"]["password"] != MYSQL_CONFIG["password"]

    assert len(calls) == 1
    action, record = calls[0]
    assert action == "created"
    assert record.config["password"] == MYSQL_CONFIG["password"]


def test_router_delete_notifies_id_and_type(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router_mod = _load_router_module()
    create_resp = api_client.post(
        "/datapaw/data-sources",
        json={"type": "mysql", "name": "del-db", "config": MYSQL_CONFIG},
    )
    record_id = create_resp.json()["id"]

    calls: list[tuple] = []
    monkeypatch.setattr(
        router_mod,
        "notify_cm",
        lambda action, record: calls.append((action, record)),
    )

    resp = api_client.delete(f"/datapaw/data-sources/{record_id}")
    assert resp.status_code == 204

    assert len(calls) == 1
    action, record = calls[0]
    assert action == "deleted"
    assert record.id == record_id
    assert record.type == "mysql"
