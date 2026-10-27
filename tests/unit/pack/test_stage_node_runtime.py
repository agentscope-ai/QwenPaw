# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Verify bundled Node upgrades replace stale runtimes on each platform."""

from __future__ import annotations

import importlib.util
import io
import sys
import tarfile
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_FILE = REPO_ROOT / f"scripts" / f"pack-tauri" / f"stage_node_runtime.py"


def test_ci_jobs_use_the_repository_node_version() -> None:
    workflow_dir = REPO_ROOT / f".github" / f"workflows"
    contents = [
        path.read_text(encoding=f"utf-8")
        for path in workflow_dir.glob(f"*.yml")
    ]

    setup_node_count = sum(
        content.count(f"actions/setup-node@") for content in contents
    )
    version_file_count = sum(
        content.count(f"node-version-file: .nvmrc") for content in contents
    )

    assert setup_node_count == version_file_count
    assert all(f"node-version:" not in content for content in contents)


def test_docker_images_verify_the_repository_node_version() -> None:
    dockerfiles = [
        REPO_ROOT / f"deploy" / f"Dockerfile",
        (
            REPO_ROOT
            / f"plugins"
            / f"apps"
            / f"qwenpaw-creator"
            / f"Dockerfile"
        ),
    ]
    creator_dockerfile = dockerfiles[1]
    dockerignore = (
        REPO_ROOT
        / f"plugins"
        / f"apps"
        / f"qwenpaw-creator"
        / f"Dockerfile.dockerignore"
    )

    for dockerfile in dockerfiles:
        content = dockerfile.read_text(encoding=f"utf-8")
        assert f"COPY .nvmrc" in content
        assert f"node --version" in content
        assert f"Node version mismatch" in content

    creator_content = creator_dockerfile.read_text(encoding=f"utf-8")
    node_version = (REPO_ROOT / f".nvmrc").read_text(encoding=f"utf-8").strip()
    assert f"FROM ${{NODE_IMAGE}} AS node-runtime" in creator_content
    assert f"COPY --from=node-runtime" in creator_content
    assert f"/usr/local/bin/node" in creator_content
    assert f"/usr/local/lib/node_modules/npm" in creator_content
    assert f"ARG NODE_IMAGE=node:{node_version}-slim" in creator_content
    assert f"ENV NODE_VERSION={node_version}" in creator_content

    ignored = dockerignore.read_text(encoding=f"utf-8")
    assert f"!.nvmrc" in ignored


def test_release_pr_workflows_include_release_branches() -> None:
    workflow_names = [
        f"tests.yml",
        f"frontend-tests.yml",
        f"creator-app-tests.yml",
    ]
    workflow_dir = REPO_ROOT / f".github" / f"workflows"

    for workflow_name in workflow_names:
        content = (workflow_dir / workflow_name).read_text(encoding=f"utf-8")
        assert f"release/**" in content


@pytest.mark.parametrize(
    f"workflow_name",
    [f"tests.yml", f"frontend-tests.yml"],
)
def test_node_version_changes_trigger_changedetection_workflows(
    workflow_name: str,
) -> None:
    workflow_path = REPO_ROOT / f".github" / f"workflows" / workflow_name
    workflow = yaml.safe_load(
        workflow_path.read_text(encoding=f"utf-8"),
    )

    # PyYAML 1.1 normalizes the unquoted workflow key "on" to True.
    push_paths = workflow[True][f"push"][f"paths"]
    assert f".nvmrc" in push_paths

    changes_steps = workflow[f"jobs"][f"changes"][f"steps"]
    paths_filter = next(
        step[f"with"][f"filters"]
        for step in changes_steps
        if step.get(f"uses", "").startswith(f"dorny/paths-filter@")
    )
    assert f".nvmrc" in paths_filter


def test_node_version_changes_trigger_creator_tests() -> None:
    workflow_path = (
        REPO_ROOT / f".github" / f"workflows" / f"creator-app-tests.yml"
    )
    workflow = yaml.safe_load(
        workflow_path.read_text(encoding=f"utf-8"),
    )
    triggers = workflow[True]

    assert f".nvmrc" in triggers[f"push"][f"paths"]
    assert f".nvmrc" in triggers[f"pull_request"][f"paths"]


@pytest.mark.parametrize(f"system", [f"Windows", f"Darwin", f"Linux"])
@pytest.mark.parametrize(f"machine", [f"AMD64", f"aarch64"])
def test_upgrade_replaces_old_runtime_and_reuses_new_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    machine: str,
) -> None:
    spec = importlib.util.spec_from_file_location(
        f"stage_node_runtime_under_test",
        SCRIPT_FILE,
    )
    assert spec is not None and spec.loader is not None
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    monkeypatch.setattr(runtime.platform, f"system", lambda: system)
    monkeypatch.setattr(runtime.platform, f"machine", lambda: machine)
    monkeypatch.delenv(f"QWENPAW_NODE_VERSION", raising=False)

    nvmrc = REPO_ROOT / f".nvmrc"
    version = f"v{nvmrc.read_text(encoding=f'utf-8').strip()}"
    assert runtime.DEFAULT_NODE_VERSION == version
    os_name = {f"Windows": f"win", f"Darwin": f"darwin", f"Linux": f"linux"}
    arch = f"x64" if machine == f"AMD64" else f"arm64"
    target = f"{os_name[system]}-{arch}"
    suffix = f"zip" if system == f"Windows" else f"tar.xz"
    root = f"node-{version}-{target}"
    dest = tmp_path / f"runtime with spaces"
    dest.mkdir()
    marker = dest / f".node-runtime-version"
    marker.write_text(f"v22.20.0-{target}", encoding=f"utf-8")
    stale = dest / f"stale-file"
    stale.touch()
    node = runtime._node_exe(dest)
    npx = runtime._npx_exe(dest)
    node.parent.mkdir(parents=True, exist_ok=True)
    node.write_bytes(b"old node")
    npx.write_bytes(b"old npx")

    buffer = io.BytesIO()
    files = {node.relative_to(dest).as_posix(): b"new node"}
    files[npx.relative_to(dest).as_posix()] = b"new npx"
    if suffix == f"zip":
        with zipfile.ZipFile(buffer, f"w") as archive:
            for name, content in files.items():
                archive.writestr(f"{root}/{name}", content)
    else:
        with tarfile.open(fileobj=buffer, mode=f"w:xz") as archive:
            for name, content in files.items():
                member = tarfile.TarInfo(f"{root}/{name}")
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))

    download = Mock(return_value=buffer.getvalue())
    monkeypatch.setattr(runtime, f"_http_get", download)
    monkeypatch.setattr(sys, f"argv", [str(SCRIPT_FILE), f"--dest", str(dest)])
    runtime.main()

    download.assert_called_once_with(
        f"{runtime.NODE_DIST_URL}/{version}/{root}.{suffix}",
    )
    assert node.read_bytes() == b"new node"
    assert npx.read_bytes() == b"new npx"
    assert not stale.exists()
    assert marker.read_text(encoding=f"utf-8") == f"{version}-{target}"

    runtime.main()

    assert download.call_count == 1
