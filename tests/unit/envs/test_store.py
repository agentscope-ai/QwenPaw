# -*- coding: utf-8 -*-
"""Tests for persisted environment overrides."""
# pylint: disable=protected-access,redefined-outer-name

from __future__ import annotations

import json

import pytest

from qwenpaw.envs import store


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
