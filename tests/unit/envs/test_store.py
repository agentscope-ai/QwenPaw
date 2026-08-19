# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from qwenpaw.envs import store


@pytest.fixture(autouse=True)
def _stub_secret_codec(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("A", "B", "C"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(store, "encrypt", lambda value: f"ENC:{value}")
    monkeypatch.setattr(
        store,
        "decrypt",
        lambda value: value.removeprefix("ENC:"),
    )
    monkeypatch.setattr(
        store,
        "is_encrypted",
        lambda value: value.startswith("ENC:"),
    )


def test_load_corrupt_envs_quarantines_original(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "envs.json"
    corrupt_content = '{"A": "ENC:truncated"'
    path.write_text(corrupt_content, encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger=store.__name__):
        assert store.load_envs(path) == {}

    assert not path.exists()
    quarantined = list(tmp_path.glob("envs.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == corrupt_content
    assert "quarantined" in caplog.text


def test_set_after_corruption_preserves_recovery_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "envs.json"
    store.save_envs({"A": "1", "B": "2"}, path)
    corrupt_content = path.read_text(encoding="utf-8")[:-1]
    path.write_text(corrupt_content, encoding="utf-8")
    monkeypatch.setattr(store, "_ENVS_JSON", path)

    assert store.set_env_var("C", "3") == {"C": "3"}

    assert store.load_envs(path) == {"C": "3"}
    quarantined = list(tmp_path.glob("envs.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == corrupt_content


def test_delete_after_corruption_preserves_recovery_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "envs.json"
    store.save_envs({"A": "1", "B": "2"}, path)
    corrupt_content = path.read_text(encoding="utf-8")[:-1]
    path.write_text(corrupt_content, encoding="utf-8")
    monkeypatch.setattr(store, "_ENVS_JSON", path)

    assert not store.delete_env_var("A")

    assert store.load_envs(path) == {}
    quarantined = list(tmp_path.glob("envs.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == corrupt_content


def test_set_refuses_to_overwrite_when_quarantine_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "envs.json"
    corrupt_content = '{"A": "ENC:truncated"'
    path.write_text(corrupt_content, encoding="utf-8")
    monkeypatch.setattr(store, "_ENVS_JSON", path)
    original_rename = Path.rename

    def fail_quarantine(self: Path, target: Path) -> Path:
        if self == path:
            raise PermissionError("read-only directory")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", fail_quarantine)

    with pytest.raises(PermissionError, match="read-only directory"):
        store.set_env_var("C", "3")

    assert path.read_text(encoding="utf-8") == corrupt_content


def test_quarantine_preserves_envs_symlink(tmp_path: Path) -> None:
    target = tmp_path / "persisted" / "envs.json"
    target.parent.mkdir()
    target.write_text('{"A": "ENC:truncated"', encoding="utf-8")
    path = tmp_path / "envs.json"
    try:
        path.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    assert store.load_envs(path) == {}

    assert path.is_symlink()
    assert not target.exists()
    assert len(list(target.parent.glob("envs.json.corrupt-*"))) == 1

    store.save_envs({"B": "2"}, path)
    assert path.is_symlink()
    assert target.exists()
    assert store.load_envs(path) == {"B": "2"}


def test_concurrent_set_keeps_both_updates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "envs.json"
    monkeypatch.setattr(store, "_ENVS_JSON", path)
    original_load = store.load_envs
    simultaneous_reads = threading.Barrier(2)

    def synchronized_load(*args: object, **kwargs: object) -> dict[str, str]:
        envs = original_load(*args, **kwargs)
        simultaneous_reads.wait(timeout=5)
        return envs

    monkeypatch.setattr(store, "load_envs", synchronized_load)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(store.set_env_var, "A", "1")
        second = executor.submit(store.set_env_var, "B", "2")
        first.result(timeout=5)
        second.result(timeout=5)

    assert original_load(path) == {"A": "1", "B": "2"}


def test_failed_atomic_save_preserves_previous_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "envs.json"
    store.save_envs({"A": "1"}, path)
    original_content = path.read_text(encoding="utf-8")

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "write_json_atomic", fail_write)

    with pytest.raises(OSError, match="disk full"):
        store.save_envs({"B": "2"}, path)

    assert path.read_text(encoding="utf-8") == original_content
    assert store.load_envs(path) == {"A": "1"}
