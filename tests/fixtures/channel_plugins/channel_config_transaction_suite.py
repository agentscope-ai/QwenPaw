"""Real channel HTTP saves, isolated from the repository's SDK mocks.

Only runtime rebuilds and QR cleanup timing are doubles. Configuration models,
Workspace.config, agent lookup, validation, CAS and file writes remain real.
"""

import asyncio
from contextlib import asynccontextmanager
from importlib import import_module
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
import pytest
import pytest_asyncio

# The test virtualenv can have an editable install of a sibling checkout.
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/qwenpawmail-mcp/src"))
sys.path.insert(0, str(ROOT / "src"))

import qwenpaw  # noqa: E402
from qwenpaw.app.exception_handlers import register_exception_handlers  # noqa: E402
from qwenpaw.app.workspace.workspace import Workspace  # noqa: E402
from qwenpaw.config import utils as config_utils  # noqa: E402
from qwenpaw.config.config import (  # noqa: E402
    AgentProfileConfig,
    AgentProfileRef,
    AgentsConfig,
    ChannelConfig,
    Config,
    ConsoleConfig,
    DiscordConfig,
    TelegramConfig,
    load_agent_config,
    save_agent_config,
)

CONFIG = import_module("qwenpaw.config.config")
ROUTER = import_module("qwenpaw.app.routers.config")
for module in (
    qwenpaw,
    CONFIG,
    ROUTER,
    import_module(Workspace.__module__),
):
    assert Path(module.__file__).resolve().is_relative_to(ROOT / "src")


class Lifecycle:
    """Retain the same Workspace while rebuilds wait or fail."""

    def __init__(self, workspace):
        self.workspace = workspace
        self.failure = False
        self.release = asyncio.Event()
        self.tasks = []
        self.reload_calls = 0
        self.reload_failures = 0
        self.generations = 0

    async def get_agent(self, agent_id):
        assert agent_id == "agent"
        return self.workspace

    def note_agent_config_changed(self, agent_id):
        assert agent_id == "agent"
        self.generations += 1

    async def reload_agent(self, agent_id):
        assert agent_id == "agent"
        self.tasks.append(asyncio.current_task())
        self.reload_calls += 1
        if self.failure:
            self.reload_failures += 1
            raise RuntimeError("intentional test rebuild failure")
        await self.release.wait()
        return False


@pytest_asyncio.fixture
async def runtime(tmp_path, monkeypatch):
    root_path = tmp_path / "config.json"
    monkeypatch.setattr(config_utils, "get_config_path", lambda: root_path)
    monkeypatch.setattr(config_utils, "_config_cache", None)
    monkeypatch.setattr(config_utils, "_config_mtime", None)
    monkeypatch.setattr(config_utils, "_agent_config_cache", {})
    directory = tmp_path / "agent"
    directory.mkdir()
    config_utils.save_config(
        Config(
            agents=AgentsConfig(
                active_agent="agent",
                profiles={
                    "agent": AgentProfileRef(
                        id="agent",
                        workspace_dir=str(directory),
                    )
                },
            )
        )
    )
    save_agent_config(
        "agent",
        AgentProfileConfig(
            id="agent",
            name="Agent",
            description="keep-description",
            channels=ChannelConfig(
                console=ConsoleConfig(media_dir="initial"),
                discord=DiscordConfig(bot_prefix="keep-prefix"),
                telegram=TelegramConfig(enabled=True),
            ),
        ),
    )
    workspace = object.__new__(Workspace)
    workspace.agent_id = "agent"
    workspace.workspace_dir = directory
    workspace._config = None
    workspace._config_mtime = None
    workspace.config  # Pin the real property before any HTTP request.
    lifecycle = Lifecycle(workspace)
    app = FastAPI()
    app.state.multi_agent_manager = lifecycle
    register_exception_handlers(app)
    app.include_router(ROUTER.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Agent-Id": "agent"},
    ) as client:
        try:
            yield SimpleNamespace(
                client=client,
                workspace=workspace,
                lifecycle=lifecycle,
                app=app,
                path=directory / "agent.json",
            )
        finally:
            lifecycle.release.set()
            await asyncio.sleep(0)
            if lifecycle.tasks:
                await asyncio.gather(*lifecycle.tasks)


def put(runtime, kind, channel, values):
    if kind == "single":
        return runtime.client.put(f"/config/channels/{channel}", json=values)
    return runtime.client.put("/config/channels", json={channel: values})


def disk(runtime):
    return json.loads(runtime.path.read_text())


