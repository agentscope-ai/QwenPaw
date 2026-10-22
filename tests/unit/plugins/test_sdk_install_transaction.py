# -*- coding: utf-8 -*-
"""SDK opt-in packages use real install/update/recovery transactions."""

import json

import pytest

from .sdk_author_fixture import make_plugin
from .sdk_dependency_fixture import dependency_python

SOURCE = """
from qwenpaw.plugins.tools import ToolSpec, ToolResult


class Plugin:
    def register(self, plugin):
        async def tool(call, args):
            count = plugin.storage.read_json("count.json", 0) + 1
            plugin.storage.write_json("count.json", count)
            return ToolResult.text(
                "__VERSION__:"
                + plugin.config.get("label", "")
                + ":"
                + str(count)
            )

        plugin.register_tool(
            ToolSpec(
                "transaction_tool",
                "Transaction probe",
                {"type": "object"},
                tool,
                enabled=True,
            )
        )


plugin = Plugin()
"""


def package(tmp_path, version):
    root = tmp_path / version
    root.mkdir()
    plugin = make_plugin(
        root,
        SOURCE.replace("__VERSION__", version),
        ["tools", "storage", "config"],
    )
    manifest = json.loads((plugin / "plugin.json").read_text())
    manifest["version"] = version
    (plugin / "plugin.json").write_text(json.dumps(manifest))
    return plugin


async def text_result(host):
    return (await host.call_tool("transaction_tool", {})).content[0].text


async def test_install_config_disable_upgrade_uninstall_preserves_user_data(
    tmp_path,
):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    one, two = package(tmp_path, "1.0.0"), package(tmp_path, "2.0.0")
    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        assert (await host.install(one, config={"label": "initial"})).ok
        assert await text_result(host) == "1.0.0:initial:1"
        assert (
            await host.update_config(
                "extension-contract",
                {"label": "updated"},
            )
        ).ok
        assert (await host.set_enabled("extension-contract", False)).ok
        with pytest.raises(SDKError):
            await host.call_tool("transaction_tool", {})
        assert (await host.set_enabled("extension-contract", True)).ok
        assert await text_result(host) == "1.0.0:updated:2"
        upgraded = await host.install(two, replace=True)
        assert upgraded.ok and upgraded.version == "2.0.0"
        assert await text_result(host) == "2.0.0:updated:3"
        assert (
            json.loads(
                (root / "plugins/extension-contract/plugin.json").read_text(),
            )["version"]
            == "2.0.0"
        )
        result = await host.uninstall("extension-contract")
        assert result.clean and result.quiescent and not result.needs_restart
        assert not (root / "plugins/extension-contract").exists()
        assert (
            json.loads(
                (
                    root / "plugin-data/extension-contract/count.json"
                ).read_text(),
            )
            == 3
        )


@pytest.mark.parametrize("point", ["before_commit", "post_commit_cleanup"])
async def test_sdk_transaction_commit_boundary_retains_correct_code_and_data(
    tmp_path,
    point,
):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    one, two = package(tmp_path, "1.0.0"), package(tmp_path, "2.0.0")
    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        await host.install(one, config={"label": "persist"})
        assert await text_result(host) == "1.0.0:persist:1"
        with host.inject_failure(point) as fault:
            if point == "before_commit":
                with pytest.raises(SDKError):
                    await host.install(two, replace=True)
            else:
                result = await host.install(two, replace=True)
                assert result.ok and result.errors
        assert fault.hits == 1
        expected = "1.0.0" if point == "before_commit" else "2.0.0"
        assert (
            json.loads(
                (root / "plugins/extension-contract/plugin.json").read_text(),
            )["version"]
            == expected
        )
        assert await text_result(host) == expected + ":persist:2"
        assert (await host.reload("extension-contract")).ok
        assert await text_result(host) == expected + ":persist:3"


