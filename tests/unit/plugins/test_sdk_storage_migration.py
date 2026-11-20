# -*- coding: utf-8 -*-
"""Private library paths and retryable, declared legacy-data migration."""

import asyncio
import json
from pathlib import Path
import sqlite3
import os

import pytest

from qwenpaw.plugins.errors import SDKError, StaleContextError
from qwenpaw.plugins.apps import PawApp
from qwenpaw.plugins.channels import ChannelSpec
from qwenpaw.plugins.sdk_version import validate_sdk
from qwenpaw.plugins.testing import PluginTestHost
from .sdk_author_fixture import make_plugin


def package(tmp_path, capabilities=("storage",)):
    root = make_plugin(
        tmp_path,
        "class Plugin:\n    def register(self, ctx): pass\nplugin=Plugin()\n",
        list(capabilities),
    )
    manifest = json.loads((root / "plugin.json").read_text())
    manifest["sdk"].update(
        version="1.2.0",
        legacy_storage={
            "profile": "extension-contract/profiles.json",
            "history": "extension-contract/history",
        },
    )
    (root / "plugin.json").write_text(json.dumps(manifest))
    return root


async def test_private_path_supports_sqlite_and_rejects_escape(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(package(tmp_path))
        path = ctx.storage.path("db/state.sqlite")
        assert isinstance(path, Path) and not path.exists()
        with sqlite3.connect(path) as db:
            db.execute("create table state (value text)")
            db.execute("insert into state values (?)", ("persisted",))
        db.close()
        await host.reload("extension-contract")
        with pytest.raises(StaleContextError):
            ctx.storage.path("stale.sqlite")
        current = host.context("extension-contract")
        with sqlite3.connect(current.storage.path("db/state.sqlite")) as db:
            assert db.execute("select value from state").fetchone() == (
                "persisted",
            )
        db.close()
        for name in ("..", "../escape", str(tmp_path / "outside")):
            with pytest.raises(SDKError):
                current.storage.path(name)
        outside = tmp_path / "outside"
        outside.mkdir()
        current.storage.path("link/file").parent.rmdir()
        current.storage.path("link").symlink_to(
            outside,
            target_is_directory=True,
        )
        with pytest.raises(SDKError):
            current.storage.path("link/file")


async def test_declared_migration_preserves_sources_and_existing_data(
    tmp_path,
):
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(package(tmp_path))
        old = host.root / "extension-contract"
        old.mkdir()
        source = old / "profiles.json"
        source.write_bytes(b'{"profile":"old"}')
        assert ctx.storage.import_legacy("profile", "profiles.json")
        ctx.storage.write_json("profiles.json", {"profile": "new"})
        assert not ctx.storage.import_legacy("profile", "profiles.json")
        assert ctx.storage.read_json("profiles.json") == {"profile": "new"}
        assert source.read_bytes() == b'{"profile":"old"}'
        history = old / "history"
        (history / "nested").mkdir(parents=True)
        (history / "first.json").write_bytes(b"first")
        (history / "nested/second.json").write_bytes(b"second")
        results = await asyncio.gather(
            *[
                asyncio.to_thread(
                    ctx.storage.import_legacy_tree,
                    "history",
                    "history",
                )
                for _ in range(2)
            ],
        )
        assert sorted(item for batch in results for item in batch) == [
            "history/first.json",
            "history/nested/second.json",
        ]
        assert ctx.storage.import_legacy_tree("history", "history") == ()
        assert (
            ctx.storage.read_bytes("history/nested/second.json") == b"second"
        )
        assert (history / "nested/second.json").exists()
        with pytest.raises(SDKError, match="Undeclared"):
            ctx.storage.import_legacy("unknown", "unknown")
        (history / "link").symlink_to(source)
        with pytest.raises(SDKError, match="symlink"):
            ctx.storage.import_legacy_tree("history", "partial")
        (history / "link").unlink()
        ctx.storage.import_legacy_tree("history", "partial")
        assert (
            ctx.storage.read_bytes("partial/nested/second.json") == b"second"
        )


async def test_workspace_and_app_storage_inherit_declared_sources(tmp_path):
    def migrate(storage):
        with pytest.raises(SDKError, match="Undeclared"):
            storage.import_legacy("unknown", "unknown")
        with pytest.raises(SDKError, match="Undeclared"):
            storage.import_legacy_tree("unknown", "unknown")
        return {
            "file": storage.import_legacy("profile", "profile.json"),
            "tree": list(storage.import_legacy_tree("history", "history")),
            "profile": storage.read_json("profile.json"),
            "history": storage.read_json("history/entry.json"),
        }

    expected = {
        "file": True,
        "tree": ["history/entry.json"],
        "profile": {"name": "legacy"},
        "history": {"value": 1},
    }
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            package(tmp_path, ("storage", "apps", "channels")),
        )
        origin = host.root / "extension-contract"
        (origin / "history").mkdir(parents=True)
        (origin / "profiles.json").write_text('{"name":"legacy"}')
        (origin / "history" / "entry.json").write_text('{"value":1}')
        assert migrate(ctx.storage) == expected
        for workspace_id in ("one", "two"):
            await host._workspace(workspace_id)
            async with ctx._invocation(
                workspace_id=workspace_id,
                session_id="",
            ) as call:
                assert migrate(call.storage) == expected
                call.storage.write_json("profile.json", {"name": "new"})
                assert migrate(call.storage) == {
                    **expected,
                    "file": False,
                    "tree": [],
                    "profile": {"name": "new"},
                }

        app = PawApp(app_id="migration")

        @app.route("/import", methods=("POST",))
        async def import_data(call, request):
            return migrate(call.storage)

        ctx.register_app(app)
        for workspace_id, user_id in (
            ("one", "alice"),
            ("two", "alice"),
            ("one", "bob"),
        ):
            for repeat in (False, True):
                response = await host.request(
                    "POST",
                    "/api/migration/import",
                    workspace_id=workspace_id,
                    user_id=user_id,
                )
                assert response.status == 200, response.text
                assert response.json() == {
                    **expected,
                    "file": not repeat,
                    "tree": [] if repeat else ["history/entry.json"],
                }
        assert ctx.storage.read_json("profile.json") == {"name": "legacy"}
        assert (origin / "profiles.json").read_text() == '{"name":"legacy"}'

        channel_results = []

        class Transport:
            async def start(self, call):
                channel_results.append(migrate(call.storage))

            async def stop(self, call):
                return True

            async def send(self, call, message):
                pass

        ctx.register_channel(ChannelSpec("migration", "Migration", Transport))
        for workspace_id in ("one", "two"):
            await host.start_channel("migration", workspace_id=workspace_id)
            await host.stop_channel("migration", workspace_id=workspace_id)
        assert channel_results == [expected, expected]


