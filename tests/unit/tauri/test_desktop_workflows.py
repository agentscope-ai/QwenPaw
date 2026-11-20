# -*- coding: utf-8 -*-
"""Regression tests for desktop packaging workflows."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib

from packaging.specifiers import SpecifierSet
from packaging.version import Version
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]

RELEASE_HELPERS = (
    "scripts/pack/download_desktop_artifacts.sh",
    "scripts/pack/verify_github_release_assets.sh",
    "scripts/pack/oss_copy_with_readback.sh",
    "scripts/pack/generate_oss_metadata.py",
    "scripts/pack-tauri/generate_update_manifest.py",
)


def _load_workflow(name: str) -> dict:
    return yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / name).read_text(
            encoding="utf-8",
        ),
    )


def test_fork_desktop_build_uses_supported_python() -> None:
    """Both platform builders must bootstrap a project-supported Python."""
    project = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"),
    )
    supported = SpecifierSet(project["project"]["requires-python"])
    workflow = _load_workflow("fork-verify-desktop.yml")

    for job_name in ("tauri-macos", "tauri-windows"):
        setup_python = next(
            step
            for step in workflow["jobs"][job_name]["steps"]
            if step.get("uses", "").startswith("actions/setup-python@")
        )
        version = Version(str(setup_python["with"]["python-version"]))
        assert version in supported, (
            f"{job_name} bootstraps unsupported Python {version}; "
            f"project requires {supported}"
        )


@pytest.mark.parametrize(
    ("workflow_name", "job_name"),
    [
        ("desktop-publish.yml", "upload-release"),
        ("desktop-publish.yml", "upload-oss"),
        ("desktop-promote.yml", "promote-oss"),
        ("desktop-release.yml", "upload-release"),
        ("desktop-release.yml", "upload-oss"),
    ],
)
def test_publish_jobs_load_infrastructure_from_workflow_revision(
    workflow_name: str,
    job_name: str,
) -> None:
    """Old release targets must not provide the active workflow's helpers."""
    job = _load_workflow(workflow_name)["jobs"][job_name]
    steps = job["steps"]
    infrastructure_checkout = next(
        step
        for step in steps
        if step.get("name") == "Checkout release infrastructure"
    )

    assert infrastructure_checkout["uses"].startswith("actions/checkout@")
    assert infrastructure_checkout["with"] == {
        "ref": "${{ github.workflow_sha }}",
        "path": ".release-infra",
        "sparse-checkout": "scripts\nsrc/qwenpaw/security\n",
        "persist-credentials": False,
    }
    assert job["env"]["RELEASE_INFRA"] == (
        "${{ github.workspace }}/.release-infra"
    )

    target_checkout_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Checkout release target"
    )
    infrastructure_checkout_index = steps.index(infrastructure_checkout)
    assert target_checkout_index < infrastructure_checkout_index

    helper_lines = [
        line
        for step in steps
        for line in step.get("run", "").splitlines()
        if any(helper in line for helper in RELEASE_HELPERS)
    ]
    assert helper_lines
    assert all("$RELEASE_INFRA/" in line for line in helper_lines)


