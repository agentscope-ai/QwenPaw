# -*- coding: utf-8 -*-
"""Isolated Chromium fixtures for Unified Browser integration contracts."""

# pylint: disable=protected-access,wrong-import-position

from pathlib import Path
import json
import os
import shutil
import tempfile

import pytest
import pytest_asyncio

# This executes before any QwenPaw module is imported by browser tests. Worker
# subprocesses inherit it, so they cannot read a developer's live config or
# launch the system browser in headed mode.
_TEST_WORKING_DIR = Path(tempfile.mkdtemp(prefix="qwenpaw-browser-tests-"))
os.environ["QWENPAW_WORKING_DIR"] = str(_TEST_WORKING_DIR)
os.environ["QWENPAW_CONFIG_FILE"] = "config.json"
os.environ.pop("PWDEBUG", None)
(_TEST_WORKING_DIR / "config.json").write_text(
    json.dumps(
        {
            "browser": {
                "engine": "chromium",
                "headless": "true",
                "use_system_default": False,
            },
        },
    ),
    encoding="utf-8",
)

from qwenpaw.browser.control_link.playwright.adapter import (  # noqa: E402
    PlaywrightControlLink,
)
from qwenpaw.browser.execution.subprocess_plane import (  # noqa: E402
    SubprocessPlane,
)
from qwenpaw.browser.runtime import links as runtime_links  # noqa: E402


class _OwnerBoundLink:
    """Keep legacy provider fixture calls explicit on the wire."""

    def __init__(self, link: PlaywrightControlLink) -> None:
        self._link = link
        self._workspaces = {"s1": "ws1"}

    def __getattr__(self, name: str):
        return getattr(self._link, name)

    async def request(self, method: str, params: dict, **kwargs):
        payload = dict(params)
        session_id = payload.get("session_id")
        if (
            method == "open_session"
            and session_id
            and payload.get("workspace_id")
        ):
            self._workspaces[str(session_id)] = str(payload["workspace_id"])
        if session_id and "workspace_id" not in payload:
            payload["workspace_id"] = self._workspaces[str(session_id)]
        return await self._link.request(method, payload, **kwargs)


@pytest_asyncio.fixture(autouse=True)
async def isolated_browser_runtime(monkeypatch: pytest.MonkeyPatch):
    """Forbid interactive browsers and destroy test-created resources."""
    planes: list[SubprocessPlane] = []
    initial_links = list(runtime_links._local)
    original_init = SubprocessPlane.__init__
    from qwenpaw.browser.control_link.playwright import adapter

    original_build_launch_kwargs = adapter._build_launch_kwargs

    def isolated_launch_kwargs(params):
        launch, context = original_build_launch_kwargs(params)
        launch["headless"] = True
        launch.pop("channel", None)
        launch.pop("executable_path", None)
        return launch, context

    def tracked_init(self, *args, **kwargs) -> None:
        original_init(self, *args, **kwargs)
        planes.append(self)

    monkeypatch.setattr(SubprocessPlane, "__init__", tracked_init)
    monkeypatch.setattr(
        adapter,
        "_build_launch_kwargs",
        isolated_launch_kwargs,
    )
    monkeypatch.setattr(runtime_links, "_external", lambda: ())
    try:
        yield
    finally:
        for plane in reversed(planes):
            workers = list(plane._workers.items())
            if all(hasattr(worker, "link_server") for _key, worker in workers):
                await plane.discard_all_workers()
            else:
                for key, worker in workers:
                    if hasattr(worker, "link_server"):
                        await plane.discard_worker(key)
        for link in list(adapter._LIVE):
            await link.close_all()
        for link in list(runtime_links._local):
            if link not in initial_links:
                runtime_links.unregister_local(link)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Remove the temporary test profile after all async teardown has run."""
    del session, exitstatus
    shutil.rmtree(_TEST_WORKING_DIR, ignore_errors=True)


@pytest.fixture
def fixture_url() -> str:
    return (Path(__file__).parent / "fixtures" / "basic.html").as_uri()


@pytest_asyncio.fixture
async def provider():
    link = PlaywrightControlLink()
    await link.request(
        "open_session",
        {
            "workspace_id": "ws1",
            "session_id": "s1",
            "context": "incognito",
        },
    )
    try:
        yield _OwnerBoundLink(link)
    finally:
        if link._procs:
            await link.close_all()
