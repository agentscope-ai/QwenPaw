# -*- coding: utf-8 -*-
"""Runtime ownership survives clients without replacing a live backend."""

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from qwenpaw.tauri.backend_guard import BackendInstance


@pytest.fixture(name="manifest_to_semver", scope="module")
def _manifest_to_semver():
    script = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "pack-tauri"
        / "generate_update_manifest.py"
    )
    return runpy.run_path(str(script))["to_semver"]


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("2.3.0", "2.3.0"),
        ("2.3.0a1", "2.3.0-alpha.1"),
        ("2.3.0b2", "2.3.0-beta.2"),
        ("2.3.0rc3", "2.3.0-rc.3"),
        ("2.3.0.dev1", "2.3.0-dev.1"),
        ("2.3.0b2.dev1", "2.3.0-beta.2.dev.1"),
        ("2.3.0.post1", "2.3.0+post.1"),
        ("2.3.0.post1.dev2", "2.3.0-dev.2+post.1"),
    ],
)
def test_runtime_lock_rejects_a_second_owner(
    tmp_path,
    monkeypatch,
    version,
    expected,
    manifest_to_semver,
):
    monkeypatch.setattr(
        "qwenpaw.tauri.backend_guard.__version__",
        version,
    )
    monkeypatch.delenv("QWENPAW_RUNTIME_ID", raising=False)
    with BackendInstance(tmp_path, "shared") as first:
        first.publish(12345)
        with pytest.raises(RuntimeError, match="already owns"):
            with BackendInstance(tmp_path, "shared"):
                pytest.fail("Two runtimes acquired the same directory")
        record = json.loads((first.directory / "runtime.json").read_text())
        assert record["instance"] == first.instance
        assert record["mode"] == "shared"
        assert record["version"] == expected
        assert record["version"] == manifest_to_semver(version)
        assert record["token"] == first.token
    assert not (first.directory / "runtime.json").exists()
    with BackendInstance(tmp_path, "shared") as replacement:
        assert replacement.instance != first.instance


def test_runtime_lock_is_released_after_process_death(tmp_path):
    source = (
        f"from pathlib import Path; import time; "
        f"from qwenpaw.tauri.backend_guard import BackendInstance; "
        f"instance = BackendInstance(Path({str(tmp_path)!r}), 'shared'); "
        f"instance.__enter__(); instance.publish(12345); "
        f"print('ready', flush=True); time.sleep(60)"
    )
    environment = dict(os.environ)
    environment.pop("QWENPAW_RUNTIME_ID", None)
    with subprocess.Popen(
        [sys.executable, "-c", source],
        stdout=subprocess.PIPE,
        text=True,
        env=environment,
    ) as child:
        try:
            assert child.stdout.readline().strip() == "ready"
            child.kill()
            child.wait(timeout=5)
            with BackendInstance(tmp_path, "shared") as replacement:
                replacement.publish(23456)
                record = json.loads(
                    (replacement.directory / "runtime.json").read_text(),
                )
                assert record["port"] == 23456
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdout.close()


def test_modes_have_separate_discovery_records(tmp_path):
    with BackendInstance(tmp_path, "shared") as shared:
        with BackendInstance(tmp_path, "stdio") as stdio:
            assert shared.directory != stdio.directory


def test_hub_cannot_publish_a_shared_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("QWENPAW_RUNTIME_ID", "hub-tenant")
    with pytest.raises(RuntimeError, match="Hub"):
        with BackendInstance(tmp_path, "shared"):
            pytest.fail("Hub runtime acquired shared ownership")
    assert not (tmp_path / "runtime").exists()


def test_explicit_stop_persists_supervisor_intent(tmp_path):
    with BackendInstance(tmp_path, "shared") as instance:
        instance.request_stop()
        assert (instance.directory / "stop-request").read_text() == (
            instance.instance
        )
    assert (instance.directory / "stop-request").exists()
