# -*- coding: utf-8 -*-
# pylint: disable=protected-access
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from textwrap import indent
from types import SimpleNamespace

import pytest

from qwenpaw.app.agent_context import scoped_session_id
from qwenpaw.modes.mission import MissionMode
from qwenpaw.portability.adaptation_loop import (
    _DRAINING_WORKERS,
    _run_phase,
    _stop_worker,
    drain_adaptation_workers,
    get_active_adaptation_context,
    run_adaptation_loop,
)
from qwenpaw.portability.compatibility import (
    CompatibilityAsset,
    AssetType,
    AssetZone,
)
from qwenpaw.portability.compatibility_testing import (
    CompatibilityTester,
)
from qwenpaw.portability.models import (
    ProviderInventory,
    SourceMCPServer,
    SourcePlugin,
    SourceSkill,
)


def _skill(tmp_path: Path, body: str) -> SourceSkill:
    root = tmp_path / "source-skill"
    root.mkdir()
    (root / "SKILL.md").write_text(body, encoding="utf-8")
    return SourceSkill(
        source_id="demo",
        name="demo",
        description="demo",
        directory=root,
    )


class _Workspace:
    def __init__(self, root: Path, action) -> None:
        self.workspace_dir = root / "workspace"
        self.workspace_dir.mkdir()
        self.agent_id = "agent"
        self.plugins = SimpleNamespace(
            modes=[MissionMode()],
            tool_registry=SimpleNamespace(names=lambda: ["read_file"]),
        )
        self.cron_manager = None
        self._action = action
        self.request = None
        self.requests = []
        self.active_queries = 0
        self.max_active_queries = 0

    async def stream_query(self, request):
        self.request = request
        self.requests.append(request)
        self.active_queries += 1
        self.max_active_queries = max(
            self.max_active_queries,
            self.active_queries,
        )
        try:
            await asyncio.sleep(0)
            with scoped_session_id(request.session_id):
                await self._action(get_active_adaptation_context())
        finally:
            self.active_queries -= 1
        if self.request is None:
            yield None


@pytest.mark.asyncio
async def test_stopping_an_uncooperative_worker_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()

    async def worker() -> None:
        while not release.is_set():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                continue

    workspace = SimpleNamespace(agent_id="agent")
    task = asyncio.create_task(worker())
    await asyncio.sleep(0)
    monkeypatch.setattr(
        "qwenpaw.portability.adaptation_loop._WORKER_STOP_GRACE_SECONDS",
        0.01,
    )
    await _stop_worker(workspace, task)
    assert task in _DRAINING_WORKERS[workspace.agent_id]
    assert await drain_adaptation_workers(timeout=0.01) == 1
    release.set()
    task.cancel()
    await task
    assert workspace.agent_id not in _DRAINING_WORKERS


def _phase_context() -> SimpleNamespace:
    return SimpleNamespace(
        progress=None,
        activity=lambda _session_id: "",
        clear_activity=lambda _session_id: None,
    )


