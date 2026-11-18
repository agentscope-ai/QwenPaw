#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

REQUIRED_INFO = {
    "format_version",
    "source_project",
    "source_commit",
    "source_lock_sha256",
    "patch_sha256",
    "bridge_sha256",
    "gateway_base",
    "context_console_url",
}
REQUIRED_FILES = {
    "index.html",
    "paw-bridge.js",
    "BUILD_INFO",
    "SHA256SUMS",
    "assets/index.js",
    "assets/style.css",
}
INTERNAL_MARKERS = (
    b"alibaba-inc",
    b"gitlab.alibaba",
    b"login.alibaba",
    b"bucsso",
    b"aliyun-inc",
)
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
HTML_ASSET_RE = re.compile(r'(?:src|href)=["\']([^"\']+)["\']')
ROOT_STATIC_RE = re.compile(
    r"(?:"
    r"(?:src|href|media\.src)\s*(?:=|:)\s*[\"'`]"
    r"|url\(\s*[\"']?"
    r")/((?!api/|/)[^\"'`)]+)",
)


class ValidationError(Exception):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValidationError(
                f"symlink is not allowed: {path.relative_to(root)}",
            )
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path
    return files


def parse_build_info(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValidationError(f"invalid BUILD_INFO line: {line!r}")
        key, value = line.split("=", 1)
        if not key or key in values:
            raise ValidationError(f"invalid BUILD_INFO key: {key!r}")
        values[key] = value
    if set(values) != REQUIRED_INFO:
        missing = sorted(REQUIRED_INFO - set(values))
        extra = sorted(set(values) - REQUIRED_INFO)
        raise ValidationError(
            f"invalid BUILD_INFO fields: missing={missing}, extra={extra}",
        )
    if values["format_version"] != "1":
        raise ValidationError("unsupported BUILD_INFO format_version")
    if values["source_project"] != "QwenPaw-Data-Cloud":
        raise ValidationError("unexpected BUILD_INFO source_project")
    if not COMMIT_RE.fullmatch(values["source_commit"]):
        raise ValidationError("source_commit must be a full Git commit")
    for key in ("source_lock_sha256", "patch_sha256", "bridge_sha256"):
        if not HASH_RE.fullmatch(values[key]):
            raise ValidationError(f"{key} must be a SHA-256 digest")
    if values["gateway_base"] != "/api/qwenpaw-data/engine":
        raise ValidationError("unexpected engine gateway base")
    if values["context_console_url"] != (
        "/api/frontend_plugin/qwenpaw-data/files/"
        "ui/dist/context-console/index.html#"
    ):
        raise ValidationError("unexpected Context console URL")
    return values


def parse_checksums(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValidationError(f"invalid SHA256SUMS line: {line!r}")
        digest, relative = match.groups()
        if relative in checksums or relative == "SHA256SUMS":
            raise ValidationError(f"invalid checksum entry: {relative}")
        checksums[relative] = digest
    return checksums


def write_checksums(root: Path) -> None:
    files = snapshot_files(root)
    lines = [
        f"{sha256(path)}  {relative}"
        for relative, path in files.items()
        if relative != "SHA256SUMS"
    ]
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_provenance(
    files: dict[str, Path],
    canonical_bridge: Path | None,
    canonical_patch: Path | None,
) -> None:
    info = parse_build_info(files["BUILD_INFO"])
    if canonical_patch is not None:
        if not canonical_patch.is_file():
            raise ValidationError(
                f"canonical patch not found: {canonical_patch}",
            )
        if sha256(canonical_patch) != info["patch_sha256"]:
            raise ValidationError(
                "BUILD_INFO does not match the canonical patch",
            )

    checksums = parse_checksums(files["SHA256SUMS"])
    expected_files = set(files) - {"SHA256SUMS"}
    if set(checksums) != expected_files:
        missing_sums = sorted(expected_files - set(checksums))
        stale_sums = sorted(set(checksums) - expected_files)
        raise ValidationError(
            f"checksum inventory mismatch: missing={missing_sums}, "
            f"stale={stale_sums}",
        )
    for relative, expected in checksums.items():
        if sha256(files[relative]) != expected:
            raise ValidationError(f"checksum mismatch: {relative}")

    bridge = files["paw-bridge.js"]
    if sha256(bridge) != info["bridge_sha256"]:
        raise ValidationError("paw-bridge.js does not match BUILD_INFO")
    if canonical_bridge is None:
        return
    if not canonical_bridge.is_file():
        raise ValidationError(
            f"canonical bridge not found: {canonical_bridge}",
        )
    if bridge.read_bytes() != canonical_bridge.read_bytes():
        raise ValidationError(
            "vendored paw-bridge.js differs from the canonical bridge",
        )


def validate_index_assets(root: Path, files: dict[str, Path]) -> None:
    index = files["index.html"].read_text(encoding="utf-8")
    bridge_position = index.find('<script src="./paw-bridge.js"></script>')
    module_position = index.find('<script type="module"')
    if (
        bridge_position < 0
        or module_position < 0
        or bridge_position > module_position
    ):
        raise ValidationError(
            "paw-bridge.js must load before the module bundle",
        )
    for reference in HTML_ASSET_RE.findall(index):
        if reference.startswith(
            ("http://", "https://", "data:", "#", "/api/"),
        ):
            continue
        asset = (root / reference.split("?", 1)[0].split("#", 1)[0]).resolve()
        try:
            asset.relative_to(root.resolve())
        except ValueError as exc:
            raise ValidationError(
                f"asset escapes snapshot: {reference}",
            ) from exc
        if not asset.is_file():
            raise ValidationError(f"referenced asset is missing: {reference}")


def validate_file_contents(files: dict[str, Path]) -> None:
    for relative, path in files.items():
        if relative.endswith(".map"):
            raise ValidationError(f"source map is not allowed: {relative}")
        content = path.read_bytes()
        if path.suffix in {".html", ".js", ".css"}:
            root_static = ROOT_STATIC_RE.search(content.decode("utf-8"))
            if root_static:
                raise ValidationError(
                    f"root-absolute static asset reference in {relative}: "
                    f"/{root_static.group(1)}",
                )
        lowered = content.lower()
        if b"sourcemappingurl" in lowered:
            raise ValidationError(
                f"source map reference is not allowed: {relative}",
            )
        for marker in INTERNAL_MARKERS:
            if marker in lowered:
                raise ValidationError(
                    f"internal marker {marker.decode()} found in {relative}",
                )


def validate(
    root: Path,
    canonical_bridge: Path | None,
    canonical_patch: Path | None = None,
) -> None:
    if not root.is_dir():
        raise ValidationError(f"snapshot directory not found: {root}")
    files = snapshot_files(root)
    missing = sorted(REQUIRED_FILES - set(files))
    if missing:
        raise ValidationError(f"required files are missing: {missing}")

    validate_provenance(files, canonical_bridge, canonical_patch)
    validate_index_assets(root, files)
    validate_file_contents(files)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the vendored Data console",
    )
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--canonical-bridge", type=Path)
    parser.add_argument("--canonical-patch", type=Path)
    parser.add_argument("--write-checksums", action="store_true")
    args = parser.parse_args()
    try:
        if args.write_checksums:
            write_checksums(args.snapshot)
        validate(args.snapshot, args.canonical_bridge, args.canonical_patch)
    except (OSError, UnicodeError, ValidationError) as exc:
        print(f"Data console verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"Data console verified: {args.snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
