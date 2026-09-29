# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Corrupt state and cleanup failures must not block healthy sandboxes."""

import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.sandbox import windows_appcontainer_sandbox as app
from qwenpaw.sandbox import windows_elevated_sandbox as elevated
from qwenpaw.sandbox import windows_unelevated_sandbox as unelevated


@pytest.fixture(
    params=[app, elevated, unelevated],
    ids=["app", "elevated", "unelevated"],
)
def backend(request, tmp_path, monkeypatch):
    module = request.param
    folder = tmp_path / "containers"
    folder.mkdir()
    monkeypatch.setattr(app, "_state_dir", tmp_path)
    monkeypatch.setattr(elevated, "_sandboxes_dir", lambda _: folder)
    monkeypatch.setattr(
        unelevated,
        "_unelevated_sandboxes_dir",
        lambda: folder,
    )
    monkeypatch.setattr(unelevated, "_migrate_legacy_state_file", lambda: None)
    monkeypatch.setattr(unelevated, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(
        unelevated,
        "DenyPathsProtection",
        lambda: SimpleNamespace(active=False),
    )
    monkeypatch.setattr(
        "qwenpaw.utils.platform.is_windows_admin",
        lambda: True,
    )
    original_glob = Path.glob
    monkeypatch.setattr(
        Path,
        "glob",
        lambda path, pattern: iter(sorted(original_glob(path, pattern))),
    )

    def cleanup(meta, path):
        if meta.get("fail"):
            raise RuntimeError("simulated Win32 error")
        path.unlink()
        return True

    monkeypatch.setattr(app, "_cleanup_single_container", cleanup)
    monkeypatch.setattr(elevated, "_cleanup_from_metadata", cleanup)
    monkeypatch.setattr(
        unelevated,
        "_cleanup_unelevated_metadata",
        lambda path, meta: cleanup(meta, path),
    )
    return module, folder


def metadata(**extra):
    return json.dumps(
        {
            "container_name": "test",
            "username": "test",
            "cap_sid": "S-1-test",
            "owner_pid": os.getpid(),
            **extra,
        },
    ).encode("utf-8")


class RejectLogHandler(logging.Handler):
    def emit(self, record):
        raise AssertionError("quiet cleanup wrote to a handler")


def quiet_handlers(monkeypatch):
    for module in (app, elevated, unelevated):
        monkeypatch.setattr(module.logger, "handlers", [RejectLogHandler()])
        monkeypatch.setattr(module.logger, "propagate", False)
        monkeypatch.setattr(module.logger, "level", logging.DEBUG)
        monkeypatch.setattr(module.logger, "_cache", {})


@pytest.mark.parametrize("quiet", [True, False])
@pytest.mark.parametrize(
    "bad",
    [
        b'{"path":"\xe4',
        b"null",
        b"[]",
        b"{",
        metadata(owner_pid="bad"),
        metadata(owner_pid=True),
    ],
)
def test_bad_metadata_does_not_block_healthy_cleanup(
    backend,
    monkeypatch,
    caplog,
    bad,
    quiet,
):
    module, folder = backend
    broken = folder / "a_bad.json"
    healthy = folder / "b_good.json"
    broken.write_bytes(bad)
    healthy.write_bytes(metadata())
    if quiet:
        quiet_handlers(monkeypatch)
    with caplog.at_level(logging.ERROR):
        module.shutdown_cleanup(log_progress=not quiet)
    assert broken.read_bytes() == bad
    assert not healthy.exists()
    assert bool(caplog.records) is not quiet
    if not quiet:
        # Handlers may render and clear exc_info before caplog sees it.
        assert "Traceback (most recent call last):" in caplog.text
        assert "a_bad.json" in caplog.text


@pytest.mark.parametrize("quiet", [True, False])
def test_cleanup_failure_is_reported_and_next_container_runs(
    backend,
    monkeypatch,
    caplog,
    quiet,
):
    module, folder = backend
    broken = folder / "a_bad.json"
    healthy = folder / "b_good.json"
    broken.write_bytes(metadata(fail=True))
    healthy.write_bytes(metadata())
    if quiet:
        quiet_handlers(monkeypatch)
    with caplog.at_level(logging.ERROR):
        module.shutdown_cleanup(log_progress=not quiet)
    assert broken.exists()
    assert not healthy.exists()
    assert bool(caplog.records) is not quiet
    if not quiet:
        assert "Traceback (most recent call last):" in caplog.text
        assert "RuntimeError: simulated Win32 error" in caplog.text
        assert "a_bad.json" in caplog.text


@pytest.mark.parametrize("quiet", [True, False])
def test_top_level_cleanup_failure_does_not_escape(
    backend,
    monkeypatch,
    caplog,
    quiet,
):
    module, _ = backend

    def fail(**kwargs):
        raise OSError("directory enumeration failed")

    monkeypatch.setattr(module, "_shutdown_cleanup", fail)
    if quiet:
        quiet_handlers(monkeypatch)
    with caplog.at_level(logging.ERROR):
        module.shutdown_cleanup(log_progress=not quiet)
    assert bool(caplog.records) is not quiet


def test_owner_probe_failure_does_not_block_next_container(
    backend,
    monkeypatch,
    caplog,
):
    module, folder = backend
    broken = folder / "a_bad.json"
    healthy = folder / "b_good.json"
    broken.write_bytes(metadata(owner_pid=os.getpid() + 1))
    healthy.write_bytes(metadata())

    def fail(_pid):
        raise OSError("owner probe failed")

    monkeypatch.setattr(app, "_is_pid_alive", fail)
    monkeypatch.setattr(unelevated, "_is_pid_alive", fail)
    module.shutdown_cleanup()
    assert broken.exists()
    assert not healthy.exists()
    assert "owner probe failed" in caplog.text
