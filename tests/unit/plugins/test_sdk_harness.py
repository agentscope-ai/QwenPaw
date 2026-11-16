# -*- coding: utf-8 -*-
"""Wheel-portable Harness author acceptance, using only public SDK imports."""

import asyncio
import dataclasses
import json

import pytest
from pydantic import SecretStr

from qwenpaw.plugins import SDKError
from qwenpaw.plugins.harnesses import (
    HarnessCallContext,
    HarnessContext,
    HarnessMCPServerDefinition,
    HarnessRunRequest,
    HarnessRuntimeCapabilities,
    HarnessSpec,
    HarnessStatus,
)
from qwenpaw.plugins.testing import PluginTestHost

SOURCE = """
from qwenpaw.plugins.harnesses import (
    HarnessApprovalSummary, HarnessCapabilities, HarnessEvent,
    HarnessEventKind, HarnessSpec, HarnessStatus,
)

class Backend:
    def __init__(self, context):
        self.context = context

    async def status(self, context):
        assert context.runtime_capabilities is None
        return HarnessStatus(installed=True, authenticated=True)

    async def run_turn(self, context, request):
        assert isinstance(context.settings, dict)
        assert context.runtime_capabilities is not None
        assert (context.session_id, context.user_id) == ("session", "alice")
        decision = await context.request_approval(
            HarnessApprovalSummary("shell", "Allow shell?"), timeout=5
        )
        yield HarnessEvent(HarnessEventKind.TEXT_DELTA, text=decision)
        yield HarnessEvent(HarnessEventKind.COMPLETED)

    async def close(self):
        pass

class Plugin:
    def register(self, context):
        def create(factory_context, settings):
            count = context.storage.read_json("factories", 0)
            context.storage.write_json("factories", count + 1)
            return Backend(factory_context)
        context.register_harness(HarnessSpec(
            "author-harness", "Author harness", create, HarnessCapabilities()
        ))

plugin = Plugin()
"""


def package(
    tmp_path,
    name="author-owner",
    *,
    version="1.1.0",
    capabilities=None,
):
    root = tmp_path / name
    root.mkdir()
    (root / "main.py").write_text(SOURCE, encoding="utf-8")
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": name,
                "version": "1.0.0",
                "entry": {"backend": "main.py"},
                "sdk": {
                    "version": version,
                    "capabilities": (
                        capabilities
                        if capabilities is not None
                        else ["harnesses", "storage"]
                    ),
                },
                "meta": {
                    "harnesses": [{"id": "author-harness", "label": "Author"}],
                },
            },
        ),
        encoding="utf-8",
    )
    return root


def test_public_requests_contexts_and_credentials():
    for cls in (HarnessSpec, HarnessContext, HarnessCallContext):
        assert (
            dataclasses.is_dataclass(cls) and cls.__dataclass_params__.frozen
        )
    request = HarnessRunRequest("hello")
    assert request.attachments == ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.prompt = "changed"
    server = HarnessMCPServerDefinition(
        name="private",
        display_name="Private",
        transport="stdio",
        env={"TOKEN": SecretStr("author-secret")},
        headers={"Authorization": SecretStr("author-header")},
    )
    capabilities = HarnessRuntimeCapabilities(mcp_servers=(server,))
    assert server.revealed_env() == {"TOKEN": "author-secret"}
    assert server.revealed_headers() == {"Authorization": "author-header"}
    rendered = repr(capabilities) + json.dumps(
        dataclasses.asdict(capabilities),
        default=str,
    )
    assert "author-secret" not in rendered and "author-header" not in rendered
    assert "author-secret" not in capabilities.fingerprint


