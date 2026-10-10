# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Managed Chromium download cooldown and single-flight."""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

import qwenpaw.browser.runtime.managed_playwright as managed


class _Done:
    def done(self):
        return True


@pytest.fixture
def managed_state(monkeypatch):
    """Reset process-local download state around each test."""
    monkeypatch.setattr(managed, "_download_task", None)
    monkeypatch.setattr(managed, "_install_process", None)
    monkeypatch.setattr(managed, "_last_download_error", "")
    monkeypatch.setattr(managed, "_last_failure_at", 0.0)
    monkeypatch.setattr(
        managed,
        "desktop_managed_playwright_enabled",
        lambda: True,
    )
    monkeypatch.setattr(managed, "managed_chromium_ready", lambda: False)
    yield managed
    task = managed._download_task
    if task is not None and not task.done():
        task.cancel()


def _block_create(monkeypatch, module):
    def fail_create(*_args, **_kwargs):
        raise AssertionError("must not start a download")

    monkeypatch.setattr(module.asyncio, "create_task", fail_create)


def _count_create(monkeypatch, module):
    created: list[bool] = []
    real_create = module.asyncio.create_task

    def capture(coro):
        created.append(True)
        return real_create(coro)

    monkeypatch.setattr(module.asyncio, "create_task", capture)
    return created


def test_failed_download_does_not_restart_during_cooldown(
    managed_state,
    monkeypatch,
):
    monkeypatch.setattr(managed_state, "_download_task", _Done())
    monkeypatch.setattr(managed_state, "_last_download_error", "firewall")
    monkeypatch.setattr(
        managed_state,
        "_last_failure_at",
        managed.time.monotonic(),
    )
    _block_create(monkeypatch, managed_state)
    ready, detail = managed_state.start_managed_chromium_download()
    assert ready is False
    assert detail == "firewall"


@pytest.mark.asyncio
async def test_failed_download_restarts_after_cooldown(
    managed_state,
    monkeypatch,
):
    async def noop():
        return None

    monkeypatch.setattr(managed_state, "_download_and_record", noop)
    monkeypatch.setattr(managed_state, "_download_task", _Done())
    monkeypatch.setattr(managed_state, "_last_download_error", "firewall")
    monkeypatch.setattr(
        managed_state,
        "_last_failure_at",
        managed.time.monotonic() - 61.0,
    )
    created = _count_create(monkeypatch, managed_state)
    ready, _detail = managed_state.start_managed_chromium_download()
    assert ready is False
    assert created == [True]
    task = managed_state._download_task
    if task is not None:
        await task


def test_ensure_returns_immediately_during_cooldown(
    managed_state,
    monkeypatch,
):
    monkeypatch.setattr(managed_state, "_download_task", _Done())
    monkeypatch.setattr(managed_state, "_last_download_error", "firewall")
    monkeypatch.setattr(
        managed_state,
        "_last_failure_at",
        managed.time.monotonic(),
    )
    _block_create(monkeypatch, managed_state)
    started = time.monotonic()
    ready, detail, retry_after = managed_state.ensure_managed_chromium()
    assert time.monotonic() - started < 0.2
    assert ready is False
    assert detail == "firewall"
    assert retry_after > 0


@pytest.mark.asyncio
async def test_in_flight_download_does_not_start_second_task(
    managed_state,
    monkeypatch,
):
    async def hang():
        await asyncio.sleep(10)

    monkeypatch.setattr(managed_state, "_download_and_record", hang)
    created = _count_create(monkeypatch, managed_state)
    first = managed_state.start_managed_chromium_download()
    second = managed_state.start_managed_chromium_download()
    assert first[0] is False
    assert second[0] is False
    assert created == [True]


@pytest.mark.asyncio
async def test_ensure_returns_immediately_while_download_runs(
    managed_state,
    monkeypatch,
):
    async def hang():
        await asyncio.sleep(10)

    monkeypatch.setattr(managed_state, "_download_and_record", hang)
    started = time.monotonic()
    ready, detail, retry_after = managed_state.ensure_managed_chromium()
    task = managed_state._download_task
    assert time.monotonic() - started < 0.2
    assert ready is False
    assert detail == ""
    assert retry_after == managed._IN_FLIGHT_RETRY_SECONDS
    assert task is not None
    assert not task.done()


@pytest.mark.asyncio
async def test_ensure_after_cooldown_is_inflight_not_failed(
    managed_state,
    monkeypatch,
):
    async def hang():
        await asyncio.sleep(10)

    monkeypatch.setattr(managed_state, "_download_and_record", hang)
    monkeypatch.setattr(managed_state, "_download_task", _Done())
    monkeypatch.setattr(managed_state, "_last_download_error", "firewall")
    monkeypatch.setattr(
        managed_state,
        "_last_failure_at",
        managed.time.monotonic() - 61.0,
    )
    ready, detail, retry_after = managed_state.ensure_managed_chromium()
    task = managed_state._download_task
    assert ready is False
    assert detail == ""
    assert retry_after == managed._IN_FLIGHT_RETRY_SECONDS
    assert task is not None
    assert not task.done()