def _phase_asset() -> CompatibilityAsset:
    return CompatibilityAsset(
        asset_key="skills:demo",
        asset_type=AssetType.SKILL,
        source_id="demo",
        name="demo",
        updated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_heartbeat_does_not_reset_mission_idle_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def stream_query(_request):
        while True:
            yield SimpleNamespace(type="heartbeat")
            await asyncio.sleep(0.001)

    workspace = SimpleNamespace(agent_id="agent", stream_query=stream_query)
    monkeypatch.setattr(
        "qwenpaw.portability.adaptation_loop._HEARTBEAT_SECONDS",
        0.005,
    )
    monkeypatch.setattr(
        "qwenpaw.portability.adaptation_loop._IDLE_SECONDS",
        0.03,
    )
    with pytest.raises(TimeoutError, match="was idle"):
        await _run_phase(
            workspace,
            _phase_context(),
            session_id="test-heartbeat",
            asset=_phase_asset(),
            prompt="test",
            tools=(),
            label="test",
        )


@pytest.mark.asyncio
async def test_mission_worker_has_absolute_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def stream_query(_request):
        while True:
            yield SimpleNamespace(type="message")
            await asyncio.sleep(0.001)

    workspace = SimpleNamespace(agent_id="agent", stream_query=stream_query)
    monkeypatch.setattr(
        "qwenpaw.portability.adaptation_loop._HEARTBEAT_SECONDS",
        0.005,
    )
    monkeypatch.setattr(
        "qwenpaw.portability.adaptation_loop._IDLE_SECONDS",
        1,
    )
    monkeypatch.setattr(
        "qwenpaw.portability.adaptation_loop._MAX_WORKER_SECONDS",
        0.03,
    )
    with pytest.raises(TimeoutError, match="exceeded"):
        await _run_phase(
            workspace,
            _phase_context(),
            session_id="test-deadline",
            asset=_phase_asset(),
            prompt="test",
            tools=(),
            label="test",
        )


def _write_native_plugin(root: Path, backend: str) -> None:
    (root / "plugin.json").write_text(
        '{"id":"native","version":"1.0.0","entry":{"backend":"plugin.py"}}',
        encoding="utf-8",
    )
    (root / "plugin.py").write_text(backend, encoding="utf-8")


def _native_backend(
    registration: str,
    *,
    definitions: str = "",
    register_args: str = "self, api",
) -> str:
    prefix = f"{definitions.rstrip()}\n\n" if definitions else ""
    return (
        f"{prefix}class NativePlugin:\n"
        f"    def register({register_args}):\n"
        f"{indent(registration.strip(), '        ')}\n\n"
        "plugin = NativePlugin()\n"
    )


@pytest.mark.parametrize(
    ("backend", "message"),
    [
        (
            _native_backend(
                "api.register_slash_command(\n"
                "    name='demo', async_handler=command)",
                definitions="async def command(ctx, args):\n    return None",
            ),
            "unexpected keyword.*async_handler",
        ),
        (
            _native_backend(
                "api.register_slash_command('demo', command)",
                definitions="async def command(args):\n    return None",
            ),
            "register_slash_command.handler",
        ),
        (
            _native_backend(
                "api.register_slash_command('demo', command)",
                definitions="def command(ctx, args):\n    return None",
            ),
            "register_slash_command.handler",
        ),
        (
            _native_backend("api.register_skill_provider('skills', True)"),
            "register_skill_provider",
        ),
        (
            _native_backend("pass", register_args="self, api, required"),
            r"callable as register\(api\)",
        ),
        (
            _native_backend(
                "api.register_startup_hook('start', startup)",
                definitions="def startup(required):\n    pass",
            ),
            "register_startup_hook.callback",
        ),
        (
            _native_backend(
                "api.register_middleware(middleware)",
                definitions="async def middleware(ctx, config):\n    pass",
            ),
            "register_middleware.middleware_factory",
        ),
        (
            _native_backend(
                "api.register_control_command(Handler())",
                definitions=(
                    "class Handler:\n"
                    "    command_name = '/demo'\n"
                    "    def handle(self, context):\n"
                    "        pass"
                ),
            ),
            "register_control_command.handler",
        ),
        (
            _native_backend(
                "configure(api)",
                definitions=(
                    "def configure(api):\n"
                    "    api.register_skill_provider('skills')"
                ),
            ),
            "PluginApi value escapes",
        ),
    ],
)
def test_native_plugin_rejects_invalid_registration_contract(
    tmp_path: Path,
    backend: str,
    message: str,
) -> None:
    _write_native_plugin(tmp_path, backend)

    with pytest.raises(ValueError, match=message):
        CompatibilityTester._test_native_plugin(tmp_path)


def test_native_plugin_test_accepts_valid_registration_contract(
    tmp_path: Path,
) -> None:
    _write_native_plugin(
        tmp_path,
        "async def command(ctx, args):\n"
        "    return None\n\n"
        "class NativePlugin:\n"
        "    def register(self, api):\n"
        "        api.register_skill_provider(\n"
        "            'skills', enabled_by_default=True, channels=['all'])\n"
        "        api.register_slash_command(\n"
        "            name='demo', handler=command, help_text='Demo')\n\n"
        "plugin = NativePlugin()\n",
    )

    result = CompatibilityTester._test_native_plugin(tmp_path)

    assert result.passed
    assert "plugin_api_calls_validated=2" in result.evidence


@pytest.mark.asyncio
async def test_mission_classifies_portable_asset_for_enabled_migration(
    tmp_path: Path,
) -> None:
    progress_messages = []
    stopped = asyncio.Event()

    async def progress(message: str) -> None:
        progress_messages.append(message)

    async def action(context):
        finalized = await context.finalize_asset("skills:demo", "native")
        assert finalized["passed"], finalized
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    workspace = _Workspace(tmp_path, action)
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        skills=[
            _skill(
                tmp_path,
                "---\nname: demo\ndescription: demo\n---\nUse QwenPaw.\n",
            ),
        ],
    )
    result = await asyncio.wait_for(
        run_adaptation_loop(workspace, inventory, "migration-1", progress),
        timeout=1,
    )
    assert result.manifest.state.value == "completed"
    assert result.manifest.assets[0].zone is AssetZone.MIGRATE
    assert result.summary_path.is_file()
    mission_prd = json.loads(
        (result.summary_path.parent / "mission" / "prd.json").read_text(
            encoding="utf-8",
        ),
    )
    assert mission_prd["userStories"][0]["passes"] is True
    assert stopped.is_set()
    assert any("正在测试 Skill「demo」" in item for item in progress_messages)
    assert any("兼容性优化完成，已进入待迁移区" in item for item in progress_messages)
    assert [
        item.request_context["portability_phase"]
        for item in workspace.requests
    ] == ["mission_repair"]


