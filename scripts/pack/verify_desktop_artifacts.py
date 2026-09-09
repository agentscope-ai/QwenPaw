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
    "macos-updater": ("tauri-updater-meta-macos/QwenPaw-Tauri-*-macOS.app.tar.gz"),
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


def verify_artifact(artifact: Path, platform: str) -> None:
    sidecar = Path(f"{artifact}.sha256")
    if not sidecar.is_file():
        raise ValueError(f"missing checksum sidecar: {sidecar}")

    expected = read_expected_sha256(sidecar, artifact)
    actual = calculate_sha256(artifact)
    if actual != expected:
        raise ValueError(
            f"SHA-256 mismatch for {artifact}: expected {expected}, got {actual}",
        )

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


def verify_macos_updater_metadata(artifact: Path) -> None:
    signature = Path(f"{artifact}.sig")
    if not signature.is_file():
        raise ValueError(f"missing macOS updater signature: {signature}")
    if signature.stat().st_size == 0:
        raise ValueError(f"empty macOS updater signature: {signature}")

    metadata_files = sorted(artifact.parent.glob("tauri-darwin-*-updater.json"))
    if len(metadata_files) != 1:
        raise ValueError(
            "expected exactly one macOS updater metadata file, "
            f"found {len(metadata_files)}",
        )

    metadata_path = metadata_files[0]
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"invalid updater metadata {metadata_path}: {error}"
        ) from error
    if not isinstance(metadata, dict):
        raise ValueError(f"updater metadata {metadata_path} must be a JSON object")

    expected = {
        "artifact": artifact.name,
        "signature": signature.name,
    }
    for field, expected_value in expected.items():
        if metadata.get(field) != expected_value:
            raise ValueError(
                f"updater metadata {metadata_path} has {field}={metadata.get(field)!r}, "
                f"expected {expected_value!r}",
            )
    if not isinstance(metadata.get("target"), str) or not metadata["target"].strip():
        raise ValueError(f"updater metadata {metadata_path} has no valid target")


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
        choices=tuple(ARTIFACT_PATTERNS),
        default=[],
        help="Fail unless exactly one artifact for this platform is present",
    )
    args = parser.parse_args()

    required_platforms = set(args.require)
    if (args.root / "tauri-updater-meta-macos").is_dir():
        required_platforms.add("macos-updater")

    failed = False
    found_any = False
    for platform, pattern in ARTIFACT_PATTERNS.items():
        artifacts = sorted(args.root.glob(pattern))
        if artifacts:
            found_any = True
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

        try:
            verify_artifact(artifacts[0], platform)
            if platform == "macos-updater":
                verify_macos_updater_metadata(artifacts[0])
        except ValueError as error:
            print(f"::error::{error}", file=sys.stderr)
            failed = True

    if not found_any:
        print("::error::No desktop artifacts found", file=sys.stderr)
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
