# -*- coding: utf-8 -*-
"""Run real legacy-plugin lifecycle phases in separate host processes.

Set QWENPAW_WORKING_DIR to synthetic data before starting Python. ``seed``
supports the pre-lifecycle loader; the other phases exercise the candidate's
production Loader/Lifecycle. Copy the seeded runtime before comparing builds.
No network, model, service registry, or lifecycle is replaced by a fake.
"""

import argparse
import asyncio
import inspect
import json
import os
from pathlib import Path

PLUGIN_ID = "legacy-lifecycle-contract"
TOOL_NAME = "legacy_contract_echo"


def package(root, version):
    root.mkdir(parents=True, exist_ok=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": PLUGIN_ID,
                "name": "Legacy lifecycle contract",
                "version": version,
                "type": "tool",
                "entry": {"backend": "main.py"},
                "min_version": "0.1.0",
                "max_version": "0.2.0",
            },
        ),
        encoding="utf-8",
    )
    source = """
import json
import os
from pathlib import Path
from qwenpaw.plugins import PluginApi


class Plugin:
    def register(self, api):
        assert type(api) is PluginApi
        self.api = api

        async def legacy_contract_echo(text: str):
            directory = (
                Path(os.environ["QWENPAW_WORKING_DIR"])
                / "legacy-user-data"
            )
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "state.json"
            state = (
                json.loads(path.read_text())
                if path.exists()
                else {"calls": 0, "user_note": "keep"}
            )
            state["calls"] += 1
            path.write_text(json.dumps(state))
            return {
                "text": text,
                "version": VERSION,
                "label": api.config["label"],
                **state,
            }

        api.register_tool(
            "legacy_contract_echo",
            legacy_contract_echo,
            enabled=True,
        )


plugin = Plugin()
""".replace(
        "VERSION",
        repr(version),
    )
    (root / "main.py").write_text(source, encoding="utf-8")
    return root


async def run(phase):
    # Keep this ownership/cleanup scenario and its assertions together.
    # pylint: disable=too-many-statements
    working = Path(os.environ["QWENPAW_WORKING_DIR"]).resolve()
    assert (
        working != Path.home() / ".qwenpaw"
    ), "Synthetic working directory required"

    def check_workspace_paths():
        path = working / "config.json"
        if not path.exists():
            return
        config = json.loads(path.read_text())
        for identifier, profile in (
            config.get("agents", {}).get("profiles", {}).items()
        ):
            expected = working / "workspaces" / identifier
            assert (
                Path(profile["workspace_dir"]).resolve() == expected
            ), profile

    # Reject copied absolute references before importing code that may migrate
    # data.
    check_workspace_paths()
    from qwenpaw.agents import tools
    from qwenpaw.config.utils import load_config, save_config
    from qwenpaw.plugins import PluginApi, PluginLoader

    loader = PluginLoader([working / "plugins"])
    observations = []

    async def call(label, version, count):
        record = loader.get_loaded_plugin(PLUGIN_ID)
        assert type(record.instance.api) is PluginApi
        result = await getattr(tools, TOOL_NAME)("probe")
        assert result == {
            "text": "probe",
            "version": version,
            "label": label,
            "calls": count,
            "user_note": "keep",
        }, result
        observations.append(result)

    if phase == "seed":
        config = load_config()
        config.plugins[PLUGIN_ID] = {"label": "initial", "enabled": True}
        save_config(config)
        await loader.load_plugin_from_path(
            package(working.parent / "packages" / "v1", "1.0.0"),
            config={"label": "initial"},
        )
        if not hasattr(loader, "lifecycle"):
            # This is the old application's real startup-hook ordering.
            for hook in loader.registry.get_startup_hooks():
                result = hook.callback()
                if inspect.isawaitable(result):
                    await result
        await call("initial", "1.0.0", 1)
        await loader.unload_plugin(PLUGIN_ID)
    else:
        from qwenpaw.plugins import UnloadMode

        records = await loader.load_all_plugins(
            load_config().plugins,
            activate=True,
        )
        assert records[PLUGIN_ID].status == "active"
        if phase == "cycle":
            await call("initial", "1.0.0", 2)
            report = await loader.lifecycle.update_config(
                PLUGIN_ID,
                {"label": "updated"},
            )
            assert report.ok, report.errors
            await call("updated", "1.0.0", 3)
            report = await loader.lifecycle.reload(
                PLUGIN_ID,
                new_source=package(
                    working.parent / "packages" / "v2",
                    "2.0.0",
                ),
            )
            assert report.ok, report.errors
            await call("updated", "2.0.0", 4)
            report = await loader.lifecycle.set_enabled(PLUGIN_ID, False)
            assert report.clean and report.quiescent
            assert not hasattr(tools, TOOL_NAME)
            assert load_config().plugins[PLUGIN_ID]["enabled"] is False
            record = await loader.lifecycle.set_enabled(PLUGIN_ID, True)
            assert record.status == "active"
            await call("updated", "2.0.0", 5)
        elif phase == "cold":
            await call("updated", "2.0.0", 6)
        elif phase == "uninstall":
            report = await loader.lifecycle.unload(
                PLUGIN_ID,
                UnloadMode.UNINSTALL,
                delete_files=True,
            )
            assert report.clean and report.quiescent, report
            assert not (working / "plugins" / PLUGIN_ID).exists()
            assert not hasattr(tools, TOOL_NAME)
            assert PLUGIN_ID not in load_config().plugins
            assert json.loads(
                (working / "legacy-user-data/state.json").read_text(),
            ) == {
                "calls": 6,
                "user_note": "keep",
            }
        reports = await loader.lifecycle.unload_all(UnloadMode.SHUTDOWN)
        assert all(report.clean and report.quiescent for report in reports)
    check_workspace_paths()
    print(
        json.dumps({"phase": phase, "observations": observations, "ok": True}),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=("seed", "cycle", "cold", "uninstall"),
    )
    parser.add_argument(
        "--working-dir",
        type=Path,
        help="Fresh synthetic runtime or its copied snapshot",
    )
    options = parser.parse_args()
    if options.working_dir is not None:
        os.environ["QWENPAW_WORKING_DIR"] = str(options.working_dir.resolve())
    asyncio.run(run(options.phase))
