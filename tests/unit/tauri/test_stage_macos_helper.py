# -*- coding: utf-8 -*-
"""Build-only Helper packaging; no installation, TCC or native execution."""

import importlib.util
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(name="stage")
def stage_module():
    spec = importlib.util.spec_from_file_location(
        "stage_macos_helper",
        ROOT / "scripts/pack-tauri/stage_macos_helper.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="desktop")
def desktop_fixture(tmp_path):
    root = tmp_path / "Desktop with spaces.app"
    contents = root / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "Frameworks").mkdir()
    executable = contents / "MacOS/qwenpaw-computer-use-helper"
    executable.write_bytes(b"fake build executable")
    executable.chmod(0o755)
    (contents / "Frameworks/libqwenpaw_record_replay.dylib").write_bytes(
        b"fake shim",
    )
    return root


def test_stages_fixed_identity_without_mutating_inputs(stage, desktop):
    target = stage.stage_helper(desktop)
    assert target == desktop / "Contents/Helpers/QwenPaw Computer Use.app"
    info = plistlib.loads((target / "Contents/Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == stage.IDENTIFIER
    assert info["LSMinimumSystemVersion"] == "14.0"
    for relative in (
        "MacOS/qwenpaw-computer-use-helper",
        "Frameworks/libqwenpaw_record_replay.dylib",
    ):
        source = desktop / "Contents" / relative
        copy = target / "Contents" / relative
        assert copy.read_bytes() == source.read_bytes()
        assert copy.stat().st_mode == source.stat().st_mode


def test_existing_seed_is_never_overwritten(stage, desktop):
    target = stage.stage_helper(desktop)
    marker = target / "preserve"
    marker.write_bytes(b"existing signed seed")
    with pytest.raises(FileExistsError):
        stage.stage_helper(desktop)
    assert marker.read_bytes() == b"existing signed seed"


@pytest.mark.parametrize(
    "field",
    ["CFBundleIdentifier", "CFBundleExecutable", "LSMinimumSystemVersion"],
)
def test_changed_identity_or_baseline_is_rejected(
    stage,
    desktop,
    tmp_path,
    field,
):
    original = ROOT / "console/src-tauri/helper-Info.plist"
    info = plistlib.loads(original.read_bytes())
    info[field] = "changed"
    custom = tmp_path / "Info.plist"
    custom.write_bytes(plistlib.dumps(info))
    with pytest.raises(ValueError):
        stage.stage_helper(desktop, metadata=custom)
    assert not (desktop / "Contents/Helpers").exists()


@pytest.mark.parametrize("kind", ["missing", "link", "directory"])
def test_invalid_executable_is_rejected(stage, desktop, tmp_path, kind):
    executable = desktop / "Contents/MacOS/qwenpaw-computer-use-helper"
    executable.unlink()
    if kind == "link":
        executable.symlink_to(tmp_path / "outside")
    elif kind == "directory":
        executable.mkdir()
    with pytest.raises(ValueError):
        stage.stage_helper(desktop)


def test_partial_build_cleanup_is_owned_only(stage, desktop, monkeypatch):
    monkeypatch.setattr(
        stage.shutil,
        "copy2",
        Mock(side_effect=OSError("injected copy failure")),
    )
    with pytest.raises(OSError):
        stage.stage_helper(desktop)
    assert not (desktop / "Contents/Helpers/QwenPaw Computer Use.app").exists()
    assert (desktop / "Contents/MacOS/qwenpaw-computer-use-helper").is_file()


def test_runtime_never_synthesizes_or_signs_helper():
    runtime = (
        (ROOT / "console/src-tauri/src/computer_use_helper.rs")
        .read_text()
        .split("#[cfg(test)]\nmod tests")[0]
    )
    assert '"--sign"' not in runtime
    assert "fs::write(" not in runtime
    assert '"--verify", "--deep", "--strict"' in runtime
    assert 'join("Helpers").join(HELPER_BUNDLE_NAME)' in runtime


def test_packaging_stages_before_final_sign_and_seals_nested_apps():
    build = (
        ROOT / "scripts/pack-tauri/build_macos_pyinstaller.sh"
    ).read_text()
    assert build.index("stage_macos_helper.py") < build.index(
        "Signing Final macOS App",
    )
    signing = (ROOT / "scripts/pack-tauri/sign_macos_bundle.sh").read_text()
    assert "-depth -type d -name '*.app' -print0" in signing


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="real macOS codesign fixture",
)
def test_real_nested_app_signing_order(stage, desktop):
    """Sign copied Mach-O fixtures, never install, register or execute them."""
    contents = desktop / "Contents"
    fixture_binary = Path(sys.executable).resolve()
    for relative in (
        "MacOS/desktop-signing-fixture",
        "MacOS/qwenpaw-computer-use-helper",
        "Frameworks/libqwenpaw_record_replay.dylib",
    ):
        shutil.copy2(fixture_binary, contents / relative)
    (contents / "Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleIdentifier": "example.qwenpaw.signing-fixture",
                "CFBundleExecutable": "desktop-signing-fixture",
                "CFBundlePackageType": "APPL",
            },
        ),
    )
    nested = stage.stage_helper(desktop)
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "scripts/pack-tauri/sign_macos_bundle.sh"),
            str(desktop),
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for bundle in (nested, desktop):
        subprocess.run(
            [
                "/usr/bin/codesign",
                "--verify",
                "--deep",
                "--strict",
                str(bundle),
            ],
            check=True,
            capture_output=True,
            timeout=10,
        )