@pytest.mark.asyncio
async def test_mission_repairs_then_retests_skill(tmp_path: Path) -> None:
    async def action(context):
        await context.write_file(
            "skills:demo",
            "SKILL.md",
            "---\nname: demo\ndescription: demo\n---\nRun QwenPaw tools.\n",
        )
        assert (await context.finalize_asset("skills:demo", "retested"))[
            "passed"
        ]

    workspace = _Workspace(tmp_path, action)
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        skills=[
            _skill(
                tmp_path,
                "---\nname: demo\ndescription: demo\n---\nRun codex exec.\n",
            ),
        ],
    )
    result = await run_adaptation_loop(workspace, inventory, "migration-2")
    assert result.manifest.get_asset("skills:demo").zone.value == "migrate"
    staged = inventory.skills[0].directory / "SKILL.md"
    assert "QwenPaw tools" in staged.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_missing_mission_mode_fails_safe_into_repair(
    tmp_path: Path,
) -> None:
    async def action(context):
        await context.finalize_asset("skills:demo", "native")

    workspace = _Workspace(tmp_path, action)
    workspace.plugins.modes = []
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        skills=[
            _skill(
                tmp_path,
                "---\nname: demo\ndescription: demo\n---\n",
            ),
        ],
    )
    result = await run_adaptation_loop(workspace, inventory, "migration-4")
    assert result.manifest.state.value == "stopped_limit"
    assert result.manifest.get_asset("skills:demo").zone.value == "repair"
    summary = result.summary_path.read_text(encoding="utf-8")
    assert "停止原因：无法完成 QwenPaw Mission" in summary


@pytest.mark.asyncio
async def test_rejected_secret_repair_does_not_mutate_source(
    tmp_path: Path,
) -> None:
    server = SourceMCPServer(
        source_id="safe-mcp",
        name="safe-mcp",
        command=sys.executable,
    )

    async def action(context):
        with pytest.raises(ValueError, match="contains a secret"):
            await context.update_asset(
                "mcp:safe-mcp",
                "args",
                '["--api-key", "sk-do-not-persist"]',
            )
        assert server.args == []
        finalized = await context.finalize_asset("mcp:safe-mcp", "native")
        assert finalized["passed"], finalized

    workspace = _Workspace(tmp_path, action)
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        mcp_servers=[server],
    )

    result = await run_adaptation_loop(workspace, inventory, "migration-5")

    assert result.manifest.get_asset("mcp:safe-mcp").zone.value == "migrate"
    persisted = result.manifest.model_dump_json()
    assert "sk-do-not-persist" not in persisted


