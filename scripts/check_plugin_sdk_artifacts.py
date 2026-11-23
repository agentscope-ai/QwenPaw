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
import sys
import tarfile
import zipfile

from packaging.requirements import Requirement

# These suites can run against an installed wheel outside the checkout.
AUTHOR_TESTS = (
    "test_sdk_channel_contract.py",
    "test_sdk_context_lifecycle.py",
    "test_sdk_driver_contract.py",
    "test_sdk_driver_lifecycle.py",
    "test_sdk_driver_replacement.py",
    "test_sdk_install_transaction.py",
    "test_sdk_market_contract.py",
    "test_sdk_memory_contract.py",
    "test_sdk_workspace_contract.py",
    "test_sdk_harness.py",
)


def prepare_author_tests(
    source: Path,
    root: Path,
    selected: list[str] | None = None,
) -> list[str]:
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
    for name in AUTHOR_TESTS:
        if selected is None or name in selected:
            file = source / "tests/unit/plugins" / name
            shutil.copy2(file, suite)
            tests.append(file.name)
    assert tests, "No public author tests found in build snapshot"
    if selected is not None:
        assert set(tests) == set(selected), "Unknown or internal author tests"
    (root / "pytest.ini").write_text(
        "[pytest]\nasyncio_mode = auto\n"
        "markers =\n"
        "    p1: supported feature contracts\n",
    )
    return tests


def check_local_provider_artifact(artifact: Path, source: Path) -> None:
    """Check that the bundled provider ships its Python and metadata files."""
    local = source / "plugins/provider/local-llamacpp"
    files = list(local.rglob("*.py")) + [
        local / "plugin.json",
        local / "requirements.txt",
        local / "runtime-release.json",
    ]
    wheel = artifact.suffix == ".whl"
    with (
        zipfile.ZipFile(artifact) if wheel else tarfile.open(artifact)
    ) as archive:
        names = archive.namelist() if wheel else archive.getnames()
        prefix = (
            "qwenpaw/plugins/bundled/provider/local-llamacpp"
            if wheel
            else names[0].split("/")[0] + "/plugins/provider/local-llamacpp"
        )
        for file in files:
            name = f"{prefix}/{file.relative_to(local).as_posix()}"
            assert (
                name in names
            ), f"Missing bundled local provider file: {name}"
            if wheel:
                content = archive.read(name)
            else:
                with archive.extractfile(name) as stream:
                    content = stream.read()
            assert (
                content == file.read_bytes()
            ), f"Bundled local provider differs from source: {name}"


def prepare_local_provider_tests(source: Path, root: Path) -> list[str]:
    """Select installed local-provider checks separately from SDK authors."""
    suite = root / "local_provider_tests"
    suite.mkdir()
    file = "test_provider.py"
    shutil.copy2(
        source / "tests/plugins/local_model" / file,
        suite,
    )
    return [
        f"{suite / file}::{name}"
        for name in (
            "test_bundle_load_does_not_import_backend_or_download_packages",
            "test_local_dataclasses_preserve_management_http_responses",
        )
    ]


def run_acceptance_tests(
    run,
    source: Path,
    root: Path,
    *,
    local_provider: bool = False,
) -> None:
    """Run public SDK tests and explicitly requested local checks."""
    suites = {"public-author-tests": [str(root / "author_tests")]}
    if local_provider:
        suites[
            "installed-local-provider-tests"
        ] = prepare_local_provider_tests(
            source,
            root,
        )
    for name, nodes in suites.items():
        run(name, "-m", "pytest", *nodes, "-q", "--tb=short", "--timeout=45")


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--test-files", nargs="+")
    parser.add_argument(
        "--local-provider",
        action="store_true",
        help="Also check the installed local provider (requires the local extra).",
    )
    return parser.parse_args(argv)