def test_download_helper_resolves_verifier_from_its_own_checkout() -> None:
    """The helper must still work when the product checkout has no scripts."""
    script = (
        REPO_ROOT / "scripts/pack/download_desktop_artifacts.sh"
    ).read_text(encoding="utf-8")

    assert 'script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")"' in script
    assert 'python3 "$script_dir/verify_desktop_artifacts.py"' in script


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Desktop manifest upload steps run in Bash on Ubuntu",
)
@pytest.mark.parametrize(
    ("workflow_name", "job_name"),
    [
        ("desktop-promote.yml", "promote-oss"),
        ("desktop-release.yml", "upload-oss"),
    ],
)
@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("2.3.0", "2.3.0"),
        ("2.3.0.post1", "2.3.0+post.1"),
        ("2.3.0a1", None),
        ("2.3.0b2", None),
        ("2.3.0-beta.2", None),
        ("2.3.0rc1", None),
        ("2.3.0.dev1", None),
        ("2.3.0.post1.dev1", None),
        ("invalid", None),
    ],
)
def test_desktop_updater_manifest_only_publishes_stable_versions(
    tmp_path,
    workflow_name,
    job_name,
    version,
    expected,
) -> None:
    """Execute the real upload step with a local substitute for OSS."""
    steps = _load_workflow(workflow_name)["jobs"][job_name]["steps"]
    step = next(
        step
        for step in steps
        if step.get("name") == "Generate and upload OSS updater manifest"
    )
    script = (
        step["run"]
        .replace(
            "${{ steps.version.outputs.version }}",
            version,
        )
        .replace("${{ inputs.tag }}", "test-release")
    )

    infrastructure = tmp_path / "infra"
    helpers = infrastructure / "scripts/pack"
    helpers.mkdir(parents=True)
    (infrastructure / "scripts/pack-tauri").symlink_to(
        REPO_ROOT / "scripts/pack-tauri",
        target_is_directory=True,
    )
    (helpers / "oss_copy_with_readback.sh").write_text(
        'test "$2" = "oss://test-bucket/metadata/qwenpaw-tauri-latest.json"\n'
        'cp "$1" "$PUBLISHED_MANIFEST"\n',
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text("#!/bin/sh\necho 'Test release notes'\n", encoding="utf-8")
    gh.chmod(0o755)
    metadata = tmp_path / "tauri-updater-meta-windows"
    metadata.mkdir()
    (metadata / "installer.exe").write_bytes(b"MZtest")
    (metadata / "installer.exe.sig").write_text("test-signature")
    (metadata / "tauri-windows-x86_64-updater.json").write_text(
        json.dumps(
            {
                "target": "windows-x86_64",
                "artifact": "installer.exe",
                "signature": "installer.exe.sig",
            },
        ),
        encoding="utf-8",
    )
    published = tmp_path / "published.json"
    previous = '{"version": "2.2.2"}\n'
    published.write_text(previous, encoding="utf-8")
    result = subprocess.run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-e",
            "-o",
            "pipefail",
            "-c",
            script,
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": os.pathsep.join(
                (
                    str(bin_dir),
                    str(Path(sys.executable).parent),
                    "/usr/bin",
                    "/bin",
                ),
            ),
            "RELEASE_INFRA": str(infrastructure),
            "OSS_BUCKET": "test-bucket",
            "OSS_PUBLIC_BASE_URL": "https://example.test/desktop",
            "GITHUB_REPOSITORY": "test/repo",
            "RELEASE_BODY": "Test release notes",
            "PUBLISHED_MANIFEST": str(published),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    if version == "invalid":
        assert result.returncode != 0
    else:
        assert result.returncode == 0, result.stderr
    if expected is None:
        assert published.read_text(encoding="utf-8") == previous
        assert not (tmp_path / "qwenpaw-tauri-latest-oss.json").exists()
    else:
        manifest = json.loads(published.read_text(encoding="utf-8"))
        assert manifest["version"] == expected
        assert manifest["platforms"]["windows-x86_64"] == {
            "url": "https://example.test/desktop/win-tauri/installer.exe",
            "signature": "test-signature",
        }


def test_nsis_template_avoids_solid_compression() -> None:
    """Large desktop payloads must not use NSIS solid compression."""
    config = json.loads(
        (REPO_ROOT / "console/src-tauri/tauri.conf.json").read_text(
            encoding="utf-8",
        ),
    )
    package_lock = json.loads(
        (REPO_ROOT / "console/package-lock.json").read_text(
            encoding="utf-8",
        ),
    )
    nsis = config["bundle"]["windows"]["nsis"]
    template = (REPO_ROOT / "console/src-tauri" / nsis["template"]).read_text(
        encoding="utf-8",
    )
    tauri_cli_version = package_lock["packages"][
        "node_modules/@tauri-apps/cli"
    ]["version"]

    assert nsis["compression"] == "zlib"
    # This is a version-sync reminder, not an upstream content check.
    # When upgrading the CLI, compare the template with that release.
    assert f"Vendored from Tauri v{tauri_cli_version}" in template
    assert 'SetCompressor "{{compression}}"' in template
    assert "SetCompressor /SOLID" not in template


