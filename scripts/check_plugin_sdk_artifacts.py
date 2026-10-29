#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify built artifacts using an already wheel-installed external interpreter.

The caller installs the wheel and test dependencies in an isolated venv first.
This script never installs from the checkout or loads repository conftest files.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

INTERNAL = {
    "test_sdk_entry_contract.py",
    "test_sdk_host_bridge.py",
    "test_sdk_context_bridge.py",
    "test_sdk_message_bridge.py",
    "test_sdk_event_bridge.py",
    "test_sdk_approval_event_bridge.py",
    "test_sdk_channel_bridge.py",
    "test_sdk_channel_run_bridge.py",
}


def prepare_author_tests(source: Path, root: Path) -> list[str]:
    """Copy the standalone author suite and its local helpers."""
    suite = root / "author_tests"
    suite.mkdir()
    (suite / "__init__.py").touch()
    for fixture in (
        "sdk_author_fixture.py",
        "timing.py",
    ):
        shutil.copy2(source / "tests/unit/plugins" / fixture, suite)
    tests = []
    for file in sorted((source / "tests/unit/plugins").glob("test_sdk_*.py")):
        if file.name not in INTERNAL:
            shutil.copy2(file, suite)
            tests.append(file.name)
    assert tests, "No public author tests found in build snapshot"
    (root / "pytest.ini").write_text("[pytest]\nasyncio_mode = auto\n")
    return tests


# The standalone acceptance sequence shares one report and environment.
# pylint: disable-next=too-many-statements
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, source = args.output.resolve(), args.source_root.resolve()
    assert not root.exists(), "Author output must be a new directory"
    assert not root.is_relative_to(
        source,
    ), "Author check must run outside the checkout"
    root.mkdir(parents=True)
    interpreter = str(args.python.absolute())
    report = {"artifacts": {}, "steps": [], "tests": []}
    env = {
        key: value
        for key, value in os.environ.items()
        if not any(
            part in key.upper()
            for part in ("TOKEN", "SECRET", "API_KEY", "APP_KEY", "PASSWORD")
        )
    }
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONDONTWRITEBYTECODE"):
        env.pop(name, None)
    env.update(
        PATH=str(args.python.absolute().parent)
        + os.pathsep
        + env.get("PATH", ""),
        QWENPAW_WORKING_DIR=str(root / "runtime/working"),
        QWENPAW_SECRET_DIR=str(root / "runtime/secrets"),
        XDG_CACHE_HOME=str(root / "runtime/cache"),
        XDG_CONFIG_HOME=str(root / "runtime/config"),
        QWENPAW_LOG_LEVEL="warning",
    )

    def run(name, *arguments):
        result = subprocess.run(
            [interpreter, *arguments],
            cwd=root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=600,
            check=False,
        )
        (root / (name + ".log")).write_text(result.stdout)
        report["steps"].append({"name": name, "returncode": result.returncode})
        (root / "report.json").write_text(json.dumps(report, indent=2))
        assert (
            result.returncode == 0
        ), f"{name} failed; see {root / (name + '.log')}"
        return result.stdout

    for artifact in (args.wheel.resolve(), args.sdist.resolve()):
        if artifact.suffix == ".whl":
            with zipfile.ZipFile(artifact) as archive:
                names = archive.namelist()
            assert "qwenpaw/plugins/frontend/package.json" in names
            assert "qwenpaw/plugins/templates/hello/plugin.json" in names
        else:
            with tarfile.open(artifact) as archive:
                names = archive.getnames()
        assert not any(
            "sdk_test" in Path(name).parts for name in names
        ), "Local experiment content leaked into artifact"
        report["artifacts"][artifact.name] = {
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "files": len(names),
        }
    import_check = f"""
import importlib.metadata, json
from pathlib import Path
import qwenpaw
location = Path(qwenpaw.__file__).resolve()
assert "site-packages" in location.parts, location
assert not location.is_relative_to(Path({str(source)!r})), location
versions = {{
    name: importlib.metadata.version(name)
    for name in ("qwenpaw", "agentscope", "fastapi", "pytest")
}}
print(json.dumps({{
    "import_path": str(location), "versions": versions,
}}))
"""
    report["environment"] = json.loads(
        run("installed-import", "-c", import_check),
    )
    typing_source = source / "tests/typing/plugin_sdk_author.py"
    shutil.copy2(typing_source, root / typing_source.name)
    run(
        "public-author-types",
        "-m",
        "mypy",
        "--strict",
        "--follow-imports=silent",
        str(root / typing_source.name),
    )
    report["tests"] = prepare_author_tests(source, root)
    run(
        "public-author-tests",
        "-m",
        "pytest",
        str(root / "author_tests"),
        "-q",
        "--tb=short",
        "--timeout=45",
    )
    template, frontend = root / "template", root / "frontend"
    run(
        "export-template",
        "-m",
        "qwenpaw.plugins.check",
        "--template",
        str(template),
    )
    run(
        "export-frontend",
        "-m",
        "qwenpaw.plugins.check",
        "--frontend",
        str(frontend),
    )
    run(
        "template-compliance",
        "-m",
        "qwenpaw.plugins.check",
        str(template),
        "--runtime",
    )
    run(
        "template-real-runtime",
        "-c",
        f"""
import asyncio
from pathlib import Path
from qwenpaw.plugins.testing import PluginTestHost
async def main():
    async with PluginTestHost(Path({str(root / "template-host")!r})) as host:
        await host.load(Path({str(template)!r}))
        first = await host.call_tool("hello_sdk", {{"name": "outside"}})
        assert first.content[0].text == "Hello outside (1)"
        assert (await host.reload("hello-sdk")).ok
        second = await host.call_tool("hello_sdk", {{"name": "outside"}})
        assert second.content[0].text == "Hello outside (2)"
        other = await host.call_tool(
            "hello_sdk", {{"name": "other"}}, workspace_id="other",
        )
        assert other.content[0].text == "Hello other (1)"
asyncio.run(main())
""",
    )
    report["frontend_export"] = str(frontend)
    (root / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