@pytest.mark.asyncio
async def test_install_timeout_records_failure(
    managed_state,
    monkeypatch,
    tmp_path,
):
    class _Proc:
        returncode = None

        def terminate(self):
            self.returncode = -1

        def kill(self):
            self.returncode = -1

        async def wait(self):
            return None

        async def communicate(self):
            await asyncio.sleep(10)
            return b"", None

    _patch_fake_install(monkeypatch, managed_state, tmp_path, _Proc)
    await managed_state._download_and_record()
    assert "timed out" in managed_state._last_download_error.lower()
    assert managed_state._last_failure_at > 0
    monkeypatch.setattr(managed_state, "_download_task", _Done())
    _block_create(monkeypatch, managed_state)
    ready, detail, retry_after = managed_state.ensure_managed_chromium()
    assert ready is False
    assert "timed out" in detail.lower()
    assert retry_after > 0


def test_ready_requires_installation_complete_marker(monkeypatch, tmp_path):
    chromium = "chromium-1"
    headless = "chromium_headless_shell-1"
    monkeypatch.setattr(
        managed,
        "desktop_managed_playwright_enabled",
        lambda: True,
    )
    monkeypatch.setattr(managed, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        managed,
        "_required_browser_directories",
        lambda: (chromium, headless),
    )
    (tmp_path / chromium).mkdir()
    (tmp_path / headless).mkdir()
    assert managed.managed_chromium_ready() is False
    (tmp_path / chromium / managed._INSTALL_MARKER).write_text("")
    (tmp_path / headless / managed._INSTALL_MARKER).write_text("")
    assert managed.managed_chromium_ready() is True


@pytest.mark.asyncio
async def test_ready_wins_over_in_flight(managed_state, monkeypatch):
    async def hang():
        await asyncio.sleep(10)

    monkeypatch.setattr(managed_state, "_download_and_record", hang)
    created = _count_create(monkeypatch, managed_state)
    first = managed_state.start_managed_chromium_download()
    monkeypatch.setattr(managed_state, "managed_chromium_ready", lambda: True)
    second = managed_state.start_managed_chromium_download()
    ready, detail, retry_after = managed_state.ensure_managed_chromium()
    assert first[0] is False
    assert second[0] is True
    assert created == [True]
    assert ready is True
    assert detail == ""
    assert retry_after == 0.0


def test_empty_error_still_cools_down(managed_state, monkeypatch):
    monkeypatch.setattr(managed_state, "_download_task", _Done())
    monkeypatch.setattr(managed_state, "_last_download_error", "")
    monkeypatch.setattr(
        managed_state,
        "_last_failure_at",
        managed.time.monotonic(),
    )
    _block_create(monkeypatch, managed_state)
    ready, detail = managed_state.start_managed_chromium_download()
    assert ready is False
    assert detail == "install failed"
    ready, detail, retry_after = managed_state.ensure_managed_chromium()
    assert ready is False
    assert detail == "install failed"
    assert retry_after > 0


def test_ready_wins_over_cooldown(managed_state, monkeypatch):
    monkeypatch.setattr(managed_state, "_download_task", _Done())
    monkeypatch.setattr(managed_state, "_last_download_error", "timed out")
    monkeypatch.setattr(
        managed_state,
        "_last_failure_at",
        managed.time.monotonic(),
    )
    monkeypatch.setattr(managed_state, "managed_chromium_ready", lambda: True)
    _block_create(monkeypatch, managed_state)
    ready, detail = managed_state.start_managed_chromium_download()
    assert ready is True
    assert detail == ""
    ready, detail, retry_after = managed_state.ensure_managed_chromium()
    assert ready is True
    assert detail == ""
    assert retry_after == 0.0


