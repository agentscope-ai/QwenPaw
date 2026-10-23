# -*- coding: utf-8 -*-
"""C7 release artifacts: inspect products of the real offline build backend."""

from __future__ import annotations

import email
import hashlib
import io
import json
import os
import runpy
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[3]
OFFICIAL_ROWS = runpy.run_path(
    str(ROOT / "src/qwenpaw/plugins/official_channel_catalog.py"),
)["OFFICIAL_CHANNELS"]
SOURCE_DIRS = {row["plugin_id"]: row["source_dir"] for row in OFFICIAL_ROWS}
OFFICIAL_IDS = tuple(sorted(SOURCE_DIRS))
# Azure Bot was public before extraction (#5849); bundling preserves that
# existing publication policy. The other official sources remain private.
PUBLIC_OFFICIAL_IDS = frozenset({"azure-bot"})
EXCLUSIVE_SDKS = {
    "lark-oapi",
    "dingtalk-stream",
    "alibabacloud-dingtalk",
}


def _copy_release_inputs(source: Path, destination: Path) -> None:
    """Stage only the normal backend inputs, outside the checkout."""
    destination.mkdir()
    for name in ("pyproject.toml", "setup.py", "README.md", "LICENSE"):
        shutil.copy2(source / name, destination / name)
    if (source / "MANIFEST.in").exists():
        shutil.copy2(source / "MANIFEST.in", destination / "MANIFEST.in")
    ignored = shutil.ignore_patterns(
        "__pycache__",
        "*.pyc",
        "*.egg-info",
        ".pytest_cache",
        ".DS_Store",
    )
    shutil.copytree(source / "src", destination / "src", ignore=ignored)
    shutil.copytree(
        source / "packages" / "qwenpawmail-mcp" / "src",
        destination / "packages" / "qwenpawmail-mcp" / "src",
        ignore=ignored,
    )
    for kind in ("channel", "hub"):
        shutil.copytree(
            source / "plugins" / kind,
            destination / "plugins" / kind,
            ignore=ignored,
        )
    shutil.copytree(
        source / "scripts" / "pack",
        destination / "scripts" / "pack",
        ignore=ignored,
    )


