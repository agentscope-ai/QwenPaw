#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assemble the existing Helper as a nested App at build time, before signing.

This never installs/launches a Helper or touches TCC. The following signing
step must seal nested Apps before the outer Desktop. Runtime only copies that
sealed tree; it does not synthesize metadata or sign code on the user's Mac.
"""

from __future__ import annotations

import argparse
import plistlib
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_NAME = "QwenPaw Computer Use.app"
EXECUTABLE = "qwenpaw-computer-use-helper"
SHIM = "libqwenpaw_record_replay.dylib"
IDENTIFIER = "io.agentscope.qwenpaw.computer-use.v1"


def stage_helper(desktop: Path, *, metadata: Path | None = None) -> Path:
    """Refuse missing inputs, symlinks and overwrite of an existing seed."""
    metadata = metadata or REPO_ROOT / "console/src-tauri/helper-Info.plist"
    if (
        desktop.is_symlink()
        or not desktop.is_dir()
        or desktop.suffix != ".app"
    ):
        raise ValueError("expected an existing regular Desktop App directory")
    contents = desktop / "Contents"
    executable = contents / "MacOS" / EXECUTABLE
    shim = contents / "Frameworks" / SHIM
    for path in (metadata, executable, shim):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"expected a regular build input: {path}")
    info = plistlib.loads(metadata.read_bytes())
    if (
        info.get("CFBundleIdentifier") != IDENTIFIER
        or info.get("CFBundleExecutable") != EXECUTABLE
        or info.get("LSMinimumSystemVersion") != "14.0"
    ):
        raise ValueError(
            "Helper identity, executable and macOS baseline must stay fixed",
        )
    helpers = contents / "Helpers"
    for directory in (contents, executable.parent, shim.parent, helpers):
        if directory.is_symlink():
            raise ValueError("build directories must not be symlinks")
    helpers.mkdir(exist_ok=True)
    target = helpers / BUNDLE_NAME
    target.mkdir()  # An existing signed seed is never silently overwritten.
    try:
        macos = target / "Contents" / "MacOS"
        frameworks = target / "Contents" / "Frameworks"
        macos.mkdir(parents=True)
        frameworks.mkdir()
        shutil.copy2(executable, macos / EXECUTABLE)
        shutil.copy2(shim, frameworks / SHIM)
        shutil.copy2(metadata, target / "Contents" / "Info.plist")
    except BaseException:
        # Only the newly-created build-owned directory is removed.
        shutil.rmtree(target)
        raise
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    args = parser.parse_args()
    print(stage_helper(args.app))
