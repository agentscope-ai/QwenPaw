#!/usr/bin/env python3
"""Verify desktop installers after they are downloaded from Actions artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile


ARTIFACT_PATTERNS = {
    "windows": "QwenPaw-Desktop-Tauri-Windows-*/QwenPaw-Tauri-*-Windows-setup.exe",
    "macos": "QwenPaw-Desktop-Tauri-macOS-*/QwenPaw-Tauri-*-macOS.zip",
}

UPDATER_SPECS = {
    "windows-updater": {
        "directory": "tauri-updater-meta-windows",
        "artifact_pattern": "QwenPaw-Tauri-*-Windows-setup.exe.sig",
        "metadata_pattern": "tauri-windows-*-updater.json",
        "target": "windows-x86_64",
    },
    "macos-updater": {
        "directory": "tauri-updater-meta-macos",
        "artifact_pattern": "QwenPaw-Tauri-*-macOS.app.tar.gz",
        "metadata_pattern": "tauri-darwin-*-updater.json",
        "target": "darwin-aarch64",
    },
}


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_expected_sha256(sidecar: Path, artifact: Path) -> str:
    try:
        fields = sidecar.read_text(encoding="ascii").strip().split()
    except OSError as error:
        raise ValueError(f"cannot read checksum sidecar {sidecar}: {error}") from error

    if len(fields) != 2 or len(fields[0]) != 64:
        raise ValueError(f"invalid checksum sidecar: {sidecar}")
    if Path(fields[1].lstrip("*")).name != artifact.name:
        raise ValueError(
            f"checksum sidecar {sidecar} names {fields[1]!r}, expected {artifact.name!r}",
        )
    try:
        int(fields[0], 16)
    except ValueError as error:
        raise ValueError(f"invalid SHA-256 in {sidecar}") from error
    return fields[0].lower()


def verify_checksum(artifact: Path) -> None:
    sidecar = Path(f"{artifact}.sha256")
    if not sidecar.is_file():
        raise ValueError(f"missing checksum sidecar: {sidecar}")

    expected = read_expected_sha256(sidecar, artifact)
    actual = calculate_sha256(artifact)
    if actual != expected:
        raise ValueError(
            f"SHA-256 mismatch for {artifact}: expected {expected}, got {actual}",
        )


def verify_artifact(artifact: Path, platform: str) -> None:
    verify_checksum(artifact)

    if platform == "macos":
        try:
            with zipfile.ZipFile(artifact) as archive:
                corrupt_member = archive.testzip()
        except (OSError, zipfile.BadZipFile) as error:
            raise ValueError(f"invalid macOS ZIP {artifact}: {error}") from error
        if corrupt_member is not None:
            raise ValueError(
                f"CRC check failed for {corrupt_member!r} in {artifact}",
            )

    print(f"verified {platform} artifact: {artifact} ({artifact.stat().st_size} bytes)")


def find_exactly_one(directory: Path, pattern: str, label: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {label}, found {len(matches)}")
    return matches[0]


def verify_updater_metadata(
    artifact_name: str,
    signature: Path,
    metadata_path: Path,
    expected_target: str,
) -> None:
    if signature.stat().st_size == 0:
        raise ValueError(f"empty updater signature: {signature}")

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"invalid updater metadata {metadata_path}: {error}"
        ) from error
    if not isinstance(metadata, dict):
        raise ValueError(f"updater metadata {metadata_path} must be a JSON object")

    expected = {
        "artifact": artifact_name,
        "signature": signature.name,
        "target": expected_target,
    }
    for field, expected_value in expected.items():
        if metadata.get(field) != expected_value:
            raise ValueError(
                f"updater metadata {metadata_path} has {field}={metadata.get(field)!r}, "
                f"expected {expected_value!r}",
            )


def verify_updater_artifact(
    root: Path,
    platform: str,
    installer_names: dict[str, str],
) -> None:
    spec = UPDATER_SPECS[platform]
    directory = root / spec["directory"]
    updater_artifact = find_exactly_one(
        directory,
        spec["artifact_pattern"],
        f"{platform} artifact",
    )
    metadata_path = find_exactly_one(
        directory,
        spec["metadata_pattern"],
        f"{platform} metadata file",
    )

    if platform == "windows-updater":
        signature = updater_artifact
        artifact_name = signature.name.removesuffix(".sig")
        if artifact_name != installer_names.get("windows"):
            raise ValueError(
                f"Windows updater signature names {artifact_name!r}, "
                f"expected {installer_names.get('windows')!r}",
            )
    else:
        artifact_name = updater_artifact.name
        signature = Path(f"{updater_artifact}.sig")
        if not signature.is_file():
            raise ValueError(f"missing macOS updater signature: {signature}")
        verify_checksum(updater_artifact)

    verify_checksum(signature)
    verify_checksum(metadata_path)
    verify_updater_metadata(
        artifact_name,
        signature,
        metadata_path,
        spec["target"],
    )
    print(f"verified {platform} metadata: {metadata_path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Directory containing the downloaded Actions artifact directories",
    )
    parser.add_argument(
        "--require",
        action="append",
        choices=tuple(ARTIFACT_PATTERNS) + tuple(UPDATER_SPECS),
        default=[],
        help="Fail unless exactly one artifact for this platform is present",
    )
    args = parser.parse_args()

    required_platforms = set(args.require)
    for platform, spec in UPDATER_SPECS.items():
        if (args.root / spec["directory"]).is_dir():
            required_platforms.add(platform)

    failed = False
    found_any = False
    installer_names: dict[str, str] = {}
    for platform, pattern in ARTIFACT_PATTERNS.items():
        artifacts = sorted(args.root.glob(pattern))
        found_any = found_any or bool(artifacts)
        if len(artifacts) > 1:
            print(
                f"::error::Expected at most one {platform} artifact, found {len(artifacts)}",
                file=sys.stderr,
            )
            failed = True
            continue
        if not artifacts:
            if platform in required_platforms:
                print(f"::error::Missing required {platform} artifact", file=sys.stderr)
                failed = True
            continue

        installer_names[platform] = artifacts[0].name
        try:
            verify_artifact(artifacts[0], platform)
        except ValueError as error:
            print(f"::error::{error}", file=sys.stderr)
            failed = True

    for platform, spec in UPDATER_SPECS.items():
        if platform not in required_platforms:
            continue
        if not (args.root / spec["directory"]).is_dir():
            print(f"::error::Missing required {platform} artifact", file=sys.stderr)
            failed = True
            continue
        found_any = True
        try:
            verify_updater_artifact(args.root, platform, installer_names)
        except (OSError, ValueError) as error:
            print(f"::error::{error}", file=sys.stderr)
            failed = True

    if not found_any:
        print("::error::No desktop artifacts found", file=sys.stderr)
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