def _build(
    stage: Path,
    output: Path,
    method: str,
    config_settings: dict | None = None,
    metadata_directory: Path | None = None,
) -> Path:
    output.mkdir(parents=True)
    metadata_arg = (
        f", metadata_directory={str(metadata_directory)!r}"
        if metadata_directory is not None
        else ""
    )
    script = (
        "import os, setuptools.build_meta as backend; "
        f"os.chdir({str(stage)!r}); "
        f"print('C7_ARTIFACT=' + backend.{method}("
        f"{str(output)!r}, config_settings={config_settings!r}{metadata_arg}))"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=stage,
        env={**os.environ, "PIP_NO_INDEX": "1", "PYTHONNOUSERSITE": "1"},
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, (
        result.stdout[-4000:] + result.stderr[-4000:]
    )
    names = [
        line.removeprefix("C7_ARTIFACT=")
        for line in result.stdout.splitlines()
        if line.startswith("C7_ARTIFACT=")
    ]
    assert len(names) == 1, result.stdout[-4000:]
    artifact = output / names[0]
    if method.startswith("prepare_metadata"):
        assert artifact.is_dir()
    else:
        assert artifact.is_file()
    return artifact


@pytest.fixture(name="c7_artifacts", scope="module")
def _c7_artifacts(tmp_path_factory):
    root = tmp_path_factory.mktemp("c7-release")
    stage = root / "stage"
    _copy_release_inputs(ROOT, stage)
    wheel = _build(stage, root / "wheel", "build_wheel")
    sdist = _build(stage, root / "sdist", "build_sdist")
    return stage, wheel, sdist


def _assert_official_bundle(wheel: Path, source: Path) -> dict:
    with zipfile.ZipFile(wheel) as host:
        prefix = "qwenpaw/official_channels/"
        index = json.loads(host.read(prefix + "index.json"))
        assert set(index) == {"schema_version", "host_version", "plugins"}
        assert index["schema_version"] == 1
        assert [item["plugin_id"] for item in index["plugins"]] == list(
            OFFICIAL_IDS,
        )
        for item in index["plugins"]:
            channel = item["plugin_id"]
            manifest = json.loads(
                (
                    source
                    / "plugins"
                    / "channel"
                    / SOURCE_DIRS[channel]
                    / "plugin.json"
                ).read_text(),
            )
            if channel in PUBLIC_OFFICIAL_IDS:
                assert manifest.get("publish", True) is True
            else:
                assert manifest["publish"] is False
            assert set(item) == {
                "plugin_id",
                "version",
                "filename",
                "sha256",
                "descriptor_sha256",
                "requirements_sha256",
                "qwenpaw_version",
            }
            assert item["version"] == manifest["version"]
            assert item["qwenpaw_version"] == manifest["qwenpaw_version"]
            assert item["filename"] == f"{channel}-{manifest['version']}.zip"
            archive_bytes = host.read(prefix + item["filename"])
            assert hashlib.sha256(archive_bytes).hexdigest() == item["sha256"]
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as plugin:
                assert plugin.testzip() is None
                names = {
                    name
                    for name in plugin.namelist()
                    if not name.endswith("/")
                }
                source_dir = (
                    source / "plugins" / "channel" / SOURCE_DIRS[channel]
                )
                expected = {
                    f"{channel}/{path.relative_to(source_dir).as_posix()}"
                    for path in source_dir.rglob("*")
                    if path.is_file()
                    and "__pycache__" not in path.parts
                    and path.suffix != ".pyc"
                }
                assert names == expected
                assert (
                    plugin.read(f"{channel}/plugin.json")
                    == (source_dir / "plugin.json").read_bytes()
                )
                for rel, key in (
                    ("channel.json", "descriptor_sha256"),
                    ("requirements.txt", "requirements_sha256"),
                ):
                    digest = hashlib.sha256(
                        plugin.read(f"{channel}/{rel}"),
                    ).hexdigest()
                    assert digest == item[key]
        return index


def test_c7_wheel_has_closed_private_official_bundle(c7_artifacts) -> None:
    stage, wheel, _ = c7_artifacts
    _assert_official_bundle(wheel, stage)


def _assert_editable_official_sources(
    stage: Path,
    wheel: Path,
    tmp_path,
) -> None:
    """Extract canonical sources from the isolated installed artifact."""
    installed = tmp_path / "site"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(installed)

    script = r"""
import hashlib, importlib.abc, io, json, pathlib, site, sys, zipfile
from importlib import resources

stage = pathlib.Path(sys.argv[1]).resolve()
installed = pathlib.Path(sys.argv[2]).resolve()
public_officials = set(json.loads(sys.argv[4]))
# -S avoids the current environment's editable .pth finder. Process only
# the wheel under test, then expose dependency directories without their .pths.
site.addsitedir(str(installed))
for dependency_dir in json.loads(sys.argv[3]):
    if dependency_dir not in sys.path:
        sys.path.append(dependency_dir)


class NoPlatformImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(
            (
                "lark_oapi",
                "dingtalk_stream",
                "alibabacloud_dingtalk",
                "feishu",
                "dingtalk",
                "qwenpaw.app.channels.feishu",
                "qwenpaw.app.channels.dingtalk",
            )
        ):
            raise AssertionError(
                "Platform import during extraction: " + fullname
            )


sys.meta_path.insert(0, NoPlatformImports())
import qwenpaw
from qwenpaw.__version__ import __version__
from qwenpaw.plugins.official_channels import bundled_channel_source

assert pathlib.Path(qwenpaw.__file__).resolve().is_relative_to(stage), (
    qwenpaw.__file__
)
root = resources.files("qwenpaw").joinpath("official_channels")
assert root.joinpath("index.json").is_file(), (
    "Editable install is missing official_channels/index.json: " + str(root)
)
index = json.loads(root.joinpath("index.json").read_bytes())
assert set(index) == {"schema_version", "host_version", "plugins"}
assert index["schema_version"] == 1
assert index["host_version"] == __version__
from qwenpaw.plugins.official_channel_catalog import OFFICIAL_CHANNELS
sources = {row["plugin_id"]: row["source_dir"] for row in OFFICIAL_CHANNELS}
assert [row["plugin_id"] for row in index["plugins"]] == sorted(sources)
for row in index["plugins"]:
    channel = row["plugin_id"]
    original = stage / "plugins/channel" / sources[channel]
    manifest = json.loads((original / "plugin.json").read_bytes())
    assert set(row) == {
        "plugin_id", "version", "filename", "sha256", "descriptor_sha256",
        "requirements_sha256", "qwenpaw_version",
    }
    assert row["version"] == manifest["version"]
    assert row["qwenpaw_version"] == manifest["qwenpaw_version"]
    assert row["filename"] == f"{channel}-{manifest['version']}.zip"
    payload = root.joinpath(row["filename"]).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == row["sha256"]
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.testzip() is None
        assert archive.read(f"{channel}/plugin.json") == (
            original / "plugin.json"
        ).read_bytes()
        for relative, key in (
            ("channel.json", "descriptor_sha256"),
            ("requirements.txt", "requirements_sha256"),
        ):
            assert hashlib.sha256(
                archive.read(f"{channel}/{relative}")
            ).hexdigest() == row[key]
    with bundled_channel_source(channel) as source:
        expected = {
            path.relative_to(original).as_posix(): path.read_bytes()
            for path in original.rglob("*") if path.is_file()
        }
        extracted = {
            path.relative_to(source).as_posix(): path.read_bytes()
            for path in source.rglob("*") if path.is_file()
        }
        assert extracted == expected
        extracted_manifest = json.loads((source / "plugin.json").read_bytes())
        if channel in public_officials:
            assert extracted_manifest.get("publish", True) is True
        else:
            assert extracted_manifest["publish"] is False
    assert not source.exists()
print("C7_EDITABLE_SOURCES_OK")
"""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("QWENPAW_")
    }
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            script,
            str(stage),
            str(installed),
            json.dumps(
                [
                    path
                    for path in sys.path
                    if Path(path).name in {"site-packages", "dist-packages"}
                ],
            ),
            json.dumps(sorted(PUBLIC_OFFICIAL_IDS)),
        ],
        cwd=tmp_path,
        env={
            **env,
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "C7_EDITABLE_SOURCES_OK"


@pytest.mark.parametrize("mode", [None, "strict"], ids=["default", "strict"])
@pytest.mark.parametrize(
    "versions",
    [("0.1.0.dev0",), ("0.1.0.dev0", "0.1.1.dev0")],
    ids=["install", "reinstall"],
)
def test_c7_editable_install_exposes_official_channel_sources(
    tmp_path,
    mode,
    versions,
) -> None:
    """Editable resources survive metadata preparation and version updates."""
    stage = tmp_path / "stage"
    _copy_release_inputs(ROOT, stage)
    source_bundle = stage / "src/qwenpaw/official_channels"
    shutil.rmtree(source_bundle, ignore_errors=True)
    assert not source_bundle.exists()
    config = {"editable_mode": mode} if mode else None
    manifest_path = stage / "plugins/channel/feishu/plugin.json"
    for attempt, version in enumerate(versions):
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = version
        manifest_path.write_text(json.dumps(manifest) + "\n")
        metadata = _build(
            stage,
            tmp_path / f"metadata-{attempt}",
            "prepare_metadata_for_build_editable",
            config,
        )
        wheel = _build(
            stage,
            tmp_path / f"editable-wheel-{attempt}",
            "build_editable",
            config,
            metadata_directory=metadata.parent,
        )
        _assert_editable_official_sources(
            stage,
            wheel,
            tmp_path / f"runtime-{attempt}",
        )


def test_c7_metadata_moves_exclusive_sdks_to_channels(
    c7_artifacts,
) -> None:
    stage, wheel, _ = c7_artifacts
    project = tomllib.loads((stage / "pyproject.toml").read_text())["project"]
    base = {
        canonicalize_name(Requirement(item).name)
        for item in project["dependencies"]
    }
    assert base.isdisjoint(EXCLUSIVE_SDKS)
    shared_alibaba = {
        "alibabacloud-credentials",
        "alibabacloud-tea-openapi",
        "alibabacloud-tea-util",
    }
    assert shared_alibaba <= base

    declared = {
        str(Requirement(line.strip()))
        for channel in OFFICIAL_IDS
        for line in (
            stage
            / "plugins"
            / "channel"
            / SOURCE_DIRS[channel]
            / "requirements.txt"
        )
        .read_text()
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    extras = project["optional-dependencies"]
    assert {str(Requirement(item)) for item in extras["channels"]} == declared
    assert any("qwenpaw[channels]" in item for item in extras["full"])

    with zipfile.ZipFile(wheel) as host:
        metadata_path = next(
            name
            for name in host.namelist()
            if name.endswith(".dist-info/METADATA")
        )
        metadata = email.message_from_bytes(host.read(metadata_path))
    requires = [
        Requirement(value) for value in metadata.get_all("Requires-Dist", [])
    ]
    wheel_base = {
        canonicalize_name(item.name)
        for item in requires
        if item.marker is None or item.marker.evaluate({"extra": ""})
    }
    assert wheel_base.isdisjoint(EXCLUSIVE_SDKS)
    assert "channels" in metadata.get_all("Provides-Extra", [])

    def normalized(requirement):
        return (
            canonicalize_name(requirement.name),
            tuple(sorted(requirement.extras)),
            str(requirement.specifier),
        )

    for version in ("3.11", "3.12", "3.13"):
        environment = {
            **default_environment(),
            "python_version": version,
            "python_full_version": version + ".0",
        }
        wheel_channels = {
            normalized(item)
            for item in requires
            if item.marker is not None
            and item.marker.evaluate({**environment, "extra": "channels"})
            and not item.marker.evaluate({**environment, "extra": ""})
        }
        active = {
            normalized(item)
            for value in declared
            if (item := Requirement(value)).marker is None
            or item.marker.evaluate(environment)
        }
        assert wheel_channels == active, version


def test_c7_sdist_rebuilds_the_same_official_resources(
    c7_artifacts,
    tmp_path,
) -> None:
    _, wheel, sdist = c7_artifacts
    with tarfile.open(sdist, "r:gz") as archive:
        names = archive.getnames()
        assert any(
            name.endswith("/scripts/pack/generate_plugin_metadata.py")
            for name in names
        )
        for channel in OFFICIAL_IDS:
            assert any(
                name.endswith(
                    f"/plugins/channel/{SOURCE_DIRS[channel]}/plugin.json",
                )
                for name in names
            )
        archive.extractall(tmp_path, filter="data")
    extracted = next(path for path in tmp_path.iterdir() if path.is_dir())
    rebuilt = _build(extracted, tmp_path / "rebuilt", "build_wheel")
    first = _assert_official_bundle(wheel, c7_artifacts[0])
    second = _assert_official_bundle(rebuilt, extracted)
    assert second == first


def test_c7_generic_contracts_execute_from_wheel_sdist_and_staged_support(
    c7_artifacts,
    tmp_path,
) -> None:
    """
    Missing release/support payloads must fail outside the checkout source.
    """
    import importlib.util

    _, wheel, sdist = c7_artifacts
    sdist_root = tmp_path / "source-release"
    sdist_root.mkdir()
    with tarfile.open(sdist, "r:gz") as archive:
        archive.extractall(sdist_root, filter="data")
    source = next(sdist_root.iterdir()) / "src"
    spec = importlib.util.spec_from_file_location(
        "extension_channel_support_stager",
        ROOT / "scripts/pack-tauri/stage_channel_runtime.py",
    )
    assert spec is not None and spec.loader is not None
    stager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stager)
    support = tmp_path / "resources/binaries/channel-runtime/site"
    support.mkdir(parents=True)
    # Exercise the actual wheel extraction boundary, not a fake stager.
    # pylint: disable-next=protected-access
    stager._extract_wheel(wheel, support)

    script = r"""
import importlib.abc, json, pathlib, sys

root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))


class NoPlatformImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(
            (
                "lark_oapi",
                "dingtalk_stream",
                "qwenpaw.app.channels.feishu",
                "qwenpaw.app.channels.dingtalk",
            )
        ):
            raise AssertionError(
                "Platform import from pure released contracts: " + fullname
            )


sys.meta_path.insert(0, NoPlatformImports())
from qwenpaw.channel_protocol import normalization, targets, response_policy
from qwenpaw.channel_protocol.models import InboundEvent

for module in (normalization, targets, response_policy):
    assert (
        pathlib.Path(module.__file__).resolve().is_relative_to(root)
    ), module.__file__
target = targets.encode_reply_target(
    user_id="member-17", session_id="historic-room"
)
assert targets.decode_reply_target(target) == {
    "user_id": "member-17",
    "session_id": "historic-room",
}
assert (
    response_policy.ResponsePolicy.from_mapping(
        {"streaming": True, "prepare": False, "completion_reaction": False}
    ).streaming
    is True
)
event = InboundEvent.from_mapping(
    {
        "channel_key": "sample_chat",
        "instance_id": "workspace-one",
        "generation": 1,
        "event_id": "one",
        "event_kind": "message",
        "conversation": {"id": "room-A", "type": "group"},
        "sender_id": "Alice",
        "sender_name": "Alice",
        "acl_sender_id": "actor-17",
        "content_parts": [{"type": "text", "text": "hello"}],
        "metadata": {
            "session_id": "historic-room",
            "user_id": "group",
            "debounce_key": "historic-room:actor-17",
        },
    }
)
payload = normalization.normalize_inbound_event(event)
assert (
    payload["session_id"] == "historic-room"
    and payload["acl_sender_id"] == "actor-17"
)
print(
    json.dumps(
        {
            "user_id": payload["user_id"],
            "is_group": payload["meta"]["is_group"],
        }
    )
)
"""
    for import_root in (wheel, source, support):
        result = subprocess.run(
            [sys.executable, "-I", "-c", script, str(import_root)],
            cwd=tmp_path,
            env={
                **os.environ,
                "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
                "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout) == {
            "user_id": "group",
            "is_group": True,
        }