@pytest.mark.parametrize(
    ("dependency", "module"),
    [("httpx", "httpx"), ("aiohttp", "aiohttp"), ("Pillow", "PIL")],
)
async def test_sdk_dependency_restart_rejected_before_module_execution(
    tmp_path,
    monkeypatch,
    dependency,
    module,
):
    import importlib
    import subprocess

    from qwenpaw.plugins import SDKRestartRequiredError
    from qwenpaw.plugins.testing import PluginTestHost

    loaded = importlib.import_module(module)
    assert loaded.__version__ != "0.0.1"
    # A missing guard must not make the test fetch/install packages online.
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    installer_calls = []
    spawn = subprocess.Popen

    def prohibit_installer(args, *values, **kwargs):
        if "install" in args and ("pip" in args or "uv" in str(args[0])):
            installer_calls.append(tuple(args))
            raise AssertionError("Dependency guard reached external installer")
        return spawn(args, *values, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", prohibit_installer)
    one, two = package(tmp_path, "1.0.0"), package(tmp_path, "2.0.0")
    marker = tmp_path / "incoming-module-executed"
    entry = two / "main.py"
    entry.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
        + entry.read_text(),
    )
    (two / "requirements.txt").write_text(f"{dependency}==0.0.1\n")
    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        await host.install(one, config={"label": "retained"})
        with pytest.raises(SDKRestartRequiredError):
            await host.install(two, replace=True)
        assert not installer_calls
        assert not marker.exists()
        assert await text_result(host) == "1.0.0:retained:1"
        assert (
            json.loads(
                (root / "plugins/extension-contract/plugin.json").read_text(),
            )["version"]
            == "1.0.0"
        )


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "pip-version",
        "same-version-source",
        "not-imported",
        "addition",
    ],
)
def test_sdk_transitive_dependency_cannot_replace_an_installed_distribution(
    tmp_path,
    change,
):
    (
        "A real isolated resolver sees parent -> loaded "
        "child, without installation."
    )
    import os
    import subprocess
    import zipfile

    wheels = tmp_path / "wheels"
    wheels.mkdir()

    def wheel(name, version, requires="", body=None):
        metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        if requires:
            metadata += f"Requires-Dist: {requires}\n"
        info = f"{name}-{version}.dist-info"
        files = {
            f"{name}/__init__.py": body or f"__version__ = {version!r}\n",
            f"{info}/METADATA": metadata,
            f"{info}/WHEEL": (
                "Wheel-Version: 1.0\nGenerator: "
                "sdk-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
            ),
        }
        files[f"{info}/RECORD"] = (
            "".join(f"{key},,\n" for key in files) + f"{info}/RECORD,,\n"
        )
        path = wheels / f"{name}-{version}-py3-none-any.whl"
        with zipfile.ZipFile(path, "w") as archive:
            for key, value in files.items():
                archive.writestr(key, value)
        return path

    child = wheel("sdk_loaded_child", "1.0")
    wheel("sdk_loaded_child", "2.0")
    installer = (
        "pip" if change in {"same-version-source", "pip-version"} else "uv"
    )
    python, library = dependency_python(tmp_path / "venv", installer=installer)
    with zipfile.ZipFile(child) as archive:
        archive.extractall(library)
    if change == "same-version-source":
        # Pip considers the installed same version satisfied: adding parent
        # is safe only if the differently sourced child bytes stay unchanged.
        wheel(
            "sdk_loaded_child",
            "1.0",
            body="__version__ = '1.0'\nSOURCE = 'replacement'\n",
        )
        requirement = "sdk-loaded-child @ " + child.as_uri()
    elif change == "addition":
        requirement = "sdk-loaded-child>=1.0"
    else:
        requirement = "sdk-loaded-child>=2.0"
    wheel("sdk_new_parent", "1.0", requirement)
    one, two = package(tmp_path, "1.0.0"), package(tmp_path, "2.0.0")
    (two / "requirements.txt").write_text("sdk-new-parent==1.0\n")
    code = """
import asyncio, hashlib, importlib.metadata, json, subprocess, sys
from pathlib import Path
import mcp.types
from qwenpaw.plugins import SDKRestartRequiredError
from qwenpaw.plugins.testing import PluginTestHost

root, one, two = map(Path, sys.argv[1:4])
if sys.argv[4] != "not-imported":
    import sdk_loaded_child

    assert sdk_loaded_child.__version__ == "1.0"
else:
    assert "sdk_loaded_child" not in sys.modules
dist = importlib.metadata.distribution("sdk-loaded-child")


def snapshot():
    return {
        str(p): hashlib.sha256(
            Path(dist.locate_file(p)).read_bytes()
        ).hexdigest()
        for p in dist.files
    }


before = snapshot()
spawn = subprocess.Popen
mutations = []
previews = []


def guarded(args, *values, **kwargs):
    if "install" in args and (
        "pip" in args or "uv" in str(args[0])
    ):
        if "--dry-run" not in args:
            mutations.append(list(args))
            if sys.argv[4] not in {
                "addition",
                "same-version-source",
            }:
                raise AssertionError(
                    "SDK attempted a mutating dependency install"
                )
            assert "--constraint" in args
            assert (
                args[0] == sys.executable
                or args[args.index("--python") + 1]
                == sys.executable
            )
        previews.append(list(args))
    return spawn(args, *values, **kwargs)


subprocess.Popen = guarded


async def main():
    async with PluginTestHost(root) as host:
        await host.install(one, config={"label": "retained"})
        if sys.argv[4] in {"addition", "same-version-source"}:
            result = await host.install(two, replace=True)
            assert result.ok and mutations
            assert (
                importlib.metadata.version("sdk-new-parent")
                == "1.0"
            )
        else:
            try:
                await host.install(two, replace=True)
            except SDKRestartRequiredError:
                pass
            else:
                raise AssertionError(
                    "Transitive loaded dependency did not require restart"
                )
            assert not mutations, mutations
        assert snapshot() == before
        if sys.argv[4] in {"same-version-source", "pip-version"}:
            assert any(
                "--report" in a and "--dry-run" in a
                for a in previews
            ), previews
        else:
            assert any(
                "uv" in str(a[0]) and "--dry-run" in a
                for a in previews
            ), previews
        assert (
            importlib.metadata.version("sdk-loaded-child") == "1.0"
        )
        result = await host.call_tool("transaction_tool", {})
        expected = (
            "2.0.0"
            if sys.argv[4] in {"addition", "same-version-source"}
            else "1.0.0"
        )
        assert result.content[0].text == expected + ":retained:1"
    print(
        json.dumps(
            {
                "mutations": mutations,
                "previews": previews,
                "unchanged": snapshot() == before,
            }
        )
    )


asyncio.run(main())
"""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("QWENPAW_", "PYTHON"))
        and not any(
            word in key.upper()
            for word in ("TOKEN", "SECRET", "API_KEY", "PASSWORD")
        )
    }
    env.update(
        QWENPAW_WORKING_DIR=str(tmp_path / "bootstrap"),
        QWENPAW_SECRET_DIR=str(tmp_path / "bootstrap-secrets"),
        PIP_NO_INDEX="1",
        UV_NO_INDEX="1",
        PIP_FIND_LINKS=str(wheels),
        UV_FIND_LINKS=str(wheels),
        UV_CACHE_DIR=str(tmp_path / "uv-cache"),
        UV_CREDENTIALS_DIR=str(tmp_path / "uv-credentials"),
        PIP_CACHE_DIR=str(tmp_path / "pip-cache"),
        XDG_CONFIG_HOME=str(tmp_path / "xdg-config"),
    )
    result = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            code,
            str(tmp_path / "host"),
            str(one),
            str(two),
            change,
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    (tmp_path / "transitive-result.log").write_text(
        result.stdout + result.stderr,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1])["unchanged"]