# The standalone acceptance sequence shares one report and environment.
# pylint: disable-next=too-many-statements
def main():
    args = _parse_args()
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
        QWENPAW_DEPENDENCY_STATE_DIR=str(root / "runtime/dependencies"),
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
        if result.returncode != 0:
            print("\n".join(result.stdout.splitlines()[-40:]), file=sys.stderr)
        assert (
            result.returncode == 0
        ), f"{name} failed; see {root / (name + '.log')}\n{result.stdout}"
        return result.stdout

    for artifact in (args.wheel.resolve(), args.sdist.resolve()):
        check_local_provider_artifact(artifact, source)
        if artifact.suffix == ".whl":
            with zipfile.ZipFile(artifact) as archive:
                names = archive.namelist()
                metadata = archive.read(
                    next(
                        n for n in names if n.endswith(".dist-info/METADATA")
                    ),
                ).decode()
            assert not any(
                name.startswith(
                    (
                        "qwenpaw/harnesses/",
                        "openai_codex/",
                        "codex_cli_bin/",
                        "qoder_agent_sdk/",
                    ),
                )
                for name in names
            ), "Optional Harness runtime leaked into core wheel"
            for line in metadata.splitlines():
                if not line.startswith("Requires-Dist: "):
                    continue
                requirement = Requirement(line.removeprefix("Requires-Dist: "))
                if requirement.marker and not requirement.marker.evaluate(
                    {"extra": "full"},
                ):
                    continue
                assert requirement.name.lower().replace("_", "-") not in {
                    "openai-codex",
                    "openai-codex-cli-bin",
                    "codex-cli-bin",
                    "qoder-agent-sdk",
                }, "Optional Harness dependency required by core wheel"
                if requirement.name.lower() == "qwenpaw":
                    assert not {"codex", "qoder"} & requirement.extras
            assert "qwenpaw/plugins/frontend/package.json" in names
            assert "qwenpaw/plugins/frontend/index.js" in names
            assert "qwenpaw/plugins/templates/hello/plugin.json" in names
            assert "qwenpawmail_mcp/__init__.py" in names
            whisper = "qwenpaw/plugins/bundled/transcription/local-whisper"
            assert {f"{whisper}/plugin.py", f"{whisper}/plugin.json"} <= set(
                names,
            ), "Missing bundled Local Whisper plugin"
            for hub in (
                "qwenpaw-hub",
                "clawhub-hub",
                "modelscope-hub",
                "aliyun-hub",
            ):
                assert any(n.endswith(f"/{hub}/plugin.json") for n in names)
                assert any(n.endswith(f"/{hub}/plugin.py") for n in names)
        else:
            with tarfile.open(artifact) as archive:
                names = archive.getnames()
        assert not any(
            any(
                part in Path(name).parts
                for part in ("sdk_test", "sdk_validation_v1_1")
            )
            for name in names
        ), "Local experiment content leaked into artifact"
        report["artifacts"][artifact.name] = {
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "files": len(names),
        }
    import_check = f"""
import hashlib, importlib.metadata, json, zipfile
from email.parser import BytesParser
from pathlib import Path
import qwenpaw
location = Path(qwenpaw.__file__).resolve()
assert "site-packages" in location.parts, location
assert not location.is_relative_to(Path({str(source)!r})), location
package_root = location.parent.parent
distributions = [
    dist for dist in importlib.metadata.distributions(path=[str(package_root)])
    if dist.metadata["Name"].lower().replace("_", "-") == "qwenpaw"
]
assert distributions, "Missing qwenpaw metadata in imported package directory"
assert len(distributions) == 1, (
    "Multiple qwenpaw metadata records in imported package directory"
)
selected = importlib.metadata.distribution("qwenpaw")
assert Path(selected.locate_file("")).resolve() == package_root, (
    "Selected qwenpaw metadata belongs to a different installation"
)
assert Path(selected.locate_file("qwenpaw/__init__.py")).resolve() == location, (
    "Selected qwenpaw metadata does not match the imported package"
)
with zipfile.ZipFile({str(args.wheel.resolve())!r}) as archive:
    metadata = next(
        name for name in archive.namelist()
        if name.endswith(".dist-info/METADATA")
    )
    expected = BytesParser().parsebytes(archive.read(metadata))["Version"]
    assert selected.version == distributions[0].version == expected, (
        "Installed wheel version mismatch"
    )
    for name in archive.namelist():
        if name.startswith("qwenpaw/") and not name.endswith("/"):
            installed = package_root / name
            assert installed.is_file(), f"Missing installed wheel file: {{name}}"
            assert hashlib.sha256(installed.read_bytes()).digest() == hashlib.sha256(
                archive.read(name)
            ).digest(), f"Installed wheel bytes mismatch: {{name}}"
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
    run(
        "native-app-import",
        "-c",
        "from importlib.util import find_spec; "
        "from qwenpaw.app._app import app; "
        "assert app is not None; "
        "assert all(find_spec(name) is None for name in "
        "('openai_codex', 'codex_cli_bin', 'qoder_agent_sdk'))",
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
    report["tests"] = prepare_author_tests(source, root, args.test_files)
    run_acceptance_tests(
        run,
        source,
        root,
        local_provider=args.local_provider,
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
