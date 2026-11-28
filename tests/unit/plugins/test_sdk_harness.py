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
