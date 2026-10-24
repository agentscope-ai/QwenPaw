# -*- coding: utf-8 -*-
"""Tests for the module-level app helpers in ``qwenpaw/app/_app.py``.

``test_scroll_startup_io.py`` pins the worker-thread offload of the scroll
history sync and ``test_provider_startup_offload.py`` pins which startup
helpers are dispatched off the loop; neither reaches the browser
housekeeping tasks, the console static-directory resolution chain, the
desktop-sidecar shutdown endpoint or the root route. All of those are
module-level functions that can be driven with stub kernels and a
temporary working directory, so no real browser, console build or Tauri
shell is involved.
"""
# Pytest fixtures intentionally provide setup-only arguments to tests.
# C1803 (use-implicit-booleaness-not-comparison) is disabled for the two
# `kernel.calls == []` checks: the equality form pins "no sweep ran at all"
# strictly, whereas `not kernel.calls` would also pass for None.
# pylint: disable=redefined-outer-name,unused-argument,protected-access
# pylint: disable=use-implicit-booleaness-not-comparison
from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from typing import Any, List

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse

app_module = importlib.import_module("qwenpaw.app._app")

DESKTOP_APP_ENV = "QWENPAW_DESKTOP_APP"
DESKTOP_TOKEN_ENV = "QWENPAW_DESKTOP_SHUTDOWN_TOKEN"
CONSOLE_STATIC_ENV = "QWENPAW_CONSOLE_STATIC_DIR"


def _state(**attrs: Any):
    """Build a stand-in for ``app`` exposing only ``state``."""
    return type("StubApp", (), {"state": type("S", (), attrs)()})()


