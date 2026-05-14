# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from qwenpaw.envs import store
from qwenpaw.security import secret_store


ENV_KEYS = (
    "QWENPAW_TEST_KEY",
    "QWENPAW_EMPTY_KEY",
    "QWENPAW_KEEP_KEY",
    "QWENPAW_DROP_KEY",
    "QWENPAW_EXISTING_KEY",
    "QWENPAW_CRUD_KEY",
    "QWENPAW_WORKING_DIR",
    "QWENPAW_SECRET_DIR",
)


@pytest.fixture(autouse=True)
def _isolate_env_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    test_key = bytes.fromhex(
        "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
    )
    monkeypatch.setattr(secret_store, "_cached_master_key", test_key)
    monkeypatch.setattr(secret_store, "_cached_fernet", None)
    monkeypatch.setattr(secret_store, "_get_secret_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "_BOOTSTRAP_SECRET_DIR", tmp_path)
    monkeypatch.setattr(store, "_ENVS_JSON", tmp_path / "envs.json")
    monkeypatch.setattr(store, "_LEGACY_ENVS_JSON_CANDIDATES", ())
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _read_raw(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_save_envs_writes_encrypted_values_and_syncs_environ(
    tmp_path: Path,
) -> None:
    path = tmp_path / "envs.json"

    store.save_envs(
        {
            "QWENPAW_TEST_KEY": "secret-value",
            "QWENPAW_EMPTY_KEY": "",
        },
        path,
    )

    raw = _read_raw(path)
    assert store.is_encrypted(raw["QWENPAW_TEST_KEY"])
    assert store.decrypt(raw["QWENPAW_TEST_KEY"]) == "secret-value"
    assert raw["QWENPAW_EMPTY_KEY"] == ""
    assert store.load_envs(path) == {
        "QWENPAW_TEST_KEY": "secret-value",
        "QWENPAW_EMPTY_KEY": "",
    }
    assert os.environ["QWENPAW_TEST_KEY"] == "secret-value"
    assert os.environ["QWENPAW_EMPTY_KEY"] == ""


def test_load_envs_reencrypts_legacy_plaintext_values(tmp_path: Path) -> None:
    path = tmp_path / "envs.json"
    path.write_text(
        json.dumps(
            {
                "QWENPAW_TEST_KEY": "legacy-plain",
                "QWENPAW_EMPTY_KEY": "",
            },
        ),
        encoding="utf-8",
    )

    assert store.load_envs(path) == {
        "QWENPAW_TEST_KEY": "legacy-plain",
        "QWENPAW_EMPTY_KEY": "",
    }

    raw = _read_raw(path)
    assert store.is_encrypted(raw["QWENPAW_TEST_KEY"])
    assert store.decrypt(raw["QWENPAW_TEST_KEY"]) == "legacy-plain"
    assert raw["QWENPAW_EMPTY_KEY"] == ""


def test_save_envs_removes_stale_environ_values(tmp_path: Path) -> None:
    path = tmp_path / "envs.json"
    store.save_envs(
        {
            "QWENPAW_KEEP_KEY": "old",
            "QWENPAW_DROP_KEY": "old",
        },
        path,
    )

    store.save_envs({"QWENPAW_KEEP_KEY": "new"}, path)

    assert os.environ["QWENPAW_KEEP_KEY"] == "new"
    assert "QWENPAW_DROP_KEY" not in os.environ


def test_save_envs_preserves_runtime_override_for_stale_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "envs.json"
    store.save_envs({"QWENPAW_DROP_KEY": "persisted"}, path)
    monkeypatch.setenv("QWENPAW_DROP_KEY", "runtime")

    store.save_envs({}, path)

    assert os.environ["QWENPAW_DROP_KEY"] == "runtime"


def test_set_and_delete_env_var_use_default_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "envs.json"
    monkeypatch.setattr(store, "_ENVS_JSON", path)

    assert store.set_env_var("QWENPAW_CRUD_KEY", "created") == {
        "QWENPAW_CRUD_KEY": "created",
    }
    assert store.load_envs(path) == {"QWENPAW_CRUD_KEY": "created"}
    assert os.environ["QWENPAW_CRUD_KEY"] == "created"

    assert store.delete_env_var("QWENPAW_CRUD_KEY") == {}
    assert store.load_envs(path) == {}
    assert "QWENPAW_CRUD_KEY" not in os.environ


def test_load_envs_into_environ_preserves_runtime_and_protected_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "envs.json"
    monkeypatch.setattr(store, "_ENVS_JSON", path)
    path.write_text(
        json.dumps(
            {
                "QWENPAW_TEST_KEY": store.encrypt("persisted"),
                "QWENPAW_EXISTING_KEY": store.encrypt("persisted"),
                "QWENPAW_SECRET_DIR": store.encrypt("secret-dir"),
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("QWENPAW_EXISTING_KEY", "runtime")

    envs = store.load_envs_into_environ()

    assert envs == {
        "QWENPAW_TEST_KEY": "persisted",
        "QWENPAW_EXISTING_KEY": "persisted",
        "QWENPAW_SECRET_DIR": "secret-dir",
    }
    assert os.environ["QWENPAW_TEST_KEY"] == "persisted"
    assert os.environ["QWENPAW_EXISTING_KEY"] == "runtime"
    assert "QWENPAW_SECRET_DIR" not in os.environ


def test_load_envs_returns_empty_for_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "envs.json"
    path.write_text("{not-json", encoding="utf-8")

    assert store.load_envs(path) == {}