@pytest.mark.asyncio
async def test_mixed_plugin_is_one_asset_with_component_review_and_repair(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mixed-plugin"
    files = {
        ".qoder-plugin/plugin.json": '{"name":"mixed","version":"1"}',
        "skills/report/SKILL.md": "Report skill",
        "commands/report.md": "Run Qoder command",
        "agents/reviewer.md": "Qoder review agent",
        "hooks/hooks.json": '{"onStart":"./start.sh"}',
        "hooks/start.sh": "qoder --start",
        "rules/review.md": "Review rules",
        "mcp.json": '{"mcpServers":{}}',
    }
    for relative, content in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    async def action(context):
        await context.write_file(
            "plugins:mixed",
            "plugin.json",
            json.dumps(
                {
                    "id": "mixed",
                    "version": "1.0.0",
                    "entry": {"backend": "plugin.py"},
                },
            ),
        )
        await context.write_file(
            "plugins:mixed",
            "plugin.py",
            "class MixedPlugin:\n"
            "    def register(self, api):\n"
            "        api.register_skill_provider(skills_dir=__import__(\n"
            "            'pathlib').Path(__file__).parent / 'skills')\n\n"
            "plugin = MixedPlugin()\n",
        )
        finalized = await context.finalize_asset(
            "plugins:mixed",
            "native plugin test passed",
        )
        assert finalized["passed"], finalized

    inventory = ProviderInventory(
        provider_id="qoder",
        provider_name="Qoder",
        detected=True,
        plugins=[
            SourcePlugin(
                source_id="mixed",
                name="mixed",
                marketplace="local",
                install_source=str(source),
            ),
        ],
    )
    result = await run_adaptation_loop(
        _Workspace(tmp_path, action),
        inventory,
        "migration-mixed",
    )
    assert result.manifest.get_asset("plugins:mixed").zone.value == "migrate"
    staged = Path(inventory.plugins[0].install_source)
    assert (staged / "hooks/start.sh").is_file()


@pytest.mark.asyncio
async def test_mission_repairs_assets_in_parallel_with_isolated_scope(
    tmp_path: Path,
) -> None:
    first = _skill(tmp_path, "---\nname: demo\n---\nInvalid.\n")
    first.source_id = "first"
    first.name = "first"
    second_root = tmp_path / "second-skill"
    second_root.mkdir()
    (second_root / "SKILL.md").write_text(
        "---\nname: second\ndescription: valid\n---\nValid.\n",
        encoding="utf-8",
    )
    second = SourceSkill(
        source_id="second",
        name="second",
        directory=second_root,
    )

    async def action(context):
        key = context.active_asset_key
        other = "skills:second" if key == "skills:first" else "skills:first"
        with pytest.raises(PermissionError, match="assigned asset"):
            await context.finalize_asset(other, "passed")
        finalized = await context.finalize_asset(key, "passed")
        if finalized["passed"]:
            return
        await context.write_file(
            key,
            "SKILL.md",
            "---\nname: first\ndescription: repaired\n---\nValid.\n",
        )
        assert (await context.finalize_asset(key, "passed"))["passed"]

    workspace = _Workspace(tmp_path, action)
    result = await run_adaptation_loop(
        workspace,
        ProviderInventory(
            provider_id="codex",
            provider_name="Codex",
            detected=True,
            skills=[first, second],
        ),
        "migration-parallel",
    )
    assert result.manifest.state.value == "completed"
    assert workspace.max_active_queries == 2
    assert result.manifest.get_asset("skills:first").tests == 2
    phases = [
        item.request_context["portability_phase"]
        for item in workspace.requests
    ]
    assert phases.count("mission_repair") == 2