@pytest.fixture
def nsis_cli_install(tmp_path):
    """Run the real installer helper against an isolated installation."""
    if sys.platform != "win32":
        pytest.skip("NSIS process preparation requires Windows")
    root = tmp_path / "QwenPaw Desktop"
    backend = root / "binaries" / "qwenpaw-backend"
    backend.mkdir(parents=True)
    (root / "qwenpaw-desktop.exe").write_bytes(b"desktop")
    (backend / "qwenpaw-backend.exe").write_bytes(b"backend")
    cli = backend / "qwenpaw.exe"
    cli.write_bytes(b"old CLI")
    profile = tmp_path / "profile"
    launcher = profile / ".qwenpaw" / "bin" / "qwenpaw-nm-host.bat"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(f'@"{cli}"\n', encoding="utf-8-sig")
    powershell = (
        Path(os.environ["SystemRoot"])
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    script = REPO_ROOT / "console/src-tauri/nsis/manage-install-processes.ps1"

    def run(*actions, expected=0):
        for action in actions:
            result = subprocess.run(
                [
                    str(powershell),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-InstallDir",
                    str(root),
                    "-GateCli",
                    "-Action",
                    action,
                ],
                env={**os.environ, "USERPROFILE": str(profile)},
                capture_output=True,
                text=True,
                errors="replace",
                timeout=30,
            )
            assert result.returncode == expected, result.stdout + result.stderr
        return result.stdout

    return cli, launcher, run


@pytest.mark.parametrize("phase", ["prepare", "copy", "complete"])
def test_nsis_cli_gate_recovers_at_the_correct_install_phase(
    nsis_cli_install,
    phase,
):
    """Cancellation must never reopen an entry into a partial update."""
    cli, launcher, run = nsis_cli_install
    staged = cli.with_name(cli.name + ".qwenpaw-new")
    backup = cli.with_name(cli.name + ".qwenpaw-maintenance")
    marker = cli.parents[2] / ".qwenpaw-installing"

    run("Prepare")
    assert not cli.exists()
    assert backup.read_bytes() == b"old CLI"
    assert "QWENPAW_INSTALL_MAINTENANCE" in launcher.read_text()
    if phase != "prepare":
        staged.write_bytes(b"stale staged CLI")
        run("BeginInstall", "ClearRuntime")
        assert marker.exists()
        assert not staged.exists()
        assert not cli.exists()
    if phase == "complete":
        cli.parent.mkdir(parents=True)
        staged.write_bytes(b"new CLI")
        run("CompleteInstall")
        assert cli.read_bytes() == b"new CLI"
        assert not backup.exists()
        assert not marker.exists()

    output = run("AbortInstall", expected=1 if phase == "copy" else 0)
    if phase == "copy":
        assert "Run the installer again" in output
        assert not cli.exists()
        # A subsequent attempt can finish without restoring the old entry.
        run("Prepare", "BeginInstall", "ClearRuntime")
        cli.parent.mkdir(parents=True)
        staged.write_bytes(b"retried CLI")
        run("CompleteInstall")
        assert cli.read_bytes() == b"retried CLI"
    else:
        expected = b"old CLI" if phase == "prepare" else b"new CLI"
        assert cli.read_bytes() == expected
    assert "QWENPAW_INSTALL_MAINTENANCE" not in launcher.read_text()


def test_nsis_fresh_install_requires_a_new_cli(nsis_cli_install):
    """Fresh installs use the same staging rule and can retry publication."""
    cli, launcher, run = nsis_cli_install
    root = cli.parents[2]
    cli.unlink()
    launcher.unlink()
    (root / "qwenpaw-desktop.exe").unlink()
    (cli.parent / "qwenpaw-backend.exe").unlink()
    run("Prepare", "BeginInstall", "ClearRuntime")
    run("CompleteInstall", expected=1)
    assert not cli.exists()
    cli.parent.mkdir(parents=True)
    # With all original binaries gone, the root marker still identifies a
    # partial installation and prevents its CLI from being left runnable.
    cli.write_bytes(b"partial CLI")
    run("Prepare")
    assert not cli.exists()
    run("BeginInstall", "ClearRuntime")
    cli.parent.mkdir(parents=True)
    cli.with_name(cli.name + ".qwenpaw-new").write_bytes(b"new CLI")
    run("CompleteInstall", "CompleteInstall")
    assert cli.read_bytes() == b"new CLI"


def test_nsis_previous_uninstall_uses_the_new_installer_guard():
    """The maintenance page must not launch an old NSIS uninstaller raw."""
    template = (
        REPO_ROOT / "console/src-tauri/nsis/tauri-installer.nsi"
    ).read_text(encoding="utf-8")
    maintenance = template.split("Function PageLeaveReinstall\n", 1)[1]
    maintenance = maintenance.split("FunctionEnd", 1)[0]
    nsis_uninstall = maintenance.split(
        'ReadRegStr $4 SHCTX "${MANUPRODUCTKEY}" ""',
        1,
    )[1].split("${EndIf}", 1)[0]
    assert "!insertmacro QWENPAW_UNINSTALL_PREVIOUS" in nsis_uninstall
    assert "ExecWait" not in nsis_uninstall
    install = template.split("Section Install\n", 1)[1]
    assert install.index("BeginInstall") < install.index("ClearRuntime")
    assert install.index("ClearRuntime") < install.index(
        'File "${MAINBINARYSRCPATH}"',
    )
    uninstall = template.split("Section Uninstall\n", 1)[1]
    assert uninstall.index('ClearRuntime "un."') < uninstall.index(
        'Delete "$INSTDIR\\${MAINBINARYNAME}.exe"',
    )
    # The shared completion helper removes the marker only after cleanup.
    assert '.qwenpaw-installing"' not in uninstall


@pytest.mark.parametrize("phase", ["cancelled", "partial", "complete"])
def test_nsis_cli_gate_covers_uninstall_before_install(
    nsis_cli_install,
    phase,
):
    """Legacy uninstall cleanup must neither reopen nor orphan the CLI."""
    cli, launcher, run = nsis_cli_install
    root = cli.parents[2]
    completed = phase == "complete"
    backup = cli.with_name(cli.name + ".qwenpaw-maintenance")
    marker = root / ".qwenpaw-installing"
    run("Prepare", "BeginInstall")
    assert not cli.exists()

    # Old uninstallers remove known payload files and restore Native Host.
    if phase != "cancelled":
        (root / "qwenpaw-desktop.exe").unlink()
    if completed:
        (cli.parent / "qwenpaw-backend.exe").unlink()
    run("Restore")
    assert "QWENPAW_INSTALL_MAINTENANCE" not in launcher.read_text()

    run(
        "CompleteUninstall" if completed else "AbortInstall",
        expected=0 if completed else 1,
    )
    assert not cli.exists()
    assert backup.exists() is not completed
    assert marker.exists() is not completed
    if not completed:
        assert "QWENPAW_INSTALL_MAINTENANCE" in launcher.read_text()

    # Both successful removal and an interrupted uninstall can be repaired.
    run("Prepare", "BeginInstall", "ClearRuntime")
    assert "QWENPAW_INSTALL_MAINTENANCE" in launcher.read_text()
    cli.parent.mkdir(parents=True)
    cli.with_name(cli.name + ".qwenpaw-new").write_bytes(b"new CLI")
    run("CompleteInstall")
    assert cli.read_bytes() == b"new CLI"
    assert not backup.exists()
    assert not marker.exists()
    assert "QWENPAW_INSTALL_MAINTENANCE" not in launcher.read_text()


def test_nsis_cli_gate_blocks_repeated_external_launches(nsis_cli_install):
    """A version-probe-like caller must not reopen the CLI during copying."""
    cli, _, run = nsis_cli_install
    shutil.copyfile(Path(os.environ["SystemRoot"]) / "System32/ping.exe", cli)
    stopped = threading.Event()
    started = threading.Event()
    blocked = threading.Event()
    children = []

    def probe():
        while not stopped.is_set():
            try:
                child = subprocess.Popen(
                    [str(cli), "-t", "127.0.0.1"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except OSError:
                blocked.set()
            else:
                children.append(child)
                started.set()
                # Relaunch as soon as the installer stops the previous probe.
                while child.poll() is None and not stopped.wait(0.02):
                    pass
            stopped.wait(0.02)

    thread = threading.Thread(target=probe, daemon=True)
    thread.start()
    try:
        assert started.wait(5)
        run("Prepare")
        assert blocked.wait(5)
        assert not cli.exists()
        run("BeginInstall", "ClearRuntime")
        count = len(children)
        time.sleep(0.2)
        assert len(children) == count
        assert all(child.poll() is not None for child in children)
    finally:
        stopped.set()
        thread.join(timeout=5)
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)


@pytest.mark.parametrize("operation", ["install", "uninstall"])
def test_nsis_runtime_cleanup_stops_on_locked_files_and_can_retry(
    nsis_cli_install,
    operation,
):
    """Partial deletion stays gated; retry removes only the bundled trees."""
    cli, launcher, run = nsis_cli_install
    root = cli.parents[2]
    config = json.loads(
        (REPO_ROOT / "console/src-tauri/tauri.conf.json").read_text(
            encoding="utf-8",
        ),
    )
    runtimes = [root / path for path in config["bundle"]["resources"]]
    for directory in runtimes:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "obsolete.pyd").write_bytes(b"old runtime")
    user_data = launcher.parent.parent / "history.db"
    user_data.write_bytes(b"user history")
    unrelated = root / "binaries" / "custom"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_bytes(b"keep")
    uninstaller = root / "uninstall.exe"
    uninstaller.write_bytes(b"uninstaller")
    run("Prepare", "BeginInstall")
    with (root / "binaries/python-runtime/obsolete.pyd").open("rb"):
        run("ClearRuntime", expected=1)
    assert any(not directory.exists() for directory in runtimes)
    assert not cli.exists()
    assert (root / ".qwenpaw-installing").exists()
    assert uninstaller.read_bytes() == b"uninstaller"
    assert (root / "qwenpaw-desktop.exe").exists()
    run("AbortInstall", expected=1)
    assert "QWENPAW_INSTALL_MAINTENANCE" in launcher.read_text()
    run("Prepare", "BeginInstall", "ClearRuntime", "ClearRuntime")
    assert all(not directory.exists() for directory in runtimes)
    assert user_data.read_bytes() == b"user history"
    assert (unrelated / "keep.txt").read_bytes() == b"keep"
    if operation == "install":
        cli.parent.mkdir(parents=True)
        cli.with_name(cli.name + ".qwenpaw-new").write_bytes(b"new CLI")
        run("CompleteInstall")
        assert cli.read_bytes() == b"new CLI"
    else:
        run("CompleteUninstall")
        assert not cli.exists()
    assert "QWENPAW_INSTALL_MAINTENANCE" not in launcher.read_text()
    assert not (root / ".qwenpaw-installing").exists()


@pytest.mark.parametrize(
    ("relative", "dangling"),
    [
        ("binaries", False),
        ("binaries/node-runtime", False),
        ("binaries/node-runtime/nested", False),
        ("binaries/node-runtime", True),
    ],
)
def test_nsis_runtime_cleanup_refuses_junctions(
    nsis_cli_install,
    relative,
    dangling,
):
    """Validate all trees before deletion, including nested directory links."""
    cli, _, run = nsis_cli_install
    root = cli.parents[2]
    outside = root.parent / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_bytes(b"keep")
    run("Prepare", "BeginInstall")
    junction = root / relative
    if relative == "binaries":
        junction.rename(root / "saved-binaries")
    junction.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside)],
        check=True,
        capture_output=True,
    )
    try:
        if dangling:
            moved = outside.with_name("moved-outside")
            outside.rename(moved)
            sentinel = moved / sentinel.name
        run("ClearRuntime", expected=1)
        assert sentinel.read_bytes() == b"keep"
        backend = root / (
            "saved-binaries" if relative == "binaries" else "binaries"
        )
        assert (backend / "qwenpaw-backend/qwenpaw-backend.exe").exists()
    finally:
        junction.rmdir()


