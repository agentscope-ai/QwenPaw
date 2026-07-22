#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tauri updater helper: stage per-platform artifacts and build the manifest.

Subcommands:
  stage     Copy a Tauri-built updater archive (and its .sig) into the dist
            tree, then write a small JSON sidecar describing it.
  manifest  Aggregate one or more stage-produced sidecar JSON files into the
            unified `qwenpaw-tauri-latest.json` consumed by tauri-plugin-updater.
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from packaging.version import InvalidVersion, Version


def to_semver(version: str) -> str:
    try:
        parsed = Version(version)
    except InvalidVersion as err:
        raise SystemExit(
            f"unsupported Python version for Tauri: {version}",
        ) from err

    if parsed.epoch or parsed.local is not None or len(parsed.release) != 3:
        raise SystemExit(f"unsupported Python version for Tauri: {version}")

    major, minor, patch = parsed.release
    prerelease_map = {"a": "alpha", "b": "beta", "rc": "rc"}
    labels: list[str] = []
    if parsed.pre:
        prerelease, prerelease_n = parsed.pre
        labels.append(f"{prerelease_map[prerelease]}.{prerelease_n}")
    if parsed.dev is not None:
        labels.append(f"dev.{parsed.dev}")
    suffix = f"-{'.'.join(labels)}" if labels else ""
    post_metadata = f"+post.{parsed.post}" if parsed.post is not None else ""
    return f"{major}.{minor}.{patch}{suffix}{post_metadata}"


# stage


def _find_source(bundle_dir: Path, pattern: str) -> Path:
    matches = sorted(bundle_dir.glob(pattern))
    if not matches:
        raise SystemExit(
            f"no artifact matching {pattern!r} under {bundle_dir}",
        )
    return matches[0]


def cmd_stage(args: argparse.Namespace) -> None:
    bundle_dir = Path(args.bundle_dir)
    source = _find_source(bundle_dir, args.pattern)
    sig_source = source.with_suffix(source.suffix + ".sig")
    if not sig_source.is_file():
        raise SystemExit(f"no updater signature found at {sig_source}")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, output)
    shutil.copyfile(sig_source, output.with_suffix(output.suffix + ".sig"))

    metadata = {
        "target": args.target,
        "artifact": output.name,
        "signature": output.name + ".sig",
    }
    sidecar = output.parent / f"tauri-{args.target}-updater.json"
    sidecar.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if args.pubkey_config:
        verify_signature_key_id(
            signature_path=output.with_suffix(output.suffix + ".sig"),
            pubkey_config=Path(args.pubkey_config),
        )
    print(f"staged {output.name} ({args.target}); sidecar {sidecar.name}")


# manifest


def _read_metadata(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)
    required = {"target", "artifact", "signature"}
    missing = required - set(data)
    if missing:
        raise SystemExit(
            f"{path} missing required keys: {', '.join(sorted(missing))}",
        )
    return {key: str(data[key]) for key in required}


def _signature_text(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"signature file not found: {path}")
    return path.read_text(encoding="utf-8-sig").strip()


def _decode_base64_minisign_text(value: str, *, kind: str) -> str:
    try:
        text = base64.b64decode(value, validate=True).decode("utf-8")
    except Exception as err:
        raise SystemExit(
            f"{kind} is not valid base64 minisign text: {err}",
        ) from err
    if "untrusted comment:" not in text:
        raise SystemExit(f"{kind} is not a minisign text block")
    return text


def _minisign_key_id(text: str, *, kind: str) -> str:
    lines = [
        line.strip() for line in text.strip().splitlines() if line.strip()
    ]
    try:
        raw = base64.b64decode(lines[1], validate=True)
        key_id = raw[2:10]
        if len(key_id) != 8:
            raise ValueError("missing key id")
    except IndexError as err:
        raise SystemExit(f"{kind} is not a valid minisign text block") from err
    except Exception as err:
        raise SystemExit(
            f"{kind} has invalid minisign key/signature data: {err}",
        ) from err
    return key_id.hex()


def _pubkey_from_config(config_path: Path) -> str:
    with config_path.open("r", encoding="utf-8-sig") as f:
        config = json.load(f)
    try:
        pubkey = config["plugins"]["updater"]["pubkey"]
    except KeyError as err:
        raise SystemExit(
            f"{config_path} missing plugins.updater.pubkey: {err}",
        ) from err
    if not isinstance(pubkey, str) or not pubkey.strip():
        raise SystemExit(f"{config_path} has an empty plugins.updater.pubkey")
    return _decode_base64_minisign_text(pubkey.strip(), kind=str(config_path))