async def test_sdk_busy_stream_in_other_workspace_prevents_install_commit(
    tmp_path,
):
    import asyncio
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost

    one, two = package(tmp_path, "1.0.0"), package(tmp_path, "2.0.0")
    (one / "main.py").write_text(
        """
import asyncio
from qwenpaw.plugins.tools import ToolSpec, ToolEvent, ToolResult
from qwenpaw.plugins.messages import ContentBlock


class Plugin:
    def register(self, ctx):
        async def tool(call, args):
            try:
                yield ToolEvent(
                    "delta",
                    (
                        ContentBlock(
                            text="old:" + call.workspace_id
                        ),
                    ),
                )
                await asyncio.sleep(100)
            finally:
                ctx.storage.write_json("closed.json", True)

        ctx.register_tool(
            ToolSpec(
                "transaction_tool",
                "Busy",
                {"type": "object"},
                tool,
                enabled=True,
            )
        )


plugin = Plugin()
""",
    )
    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        await host.install(one)
        old = host.context("extension-contract")
        stream = host.stream_tool(
            "transaction_tool",
            {},
            workspace_id="other-workspace",
        )
        assert (await asyncio.create_task(anext(stream))).content[
            0
        ].text == "old:other-workspace"
        try:
            with pytest.raises(PluginBusyError):
                await host.install(two, replace=True)
            assert (
                json.loads(
                    (
                        root / "plugins/extension-contract/plugin.json"
                    ).read_text(),
                )["version"]
                == "1.0.0"
            )
            assert not old.storage.read_json("closed.json", False)
        finally:
            await stream.aclose()
        assert old.storage.read_json("closed.json") is True
        assert (await host.install(two, replace=True)).ok
        assert await text_result(host) == "2.0.0::1"


