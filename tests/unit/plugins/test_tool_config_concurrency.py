# -*- coding: utf-8 -*-
"""Legacy installations must preserve other tools' agent settings."""

# Inspect host ownership and cleanup state at the tested bridge boundary.
# pylint: disable=protected-access

import asyncio
import threading

import pytest

from .test_sdk_entry_contract import write_plugin

from .timing import WAIT_TIMEOUT


async def test_concurrent_legacy_installs_preserve_both_tools_and_user_config(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.agents import tools
    from qwenpaw.config import config as configs
    from qwenpaw.plugins import api
    from qwenpaw.plugins.testing import PluginTestHost

    roots = []
    for suffix in ("a", "b"):
        root = tmp_path / f"legacy-race-{suffix}"
        write_plugin(
            root,
            f"""
class Plugin:
    def register(self, api):
        async def legacy_race_{suffix}(text: str):
            return "{suffix}:" + text
        api.register_tool(
            "legacy_race_{suffix}", legacy_race_{suffix}, enabled=True,
        )
plugin = Plugin()
""",
        )
        roots.append(root)

    async with PluginTestHost(tmp_path / "host") as host:
        await host._workspace("test")
        config = configs.load_agent_config("test")
        config.tools.builtin_tools[
            "user_owned_tool"
        ] = configs.BuiltinToolConfig(
            name="user_owned_tool",
            enabled=False,
            description="user description",
            config={"nested": {"keep": [1, 2, 3]}},
        )
        configs.save_agent_config("test", config)
        original = configs.load_agent_config("test").model_dump()
        first_read, second_saved = threading.Event(), threading.Event()
        local = threading.local()
        write, read, save = (
            api._write_tool_config,
            configs.load_agent_config,
            configs.save_agent_config,
        )

        def marked_write(name, *args, **kwargs):
            local.tool = name
            try:
                return write(name, *args, **kwargs)
            finally:
                local.tool = None

        def gated_read(agent_id, *args, **kwargs):
            value = read(agent_id, *args, **kwargs)
            if (
                agent_id == "test"
                and getattr(local, "tool", None) == "legacy_race_a"
            ):
                first_read.set()
                # Old code allows B to commit while A holds its stale snapshot.
                # An atomic mutation may block B: bounded wait then lets A
                # commit,
                # so this gate cannot deadlock the repaired critical section.
                second_saved.wait(1)
            return value

        def observed_save(agent_id, value, *args, **kwargs):
            save(agent_id, value, *args, **kwargs)
            if (
                agent_id == "test"
                and getattr(local, "tool", None) == "legacy_race_b"
            ):
                second_saved.set()

        with monkeypatch.context() as patch:
            patch.setattr(api, "_write_tool_config", marked_write)
            patch.setattr(configs, "load_agent_config", gated_read)
            patch.setattr(configs, "save_agent_config", observed_save)
            first = asyncio.create_task(host.install(roots[0]))
            assert await asyncio.to_thread(
                first_read.wait,
                WAIT_TIMEOUT,
            ), "A never read agent config"
            second = asyncio.create_task(host.install(roots[1]))
            reports = await asyncio.wait_for(asyncio.gather(first, second), 15)
        assert all(report.ok for report in reports), reports
        assert await tools.legacy_race_a("live") == "a:live"
        assert await tools.legacy_race_b("live") == "b:live"
        actual = configs.load_agent_config("test").model_dump()
        assert set(actual["tools"]["builtin_tools"]) >= {
            "user_owned_tool",
            "legacy_race_a",
            "legacy_race_b",
        }, {
            "second_committed": second_saved.is_set(),
            "tools": actual["tools"]["builtin_tools"],
        }
        for name in ("legacy_race_a", "legacy_race_b"):
            assert (
                actual["tools"]["builtin_tools"].pop(name)["enabled"] is True
            )
        assert (
            actual == original
        ), "Concurrent plugin registration changed user settings"


@pytest.mark.parametrize("operation", ["remove", "restore"])
async def test_tool_cleanup_transaction_preserves_concurrent_registration(
    tmp_path,
    monkeypatch,
    operation,
):
    from qwenpaw.config import config as configs
    from qwenpaw.plugins import api
    from qwenpaw.plugins.testing import PluginTestHost

    root = tmp_path / "legacy-cleanup-peer"
    write_plugin(
        root,
        """
class Plugin:
    def register(self, api):
        async def legacy_cleanup_peer(text: str):
            return "peer:" + text

        api.register_tool(
            "legacy_cleanup_peer", legacy_cleanup_peer, enabled=True
        )


plugin = Plugin()
""",
    )
    async with PluginTestHost(tmp_path / "host") as host:
        await host._workspace("test")
        config = configs.load_agent_config("test")
        config.tools.builtin_tools[
            "retiring_tool"
        ] = configs.BuiltinToolConfig(
            name="retiring_tool",
            enabled=True,
            config={"keep": "settings"},
        )
        configs.save_agent_config("test", config)
        initial = configs.load_agent_config("test").model_dump()
        old = dict(
            initial["tools"]["builtin_tools"]["retiring_tool"],
            enabled=False,
        )
        entered, peer_saved = threading.Event(), threading.Event()
        local = threading.local()
        read, save = configs.load_agent_config, configs.save_agent_config

        def gated_read(agent_id, *args, **kwargs):
            value = read(agent_id, *args, **kwargs)
            if agent_id == "test" and getattr(local, "cleanup", False):
                entered.set()
                peer_saved.wait(1)
            return value

        def observed_save(agent_id, value, *args, **kwargs):
            save(agent_id, value, *args, **kwargs)
            if "legacy_cleanup_peer" in value.tools.builtin_tools:
                peer_saved.set()

        def cleanup():
            local.cleanup = True
            try:
                if operation == "remove":
                    api._remove_tool_config(
                        "retiring_tool",
                        "owner",
                        owned_names=("retiring_tool",),
                    )
                else:
                    api._restore_agent_tools_from_snapshot(
                        ("retiring_tool",),
                        {"test": {"retiring_tool": old}},
                    )
            finally:
                local.cleanup = False

        with monkeypatch.context() as patch:
            patch.setattr(configs, "load_agent_config", gated_read)
            patch.setattr(configs, "save_agent_config", observed_save)
            cleaning = asyncio.create_task(asyncio.to_thread(cleanup))
            assert await asyncio.to_thread(entered.wait, WAIT_TIMEOUT)
            _, report = await asyncio.wait_for(
                asyncio.gather(cleaning, host.install(root)),
                15,
            )
        assert report.ok
        from qwenpaw.agents import tools

        assert await tools.legacy_cleanup_peer("live") == "peer:live"
        actual = configs.load_agent_config("test").model_dump()
        assert actual["tools"]["builtin_tools"].pop("legacy_cleanup_peer")[
            "enabled"
        ]
        if operation == "remove":
            del initial["tools"]["builtin_tools"]["retiring_tool"]
        else:
            initial["tools"]["builtin_tools"]["retiring_tool"] = old
        assert actual == initial


async def test_tool_config_mutations_keep_read_write_error_and_noop_contracts(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.config import config as configs
    from qwenpaw.plugins import api
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        await host._workspace("test")
        # Materialize the default profile before injecting write failures: its
        # first load legitimately persists a newly created agent configuration.
        configs.load_agent_config("default")

        def read_error(*args, **kwargs):
            raise OSError("synthetic unreadable agent")

        def write_error(*args, **kwargs):
            raise OSError("synthetic disk full")

        with monkeypatch.context() as patch:
            patch.setattr(configs, "load_agent_config", read_error)
            api._write_tool_config("skip_tool", True, "", "", "owner")
            api._restore_agent_tools_from_snapshot(
                ("skip_tool",),
                {"test": {"skip_tool": None}},
            )
        with monkeypatch.context() as patch:
            patch.setattr(configs, "save_agent_config", write_error)
            # Missing/unowned rows and an unchanged restore must not write at
            # all.
            api._remove_tool_config(
                "missing",
                "owner",
                owned_names=("missing",),
            )
            api._remove_tool_config("missing", "owner", owned_names=())
            api._restore_agent_tools_from_snapshot(
                ("missing",),
                {"test": {"missing": None}},
            )
            with pytest.raises(OSError, match="synthetic disk full"):
                api._write_tool_config("new_tool", True, "", "", "owner")
            with pytest.raises(OSError, match="synthetic disk full"):
                api._restore_agent_tools_from_snapshot(
                    ("restored",),
                    {"test": {"restored": {"enabled": False}}},
                )
        config = configs.load_agent_config("test")
        config.tools.builtin_tools["remove_me"] = configs.BuiltinToolConfig(
            name="remove_me",
        )
        configs.save_agent_config("test", config)
        with monkeypatch.context() as patch:
            patch.setattr(configs, "save_agent_config", write_error)
            with pytest.raises(RuntimeError, match="synthetic disk full"):
                api._remove_tool_config(
                    "remove_me",
                    "owner",
                    owned_names=("remove_me",),
                )