def assert_preserved(runtime):
    persisted = disk(runtime)
    assert persisted["description"] == "keep-description"
    assert persisted["channels"]["discord"]["bot_prefix"] == "keep-prefix"


def durable_fields(value):
    """HTTP includes default nulls; persisted agent JSON excludes them."""
    if isinstance(value, dict):
        return {
            key: durable_fields(item) for key, item in value.items() if item is not None
        }
    if isinstance(value, list):
        return [durable_fields(item) for item in value]
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["single", "bulk"])
@pytest.mark.parametrize("legacy_null", [False, True])
async def test_slack_null_roundtrip_edits_and_enable_toggles(
    runtime,
    monkeypatch,
    kind,
    legacy_null,
):
    from qwenpaw.plugins.official_channels import bundled_channel_description
    from qwenpaw.plugins.registry import PluginRegistry

    monkeypatch.setattr(PluginRegistry, "_instance", None)
    if legacy_null:
        # Exercise the installed descriptor path with the real packaged schema.
        PluginRegistry().register_channel_descriptor(
            "slack",
            bundled_channel_description("slack"),
        )
        payload = disk(runtime)
        payload["channels"]["slack"]["allow_from"] = None
        CONFIG.write_json_atomic(runtime.path, payload)
    before = disk(runtime)
    response = await runtime.client.get("/config/channels/slack")
    assert response.status_code == 200, response.text
    values = response.json()
    assert values["allow_from"] is None
    for changes in (
        {},
        {"bot_token": "saved-bot", "app_token": "saved-app"},
        {"enabled": True},
        {"enabled": False},
    ):
        values.update(changes)
        response = await put(runtime, kind, "slack", values)
        assert response.status_code == 200, response.text
        saved = response.json()
        saved = saved if kind == "single" else saved["slack"]
        assert saved == {**values, "allow_from": []}
        assert disk(runtime) == {
            **before,
            "channels": {
                **before["channels"],
                "slack": durable_fields(saved),
            },
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["single", "bulk"])
@pytest.mark.parametrize(
    "values, expected",
    [({}, []), ({"allow_from": []}, []), ({"allow_from": ["U123"]}, ["U123"])],
)
async def test_slack_missing_or_list_allow_from_saves(
    runtime,
    kind,
    values,
    expected,
):
    response = await put(runtime, kind, "slack", values)
    assert response.status_code == 200, response.text
    saved = response.json()
    saved = saved if kind == "single" else saved["slack"]
    assert saved["allow_from"] == expected
    assert disk(runtime)["channels"]["slack"]["allow_from"] == expected
    assert_preserved(runtime)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["single", "bulk"])
@pytest.mark.parametrize(
    "channel, value",
    [
        ("slack", False),
        ("slack", ""),
        ("slack", 7),
        ("slack", {}),
        ("discord", None),
    ],
)
async def test_allow_from_invalid_values_do_not_change_disk(
    runtime,
    kind,
    channel,
    value,
):
    before = runtime.path.read_bytes()
    response = await put(runtime, kind, channel, {"allow_from": value})
    assert response.status_code == 422, response.text
    assert any(
        error["loc"] == ["allow_from"] for error in response.json()["detail"]
    )
    assert runtime.path.read_bytes() == before
    assert runtime.lifecycle.generations == 0
    assert runtime.lifecycle.reload_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["single", "bulk"])
@pytest.mark.parametrize("reload_fails", [False, True])
async def test_sequential_saves_do_not_depend_on_runtime_rebuild(
    runtime,
    kind,
    reload_fails,
):
    runtime.lifecycle.failure = reload_fails
    for value in ("first", "second"):
        response = await put(runtime, kind, "console", {"media_dir": value})
        assert response.status_code == 200, response.text
        persisted = disk(runtime)["channels"]
        assert persisted["console"]["media_dir"] == value
        assert durable_fields(response.json()) == (
            persisted["console"] if kind == "single" else persisted
        )
        await asyncio.sleep(0)
    assert runtime.workspace.config.channels.console.media_dir == "second"
    assert runtime.lifecycle.reload_calls == 2
    assert runtime.lifecycle.reload_failures == (2 if reload_fails else 0)
    assert runtime.lifecycle.generations == 2
    assert_preserved(runtime)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["single", "bulk"])