@pytest.mark.parametrize(
    "plugin_id, path",
    [
        ("remote", "../secrets"),
        ("remote", "/tmp/remote"),
        ("remote", "other-plugin/data"),
        ("secrets", "secrets/data"),
        ("remote", "remote/../secrets"),
        ("remote", "remote\\data"),
    ],
)
def test_legacy_manifest_rejects_foreign_namespace(plugin_id, path):
    with pytest.raises(SDKError):
        validate_sdk(
            {"version": "1.2.0", "legacy_storage": {"data": path}},
            plugin_id,
        )


async def test_legacy_source_symlink_rejected(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(package(tmp_path))
        old = host.root / "extension-contract"
        old.symlink_to(tmp_path, target_is_directory=True)
        with pytest.raises(SDKError, match="symlink"):
            ctx.storage.import_legacy("profile", "profile")


async def test_partial_copy_retry_and_source_preservation(
    tmp_path,
    monkeypatch,
):
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(package(tmp_path))
        origin = host.root / "extension-contract/history"
        origin.mkdir(parents=True)
        for name in ("a", "b"):
            (origin / name).write_bytes(name.encode())
        link = os.link

        def fail_second(source, destination):
            if destination.name == "b":
                raise OSError("simulated disk failure")
            return link(source, destination)

        with monkeypatch.context() as failure:
            failure.setattr(os, "link", fail_second)
            with pytest.raises(OSError, match="disk failure"):
                ctx.storage.import_legacy_tree("history", "history")
        assert ctx.storage.read_bytes("history/a") == b"a"
        assert not ctx.storage.path("history/b").exists()
        assert ctx.storage.import_legacy_tree("history", "history") == (
            "history/b",
        )
        assert sorted(
            path.name
            for path in ctx.storage.path("history/a").parent.iterdir()
        ) == ["a", "b"]
        assert sorted(path.name for path in origin.iterdir()) == ["a", "b"]
