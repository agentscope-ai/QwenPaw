# -*- coding: utf-8 -*-
"""Tests for persisted environment overrides."""
# pylint: disable=protected-access,redefined-outer-name

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers.envs import router
from qwenpaw.envs import store
from qwenpaw.utils.shell_resources import ShellGuard


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Point the environment store at a temporary flat JSON file."""
    path = tmp_path / "envs.json"
    monkeypatch.setattr(store, "_ENVS_JSON", path)
    monkeypatch.setattr(store, "_LEGACY_ENVS_JSON_CANDIDATES", ())
    monkeypatch.setattr(store, "_BOOTSTRAP_SECRET_DIR", tmp_path)
    monkeypatch.setattr(store, "encrypt", lambda value: f"enc:{value}")
    monkeypatch.setattr(
        store,
        "is_encrypted",
        lambda value: value.startswith("enc:"),
    )
    monkeypatch.setattr(
        store,
        "decrypt",
        lambda value: value.removeprefix("enc:"),
    )
    store._HOST_ENV_VALUES.clear()
    yield path
    store._HOST_ENV_VALUES.clear()


def test_update_env_vars_merges_and_updates_process_env(
    isolated_store,
    monkeypatch,
) -> None:
    del isolated_store
    monkeypatch.delenv("FIRST_VALUE", raising=False)
    monkeypatch.delenv("SECOND_VALUE", raising=False)

    store.update_env_vars({"FIRST_VALUE": "one"})
    result = store.update_env_vars({"SECOND_VALUE": "two"})

    assert result == {"FIRST_VALUE": "one", "SECOND_VALUE": "two"}
    assert store.os.environ["FIRST_VALUE"] == "one"
    assert store.os.environ["SECOND_VALUE"] == "two"


def test_persisted_value_overrides_then_restores_inherited_value(
    isolated_store,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MANAGED_VALUE", "system")
    isolated_store.write_text(
        json.dumps({"MANAGED_VALUE": "enc:user"}),
        encoding="utf-8",
    )

    store.load_envs_into_environ()
    assert store.os.environ["MANAGED_VALUE"] == "user"

    store.delete_env_var("MANAGED_VALUE")
    assert store.os.environ["MANAGED_VALUE"] == "system"


def test_missing_store_stays_sparse(isolated_store) -> None:
    assert store.load_envs() == {}
    assert not isolated_store.exists()


@pytest.mark.parametrize(
    "key",
    [
        "PATH",
        "PythonPath",
        "PIP_TARGET",
        "UV_PYTHON",
        "CONDA_PREFIX",
        "BASH_ENV",
        "LD_PRELOAD",
        "QWENPAW_HUB_MODEL_TOKEN",
        "HOME",
        "QWENPAW_DEPENDENCY_STATE_DIR",
    ],
)
def test_managed_runtime_rejects_persisted_control_overrides(
    isolated_store,
    monkeypatch,
    key,
):
    monkeypatch.setenv("QWENPAW_RUNTIME_ID", "user-a")
    with pytest.raises(ValueError, match="managed"):
        store.update_env_vars({key: "injected"})
    isolated_store.write_text(json.dumps({key: "enc:injected"}))
    before = store.os.environ.get(key)
    store.load_envs_into_environ()
    assert store.os.environ.get(key) == before
    if key == "QWENPAW_DEPENDENCY_STATE_DIR":
        monkeypatch.delenv("QWENPAW_RUNTIME_ID")
        with pytest.raises(ValueError, match="managed"):
            store.update_env_vars({key: "changed"})
        store._apply_to_environ({key: "injected"})
        assert store.os.environ.get(key) == before
        store._sync_environ({key: before}, {})
        assert store.os.environ.get(key) == before
        assert json.loads(isolated_store.read_text())[key] == "enc:injected"
        monkeypatch.delenv("ORDINARY_VALUE", raising=False)
        store.update_env_vars({"ORDINARY_VALUE": "allowed"})
        assert store.os.environ["ORDINARY_VALUE"] == "allowed"
        assert store.os.environ.get(key) == before
        assert json.loads(isolated_store.read_text())[key] == "enc:injected"


def test_managed_runtime_does_not_migrate_shared_envs(tmp_path, monkeypatch):
    shared = tmp_path / "shared-envs.json"
    shared.write_text('{"HOST_ONLY": "host"}', encoding="utf-8")
    target = tmp_path / "user" / "envs.json"
    monkeypatch.setenv("QWENPAW_RUNTIME_ID", "user-runtime")
    monkeypatch.setattr(store, "_LEGACY_ENVS_JSON_CANDIDATES", (shared,))
    assert store.load_envs(target) == {}
    assert not target.exists()


async def test_shell_limit_catalog_hot_update_and_reset(
    isolated_store,
    monkeypatch,
):
    """Console writes validate, persist, apply and reset one live setting."""
    key = "QWENPAW_SHELL_MEMORY_LIMIT_MB"
    monkeypatch.delenv(key, raising=False)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        catalog = client.get("/envs/catalog").json()
        spec = next(item for item in catalog if item["key"] == key)
        assert spec["editable"] and spec["mutability"] == "hot_runtime"
        assert spec["effective_value"] == "0"
        assert await ShellGuard.from_environment(10485760) is None

        assert client.patch("/envs", json={key: "64"}).status_code == 200
        assert store.load_envs()[key] == "64"
        initial = await ShellGuard.from_environment(10485760)
        assert initial is not None
        initial_limit = initial.memory_limit
        for invalid in ("-1", "1.5", "NaN", ""):
            response = client.patch("/envs", json={key: invalid})
            assert response.status_code == 400
            assert response.json()["detail"] == (
                "Use 0, auto, or a positive integer for the memory limit"
            )
            assert store.load_envs()[key] == "64"

        assert client.patch("/envs", json={key: "0"}).status_code == 200
        assert await ShellGuard.from_environment(10485760) is None
        assert initial.memory_limit == initial_limit
        assert client.patch("/envs", json={key: "auto"}).status_code == 200
        automatic = await ShellGuard.from_environment(10485760)
        assert automatic is not None
        assert 0 < automatic.memory_limit <= 4096 * 1024 * 1024
        assert client.post(f"/envs/{key}/reset").status_code == 200
        assert key not in store.load_envs()
        assert await ShellGuard.from_environment(10485760) is None