def test_nsis_abort_preserves_an_older_installation_marker(nsis_cli_install):
    """Packages with the previous marker location remain safe to repair."""
    cli, _, run = nsis_cli_install
    run("Prepare")
    cli.with_name(cli.name + ".qwenpaw-installing").write_text("incomplete")
    run("AbortInstall", expected=1)
    assert not cli.exists()
    run("BeginInstall", "ClearRuntime")
    assert (cli.parents[2] / ".qwenpaw-installing").exists()
    assert not cli.parent.exists()


def test_shared_daemon_keeps_channel_runtime_environment() -> None:
    """A desktop runtime launched through the daemon needs offline channels."""
    native = REPO_ROOT / "console/src-tauri/src"
    commands = (native / "backend/command.rs").read_text(encoding="utf-8")
    collector = (native / "runtime_env.rs").read_text(encoding="utf-8")
    channels = (native / "channel_runtime.rs").read_text(encoding="utf-8")
    runtime = (native / "backend/runtime.rs").read_text(encoding="utf-8")
    daemon = (native / "backend/daemon.rs").read_text(encoding="utf-8")

    # Both development and packaged command factories must use the shared
    # contributor boundary; collecting Computer Use client metadata in
    # runtime::connect alone never delivers these paths to Python.
    factories = re.findall(
        r"pub\(super\) fn create\(.*?(?=\n#\[cfg|\Z)",
        commands,
        re.DOTALL,
    )
    assert len(factories) == 2
    for factory in factories:
        assert "command.envs(crate::runtime_env::collect(app))" in factory
    assert "crate::channel_runtime::backend_environment(app)" in collector
    for key in (
        "QWENPAW_CHANNEL_RUNTIME_MANIFEST",
        "QWENPAW_CHANNEL_SUPPORT_ROOT",
        "QWENPAW_CHANNEL_DEPENDENCY_PATHS",
    ):
        assert f'"{key}"' in channels

    launch = runtime.split("fn launch(", 1)[1]
    assert "super::command::create(app)?" in launch
    assert '.arg("--agent-host")' in launch
    assert "backend.get_envs()" in launch
    assert "command.env(key, value)" in launch
    assert "command.env_remove(key)" in launch
    assert "Command::new(&program)" in daemon
    assert ".env_clear()" not in daemon
