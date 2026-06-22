# -*- coding: utf-8 -*-
import os
import subprocess
import sys
import textwrap


def test_runner_submodule_import_is_lightweight():
    """Importing lightweight runner submodules should not load agent tools."""
    code = textwrap.dedent(
        """
        import importlib
        import sys

        importlib.import_module("qwenpaw.app.runner.session")
        importlib.import_module("qwenpaw.app.runner.command_dispatch")

        heavy_modules = [
            "qwenpaw.agents.react_agent",
            "qwenpaw.agents.acp",
        ]
        loaded = [name for name in heavy_modules if name in sys.modules]
        if loaded:
            raise SystemExit(f"heavy modules loaded: {loaded}")
        """,
    )

    env = os.environ.copy()
    src_path = os.path.abspath("src")
    env["PYTHONPATH"] = (
        src_path
        if not env.get("PYTHONPATH")
        else src_path + os.pathsep + env["PYTHONPATH"]
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_runner_package_lazy_exports_remain_available():
    """Package-level imports stay compatible via lazy __getattr__."""
    code = textwrap.dedent(
        """
        from qwenpaw.app.runner import ChatManager

        assert ChatManager.__name__ == "ChatManager"
        """,
    )

    env = os.environ.copy()
    src_path = os.path.abspath("src")
    env["PYTHONPATH"] = (
        src_path
        if not env.get("PYTHONPATH")
        else src_path + os.pathsep + env["PYTHONPATH"]
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