async def test_same_mtime_pinned_workspace_does_not_reject_repeated_saves(
    runtime,
    kind,
):
    pinned = runtime.workspace.config
    initial = runtime.path.stat()
    first = await put(runtime, kind, "console", {"media_dir": "first"})
    assert first.status_code == 200, first.text
    assert runtime.path.stat().st_ino != initial.st_ino
    os.utime(runtime.path, ns=(initial.st_atime_ns, initial.st_mtime_ns))
    assert runtime.workspace.config is pinned
    assert pinned.channels.console.media_dir == "initial"
    for value in ("second", "third"):
        response = await put(runtime, kind, "console", {"media_dir": value})
        assert response.status_code == 200, response.text
        assert disk(runtime)["channels"]["console"]["media_dir"] == value
    assert_preserved(runtime)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["single", "bulk"])
async def test_disable_cleanup_preserves_an_independent_concurrent_save(
    runtime,
    kind,
):
    entered, release = asyncio.Event(), asyncio.Event()

    class Sessions:
        @asynccontextmanager
        async def operation_guard(self, agent_id, channels):
            assert agent_id == "agent"
            if "telegram" in channels:
                entered.set()
                await release.wait()
            yield

    runtime.app.state.channel_qrcode_sessions = Sessions()
    first = asyncio.create_task(
        put(
            runtime,
            kind,
            "telegram",
            {"enabled": False},
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        other = await put(
            runtime,
            "single",
            "console",
            {"media_dir": "other-request"},
        )
        assert other.status_code == 200, other.text
        assert disk(runtime)["channels"]["console"]["media_dir"] == "other-request"
    finally:
        release.set()
    response = await first
    assert response.status_code == 200, response.text
    persisted = disk(runtime)["channels"]
    assert persisted["console"]["media_dir"] == "other-request"
    assert persisted["telegram"]["enabled"] is False
    assert durable_fields(response.json()) == (
        persisted["telegram"] if kind == "single" else persisted
    )
    assert_preserved(runtime)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["single", "bulk"])
async def test_external_write_between_read_and_cas_still_returns_conflict(
    runtime,
    monkeypatch,
    kind,
):
    check = CONFIG._assert_agent_config_unchanged
    injected = False

    def external_write_before_check(path, digest, agent_id):
        nonlocal injected
        assert Path(path) == runtime.path
        assert not injected
        injected = True
        payload = disk(runtime)
        payload["description"] = "external-update"
        CONFIG.write_json_atomic(path, payload)
        return check(path, digest, agent_id)

    monkeypatch.setattr(
        CONFIG,
        "_assert_agent_config_unchanged",
        external_write_before_check,
    )
    response = await put(runtime, kind, "console", {"media_dir": "rejected"})
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "AGENT_CONFIG_STALE"
    assert injected
    persisted = disk(runtime)
    assert persisted["description"] == "external-update"
    assert persisted["channels"]["console"]["media_dir"] == "initial"
    assert runtime.lifecycle.generations == 0
    assert runtime.lifecycle.reload_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["single", "bulk"])
async def test_failed_disk_write_does_not_publish_candidate_or_reload(
    runtime,
    monkeypatch,
    kind,
):
    before = runtime.path.read_bytes()
    pinned = runtime.workspace.config

    def fail_write(path, _payload):
        assert Path(path) == runtime.path
        raise OSError("injected channel write failure")

    monkeypatch.setattr(CONFIG, "write_json_atomic", fail_write)
    with pytest.raises(OSError, match="injected channel write failure"):
        await put(runtime, kind, "console", {"media_dir": "uncommitted"})
    assert runtime.path.read_bytes() == before
    assert runtime.workspace.config is pinned
    assert pinned.channels.console.media_dir == "initial"
    assert load_agent_config("agent").channels.console.media_dir == "initial"
    assert runtime.lifecycle.generations == 0
    assert runtime.lifecycle.reload_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["single", "bulk"])
@pytest.mark.parametrize("disabling", [False, True])
async def test_cleanup_guard_observes_required_commit_order(
    runtime,
    kind,
    disabling,
):
    observations = []
    channel = "telegram" if disabling else "console"
    values = {"enabled": False} if disabling else {"media_dir": "committed"}

    class Sessions:
        @asynccontextmanager
        async def operation_guard(self, agent_id, channels):
            assert agent_id == "agent"
            assert channel in channels
            current = disk(runtime)["channels"][channel]
            observations.append(
                current["enabled"] if disabling else current["media_dir"],
            )
            yield

    runtime.app.state.channel_qrcode_sessions = Sessions()
    response = await put(runtime, kind, channel, values)
    assert response.status_code == 200, response.text
    assert observations == ([True] if disabling else ["committed"])
    persisted = disk(runtime)["channels"][channel]
    assert persisted["enabled"] is (False if disabling else True)
    if not disabling:
        assert persisted["media_dir"] == "committed"