def _patch_fake_install(monkeypatch, module, tmp_path, factory):
    async def fake_exec(*_args, **_kwargs):
        return factory()

    monkeypatch.setattr(module, "_INSTALL_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(module, "_PROCESS_STOP_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(module, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "playwright._impl._driver.compute_driver_executable",
        lambda: ("node", "cli"),
    )
    monkeypatch.setattr(
        "playwright._impl._driver.get_driver_env",
        lambda: {},
    )
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", fake_exec)


@pytest.mark.asyncio
async def test_unkillable_process_blocks_second_install(
    managed_state,
    monkeypatch,
    tmp_path,
):
    class _Proc:
        returncode = None

        def terminate(self):
            return None

        def kill(self):
            return None

        async def wait(self):
            await asyncio.sleep(10)
            return None

        async def communicate(self):
            await asyncio.sleep(10)
            return b"", None

    _patch_fake_install(monkeypatch, managed_state, tmp_path, _Proc)
    await managed_state._download_and_record()
    monkeypatch.setattr(managed_state, "_download_task", _Done())
    monkeypatch.setattr(
        managed_state,
        "_last_failure_at",
        managed.time.monotonic() - 61.0,
    )
    _block_create(monkeypatch, managed_state)
    assert managed_state._install_process is not None
    assert managed_state._install_process_alive()
    ready, detail, retry_after = managed_state.ensure_managed_chromium()
    assert ready is False
    assert detail
    assert "downloading" not in detail.lower()
    assert retry_after >= managed._IN_FLIGHT_RETRY_SECONDS
    ready, detail = managed_state.start_managed_chromium_download()
    assert ready is False
    assert detail
    managed_state._install_process.returncode = -1
    assert managed_state._install_process_alive() is False


@pytest.mark.asyncio
async def test_stop_kills_after_terminate_does_not(
    managed_state,
    monkeypatch,
    tmp_path,
):
    class _Proc:
        returncode = None

        def terminate(self):
            return None

        def kill(self):
            self.returncode = -1

        async def wait(self):
            if self.returncode is None:
                await asyncio.sleep(10)
            return None

        async def communicate(self):
            await asyncio.sleep(10)
            return b"", None

    _patch_fake_install(monkeypatch, managed_state, tmp_path, _Proc)
    await managed_state._download_and_record()
    assert "timed out" in managed_state._last_download_error.lower()
    assert managed_state._install_process is None


def test_disabled_does_not_start_download(monkeypatch):
    monkeypatch.setattr(managed, "_download_task", None)
    monkeypatch.setattr(managed, "_install_process", None)
    monkeypatch.setattr(
        managed,
        "desktop_managed_playwright_enabled",
        lambda: False,
    )
    _block_create(monkeypatch, managed)
    ready, detail = managed.start_managed_chromium_download()
    assert ready is True
    assert detail == ""


class _Alive:
    returncode = None

    def terminate(self):
        self.returncode = -1

    def kill(self):
        self.returncode = -1

    async def wait(self):
        return None


@pytest.mark.asyncio
async def test_stop_reaps_leftover_after_task_done(managed_state, monkeypatch):
    monkeypatch.setattr(managed_state, "_download_task", _Done())
    monkeypatch.setattr(managed_state, "_install_process", _Alive())
    await managed_state.stop_managed_chromium_download()
    assert managed_state._install_process is None


def test_ready_wins_over_leftover_process(managed_state, monkeypatch):
    monkeypatch.setattr(managed_state, "_download_task", _Done())
    monkeypatch.setattr(managed_state, "_install_process", _Alive())
    monkeypatch.setattr(managed_state, "managed_chromium_ready", lambda: True)
    _block_create(monkeypatch, managed_state)
    ready, detail = managed_state.start_managed_chromium_download()
    assert ready is True
    assert detail == ""
    ready, detail, retry_after = managed_state.ensure_managed_chromium()
    assert ready is True
    assert detail == ""
    assert retry_after == 0.0


def test_ensure_not_ready_guarantees_minimum_retry_after(
    managed_state,
    monkeypatch,
):
    monkeypatch.setattr(managed_state, "_download_task", _Done())
    monkeypatch.setattr(managed_state, "_last_failure_at", 0.0)
    monkeypatch.setattr(managed_state, "_install_process", None)

    def fake_create(coro):
        coro.close()
        return _Done()

    monkeypatch.setattr(managed_state.asyncio, "create_task", fake_create)
    ready, _detail, retry_after = managed_state.ensure_managed_chromium()
    assert ready is False
    assert retry_after >= 1.0


def test_alive_process_polls_in_flight_interval(managed_state, monkeypatch):
    monkeypatch.setattr(managed_state, "_download_task", _Done())
    monkeypatch.setattr(managed_state, "_install_process", _Alive())
    monkeypatch.setattr(managed_state, "_last_failure_at", 0.0)
    monkeypatch.setattr(managed_state, "_last_download_error", "timed out")
    _block_create(monkeypatch, managed_state)
    ready, detail, retry_after = managed_state.ensure_managed_chromium()
    assert ready is False
    assert detail == "timed out"
    assert retry_after == managed._IN_FLIGHT_RETRY_SECONDS


@pytest.mark.asyncio
async def test_stop_suppresses_non_cancelled_task_error(
    managed_state,
    monkeypatch,
):
    class _Boom:
        def done(self):
            return False

        def cancel(self):
            return None

        def __await__(self):
            if bool():  # pylint: disable=using-constant-test
                yield
            raise RuntimeError("event loop is closed")

    monkeypatch.setattr(managed_state, "_download_task", _Boom())
    monkeypatch.setattr(managed_state, "_install_process", None)
    await managed_state.stop_managed_chromium_download()


@pytest.mark.asyncio
async def test_stop_logs_warning_when_process_fails_to_exit(
    managed_state,
    monkeypatch,
    caplog,
):
    class _Zombie:
        returncode = None
        pid = 4242

        def terminate(self):
            return None

        def kill(self):
            return None

        async def wait(self):
            await asyncio.sleep(10)
            return None

    monkeypatch.setattr(managed_state, "_PROCESS_STOP_TIMEOUT_SECONDS", 0.05)
    with caplog.at_level(logging.WARNING):
        await managed_state._stop_install_process(_Zombie())
    assert "did not exit" in caplog.text.lower()