def verify_signature_key_id(signature_path: Path, pubkey_config: Path) -> None:
    signature_text = _decode_base64_minisign_text(
        _signature_text(signature_path),
        kind=str(signature_path),
    )
    pubkey_text = _pubkey_from_config(pubkey_config)
    signature_key_id = _minisign_key_id(
        signature_text,
        kind=str(signature_path),
    )
    pubkey_key_id = _minisign_key_id(pubkey_text, kind=str(pubkey_config))
    if signature_key_id != pubkey_key_id:
        raise SystemExit(
            "updater signature key id does not match configured pubkey: "
            f"signature={signature_key_id} pubkey={pubkey_key_id}",
        )
    print(f"verified updater signature key id: {signature_key_id}")


def cmd_manifest(args: argparse.Namespace) -> None:
    target_overrides: dict[str, str] = {}
    for entry in args.target_base or []:
        target, _, url = entry.partition("=")
        if not target or not url:
            raise SystemExit(
                f"--target-base expects 'target=URL', got {entry!r}",
            )
        target_overrides[target] = url

    platforms: dict[str, dict[str, str]] = {}
    for raw in args.metadata:
        meta_path = Path(raw)
        meta = _read_metadata(meta_path)
        workdir = meta_path.parent
        artifact_path = workdir / meta["artifact"]
        if not artifact_path.is_file():
            raise SystemExit(f"artifact file not found: {artifact_path}")
        base = target_overrides.get(meta["target"], args.base_url).rstrip(
            "/",
        )
        platforms[meta["target"]] = {
            "url": f"{base}/{quote(meta['artifact'])}",
            "signature": _signature_text(workdir / meta["signature"]),
        }
    if not platforms:
        raise SystemExit("no updater platforms were provided")

    manifest = {
        "version": to_semver(args.version),
        "notes": args.notes,
        "pub_date": args.pub_date,
        "platforms": platforms,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(
        f"wrote manifest {output} (platforms: {', '.join(sorted(platforms))})",
    )


# cli


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_stage = sub.add_parser(
        "stage",
        help="Copy a Tauri updater archive + .sig into dist and write a sidecar.",
    )
    p_stage.add_argument(
        "--bundle-dir",
        required=True,
        help="Tauri bundle output dir (e.g., target/release/bundle/nsis).",
    )
    p_stage.add_argument(
        "--pattern",
        required=True,
        help="Glob to find the artifact (e.g., '*-setup.exe', '*.app.tar.gz').",
    )
    p_stage.add_argument(
        "--target",
        required=True,
        help="Updater target (e.g., windows-x86_64, darwin-aarch64).",
    )
    p_stage.add_argument(
        "--output",
        required=True,
        help="Destination artifact path; .sig is staged alongside.",
    )
    p_stage.add_argument(
        "--pubkey-config",
        help=(
            "Optional tauri.conf.json path. When provided, fail if the staged "
            "signature key id does not match plugins.updater.pubkey."
        ),
    )
    p_stage.set_defaults(func=cmd_stage)

    p_manifest = sub.add_parser(
        "manifest",
        help="Aggregate per-platform sidecars into the updater manifest JSON.",
    )
    p_manifest.add_argument("--version", required=True)
    p_manifest.add_argument(
        "--base-url",
        required=True,
        help="Default URL prefix for platforms without --target-base override.",
    )
    p_manifest.add_argument(
        "--target-base",
        action="append",
        default=[],
        help=(
            "Per-target URL prefix override 'target=URL', repeatable. "
            "Used when platforms live under different paths "
            "(e.g., OSS lays win-tauri/ and mac-tauri/ separately)."
        ),
    )
    p_manifest.add_argument(
        "--metadata",
        action="append",
        default=[],
        help="Path to a sidecar JSON file (repeatable).",
    )
    p_manifest.add_argument("--notes", default="")
    p_manifest.add_argument(
        "--pub-date",
        default=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    p_manifest.add_argument("--output", required=True)
    p_manifest.set_defaults(func=cmd_manifest)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