async def test_author_registers_queries_and_runs_with_public_approval(
    tmp_path,
):
    async with PluginTestHost(tmp_path / "host") as host:
        assert (await host.install(package(tmp_path))).ok
        rows = host.list_harnesses()
        assert [(row["id"], row["status"]) for row in rows] == [
            ("author-harness", "available"),
        ]
        storage = host.context("author-owner").storage
        assert storage.read_json("factories", 0) == 0
        status = await host.harness_status(
            "author-harness",
            workspace_id="one",
        )
        assert isinstance(status, HarnessStatus) and status.installed

        async def run():
            return [
                event
                async for event in host.run_harness(
                    "author-harness",
                    HarnessRunRequest("approval"),
                    workspace_id="one",
                    session_id="session",
                    user_id="alice",
                )
            ]

        task = asyncio.create_task(run())
        try:
            async with asyncio.timeout(5):
                while not (pending := await host.approval_requests("session")):
                    await asyncio.sleep(0.005)
            assert len(pending) == 1 and pending[0].workspace_id == "one"
            assert await host.resolve_approval(
                pending[0].request_id,
                approved=True,
            )
            final = (await task)[-1]
            assert final.object == "response" and final.status == "completed"
            assert final.output[-1].content[0].text == "approved"
            assert storage.read_json("factories") == 1
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_duplicate_harness_id_preserves_registered_owner(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        assert (await host.install(package(tmp_path))).ok
        with pytest.raises(SDKError, match="author-owner"):
            await host.install(package(tmp_path, "other-owner"))
        assert (
            await host.harness_status("author-harness", workspace_id="one")
        ).installed
        assert host.list_harnesses()[0]["plugin_id"] == "author-owner"


async def test_boot_discovery_preserves_failed_harness_across_load_phases(
    tmp_path,
):
    async with PluginTestHost(tmp_path / "host") as host:
        plugins = host.root / "plugins"
        plugins.mkdir(exist_ok=True)
        root = package(plugins)
        marker = tmp_path / "entry-executed"
        (root / "main.py").write_text(
            "from pathlib import Path\n"
            f"marker = Path({str(marker)!r})\n"
            "marker.write_text(marker.read_text() + 'x' "
            "if marker.exists() else 'x')\n"
            "raise RuntimeError('entry failed')\n",
            encoding="utf-8",
        )

        await host._loader.load_all_plugins(types=["channel"])
        assert host.list_harnesses()[0]["status"] == "disabled"
        assert not marker.exists()

        await host._loader.load_all_plugins()
        record = host._loader.get_loaded_plugin("author-owner")
        assert record.status == "failed"
        for types in (["channel"], None):
            await host._loader.load_all_plugins(types=types)
            assert host.list_harnesses()[0]["status"] == "failed"
            assert host._loader.get_loaded_plugin("author-owner") is record
        assert marker.read_text() == "x"


@pytest.mark.parametrize("missing_dependency", [False, True])
async def test_offline_migration_prepares_saved_harness_without_execution(
    tmp_path,
    monkeypatch,
    missing_dependency,
):
    from qwenpaw.plugins.harness_migration import migrate_legacy_harnesses

    async with PluginTestHost(tmp_path / "host") as host:
        await host._workspace("default")
        workspace = await host._workspace("legacy")
        agent_path = workspace.workspace_dir / "agent.json"
        agent = json.loads(agent_path.read_text())
        agent.update(backend="codex", backend_settings={"model": "saved"})
        agent_path.write_text(json.dumps(agent), encoding="utf-8")
        config_path = host.root / "config.json"
        config = json.loads(config_path.read_text())
        config.setdefault("plugins", {})["qwenpaw-harness-codex"] = {
            "enabled": False,
        }
        config_path.write_text(json.dumps(config), encoding="utf-8")
        before = config_path.read_bytes(), agent_path.read_bytes()
        prepared = tmp_path / "prepared"
        prepared.mkdir()
        root = package(prepared, "qwenpaw-harness-codex")
        (root / "main.py").write_text(
            "raise AssertionError('offline migration executed entry')\n",
            encoding="utf-8",
        )
        if missing_dependency:
            (root / "requirements.txt").write_text(
                "qwenpaw-offline-migration-absent==1\n",
                encoding="utf-8",
            )

        def forbid_process(*_args, **_kwargs):
            pytest.fail("Offline migration launched a dependency installer")

        monkeypatch.setattr("subprocess.Popen", forbid_process)
        preview = (await migrate_legacy_harnesses(prepared))["plugins"][0]
        assert preview["agents"] == ["legacy"]
        assert preview["enabled"] is False
        assert preview["missing_dependencies"] == (
            ["qwenpaw-offline-migration-absent==1"]
            if missing_dependency
            else []
        )
        assert preview["action"] == (
            "prepare-dependencies" if missing_dependency else "install"
        )
        assert preview["result"] == "not-applied"
        target = host.root / "plugins" / "qwenpaw-harness-codex"
        assert not target.exists()

        applied = (await migrate_legacy_harnesses(prepared, apply=True))[
            "plugins"
        ][0]
        assert applied["result"] == (
            "not-prepared" if missing_dependency else "installed"
        )
        assert target.is_dir() == (not missing_dependency)
        if not missing_dependency:
            for name in ("main.py", "plugin.json"):
                assert (target / name).read_bytes() == (
                    root / name
                ).read_bytes()
        assert (config_path.read_bytes(), agent_path.read_bytes()) == before
        assert host._loader.get_loaded_plugin("qwenpaw-harness-codex") is None


@pytest.mark.parametrize(
    "version,capabilities",
    [
        ("1.0.0", ["harnesses", "storage"]),
        ("99.0.0", ["harnesses", "storage"]),
        ("1.1.0", ["storage"]),
    ],
)
async def test_incompatible_harness_declarations_are_rejected(
    tmp_path,
    version,
    capabilities,
):
    async with PluginTestHost(tmp_path / "host") as host:
        root = package(tmp_path, version=version, capabilities=capabilities)
        marker = tmp_path / "entry-executed"
        (root / "main.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
            + SOURCE,
            encoding="utf-8",
        )
        with pytest.raises(SDKError, match="version|harnesses|1\\.1"):
            await host.install(root)
        if version in {"1.0.0", "99.0.0"}:
            assert not marker.exists()
        assert not any(
            row["status"] == "available" for row in host.list_harnesses()
        )