class _RecordingKernel:
    """Browser kernel double recording which sweep ran, in order."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: List[str] = []
        self.fail_on = fail_on

    async def discard_idle_workers(self) -> None:
        self._run("idle")

    async def sweep_idle_sessions(self) -> None:
        self._run("sessions")

    async def sweep_wire_spill(self) -> None:
        self._run("wire")

    async def discard_all_workers(self) -> None:
        self._run("all")

    def _run(self, label: str) -> None:
        if self.fail_on == label:
            raise RuntimeError(f"{label} failed")
        self.calls.append(label)


@pytest.fixture()
def stub_playwright_stop(monkeypatch):
    """Replace the managed-chromium download stop and record the call."""
    import qwenpaw.browser.runtime.managed_playwright as mp

    stopped: List[int] = []

    async def _fake_stop() -> None:
        stopped.append(1)

    monkeypatch.setattr(mp, "stop_managed_chromium_download", _fake_stop)
    return stopped


# ---------------------------------------------------------------------------
# _start_browser_runtime / _browser_idle_watchdog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_browser_runtime_publishes_kernel_and_watchdog() -> None:
    app = _state()
    kernel = _RecordingKernel()

    app_module._start_browser_runtime(app, kernel, 0.01)
    try:
        assert app.state.browser_kernel is kernel
        assert isinstance(app.state.browser_watchdog, asyncio.Task)
        assert not app.state.browser_watchdog.done()
    finally:
        app.state.browser_watchdog.cancel()


@pytest.mark.asyncio
async def test_watchdog_runs_the_three_sweeps_in_order() -> None:
    kernel = _RecordingKernel()

    task = asyncio.create_task(
        app_module._browser_idle_watchdog(kernel, 0.005),
    )
    try:
        await asyncio.wait_for(_wait_for(kernel.calls, 3), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert kernel.calls[:3] == ["idle", "sessions", "wire"]


@pytest.mark.asyncio
async def test_watchdog_sleeps_before_the_first_sweep() -> None:
    """The first action must be the sleep, never an immediate sweep."""
    kernel = _RecordingKernel()
    task = asyncio.create_task(
        app_module._browser_idle_watchdog(kernel, 3600),
    )
    try:
        await asyncio.sleep(0.05)
        assert kernel.calls == []
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_watchdog_survives_a_failing_kernel() -> None:
    """A broken sweep must not kill the watchdog or the app."""
    kernel = _RecordingKernel(fail_on="idle")

    task = asyncio.create_task(
        app_module._browser_idle_watchdog(kernel, 0.005),
    )
    try:
        for _ in range(20):
            await asyncio.sleep(0.01)
            if not task.done():
                continue
            pytest.fail("watchdog task must keep running after a failure")
        assert kernel.calls == []
        assert not task.done()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_watchdog_later_sweeps_are_skipped_when_one_fails() -> None:
    kernel = _RecordingKernel(fail_on="sessions")

    task = asyncio.create_task(
        app_module._browser_idle_watchdog(kernel, 0.005),
    )
    try:
        await asyncio.wait_for(_wait_for(kernel.calls, 2), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    # idle ran, sessions blew up, wire never got its turn in that cycle
    assert kernel.calls[:2] == ["idle", "idle"]
    assert "wire" not in kernel.calls


async def _wait_for(calls: List[str], count: int) -> None:
    while len(calls) < count:
        await asyncio.sleep(0.005)


# ---------------------------------------------------------------------------
# _stop_browser_runtime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_browser_runtime_cancels_and_reclaims(
    stub_playwright_stop,
) -> None:
    app = _state()
    kernel = _RecordingKernel()
    app_module._start_browser_runtime(app, kernel, 3600)

    await app_module._stop_browser_runtime(app)

    assert app.state.browser_watchdog.cancelled()
    assert kernel.calls == ["all"]
    assert stub_playwright_stop == [1]


@pytest.mark.asyncio
async def test_stop_browser_runtime_without_any_state(
    stub_playwright_stop,
) -> None:
    """Shutdown must work when startup never ran (no attrs at all)."""
    app = _state()

    await app_module._stop_browser_runtime(app)

    assert stub_playwright_stop == [1]


@pytest.mark.asyncio
async def test_stop_browser_runtime_swallows_a_kernel_failure(
    stub_playwright_stop,
) -> None:
    kernel = _RecordingKernel(fail_on="all")
    app = _state(browser_kernel=kernel)

    await app_module._stop_browser_runtime(app)

    # the download stop still runs after the kernel blew up
    assert stub_playwright_stop == [1]


@pytest.mark.asyncio
async def test_stop_browser_runtime_awaits_an_already_finished_watchdog(
    stub_playwright_stop,
) -> None:
    """A watchdog that exited by itself must not stall shutdown."""

    async def finished() -> str:
        return "done"

    task = asyncio.create_task(finished())
    await task
    app = _state(browser_watchdog=task)

    await app_module._stop_browser_runtime(app)

    assert stub_playwright_stop == [1]
    assert task.done()


# ---------------------------------------------------------------------------
# _resolve_console_static_dir
# ---------------------------------------------------------------------------


def test_console_static_dir_prefers_the_environment(monkeypatch, tmp_path):
    chosen = tmp_path / "from-env"
    monkeypatch.setenv(CONSOLE_STATIC_ENV, str(chosen))
    assert app_module._resolve_console_static_dir() == str(chosen)


def _make_console(root: Path, subdir: str) -> Path:
    directory = root / subdir
    directory.mkdir(parents=True)
    (directory / "index.html").write_text("<html></html>", encoding="utf-8")
    return directory


@pytest.fixture()
def packaged_tree(monkeypatch, tmp_path):
    """Give ``__file__`` a throwaway home so the two packaged legs are ours.

    ``_resolve_console_static_dir`` derives the package candidate from
    ``Path(__file__).resolve().parent.parent`` and the repo candidate from
    that directory's grandparent. Without this seam both resolve inside the
    real clone, where a built ``console/dist`` would make every cwd-based
    expectation below depend on whether the frontend happened to be
    compiled. Laying the fake out as ``repo/src/qwenpaw/app/_app.py`` puts
    the package candidate at ``repo/src/qwenpaw/console`` and the repo
    candidate at ``repo/console/dist``, both inside *tmp_path*.
    """
    monkeypatch.delenv(CONSOLE_STATIC_ENV, raising=False)
    package = tmp_path / "repo" / "src" / "qwenpaw"
    (package / "app").mkdir(parents=True)
    fake_file = package / "app" / "_app.py"
    fake_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(app_module, "__file__", str(fake_file))
    repo = tmp_path / "repo"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return tmp_path, package, repo, cwd


def test_console_static_dir_finds_the_packaged_console(packaged_tree) -> None:
    _tmp_path, package, _repo, _cwd = packaged_tree
    shipped = _make_console(package, "console")

    assert app_module._resolve_console_static_dir() == str(shipped)


def test_console_static_dir_finds_the_repo_build(packaged_tree) -> None:
    _tmp_path, _package, repo, cwd = packaged_tree
    built = _make_console(repo, "console/dist")

    resolved = app_module._resolve_console_static_dir()

    assert resolved == str(built)
    assert cwd not in built.parents


def test_console_static_dir_finds_the_cwd_dist(packaged_tree) -> None:
    _tmp_path, _package, _repo, cwd = packaged_tree
    built = _make_console(cwd, "console/dist")

    assert app_module._resolve_console_static_dir() == str(built)


def test_console_static_dir_finds_the_cwd_console_dist_alias(
    packaged_tree,
) -> None:
    _tmp_path, _package, _repo, cwd = packaged_tree
    built = _make_console(cwd, "console_dist")

    assert app_module._resolve_console_static_dir() == str(built)


def test_console_static_dir_prefers_cwd_dist_over_the_alias(
    packaged_tree,
) -> None:
    _tmp_path, _package, _repo, cwd = packaged_tree
    first = _make_console(cwd, "console/dist")
    _make_console(cwd, "console_dist")

    assert app_module._resolve_console_static_dir() == str(first)


def test_console_static_dir_ignores_a_build_without_an_index(
    packaged_tree,
    caplog,
) -> None:
    """An empty dist directory must not be advertised as the console.

    The fallback returns the *same* path text as an accepted
    ``console/dist``, so the only observable difference between the two
    legs is the warning -- hence the log assertion, which is what keeps
    this test able to fail.
    """
    _tmp_path, _package, _repo, cwd = packaged_tree
    (cwd / "console" / "dist").mkdir(parents=True)
    (cwd / "console_dist").mkdir()

    with caplog.at_level("WARNING", logger=app_module.logger.name):
        resolved = app_module._resolve_console_static_dir()

    assert resolved == str(cwd / "console" / "dist")
    assert "not found" in caplog.text
    assert "Falling back" in caplog.text


def test_console_static_dir_falls_back_under_the_cwd(
    packaged_tree,
) -> None:
    _tmp_path, _package, _repo, cwd = packaged_tree

    resolved = app_module._resolve_console_static_dir()

    assert resolved == str(cwd / "console" / "dist")
    assert not Path(resolved).exists()


# ---------------------------------------------------------------------------
# read_root
# ---------------------------------------------------------------------------


def test_root_serves_the_console_index_with_no_cache_headers(
    monkeypatch,
    tmp_path,
) -> None:
    index = tmp_path / "index.html"
    index.write_text("<html>console</html>", encoding="utf-8")
    monkeypatch.setattr(app_module, "_CONSOLE_INDEX", index)

    response = app_module.read_root()

    assert isinstance(response, FileResponse)
    assert response.path == index
    for header, value in app_module._INDEX_NO_CACHE_HEADERS.items():
        assert response.headers[header.lower()] == value


def test_root_explains_a_missing_console_build(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(app_module, "_CONSOLE_INDEX", tmp_path / "nope.html")

    payload = app_module.read_root()

    assert isinstance(payload, dict)
    assert "npm run build" in payload["message"]


def test_root_treats_an_unset_index_as_missing(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "_CONSOLE_INDEX", None)

    payload = app_module.read_root()

    assert isinstance(payload, dict)
    assert "console" in payload["message"]


# ---------------------------------------------------------------------------
# get_doctor_runtime / get_version
# ---------------------------------------------------------------------------


def test_doctor_runtime_reports_the_running_interpreter() -> None:
    payload = app_module.get_doctor_runtime()

    assert payload["python_executable"] == sys.executable
    assert isinstance(payload["python_environment"], str)


def test_version_endpoint_does_not_leak_the_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("VIRTUAL_ENV", "/tmp/some-venv")
    payload = app_module.get_version()

    assert set(payload) == {"version"}
    assert "/tmp/some-venv" not in str(payload)


# ---------------------------------------------------------------------------
# post_desktop_shutdown
# ---------------------------------------------------------------------------


@pytest.fixture()
def desktop_env(monkeypatch):
    """Configure the sidecar env and guarantee no server leaks out."""
    monkeypatch.delenv(DESKTOP_APP_ENV, raising=False)
    monkeypatch.delenv(DESKTOP_TOKEN_ENV, raising=False)
    monkeypatch.delattr(app_module.app.state, "uvicorn_server", raising=False)
    yield monkeypatch
    monkeypatch.delattr(app_module.app.state, "uvicorn_server", raising=False)


@pytest.mark.asyncio
async def test_desktop_shutdown_is_hidden_outside_the_sidecar(desktop_env):
    desktop_env.setenv(DESKTOP_TOKEN_ENV, "tok")
    with pytest.raises(HTTPException) as exc:
        await app_module.post_desktop_shutdown(
            x_qwenpaw_desktop_shutdown_token="tok",
        )
    # 404, not 403: the endpoint must not advertise that it exists
    assert exc.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("app_flag", "token", "header"),
    [
        ("1", None, "tok"),
        ("1", "", "tok"),
        ("1", "tok", None),
        ("1", "tok", "wrong"),
        ("0", "tok", "tok"),
        ("", "tok", "tok"),
    ],
)
async def test_desktop_shutdown_rejects_every_partial_credential(
    desktop_env,
    app_flag: str,
    token: str | None,
    header: str | None,
) -> None:
    desktop_env.setenv(DESKTOP_APP_ENV, app_flag)
    if token is not None:
        desktop_env.setenv(DESKTOP_TOKEN_ENV, token)
    with pytest.raises(HTTPException) as exc:
        await app_module.post_desktop_shutdown(
            x_qwenpaw_desktop_shutdown_token=header,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_desktop_shutdown_reports_an_unready_backend(desktop_env):
    desktop_env.setenv(DESKTOP_APP_ENV, "1")
    desktop_env.setenv(DESKTOP_TOKEN_ENV, "tok")

    with pytest.raises(HTTPException) as exc:
        await app_module.post_desktop_shutdown(
            x_qwenpaw_desktop_shutdown_token="tok",
        )

    assert exc.value.status_code == 503
    assert "not ready" in exc.value.detail


@pytest.mark.asyncio
async def test_desktop_shutdown_asks_uvicorn_to_exit(desktop_env):
    desktop_env.setenv(DESKTOP_APP_ENV, "1")
    desktop_env.setenv(DESKTOP_TOKEN_ENV, "tok")
    server = type("Server", (), {"should_exit": False})()
    desktop_env.setattr(
        app_module.app.state,
        "uvicorn_server",
        server,
        raising=False,
    )

    payload = await app_module.post_desktop_shutdown(
        x_qwenpaw_desktop_shutdown_token="tok",
    )

    assert payload == {"ok": True}
    assert server.should_exit is True


@pytest.mark.asyncio
async def test_desktop_shutdown_ignores_an_absent_header(desktop_env) -> None:
    """A request without the header must not touch a live server.

    Calling the endpoint function directly bypasses FastAPI dependency
    injection, so ``Header(default=None)`` would arrive as the marker
    object itself; the absent-header case is spelled ``None`` here.
    """
    desktop_env.setenv(DESKTOP_APP_ENV, "1")
    desktop_env.setenv(DESKTOP_TOKEN_ENV, "tok")
    server = type("Server", (), {"should_exit": False})()
    desktop_env.setattr(
        app_module.app.state,
        "uvicorn_server",
        server,
        raising=False,
    )

    with pytest.raises(HTTPException) as exc:
        await app_module.post_desktop_shutdown(
            x_qwenpaw_desktop_shutdown_token=None,
        )

    assert exc.value.status_code == 404
    assert server.should_exit is False


# ---------------------------------------------------------------------------
# _sync_scroll_history_on_startup failure leg
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scroll_sync_failure_never_blocks_startup(monkeypatch) -> None:
    """A broken session sync is logged, not propagated out of startup."""
    from qwenpaw.agents.context.scroll import sync as scroll_sync

    def boom() -> None:
        raise RuntimeError("scroll sync is broken")

    monkeypatch.setattr(scroll_sync, "sync_all_scroll_agents", boom)

    await app_module._sync_scroll_history_on_startup()


@pytest.mark.asyncio
async def test_scroll_sync_success_runs_the_migration(monkeypatch) -> None:
    from qwenpaw.agents.context.scroll import sync as scroll_sync

    ran: List[str] = []

    def ok() -> None:
        ran.append("synced")

    monkeypatch.setattr(scroll_sync, "sync_all_scroll_agents", ok)

    await app_module._sync_scroll_history_on_startup()

    assert ran == ["synced"]