async def test_sdk_upgrade_partial_activation_stops_new_task_and_restores_old(
    tmp_path,
):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    one, two = package(tmp_path, "1.0.0"), package(tmp_path, "2.0.0")
    marker = tmp_path / "new-task-stopped"
    entry = two / "main.py"
    entry.write_text(
        """
import asyncio
from pathlib import Path
class Plugin:
    def register(self, plugin):
        async def activate(ctx):
            async def worker():
                try:
                    await asyncio.sleep(100)
                finally:
                    Path(__MARKER__).touch()
            ctx.resources.task(worker(), description="partial-new-start")
            await asyncio.sleep(0)
            raise RuntimeError("partial new activation failed")
        plugin.on_activate(activate)
plugin = Plugin()
""".replace(
            "__MARKER__",
            repr(str(marker)),
        ),
    )
    manifest = json.loads((two / "plugin.json").read_text())
    manifest["sdk"]["capabilities"].append("resources")
    (two / "plugin.json").write_text(json.dumps(manifest))
    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        await host.install(one, config={"label": "original"})
        assert await text_result(host) == "1.0.0:original:1"
        with pytest.raises(SDKError):
            await host.install(two, replace=True)
        assert (
            marker.exists()
        ), "Partially started new generation kept its task alive"
        assert await text_result(host) == "1.0.0:original:2"
        assert (
            json.loads(
                (root / "plugins/extension-contract/plugin.json").read_text(),
            )["version"]
            == "1.0.0"
        )
        assert (await host.reload("extension-contract")).ok


async def test_uninstall_refuses_external_source_tree_but_unload_is_allowed(
    tmp_path,
):
    import hashlib
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    source = make_plugin(
        tmp_path,
        (
            "class Plugin:\n    def register(self, ctx): "
            "pass\nplugin = Plugin()\n"
        ),
        [],
    )
    before = {
        str(path.relative_to(source)): hashlib.sha256(
            path.read_bytes(),
        ).hexdigest()
        for path in source.rglob("*")
        if path.is_file()
    }
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(source)
        with pytest.raises(SDKError):
            await host.uninstall("extension-contract")
        after = {
            str(path.relative_to(source)): hashlib.sha256(
                path.read_bytes(),
            ).hexdigest()
            for path in source.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        assert after == before
        assert (await host.unload("extension-contract")).clean
        assert source.is_dir()
